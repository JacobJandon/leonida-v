"""Start the game the way the owner does, wait until story mode has loaded, then read the mods' logs (``verify``).

    report = playtest(session, timeout=300, keep_running=False, progress=print)

Steps:
  1. Close GTA if it's running (``GTA5_Enhanced.exe``, ``PlayGTAV.exe``). If Windows refuses (the game runs as
     administrator because of a RUNASADMIN compatibility flag), stop and say how to remove the flag.
  2. Move the mods' old logs out of the game folder into ``<state>/playtest/previous/``, so every log read
     afterwards is from this run. Leonida writes nothing into the game folder outside ``Installer``.
  3. Start ``PlayGTAV.exe`` in the game folder (what the desktop shortcut runs). Never ``GTA5_Enhanced.exe``
     directly: it exits with code 4919. No extra arguments and no anti-cheat flags.
  4. Wait for ``GTA5_Enhanced.exe``, then ``ScriptHookV.log`` (~10 s), then ``ScriptHookVDotNet.log`` with its
     "Loading scripts from" line (~60-100 s: story mode has loaded), then a settle time. With Straight To Story
     Mode installed the game boots straight into story mode; without it someone has to click Story Mode.
  5. ``verify_session`` reads the logs; the game is closed again unless ``keep_running``.

``deep=True`` (``leonida playtest --deep``) also runs an in-game probe (leonida/probe): a temporary Script Hook V
.NET script that checks ``IS_DLC_PRESENT`` for every DLC pack the mods added and the handling the game applied to a
test car (Drive V). It's placed before the launch, waited for after the settle time (``probe_timeout``), its
findings join the report, and it's removed afterwards whatever happens (also on Ctrl+C).

A game process that disappears before story mode is a crash: the report carries the evidence (new crash dumps
with the exception and the module it happened in, Rockstar's own crash log, Windows "Application Error" /
"Application Hang" / WER events for GTA5_Enhanced.exe, the mods' logs' last lines, the memory just before) and it
is all saved in ``<state>/logs/playtest/crash-<time>/``. No story mode within ``timeout`` is a hang.

Memory (leonida/memwatch.py): every run samples the system's free RAM, commit charge, page file, the game's working
set / private bytes and GPU memory every 2 s into ``<state>/logs/playtest/run-<time>.csv``; the report has the peaks
and the values just before the game closed. Before the launch, less than 6 GB of free RAM gives a warning naming the
biggest memory users. ``playtest_series`` (``leonida playtest --repeat N``) runs it N times and sums it up.

Stdlib only; process handling goes through ``ProcessOps`` and memory through ``memwatch`` (tests use fakes).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import memwatch
from . import verify as V
from .logs import log_dir
from .minidump import read_minidump

log = logging.getLogger(__name__)

GAME_EXE = "GTA5_Enhanced.exe"
LAUNCHER = "PlayGTAV.exe"
GAME_PROCESSES = (GAME_EXE, LAUNCHER)
# Crash reporters that can outlive the game while they finish a dump: waited for, never killed. (The game's own
# dump in Rockstar's CrashLogs is the main signal: a .dmp still growing is always waited for; see wait_for_dumps.)
CRASH_HANDLERS = ("RockstarErrorHandler.exe", "WerFault.exe")
EXIT_QUIET = 10.0       # seconds after everything has exited before the next step (Windows releases file locks)
DUMP_TIMEOUT = 90.0     # longest wait for a crash dump that's still being written
ZERO_DUMP_FRESH = 30.0  # a 0-byte dump touched this recently is still being written; an older one was abandoned
DUMP_STABLE = 6.0       # a dump whose size hasn't changed for this long (and no crash handler running) is complete
STORY_MARK = re.compile(r"Loading scripts from", re.I)  # ScriptHookVDotNet.log: story mode is loading scripts
LOGS = (V.SHV_LOG, V.ASI_LOG, V.SHVDN_LOG, V.MENYOO_LOG, V.DSF_LOG, V.RE_LOG, *V.UAL_LOGS)
LAYERS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
STS_ID, SHV_ID, SHVDN_ID = "straighttostory", "scripthookv", "shvdne"

PASSED, FAILED, CRASHED, HANG, BLOCKED = "passed", "failed", "crashed", "hang", "blocked"
_SYS32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class PlaytestReport:
    status: str                                    # passed | failed (a mod failed) | crashed | hang | blocked
    message: str
    timeline: list[str] = field(default_factory=list)   # "  12s  Script Hook V loaded" ...
    results: list = field(default_factory=list)          # verify.VerifyResult, when the logs were read
    evidence: list[str] = field(default_factory=list)    # crash dumps, event log entries, last log lines
    notes: list[str] = field(default_factory=list)
    moved_logs: list[str] = field(default_factory=list)  # logs moved to <state>/playtest/previous
    story_mode_after: float | None = None                # seconds from launch to "Loading scripts from"
    ended_after: float | None = None                     # seconds from launch to the crash / hang being seen
    crash_reason: str | None = None                      # from the crash dump: "EXCEPTION_... in module+0x..."
    crash_site: str | None = None                        # "GTA5_Enhanced.exe+0xBCC6AD": the same for the same bug
    crash_asis: list[str] = field(default_factory=list)  # the ASI plugins loaded when it crashed
    crash_memory_load: str | None = None                 # "91%" (Rockstar's crash log, else the last sample)
    crash_stack: str = ""                                # minidump.stack_summary(): callers, native, strings
    crash_dir: str | None = None                         # <state>/logs/playtest/crash-<time>
    memory: dict = field(default_factory=dict)           # memwatch.MemWatch.summary(): csv, peak, last
    free_ram_before_mb: float | None = None              # free RAM just before the launch
    free_commit_before_mb: float | None = None           # free commit (commit limit - commit charge) then

    @property
    def ok(self) -> bool:
        return self.status == PASSED

    def verdict(self) -> str:
        """One line to grep for, always printed last: "VERDICT: CRASHED GTA5_Enhanced.exe+0xBCC6AD (at 76 s)"."""
        v = f"CRASHED {self.crash_site or 'no-crash-dump'}" if self.status == CRASHED else self.status.upper()
        if self.status in (PASSED, FAILED) and self.story_mode_after is not None:
            v += f" (story mode after {self.story_mode_after:.0f} s)"
        elif self.ended_after is not None:
            v += f" (at {self.ended_after:.0f} s)"
        return f"VERDICT: {v}"

    def summary(self) -> list[str]:
        lines = [f"{self.status.upper()}: {self.message}", *self.timeline]
        lines += [f"note: {n}" for n in self.notes]
        lines += [f"evidence: {e}" for e in self.evidence]
        lines += memory_lines(self)
        lines.append(self.verdict())
        return lines


def memory_lines(rep: PlaytestReport) -> list[str]:
    m = rep.memory or {}
    if not m:
        return []
    lines = [f"memory peak: {memwatch.describe(m.get('peak', {}))}"]
    if rep.status in (CRASHED, HANG) and m.get("last"):
        lines.append(f"memory at {m['last'].get('t', 0):.0f} s, just before the end: {memwatch.describe(m['last'])}")
    if m.get("csv"):
        lines.append(f"memory samples ({m.get('samples', 0)}, every 2 s): {m['csv']}")
    return lines


# -------------------------------------------------------------------------------------------- processes
class ProcessOps:
    """Windows process handling with the stdlib (tasklist/taskkill/wevtutil from System32)."""

    def _run(self, args: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout,
                              check=False, creationflags=_NO_WINDOW)

    def running(self, name: str) -> list[int]:
        """PIDs of processes with this image name."""
        if sys.platform != "win32":
            return []
        res = self._run([str(_SYS32 / "tasklist.exe"), "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {name}"])
        return parse_tasklist(res.stdout, name)

    def kill(self, name: str) -> tuple[bool, str]:
        """Ask Windows to end every process with this name. (False, reason) when access is denied."""
        res = self._run([str(_SYS32 / "taskkill.exe"), "/F", "/T", "/IM", name])
        out = (res.stdout + res.stderr).strip()
        return ("access is denied" not in out.lower(), out)

    def start(self, exe: Path, cwd: Path) -> None:
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([str(exe)], cwd=str(cwd), close_fds=True, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def events(self, seconds: float) -> list[str]:
        """Windows Application log entries (errors/hangs) of the last ``seconds`` that mention GTA5_Enhanced.exe."""
        if sys.platform != "win32":
            return []
        query = ("*[System[(Provider[@Name='Application Error'] or Provider[@Name='Application Hang'] or "
                 f"Provider[@Name='Windows Error Reporting']) and TimeCreated[timediff(@SystemTime) <= "
                 f"{int(max(seconds, 1) * 1000)}]]]")
        try:
            res = self._run([str(_SYS32 / "wevtutil.exe"), "qe", "Application", "/c:20", "/rd:true", "/f:text",
                             f"/q:{query}"])
        except (OSError, subprocess.SubprocessError):
            return []
        return parse_events(res.stdout, GAME_EXE)


def parse_tasklist(text: str, name: str) -> list[int]:
    pids = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[0].strip().lower() == name.lower() and row[1].strip().isdigit():
            pids.append(int(row[1]))
    return pids


def parse_events(text: str, exe: str, max_lines: int = 14) -> list[str]:
    blocks = re.split(r"(?m)^Event\[\d+\]:?\s*$", text)
    out = []
    for b in blocks:
        if exe.lower() in b.lower():
            lines = [ln.strip() for ln in b.strip().splitlines() if ln.strip()]
            out.append(" | ".join(lines[:max_lines]))
    return out


def runasadmin_flag(launcher: Path) -> str | None:
    """'HKCU'/'HKLM' when Windows is told to run the launcher as administrator (read-only check), else None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    for hive, label in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        try:
            with winreg.OpenKey(hive, LAYERS_KEY) as key:
                value, _ = winreg.QueryValueEx(key, str(launcher))
        except OSError:
            continue
        if "RUNASADMIN" in str(value).upper():
            return label
    return None


def admin_help(launcher: Path, hive: str | None = None) -> str:
    hive = hive or "HKCU"
    return (f"GTA runs as administrator, so Leonida can't close or start it. Close GTA yourself. To stop it running "
            f"as administrator: right-click {launcher.name} > Properties > Compatibility and untick 'Run this "
            f"program as an administrator', or run:  reg delete \"{hive}\\{LAYERS_KEY}\" /v \"{launcher}\" /f  "
            "(this removes all compatibility settings for PlayGTAV.exe).")


# ----------------------------------------------------------------------------------------------- crash evidence
ROCKSTAR_CONTEXT = "crashcontext.log"
# the lines of Rockstar's crashcontext.log worth reading at a glance (the file itself is kept in the crash folder)
CONTEXT_KEYS = ("Game State", "System Time", "Loading ", "Memory Load", "Physical Free", "PageFile Total",
                "PageFile Free", "Is Out of memory", "Last Movie", "Last ActionScript Method", "Version ")
KEEP_CRASH_DIRS = 20


def rockstar_crash_dirs() -> list[Path]:
    """Where the game itself writes crash dumps and crashcontext.log:
    %LOCALAPPDATA%\\Rockstar Games\\<GTAV Enhanced / GTA V ...>\\CrashLogs."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    base = Path(local) / "Rockstar Games"
    try:
        return sorted(p / "CrashLogs" for p in base.iterdir() if (p / "CrashLogs").is_dir())
    except OSError:
        return []


def crash_dirs(game: Path) -> list[Path]:
    dirs = [game, game / "CrashDumps"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "CrashDumps")
    return dirs + rockstar_crash_dirs()


def crash_files(game: Path, since: float) -> list[Path]:
    """Crash dumps / crash logs written since ``since`` (POSIX time), newest first: the game folder's, Rockstar's
    CrashLogs (dumps + crashcontext.log), and every new file in %LOCALAPPDATA%\\CrashDumps (Windows' own dumps; another
    app crashing at the same time says something too)."""
    found: list[Path] = []
    rockstar = set(rockstar_crash_dirs())
    for d in crash_dirs(game):
        if not d.is_dir():
            continue
        windows_dumps = d.name.lower() == "crashdumps" and d != game / "CrashDumps"
        for p in d.iterdir():
            low = p.name.lower()
            interesting = low.endswith(".dmp") or low.startswith("crashlog") or (low.startswith("crash") and
                                                                                 low.endswith((".log", ".txt")))
            if d in rockstar:
                interesting = low.endswith((".dmp", ".log"))
            elif windows_dumps:
                interesting = True
            try:
                if interesting and p.is_file() and p.stat().st_mtime >= since - 5:
                    found.append(p)
            except OSError:
                continue
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def rockstar_context(path: Path) -> list[str]:
    """The key lines of Rockstar's crashcontext.log ("Game State : Game Running", "Physical Free : (1307Mb)", ...)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines()[:200] + [ln for ln in text.splitlines() if ln.startswith(("Last ", "Is Out"))]:
        s = re.sub(r"\s+", " ", line.strip().replace("(", "").replace(")", ""))
        if s.startswith(CONTEXT_KEYS) and s not in out:
            out.append(s)
    return out


def context_memory_load(lines: list[str]) -> str | None:
    """The memory load ("91%") from rockstar_context's "Memory Load : 91%" line."""
    for s in lines:
        m = re.match(r"Memory Load : (\d+%)", s)
        if m:
            return m.group(1)
    return None


def is_game_dump(info) -> bool:
    return any(m.lower() == GAME_EXE.lower() for m in info.modules)


def crash_summary(info, memory_load: str | None = None) -> str:
    """One line for a crash dump: exception and site, memory load, the loaded ASIs (see ``stack_line``)."""
    parts = [info.describe()]
    if memory_load:
        parts.append(f"memory load {memory_load}")
    if info.asis:
        parts.append("ASIs: " + ", ".join(info.asis))
    return " | ".join(parts)


def name_native(info, game: Path | None) -> None:
    """Fill ``info.native_name`` from the game folder's Script Hook V .NET (leonida.nativenames)."""
    if info is not None and info.native is not None and not info.native_name:
        from .nativenames import native_names

        info.native_name = native_names(game).get(info.native, "")


def stack_line(info) -> str:
    """The crashing thread's stack, summed up: who called into the crash, the native, strings left on the stack."""
    return info.stack_summary() if info is not None else ""


def script_logs(game: Path, since: float) -> list[Path]:
    """The scripts' own logs (scripts\\*.log, e.g. EAIInitalization.log) written during the run."""
    folder = game / "scripts"
    try:
        return sorted(p for p in folder.glob("*.log") if p.is_file() and p.stat().st_mtime >= since - 5)
    except OSError:
        return []


def new_dumps(since: float) -> dict[Path, tuple[int, float]]:
    """Crash dumps (the game's CrashLogs and Windows' CrashDumps) written since ``since``: {path: (size, mtime)}."""
    out: dict[Path, tuple[int, float]] = {}
    local = os.environ.get("LOCALAPPDATA")
    for d in rockstar_crash_dirs() + ([Path(local) / "CrashDumps"] if local else []):
        try:
            for p in d.glob("*.dmp"):
                st = p.stat()
                if st.st_mtime >= since - 5:
                    out[p] = (st.st_size, st.st_mtime)
        except OSError:
            continue
    return out


def wait_for_dumps(since: float, sleep, clock, poll: float = 2.0, timeout: float = DUMP_TIMEOUT,
                   say: Callable[[str], None] | None = None, busy: Callable[[], bool] | None = None,
                   stable_for: float = DUMP_STABLE) -> bool:
    """Wait while a crash dump written since ``since`` may still be in progress, so the game or its crash handler
    is never killed halfway through a dump (and the dump is read complete). A dump is done when its size hasn't
    changed for ``stable_for`` seconds, it isn't a fresh 0-byte file (touched in the last ``ZERO_DUMP_FRESH`` s) and
    ``busy()`` (a crash handler still running) is false. Dumps last written long ago, and an abandoned 0-byte dump
    of a killed run, don't hold anything up. True when there's nothing (left) to wait for."""
    deadline, told = clock() + timeout, False
    before: dict[Path, tuple[int, float]] | None = None
    stable_since = clock()
    while True:
        now = new_dumps(since)
        if not now:
            return True
        real_now = time.time()
        empty_fresh = [q for q, (size, mtime) in now.items() if size == 0 and mtime >= real_now - ZERO_DUMP_FRESH]
        handler = bool(busy and busy())
        if before is None:
            if not handler and not empty_fresh and all(m < real_now - stable_for for _s, m in now.values()):
                return True  # all written a while ago: complete
        elif any(before.get(q, (None, 0))[0] != size for q, (size, _m) in now.items()):
            stable_since = clock()
        elif not handler and not empty_fresh and clock() - stable_since >= stable_for:
            return True
        if clock() >= deadline:
            if say:
                say(f"A crash dump may still be incomplete after {timeout:.0f} s: {', '.join(q.name for q in now)}")
            return False
        if say and not told:
            say(f"A crash dump is being written ({', '.join(q.name for q in now)}): waiting for it ...")
            told = True
        before = now
        sleep(poll)


def _tail(game: Path, name: str, n: int = 3) -> list[str]:
    lf = V.Logs(game).get(name)
    return [f"{lf.rel}: {ln}" for ln in lf.lines[-n:]] if lf else []


def collect_crash(session, game: Path, since: float, events: list[str], watch: memwatch.MemWatch | None = None,
                  top_users: list[tuple[str, float]] | None = None) -> tuple[list[str], dict, Path | None]:
    """Everything known about a crash: (evidence lines, crash info, the crash folder).

    Crash info (for the report): ``crash_reason`` (exception and site), ``crash_site`` ("GTA5_Enhanced.exe+0x..."),
    ``crash_asis`` (the ASIs loaded at the time), ``crash_memory_load`` ("91%", Rockstar's log or the last sample);
    all from the game's own dump when there's one (another app's dump in CrashDumps is only listed).

    The folder ``<state>/logs/playtest/crash-<time>/`` gets summary.txt, events.txt, dumps.txt (paths, sizes and
    the parsed exception; the dumps stay where they are, they can hold private memory), Rockstar's crashcontext.log
    and the last 200 lines of every mod log."""
    files = crash_files(game, since)
    ev: list[str] = []
    dump_lines = []
    dumps = []
    context: Path | None = None
    for p in files:
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        if p.suffix.lower() == ".dmp":
            info = read_minidump(p)
            desc = info.describe() if info else "not readable as a minidump"
            dump_lines.append(f"{p}  ({size} bytes)  {desc}")
            if info and info.code is not None:
                dumps.append(info)
        elif p.name.lower() == ROCKSTAR_CONTEXT and context is None:
            context = p
        ev.append(f"crash file: {p}")
    ctx = rockstar_context(context) if context is not None else []
    last = watch.last_with_game() if watch else None
    load = context_memory_load(ctx)
    if load is None and last is not None and last.mem_load_pct is not None:
        load = f"{last.mem_load_pct:.0f}%"
    info: dict = {}
    main = next((d for d in dumps if is_game_dump(d)), dumps[0] if dumps else None)
    if main is not None:
        name_native(main, game)
        info = {"crash_reason": main.describe(), "crash_site": main.site, "crash_asis": main.asis,
                "crash_memory_load": load, "crash_stack": stack_line(main)}
        ev.insert(0, f"crash summary: {crash_summary(main, load)} ({main.path.name})")
        if info["crash_stack"]:
            ev.insert(1, f"crash stack: {info['crash_stack']}")
    elif load:
        info = {"crash_memory_load": load}
    for d in dumps:
        if d is not main:
            ev.insert(1, f"crash: {d.describe()} ({d.path.name})")
    if ctx:
        ev.append("Rockstar crash log: " + "; ".join(ctx))
    ev += [f"Windows event: {e}" for e in events]
    for name in (V.SHV_LOG, V.SHVDN_LOG, V.ASI_LOG):
        ev += _tail(game, name)
    others = [n for n in LOGS if n not in (V.SHV_LOG, V.SHVDN_LOG, V.ASI_LOG)]
    for name in others:
        ev += _tail(game, name, 1)
    run_scripts = script_logs(game, since)
    for sp in run_scripts:
        try:
            lines = sp.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if lines:
            ev.append(f"scripts\\{sp.name}: {lines[-1].strip()}")
    if last is not None:
        ev.append(f"memory at {last.t:.0f} s (the last sample before the end): {memwatch.describe(vars(last))}")

    folder = log_dir(session.state) / "playtest" / f"crash-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        n = 1
        while folder.exists():
            n += 1
            folder = folder.with_name(f"{folder.name.split('~')[0]}~{n}")
        (folder / "mod-logs").mkdir(parents=True)
        logs = V.Logs(game)
        for name in LOGS:
            lf = logs.get(name)
            if lf:
                (folder / "mod-logs" / Path(lf.rel).name).write_text("\n".join(lf.lines[-200:]) + "\n",
                                                                     encoding="utf-8")
        for sp in run_scripts:  # the scripts' own logs too (scripts-<name>.log)
            try:
                tail = sp.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            except OSError:
                continue
            (folder / "mod-logs" / f"scripts-{sp.name}").write_text("\n".join(tail) + "\n", encoding="utf-8")
        if context is not None:
            shutil.copy2(context, folder / f"rockstar-{ROCKSTAR_CONTEXT}")
        (folder / "events.txt").write_text("\n\n".join(events) + "\n", encoding="utf-8")
        (folder / "dumps.txt").write_text("\n".join(dump_lines) + "\n", encoding="utf-8")
        summary = list(ev)
        if top_users:
            summary.append("using the most memory at the end: " + ", ".join(f"{n} ({memwatch.gb(mb)})"
                                                                            for n, mb in top_users))
        (folder / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
        memwatch.prune(folder.parent, "crash-*", KEEP_CRASH_DIRS)
        ev.append(f"crash details saved in {folder}")
    except OSError:
        log.debug("crash folder not written", exc_info=True)
        folder = None
    return ev, info, folder


# --------------------------------------------------------------------------------------------------- playtest
def _move_old_logs(game: Path, state: Path) -> list[str]:
    logs = V.Logs(game)
    dest = state / "playtest" / "previous"
    moved = []
    for name in LOGS:
        p = logs.path(name)
        if p is None or not p.is_file():
            continue
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / p.name
        try:
            if target.exists():
                target.unlink()
            shutil.move(str(p), str(target))
            moved.append(p.name)
        except OSError:
            continue  # a log the game still holds open: it gets overwritten by the next run anyway
    return moved


def playtest(session, timeout: float = 300.0, keep_running: bool = False,
             progress: Callable[[str], None] | None = None, *, deep: bool = False, probe_timeout: float = 330.0,
             settle: float = 20.0, poll: float = 2.0, launch_timeout: float = 180.0, close_timeout: float = 30.0,
             ops: ProcessOps | None = None, sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], float] = time.monotonic, mem: memwatch.NullMemory | None = None,
             sample_every: float = 2.0, exit_quiet: float = EXIT_QUIET,
             dump_timeout: float = DUMP_TIMEOUT) -> PlaytestReport:
    """Start the game, wait for story mode (``timeout`` seconds from launch), read the mods' logs, close the game.
    See the module docstring. ``progress(message)`` is called for each step. ``deep``: also run the in-game probe.
    ``mem``: the memory measurements (default: Windows' own for a real run, none with a fake ``ops``)."""
    from . import probe

    if mem is None:
        mem = memwatch.default_ops() if ops is None else memwatch.NullMemory()
    folder = log_dir(session.state) / "playtest"
    watch = memwatch.MemWatch(mem, _unique(folder / f"run-{time.strftime('%Y%m%d-%H%M%S')}.csv"), sample_every)
    if deep and session.game_dir():
        probe.remove(session)  # whatever a crashed earlier run left behind
    try:
        rep = _playtest(session, timeout, keep_running, progress, deep, probe_timeout, settle, poll, launch_timeout,
                        close_timeout, ops, sleep, clock, watch, exit_quiet, dump_timeout)
        rep.memory = watch.summary()
        save_report(session, rep)
        return rep
    finally:
        watch.close()
        memwatch.prune(folder, "run-*.csv", memwatch.KEEP_CSVS)
        if deep and session.game_dir():
            probe.remove(session)


def _unique(path: Path) -> Path:
    n, cand = 1, path
    while cand.exists():
        n += 1
        cand = path.with_name(f"{path.stem}-{n}{path.suffix}")
    return cand


def _wait_exited(ops, names, timeout: float, quiet: float, sleep, clock, poll: float, say) -> bool:
    """Wait until none of ``names`` runs any more, then ``quiet`` seconds (file locks, the next launch)."""
    end = clock() + timeout
    while any(ops.running(n) for n in names):
        if clock() > end:
            still = [n for n in names if ops.running(n)]
            say(f"Still running after {timeout:.0f} s: {', '.join(still)}")
            return False
        sleep(poll)
    if quiet > 0:
        sleep(quiet)
    return True


def save_report(session, rep: PlaytestReport) -> Path | None:
    """The last play test's report as <state>/playtest/last-report.json (for `leonida report`)."""
    data = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "status": rep.status, "message": rep.message,
            "timeline": rep.timeline, "notes": rep.notes, "evidence": rep.evidence,
            "story_mode_after": rep.story_mode_after, "ended_after": rep.ended_after,
            "crash_reason": rep.crash_reason, "crash_site": rep.crash_site, "crash_asis": rep.crash_asis,
            "crash_memory_load": rep.crash_memory_load, "crash_stack": rep.crash_stack, "crash_dir": rep.crash_dir, "memory": rep.memory,
            "free_ram_before_mb": rep.free_ram_before_mb, "free_commit_before_mb": rep.free_commit_before_mb,
            "results": [{"status": r.status, "code": r.code, "mod": r.mod, "message": r.message, "log": r.log,
                         "line": r.line} for r in rep.results]}
    p = session.state / "playtest" / "last-report.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        return None
    log.info("playtest result: %s: %s", rep.status, rep.message)
    return p


def _playtest(session, timeout, keep_running, progress, deep, probe_timeout, settle, poll, launch_timeout,
              close_timeout, ops, sleep, clock, watch: memwatch.MemWatch, exit_quiet: float = EXIT_QUIET,
              dump_timeout: float = DUMP_TIMEOUT) -> PlaytestReport:
    from . import probe

    if ops is None and sys.platform != "win32":
        return PlaytestReport(BLOCKED, "The play test starts GTA V Enhanced, so it only runs on Windows.")
    ops = ops or ProcessOps()
    game = session.game_dir()
    timeline: list[str] = []
    t0: float | None = None

    def say(msg: str) -> None:
        stamp = f"{clock() - t0:5.0f}s  " if t0 is not None else "        "
        timeline.append(stamp + msg)
        log.info("playtest: %s%s", stamp, msg)
        if progress:
            progress(msg)

    if not game or not game.is_dir():
        return PlaytestReport(BLOCKED, "The game folder isn't set. Run `leonida detect` first.")
    launcher = game / LAUNCHER
    if not launcher.is_file():
        return PlaytestReport(BLOCKED, f"{LAUNCHER} isn't in {game}. Start the game from its launcher once, or "
                                       "repair the game files.")
    installed = session.log.installed_mods()
    notes: list[str] = []
    if STS_ID not in installed:
        notes.append("Straight To Story Mode isn't installed: someone has to click Story Mode in the game's menu.")
    if SHVDN_ID not in installed:
        notes.append("Script Hook V .NET isn't installed, so its 'Loading scripts from' line can't prove that story "
                     "mode loaded; Leonida waits a fixed time instead.")

    def handlers_running() -> bool:
        return any(ops.running(n) for n in CRASH_HANDLERS)

    # 1. close GTA (a crash dump still being written is waited for first), then wait until it has all exited
    was_running = [n for n in GAME_PROCESSES + CRASH_HANDLERS if ops.running(n)]
    if was_running:
        wait_for_dumps(time.time() - 600, sleep, clock, poll, dump_timeout, say, handlers_running)
    for name in GAME_PROCESSES:
        if ops.running(name):
            say(f"Closing {name} ...")
            ok, out = ops.kill(name)
            if not ok:
                return PlaytestReport(BLOCKED, admin_help(launcher, runasadmin_flag(launcher)), timeline,
                                      evidence=[out] if out else [], notes=notes)
    end = clock() + close_timeout
    while any(ops.running(n) for n in GAME_PROCESSES):
        if clock() > end:
            return PlaytestReport(BLOCKED, admin_help(launcher, runasadmin_flag(launcher)), timeline, notes=notes)
        sleep(poll)
    if was_running:
        _wait_exited(ops, CRASH_HANDLERS, dump_timeout, exit_quiet, sleep, clock, poll, say)

    # 2. old logs aside
    moved = _move_old_logs(game, session.state)
    if moved:
        say(f"Moved the old logs aside: {', '.join(moved)}")
    plan = None
    if deep and SHVDN_ID not in installed:
        notes.append("The in-game probe (--deep) needs Script Hook V .NET; it was skipped.")
    elif deep:
        plan = probe.make_plan(session)
        notes += plan.notes
        probe.place(session, plan)
        say(f"Placed the in-game probe (scripts\\{probe.PROBE_FILE}: {len(plan.packs)} DLC pack(s)"
            + (f", {plan.car} handling" if plan.handling_mod else "") + "; removed after the run)")

    # pre-flight: enough free memory? Here a warning only: asking the user (close apps / play anyway) happens
    # before the play test starts (`leonida playtest`, the app's Play and Play test buttons).
    chk = memwatch.check_memory(watch.mem)
    free_before = chk.free_mb
    if chk.free_mb is not None:
        say(f"Free before the launch: RAM {memwatch.gb(chk.free_mb)}, commit {memwatch.gb(chk.free_commit_mb)}")
    if chk.low:
        notes.append(chk.text())
        say(f"Warning: {chk.text()}")

    # 3. start like the desktop shortcut
    wall_start = time.time()
    try:
        ops.start(launcher, game)
    except OSError as exc:
        hive = runasadmin_flag(launcher)
        if getattr(exc, "winerror", None) == 740 or hive:
            return PlaytestReport(BLOCKED, admin_help(launcher, hive), timeline, notes=notes, moved_logs=moved)
        return PlaytestReport(BLOCKED, f"Couldn't start {LAUNCHER}: {exc}", timeline, notes=notes, moved_logs=moved)
    t0 = clock()
    say(f"Started {LAUNCHER}")

    crash_info: dict = {}

    def report(status: str, message: str, **kw) -> PlaytestReport:
        return PlaytestReport(status, message, timeline, notes=notes, moved_logs=moved,
                              free_ram_before_mb=free_before, free_commit_before_mb=chk.free_commit_mb,
                              **crash_info, **kw)

    def game_pids() -> list[int]:
        """The game's PIDs, and a memory sample (every ``sample_every`` s) while at it."""
        pids = ops.running(GAME_EXE)
        watch.tick(clock() - t0, pids[0] if pids else None)
        return pids

    dumps_done = {"settled": False}

    def settle_dumps() -> None:
        if not dumps_done["settled"]:
            wait_for_dumps(wall_start, sleep, clock, poll, dump_timeout, say, handlers_running)
            dumps_done["settled"] = True

    def close() -> None:
        if keep_running:
            say("Left the game running (--keep-running)")
            return
        settle_dumps()  # never kill the game (or its handler) halfway through a crash dump
        for name in GAME_PROCESSES:
            if ops.running(name):
                ops.kill(name)
        say("Closed the game")
        if _wait_exited(ops, GAME_PROCESSES + CRASH_HANDLERS, max(close_timeout, dump_timeout), exit_quiet, sleep,
                        clock, poll, say) and exit_quiet > 0:
            say(f"Everything has exited (waited {exit_quiet:.0f} s more)")

    def crash_evidence(crashed: bool = True) -> list[str]:
        crash_info["ended_after"] = round(clock() - t0, 1)
        settle_dumps()  # read the dump once it's complete
        top = watch.mem.top_users() if crashed else None
        ev, info, folder = collect_crash(session, game, wall_start, ops.events(time.time() - wall_start + 60),
                                           watch, top)
        crash_info.update(info)
        crash_info["crash_dir"] = str(folder) if folder else None
        return ev

    # 4. wait for the game process, Script Hook V, story mode
    deadline = t0 + timeout
    seen_game = shv_at = story_at = None
    logs_seen: set[str] = set()
    while True:
        now = clock()
        alive = bool(game_pids())
        if alive and seen_game is None:
            seen_game = now
            say(f"{GAME_EXE} is running")
        if seen_game is None and now - t0 > min(launch_timeout, timeout):
            ops_ev = crash_evidence(crashed=False)
            close()
            return report(HANG, f"{GAME_EXE} didn't start within {launch_timeout:.0f} s of {LAUNCHER}. Is the "
                                "Rockstar launcher waiting for a sign-in or an update?", evidence=ops_ev)
        if seen_game is not None and not alive and story_at is None:
            sleep(poll)  # a launcher hand-over can briefly show no process
            if not ops.running(GAME_EXE):
                say(f"{GAME_EXE} closed before story mode")
                ev = crash_evidence()
                results = V.verify_session(session)
                close()
                return report(CRASHED, f"The game closed {now - seen_game:.0f} s after starting, before story mode "
                                       "loaded: a crash.", evidence=ev, results=results)
        logs = V.Logs(game)
        if shv_at is None and logs.get(V.SHV_LOG):
            shv_at = now
            say("Script Hook V loaded (ScriptHookV.log)")
        shvdn = logs.get(V.SHVDN_LOG)
        if shvdn and V.SHVDN_LOG not in logs_seen:
            logs_seen.add(V.SHVDN_LOG)
            say("Script Hook V .NET started (ScriptHookVDotNet.log)")
        if story_at is None:
            if SHVDN_ID in installed and shvdn and shvdn.find(STORY_MARK):
                story_at = now
                say("Story mode loaded ('Loading scripts from' in ScriptHookVDotNet.log)")
            elif SHVDN_ID not in installed and seen_game is not None:
                ref = shv_at if shv_at is not None else seen_game
                if now - ref >= (90 if shv_at is not None else 120):
                    story_at = now
                    say("Waited long enough for story mode (no Script Hook V .NET log to prove it)")
        if story_at is not None:
            break
        if now > deadline:
            ev = crash_evidence(crashed=False)
            results = V.verify_session(session)
            close()
            return report(HANG, f"No story mode within {timeout:.0f} s of starting the game "
                                f"({'Script Hook V loaded' if shv_at else 'no ScriptHookV.log either'}).",
                          evidence=ev, results=results)
        sleep(poll)

    # settle, still watching for a crash
    settle_end = clock() + settle
    while clock() < settle_end:
        if not game_pids():
            sleep(poll)
            if not ops.running(GAME_EXE):
                say(f"{GAME_EXE} closed right after story mode loaded")
                ev = crash_evidence()
                results = V.verify_session(session)
                close()
                return report(CRASHED, "The game closed right after story mode loaded: a crash.", evidence=ev,
                              results=results, story_mode_after=story_at - t0)
        sleep(poll)
    say(f"Settled for {settle:.0f} s")

    # the in-game probe: wait for its DONE / ABORTED line (it has its own timeouts; this is the outer one)
    probe_results = []
    if plan is not None:
        say("Waiting for the in-game probe ...")
        probe_end, next_note = clock() + probe_timeout, clock() + 30
        plog = probe.parse_log(probe.read_log(session))
        while not plog.finished and clock() < probe_end:
            if not game_pids():
                sleep(poll)
                if not ops.running(GAME_EXE):
                    say(f"{GAME_EXE} closed while the in-game probe ran")
                    ev = crash_evidence()
                    results = V.verify_session(session)
                    close()
                    return report(CRASHED, "The game closed while the in-game probe ran: a crash.", evidence=ev,
                                  results=results + probe.judge(plog, plan, finished_in_time=False),
                                  story_mode_after=story_at - t0)
            if clock() >= next_note:
                next_note = clock() + 30
                say(f"Probe still running: {plog.last_tick or 'no tick yet'}")
            sleep(poll)
            plog = probe.parse_log(probe.read_log(session))
        say(f"In-game probe {'finished: ' + (plog.done or 'aborted ' + str(plog.aborted)) if plog.finished else 'did not finish'}"
            f" ({plog.ticks} ticks, {len(plog.dlc)} DLC pack(s) checked)")
        probe_results = probe.judge(plog, plan, finished_in_time=plog.finished)

    # 5. read the logs, close
    results = V.verify_session(session) + probe_results
    close()
    failed = [r for r in results if r.status == V.FAILED]
    if failed:
        return report(FAILED, f"Story mode loaded, but {len(failed)} mod check(s) failed: "
                              + "; ".join(r.message for r in failed[:3]),
                      results=results, story_mode_after=story_at - t0)
    return report(PASSED, f"Story mode loaded after {story_at - t0:.0f} s and no mod reported an error.",
                  results=results, story_mode_after=story_at - t0)


# ------------------------------------------------------------------------------------------------------ series
@dataclass
class SeriesReport:
    runs: list[PlaytestReport] = field(default_factory=list)
    planned: int = 0
    interrupted: bool = False
    saved: Path | None = None

    def count(self, status: str) -> int:
        return sum(r.status == status for r in self.runs)

    @property
    def ok(self) -> bool:
        return bool(self.runs) and all(r.ok for r in self.runs) and not self.interrupted

    def sites(self) -> list[tuple[str, int]]:
        """[(crash site, how many runs crashed there)], most first."""
        counts: dict[str, int] = {}
        for r in self.runs:
            if r.status == CRASHED:
                counts[r.crash_site or "no crash dump"] = counts.get(r.crash_site or "no crash dump", 0) + 1
        return sorted(counts.items(), key=lambda kv: -kv[1])

    def verdict(self) -> str:
        """The series' last line: "VERDICT: 8 run(s): 6 passed, 0 failed, 2 crashed, 0 hang; 2× GTA5_...+0x..."."""
        sites = "; ".join(f"{n}× {site}" for site, n in self.sites())
        return f"VERDICT: {self.lines()[0]}" + (f"; {sites}" if sites else "")

    def memory_comparison(self) -> list[str]:
        """Free RAM / commit before the launch, by outcome: "passed runs: RAM 5.8-6.3 GB, commit 14.0-15.1 GB"."""
        def span(vals: list[float]) -> str:
            lo, hi = min(vals) / 1024, max(vals) / 1024
            return f"{lo:.1f} GB" if round(lo, 1) == round(hi, 1) else f"{lo:.1f}-{hi:.1f} GB"

        out = []
        for status in (PASSED, FAILED, CRASHED, HANG):
            rs = [r for r in self.runs if r.status == status]
            ram = [r.free_ram_before_mb for r in rs if r.free_ram_before_mb is not None]
            commit = [r.free_commit_before_mb for r in rs if r.free_commit_before_mb is not None]
            if ram or commit:
                parts = ([f"RAM {span(ram)}"] if ram else []) + ([f"commit {span(commit)}"] if commit else [])
                out.append(f"  {status} run(s) ({len(rs)}): {', '.join(parts)}")
        return ["Free before the launch:", *out] if out else []

    def lines(self) -> list[str]:
        n = len(self.runs)
        head = (f"{n} of {self.planned} run(s)" if n != self.planned else f"{n} run(s)") + ": " + ", ".join(
            f"{self.count(s)} {s}" for s in (PASSED, FAILED, CRASHED, HANG, BLOCKED) if s != BLOCKED or
            self.count(s))
        if self.interrupted:
            head += " (stopped early)"
        out = [head]
        story = sorted(r.story_mode_after for r in self.runs if r.story_mode_after is not None)
        if story:
            mid = story[len(story) // 2]
            span = f"{story[0]:.0f}" if round(story[0]) == round(story[-1]) else f"{story[0]:.0f}-{story[-1]:.0f}"
            out.append(f"Story mode after {span} s (median {mid:.0f} s).")
        out += self.memory_comparison()
        crashes = [r for r in self.runs if r.status == CRASHED]
        if crashes:
            out.append("Crashes at " + ", ".join(f"{r.ended_after:.0f} s" if r.ended_after is not None else "?"
                                                 for r in crashes) + " after the launch.")
            sites: dict[str, list[PlaytestReport]] = {}
            for r in crashes:
                sites.setdefault(r.crash_site or "no crash dump", []).append(r)
            for site, rs in sorted(sites.items(), key=lambda kv: -len(kv[1])):
                kind = rs[0].crash_reason.split(" in ")[0] if rs[0].crash_reason else ""
                loads = ", ".join(r.crash_memory_load for r in rs if r.crash_memory_load)
                out.append(f"  {len(rs)}× {site}" + (f"  {kind}" if kind else "")
                           + (f"  (memory load {loads})" if loads else ""))
        out.append("")
        for i, r in enumerate(self.runs, 1):
            when = (f"story mode {r.story_mode_after:.0f} s" if r.story_mode_after is not None and r.ok else
                    f"ended at {r.ended_after:.0f} s" if r.ended_after is not None else "")
            free = (f"free before: RAM {memwatch.gb(r.free_ram_before_mb)}, commit "
                    f"{memwatch.gb(r.free_commit_before_mb)}") if r.free_ram_before_mb is not None else ""
            out.append(f"Run {i:>2}  {r.status.upper():<8} {when:<20} {free}".rstrip())
            if r.status not in (PASSED, BLOCKED):
                out.append(f"          {r.message}")
            if r.crash_reason:
                out.append(f"          crash: {r.crash_reason}"
                           + (f" | memory load {r.crash_memory_load}" if r.crash_memory_load else ""))
            if r.crash_asis:
                out.append(f"          loaded ASIs: {', '.join(r.crash_asis)}")
            if r.crash_stack:
                out.append(f"          stack: {r.crash_stack}")
            m = r.memory or {}
            if m.get("peak"):
                out.append(f"          peak: {memwatch.describe(m['peak'])}")
            if r.status in (CRASHED, HANG) and m.get("last"):
                out.append(f"          at {m['last'].get('t', 0):.0f} s, just before: {memwatch.describe(m['last'])}")
            if m.get("csv"):
                out.append(f"          samples: {m['csv']}")
            if r.crash_dir:
                out.append(f"          crash details: {r.crash_dir}")
        return out


def playtest_series(session, repeat: int, progress: Callable[[str], None] | None = None, pause: float = 20.0,
                    sleep: Callable[[float], None] = time.sleep, **kw) -> SeriesReport:
    """Run the play test ``repeat`` times (the game is closed after each run, then ``pause`` seconds to let Windows
    free the memory) and sum it up. Stops at a BLOCKED run (nothing would change) and on Ctrl+C (the runs so far
    are kept). The summary is saved as <state>/logs/playtest/series-<time>.txt / .json."""
    kw.pop("keep_running", None)
    series = SeriesReport(planned=repeat)
    say = progress or (lambda msg: None)
    try:
        for i in range(1, repeat + 1):
            say(f"--- Run {i} of {repeat} ---")
            rep = playtest(session, progress=progress, sleep=sleep, **kw)
            series.runs.append(rep)
            say(f"Run {i} of {repeat}: {rep.message}")
            say(f"Run {i} {rep.verdict()}")
            if rep.status == BLOCKED:
                say("Stopping: this would block every run.")
                break
            if i < repeat and pause > 0:
                say(f"Waiting {pause:.0f} s before the next run ...")
                sleep(pause)
    except KeyboardInterrupt:
        series.interrupted = True
        say("Stopped (Ctrl+C).")
    series.saved = save_series(session, series)
    return series


def save_series(session, series: SeriesReport) -> Path | None:
    folder = log_dir(session.state) / "playtest"
    base = _unique(folder / f"series-{time.strftime('%Y%m%d-%H%M%S')}.txt")
    data = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "planned": series.planned,
            "interrupted": series.interrupted,
            "runs": [{"status": r.status, "message": r.message, "story_mode_after": r.story_mode_after,
                      "ended_after": r.ended_after, "crash_reason": r.crash_reason, "crash_site": r.crash_site,
                      "crash_asis": r.crash_asis, "crash_memory_load": r.crash_memory_load,
                      "crash_stack": r.crash_stack, "crash_dir": r.crash_dir,
                      "free_ram_before_mb": r.free_ram_before_mb,
                      "free_commit_before_mb": r.free_commit_before_mb, "memory": r.memory, "evidence": r.evidence,
                      "notes": r.notes} for r in series.runs]}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        base.write_text("\n".join(series.lines()) + "\n", encoding="utf-8")
        base.with_suffix(".json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        memwatch.prune(folder, "series-*.txt", 20)
        memwatch.prune(folder, "series-*.json", 20)
    except OSError:
        return None
    return base
