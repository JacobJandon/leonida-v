"""Memory while the game loads: samples every couple of seconds, a CSV per play-test run, and a pre-flight check.

    mem = default_ops()                     # WinMemory on Windows, NullMemory elsewhere
    warning = preflight(mem)                # text when less than 6 GB of RAM is free, else None
    watch = MemWatch(mem, csv_path)         # watch.tick(seconds_since_launch, game_pid) from the play-test loop
    watch.summary()                         # {"csv", "samples", "peak": {...}, "last": {...}}

One sample: the system's free RAM and memory load, the commit charge and its limit (RAM + page file), the page
file's use, GTA5_Enhanced.exe's working set and private bytes, and dedicated GPU memory (the game's own and the
whole adapter's, from Windows' "GPU Process Memory" / "GPU Adapter Memory" counters; nvidia-smi as a fallback for
the adapter). All in MB; a value Windows won't give (no access, no counter) is empty, never a guess.

Read-only: only queries (GlobalMemoryStatusEx, GetProcessMemoryInfo, NtQuerySystemInformation, PDH, tasklist,
nvidia-smi). Stdlib only (ctypes).
"""

from __future__ import annotations

import contextlib
import csv
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

MB = 1024 * 1024
LOW_FREE_MB = 6 * 1024          # pre-flight warning below this much free RAM
LOW_COMMIT_MB = 12 * 1024       # ... or this much free commit (RAM + page file not yet promised)
KEEP_CSVS = 60                  # newest run CSVs kept in <state>/logs/playtest
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_SYS32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


@dataclass
class Sample:
    t: float                                  # seconds since the launcher started
    sys_free_mb: float | None = None          # available physical memory
    sys_total_mb: float | None = None
    mem_load_pct: float | None = None
    commit_used_mb: float | None = None       # commit charge (RAM + page file in use)
    commit_limit_mb: float | None = None
    pagefile_used_mb: float | None = None
    pagefile_total_mb: float | None = None
    game_ws_mb: float | None = None           # GTA5_Enhanced.exe working set
    game_private_mb: float | None = None      # GTA5_Enhanced.exe private bytes (its commit)
    game_gpu_mb: float | None = None          # the game's dedicated GPU memory
    gpu_used_mb: float | None = None          # the adapter's dedicated GPU memory in use (every process)


COLUMNS = ["time", *(f.name for f in fields(Sample))]
# for the peaks: the highest value, except free RAM (the lowest is the worst)
LOWEST = {"sys_free_mb"}


# ------------------------------------------------------------------------------------------------ memory ops
class NullMemory:
    """No measurements (other systems, tests that don't care)."""

    def system(self) -> dict:
        return {}

    def process(self, pid: int) -> dict:
        return {}

    def pagefile(self) -> dict:
        return {}

    def gpu(self, pid: int | None) -> dict:
        return {}

    def top_users(self, n: int = 8) -> list[tuple[str, float]]:
        return []

    def close(self) -> None:
        pass


class WinMemory(NullMemory):
    """The Windows measurements, with ctypes. Every call fails soft (an empty dict)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        self._c, self._w = ctypes, w
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.OpenProcess.restype = w.HANDLE
        self._k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self._k32.CloseHandle.argtypes = [w.HANDLE]
        self._handles: dict[int, int] = {}
        self._pdh = None              # (query, process counter, adapter counter), opened on first use
        self._pdh_failed = False
        self._smi = _nvidia_smi()

    # system: GlobalMemoryStatusEx
    def system(self) -> dict:
        c, w = self._c, self._w

        class MEMORYSTATUSEX(c.Structure):
            _fields_ = [("dwLength", w.DWORD), ("dwMemoryLoad", w.DWORD), ("ullTotalPhys", c.c_ulonglong),
                        ("ullAvailPhys", c.c_ulonglong), ("ullTotalPageFile", c.c_ulonglong),
                        ("ullAvailPageFile", c.c_ulonglong), ("ullTotalVirtual", c.c_ulonglong),
                        ("ullAvailVirtual", c.c_ulonglong), ("ullAvailExtendedVirtual", c.c_ulonglong)]

        st = MEMORYSTATUSEX()
        st.dwLength = c.sizeof(st)
        if not self._k32.GlobalMemoryStatusEx(c.byref(st)):
            return {}
        return {"sys_free_mb": st.ullAvailPhys / MB, "sys_total_mb": st.ullTotalPhys / MB,
                "mem_load_pct": float(st.dwMemoryLoad), "commit_limit_mb": st.ullTotalPageFile / MB,
                "commit_used_mb": (st.ullTotalPageFile - st.ullAvailPageFile) / MB}

    # one process: GetProcessMemoryInfo (PROCESS_MEMORY_COUNTERS_EX)
    def process(self, pid: int) -> dict:
        c, w = self._c, self._w

        class PMC(c.Structure):
            _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [
                (n, c.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                          "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                          "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                                          "PrivateUsage")]

        h = self._handles.get(pid)
        if h is None:
            # PROCESS_QUERY_LIMITED_INFORMATION (+ PROCESS_VM_READ where allowed); a game running as administrator
            # refuses both, and then there are simply no process values.
            h = self._k32.OpenProcess(0x1000 | 0x0010, False, pid) or self._k32.OpenProcess(0x1000, False, pid)
            if not h:
                return {}
            self._handles[pid] = h
        pmc = PMC()
        pmc.cb = c.sizeof(pmc)
        if not self._k32.K32GetProcessMemoryInfo(w.HANDLE(h), c.byref(pmc), pmc.cb):
            return {}
        return {"game_ws_mb": pmc.WorkingSetSize / MB, "game_private_mb": pmc.PrivateUsage / MB}

    # page file: NtQuerySystemInformation(SystemPageFileInformation = 18)
    def pagefile(self) -> dict:
        c = self._c
        try:
            ntdll = c.WinDLL("ntdll")
            buf = c.create_string_buffer(64 * 1024)
            ret = c.c_ulong()
            if ntdll.NtQuerySystemInformation(18, buf, len(buf), c.byref(ret)) != 0:
                return {}
            page = 4096
            raw, off, used, total = buf.raw[:ret.value], 0, 0, 0
            while off + 16 <= len(raw):
                nxt, size, inuse = (int.from_bytes(raw[off + i:off + i + 4], "little") for i in (0, 4, 8))
                total, used = total + size, used + inuse
                if not nxt:
                    break
                off += nxt
            return {"pagefile_used_mb": used * page / MB, "pagefile_total_mb": total * page / MB}
        except (OSError, AttributeError, ValueError):
            return {}

    # GPU: PDH "GPU Process Memory(pid_*)\Dedicated Usage" + "GPU Adapter Memory(*)\Dedicated Usage"
    def gpu(self, pid: int | None) -> dict:
        out: dict = {}
        values = self._pdh_values()
        if values is not None:
            proc, adapter = values
            if pid is not None:
                mine = [v for name, v in proc if name.lower().startswith(f"pid_{pid}_")]
                if mine:
                    out["game_gpu_mb"] = sum(mine) / MB
            if adapter:
                out["gpu_used_mb"] = sum(v for _, v in adapter) / MB
        if "gpu_used_mb" not in out and self._smi:
            used = _smi_used(self._smi)
            if used is not None:
                out["gpu_used_mb"] = used
        return out

    def _pdh_values(self):
        if self._pdh_failed:
            return None
        c, w = self._c, self._w
        try:
            pdh = c.WinDLL("pdh")
            if self._pdh is None:
                q = c.c_void_p()
                if pdh.PdhOpenQueryW(None, None, c.byref(q)) != 0:
                    raise OSError("PdhOpenQuery")
                counters = []
                for path in (r"\GPU Process Memory(*)\Dedicated Usage", r"\GPU Adapter Memory(*)\Dedicated Usage"):
                    h = c.c_void_p()
                    if pdh.PdhAddEnglishCounterW(q, c.c_wchar_p(path), None, c.byref(h)) != 0:
                        raise OSError("PdhAddEnglishCounter")
                    counters.append(h)
                self._pdh = (pdh, q, *counters)
            pdh, q, proc_c, adapter_c = self._pdh
            if pdh.PdhCollectQueryData(q) != 0:
                return None

            class ITEM(c.Structure):  # PDH_FMT_COUNTERVALUE_ITEM_W with a LONGLONG value
                _fields_ = [("szName", c.c_wchar_p), ("CStatus", w.DWORD), ("largeValue", c.c_longlong)]

            def read(counter) -> list[tuple[str, float]]:
                size, count = w.DWORD(0), w.DWORD(0)
                pdh.PdhGetFormattedCounterArrayW(counter, 0x400, c.byref(size), c.byref(count), None)
                if not size.value:
                    return []
                buf = (c.c_byte * size.value)()
                if pdh.PdhGetFormattedCounterArrayW(counter, 0x400, c.byref(size), c.byref(count), buf) != 0:
                    return []
                items = c.cast(buf, c.POINTER(ITEM))
                return [(items[i].szName or "", float(items[i].largeValue)) for i in range(count.value)
                        if items[i].CStatus in (0, 1)]

            return read(proc_c), read(adapter_c)
        except (OSError, AttributeError, ValueError):
            self._pdh_failed = True
            log.debug("GPU counters unavailable", exc_info=True)
            return None

    def top_users(self, n: int = 8) -> list[tuple[str, float]]:
        """The processes using the most memory (working set), summed per name: [(name, MB)]. Names only."""
        try:
            res = subprocess.run([str(_SYS32 / "tasklist.exe"), "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, errors="replace", timeout=20, check=False, creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return []
        return parse_top_users(res.stdout, n)

    def close(self) -> None:
        for h in self._handles.values():
            self._k32.CloseHandle(h)
        self._handles.clear()
        if self._pdh is not None:
            with contextlib.suppress(OSError):
                self._pdh[0].PdhCloseQuery(self._pdh[1])
            self._pdh = None


def default_ops() -> NullMemory:
    if sys.platform != "win32":
        return NullMemory()
    try:
        return WinMemory()
    except (OSError, AttributeError):
        return NullMemory()


def _nvidia_smi() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    cand = _SYS32 / "nvidia-smi.exe"
    return str(cand) if cand.is_file() else None


def _smi_used(exe: str) -> float | None:
    try:
        res = subprocess.run([exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=10, check=False, creationflags=_NO_WINDOW)
        vals = [float(x) for x in res.stdout.split() if x.replace(".", "", 1).isdigit()]
        return sum(vals) if vals else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def parse_top_users(text: str, n: int = 8) -> list[tuple[str, float]]:
    """tasklist /FO CSV /NH -> [(image name, MB)] summed per name, biggest first. Memory is like "1,234,567 K"
    (or "1.234.567 K" in other locales): the digits are what count."""
    per: dict[str, float] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 5:
            continue
        digits = re.sub(r"\D", "", row[4])
        if not digits:
            continue
        per[row[0]] = per.get(row[0], 0.0) + int(digits) / 1024
    return sorted(per.items(), key=lambda kv: -kv[1])[:n]


def gb(mb: float | None) -> str:
    return "?" if mb is None else f"{mb / 1024:.1f} GB"


LOW_HEADLINE = "GTA may crash while loading: free memory is low"
# Never offered for closing: Windows itself, security, the game, and Leonida (its own process included).
NEVER_CLOSE = {
    "system", "registry", "memory compression", "system idle process", "secure system", "smss.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "dwm.exe",
    "explorer.exe", "sihost.exe", "ctfmon.exe", "fontdrvhost.exe", "runtimebroker.exe", "searchhost.exe",
    "searchindexer.exe", "searchapp.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "textinputhost.exe", "taskhostw.exe", "conhost.exe", "dllhost.exe", "wmiprvse.exe", "audiodg.exe",
    "spoolsv.exe", "applicationframehost.exe", "lockapp.exe", "msmpeng.exe", "nissrv.exe", "mpdefendercoreservice.exe",
    "securityhealthservice.exe", "securityhealthsystray.exe", "smartscreen.exe", "werfault.exe", "taskmgr.exe",
    "gta5_enhanced.exe", "gta5.exe", "playgtav.exe", "leonidav.exe", "leonida.exe", "python.exe", "pythonw.exe",
    "py.exe", "rockstarservice.exe", "launcher.exe", "socialclubhelper.exe", "launcherpatcher.exe",
    # the stores the game may need, and helper processes that belong to other apps (no window of their own)
    "steam.exe", "steamwebhelper.exe", "steamservice.exe", "epicgameslauncher.exe", "epicwebhelper.exe",
    "msedgewebview2.exe", "crashpad_handler.exe",
}


@dataclass
class AppUse:
    name: str
    mb: float
    closeable: bool          # an app the user may choose to close (never Windows, security, the game or Leonida)


@dataclass
class MemoryCheck:
    """Free memory before the game starts. ``low``: under 6 GB of free RAM or 12 GB of free commit."""
    free_mb: float | None = None
    free_commit_mb: float | None = None
    commit_limit_mb: float | None = None
    reasons: list[str] = field(default_factory=list)
    apps: list[AppUse] = field(default_factory=list)   # the biggest memory users, by name

    @property
    def low(self) -> bool:
        return bool(self.reasons)

    @property
    def closeable(self) -> list[AppUse]:
        return [a for a in self.apps if a.closeable]

    def text(self) -> str:
        """The warning in one paragraph (empty when memory is fine)."""
        if not self.low:
            return ""
        msg = (f"{LOW_HEADLINE}: {' and '.join(self.reasons)}. With the full pack the game needs about "
               f"{gb(LOW_FREE_MB)} of free RAM and {gb(LOW_COMMIT_MB)} of free commit (RAM + page file) while it "
               "loads. Close other apps first, or use the Performance variant.")
        if self.apps:
            msg += " Using the most memory now: " + ", ".join(f"{a.name} ({gb(a.mb)})" for a in self.apps) + "."
        return msg


def _own_names() -> set[str]:
    return {Path(sys.executable).name.lower(), Path(sys.argv[0]).name.lower() if sys.argv and sys.argv[0] else ""}


def check_memory(mem: NullMemory, free_threshold: float = LOW_FREE_MB,
                 commit_threshold: float = LOW_COMMIT_MB, n: int = 8) -> MemoryCheck:
    """Is there enough free memory to load the game? Names the biggest memory users when there isn't."""
    sysv = mem.system()
    chk = MemoryCheck(free_mb=sysv.get("sys_free_mb"), commit_limit_mb=sysv.get("commit_limit_mb"))
    if sysv.get("commit_limit_mb") is not None and sysv.get("commit_used_mb") is not None:
        chk.free_commit_mb = sysv["commit_limit_mb"] - sysv["commit_used_mb"]
    if chk.free_mb is not None and chk.free_mb < free_threshold:
        chk.reasons.append(f"{gb(chk.free_mb)} of RAM free (under {gb(free_threshold)})")
    if chk.free_commit_mb is not None and chk.free_commit_mb < commit_threshold:
        chk.reasons.append(f"{gb(chk.free_commit_mb)} of commit free (under {gb(commit_threshold)})")
    if chk.low:
        never = NEVER_CLOSE | _own_names()
        chk.apps = [AppUse(name, mb, name.lower() not in never) for name, mb in mem.top_users(n)]
    return chk


def preflight(mem: NullMemory, threshold_mb: float = LOW_FREE_MB) -> tuple[float | None, str | None]:
    """(free RAM in MB, the low-memory warning or None). See ``check_memory``."""
    chk = check_memory(mem, free_threshold=threshold_mb)
    return chk.free_mb, (chk.text() or None)


def graceful_close(name: str) -> str:
    """Ask every window of ``name`` to close, like clicking its X (``taskkill /IM`` without /F: never forced)."""
    if name.lower() in NEVER_CLOSE | _own_names():
        return f"{name} is never closed by Leonida."
    try:
        res = subprocess.run([str(_SYS32 / "taskkill.exe"), "/IM", name], capture_output=True, text=True,
                             errors="replace", timeout=20, check=False, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return (res.stdout + res.stderr).strip()


def is_running(name: str) -> bool:
    try:
        res = subprocess.run([str(_SYS32 / "tasklist.exe"), "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {name}"],
                             capture_output=True, text=True, errors="replace", timeout=20, check=False,
                             creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return any(row and row[0].lower() == name.lower() for row in csv.reader(io.StringIO(res.stdout)))


def close_apps(names: list[str], timeout: float = 15.0, close=graceful_close, running=is_running,
               sleep=time.sleep, clock=time.monotonic) -> tuple[list[str], list[str]]:
    """Close the apps the user picked, gracefully (their own close, so they can save; never forced), and wait up
    to ``timeout`` s for them to exit. Returns (closed, still running). Windows, security, the game and Leonida are
    never closed whatever is passed in. An app that only hides in the tray stays running: the user closes it."""
    picked = [n for n in dict.fromkeys(names) if n.lower() not in NEVER_CLOSE | _own_names()]
    for name in picked:
        log.info("closing %s at the user's request (graceful)", name)
        close(name)
    end = clock() + timeout
    left = [n for n in picked if running(n)]
    while left and clock() < end:
        sleep(1.0)
        left = [n for n in left if running(n)]
    return [n for n in picked if n not in left], left


# ---------------------------------------------------------------------------------------------- the watch
class MemWatch:
    """Samples every ``every`` seconds (``tick`` is called from the play-test loop) into a CSV, written as it
    goes, so a run that ends badly still leaves its numbers."""

    def __init__(self, mem: NullMemory, csv_path: Path | None, every: float = 2.0) -> None:
        self.mem, self.csv_path, self.every = mem, csv_path, every
        self.samples: list[Sample] = []
        self._last_t: float | None = None
        self._fh = None
        self._writer = None

    def tick(self, t: float, pid: int | None, force: bool = False) -> Sample | None:
        if type(self.mem) is NullMemory:
            return None
        if not force and self._last_t is not None and t - self._last_t < self.every - 1e-6:
            return None
        self._last_t = t
        values: dict = {}
        for part in (self.mem.system(), self.mem.pagefile(), self.mem.process(pid) if pid else {},
                     self.mem.gpu(pid)):
            values.update(part)
        s = Sample(t=round(t, 1), **{k: round(v, 1) for k, v in values.items()
                                     if k in Sample.__dataclass_fields__ and v is not None})
        self.samples.append(s)
        self._write(s)
        return s

    def _write(self, s: Sample) -> None:
        if self.csv_path is None:
            return
        try:
            if self._fh is None:
                self.csv_path.parent.mkdir(parents=True, exist_ok=True)
                self._fh = open(self.csv_path, "w", newline="", encoding="utf-8")  # noqa: SIM115 - kept open
                self._writer = csv.writer(self._fh)
                self._writer.writerow(COLUMNS)
            row = asdict(s)
            self._writer.writerow([time.strftime("%H:%M:%S"), *("" if row[c] is None else row[c]
                                                                for c in COLUMNS[1:])])
            self._fh.flush()
        except OSError:
            log.debug("memory CSV not written", exc_info=True)
            self.csv_path = None

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        self.mem.close()

    def peak(self) -> dict:
        out: dict = {}
        for name in COLUMNS[2:]:
            vals = [getattr(s, name) for s in self.samples if getattr(s, name) is not None]
            if vals:
                out[name] = min(vals) if name in LOWEST else max(vals)
        return out

    def last_with_game(self) -> Sample | None:
        """The last sample taken while the game was running (its values just before it closed or crashed)."""
        for s in reversed(self.samples):
            if s.game_private_mb is not None or s.game_ws_mb is not None:
                return s
        return self.samples[-1] if self.samples else None

    def summary(self) -> dict:
        if not self.samples:
            return {}
        last = self.last_with_game()
        return {"csv": str(self.csv_path) if self.csv_path else None, "samples": len(self.samples),
                "peak": self.peak(), "last": asdict(last) if last else {}}


def describe(values: dict) -> str:
    """'game 9.1 GB private / 6.8 GB in RAM, free RAM 1.2 GB, commit 25.3 of 32.3 GB, ...' for a peak/last dict."""
    v = values or {}
    parts = []
    if v.get("game_private_mb") is not None or v.get("game_ws_mb") is not None:
        parts.append(f"game {gb(v.get('game_private_mb'))} private / {gb(v.get('game_ws_mb'))} in RAM")
    if v.get("sys_free_mb") is not None:
        parts.append(f"free RAM {gb(v.get('sys_free_mb'))}")
    if v.get("commit_used_mb") is not None:
        parts.append(f"commit {gb(v.get('commit_used_mb'))} of {gb(v.get('commit_limit_mb'))}")
    if v.get("pagefile_used_mb") is not None:
        parts.append(f"page file {gb(v.get('pagefile_used_mb'))} of {gb(v.get('pagefile_total_mb'))}")
    if v.get("game_gpu_mb") is not None or v.get("gpu_used_mb") is not None:
        gpu = f"GPU {gb(v.get('gpu_used_mb'))}"
        if v.get("game_gpu_mb") is not None:
            gpu += f" (game {gb(v.get('game_gpu_mb'))})"
        parts.append(gpu)
    return ", ".join(parts) or "no memory values"


def prune(folder: Path, pattern: str, keep: int) -> None:
    """Keep only the newest ``keep`` entries matching ``pattern`` (files or folders) in ``folder``."""
    try:
        items = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for p in items[keep:]:
        try:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        except OSError:
            continue
