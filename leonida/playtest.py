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

A game process that disappears before story mode is a crash: the report carries the evidence (new crash dumps,
Windows "Application Error"/"Application Hang" events for GTA5_Enhanced.exe, the logs' last lines). No story
mode within ``timeout`` is a hang. Stdlib only; process handling goes through ``ProcessOps`` (tests use a fake).
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

from . import verify as V

log = logging.getLogger(__name__)

GAME_EXE = "GTA5_Enhanced.exe"
LAUNCHER = "PlayGTAV.exe"
GAME_PROCESSES = (GAME_EXE, LAUNCHER)
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

    @property
    def ok(self) -> bool:
        return self.status == PASSED

    def summary(self) -> list[str]:
        lines = [f"{self.status.upper()}: {self.message}", *self.timeline]
        lines += [f"note: {n}" for n in self.notes]
        lines += [f"evidence: {e}" for e in self.evidence]
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
def crash_dirs(game: Path) -> list[Path]:
    dirs = [game, game / "CrashDumps"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "CrashDumps")
    return dirs


def crash_files(game: Path, since: float) -> list[Path]:
    """Crash dumps / crash logs written since ``since`` (POSIX time), newest first."""
    found: list[Path] = []
    for d in crash_dirs(game):
        if not d.is_dir():
            continue
        for p in d.iterdir():
            low = p.name.lower()
            interesting = low.endswith(".dmp") or low.startswith("crashlog") or (low.startswith("crash") and
                                                                                 low.endswith((".log", ".txt")))
            if d.name.lower() == "crashdumps" and d != game / "CrashDumps":
                interesting = interesting and low.startswith(GAME_EXE.lower())
            try:
                if interesting and p.is_file() and p.stat().st_mtime >= since - 5:
                    found.append(p)
            except OSError:
                continue
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def _tail(game: Path, name: str, n: int = 3) -> list[str]:
    lf = V.Logs(game).get(name)
    return [f"{lf.rel}: {ln}" for ln in lf.lines[-n:]] if lf else []


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
             clock: Callable[[], float] = time.monotonic) -> PlaytestReport:
    """Start the game, wait for story mode (``timeout`` seconds from launch), read the mods' logs, close the game.
    See the module docstring. ``progress(message)`` is called for each step. ``deep``: also run the in-game probe."""
    from . import probe

    if deep and session.game_dir():
        probe.remove(session)  # whatever a crashed earlier run left behind
    try:
        rep = _playtest(session, timeout, keep_running, progress, deep, probe_timeout, settle, poll, launch_timeout,
                        close_timeout, ops, sleep, clock)
        save_report(session, rep)
        return rep
    finally:
        if deep and session.game_dir():
            probe.remove(session)


def save_report(session, rep: PlaytestReport) -> Path | None:
    """The last play test's report as <state>/playtest/last-report.json (for `leonida report`)."""
    data = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "status": rep.status, "message": rep.message,
            "timeline": rep.timeline, "notes": rep.notes, "evidence": rep.evidence,
            "story_mode_after": rep.story_mode_after,
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
              close_timeout, ops, sleep, clock) -> PlaytestReport:
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

    # 1. close GTA
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

    def report(status: str, message: str, **kw) -> PlaytestReport:
        return PlaytestReport(status, message, timeline, notes=notes, moved_logs=moved, **kw)

    def close() -> None:
        if keep_running:
            say("Left the game running (--keep-running)")
            return
        for name in GAME_PROCESSES:
            if ops.running(name):
                ops.kill(name)
        say("Closed the game")

    def crash_evidence() -> list[str]:
        ev = [f"crash file: {p}" for p in crash_files(game, wall_start)]
        ev += [f"Windows event: {e}" for e in ops.events(time.time() - wall_start + 60)]
        for name in (V.SHV_LOG, V.SHVDN_LOG, V.ASI_LOG):
            ev += _tail(game, name)
        return ev

    # 4. wait for the game process, Script Hook V, story mode
    deadline = t0 + timeout
    seen_game = shv_at = story_at = None
    logs_seen: set[str] = set()
    while True:
        now = clock()
        alive = bool(ops.running(GAME_EXE))
        if alive and seen_game is None:
            seen_game = now
            say(f"{GAME_EXE} is running")
        if seen_game is None and now - t0 > min(launch_timeout, timeout):
            ops_ev = crash_evidence()
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
            ev = crash_evidence()
            results = V.verify_session(session)
            close()
            return report(HANG, f"No story mode within {timeout:.0f} s of starting the game "
                                f"({'Script Hook V loaded' if shv_at else 'no ScriptHookV.log either'}).",
                          evidence=ev, results=results)
        sleep(poll)

    # settle, still watching for a crash
    settle_end = clock() + settle
    while clock() < settle_end:
        if not ops.running(GAME_EXE):
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
            if not ops.running(GAME_EXE):
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
