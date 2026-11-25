"""The game's state for the launcher: is GTA V running, how long has it run, play time per pack, and how a session
ended (story mode reached, or closed before it: a crash at start-up).

Running is checked with one Toolhelp snapshot of the process list (ctypes, no tasklist process to start: cheap
enough for a timer). Play time lives in ``<state>/playtime.json``::

    {"core-plus": {"total_seconds": 5400, "sessions": 3, "last_played": "2026-11-25T18:02:11+00:00",
                   "last_seconds": 1800, "last_end": "story" | "before-story" | "unknown"}}

Story mode is reached when Script Hook V .NET's log (rewritten at every start) has its "Loading scripts from" line
from this session. Without Script Hook V .NET a session that ends within ``EARLY_EXIT`` seconds counts as closing
before story mode; a longer one is "unknown". Stdlib only.
"""
from __future__ import annotations

import contextlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

GAME_EXES = ("GTA5_Enhanced.exe", "GTA5.exe")   # the game itself
LAUNCHER_EXES = ("PlayGTAV.exe",)              # Rockstar's starter: runs briefly before the game appears
STATS_NAME = "playtime.json"
STORY_MARK = re.compile(r"Loading scripts from", re.I)
SHVDN_LOG = "ScriptHookVDotNet.log"
EARLY_EXIT = 90.0            # a session shorter than this, with no proof of story mode, ended before it
START_TIMEOUT = 180.0        # "Starting…" gives up when no game process appeared within this

STORY, BEFORE_STORY, UNKNOWN = "story", "before-story", "unknown"


# ---------------------------------------------------------------------------------------------- processes
def process_names() -> set[str] | None:
    """Lower-case names of every running process (Windows), None when they can't be listed."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class ENTRY(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ENTRY)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snap or snap == wintypes.HANDLE(-1).value:
            return None
        names: set[str] = set()
        try:
            e = ENTRY()
            e.dwSize = ctypes.sizeof(ENTRY)
            ok = k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                names.add(e.szExeFile.lower())
                ok = k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
        return names
    except (OSError, AttributeError, ValueError):
        return None


def running(names=GAME_EXES, listing: set[str] | None = None) -> list[str]:
    """Which of ``names`` run now (``listing``: a process_names() result to reuse). [] when nothing can be listed."""
    procs = process_names() if listing is None else listing
    if not procs:
        return []
    return [n for n in names if n.lower() in procs]


# ------------------------------------------------------------------------------------------- story mode
def story_reached(game_dir: Path | None, since: float) -> bool | None:
    """True when Script Hook V .NET logged loading its scripts after ``since`` (POSIX time), False when its log was
    written this session without that line, None when there is no such log from this session."""
    if not game_dir:
        return None
    p = Path(game_dir) / SHVDN_LOG
    try:
        if not p.is_file() or p.stat().st_mtime < since - 5:
            return None
        text = p.read_bytes()[-2_000_000:].decode("utf-8", errors="replace")
    except OSError:
        return None
    return bool(STORY_MARK.search(text))


def ended_how(game_dir: Path | None, started: float, ended: float) -> str:
    """STORY, BEFORE_STORY or UNKNOWN for a session that ran from ``started`` to ``ended``."""
    reached = story_reached(game_dir, started)
    if reached:
        return STORY
    if reached is False or ended - started < EARLY_EXIT:
        return BEFORE_STORY
    return UNKNOWN


# ------------------------------------------------------------------------------------------------ play time
@dataclass
class PlayStats:
    total_seconds: float = 0.0
    sessions: int = 0
    last_played: str | None = None    # ISO time the last session ended
    last_seconds: float = 0.0
    last_end: str | None = None


def load_stats(state: Path) -> dict[str, PlayStats]:
    p = Path(state) / STATS_NAME
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for pack, d in (raw.items() if isinstance(raw, dict) else ()):
        if isinstance(d, dict):
            with contextlib.suppress(TypeError):
                out[pack] = PlayStats(**{k: v for k, v in d.items() if k in PlayStats.__dataclass_fields__})
    return out


def stats_for(state: Path, pack: str | None) -> PlayStats:
    return load_stats(state).get(pack or "", PlayStats())


def record_session(state: Path, pack: str | None, started: float, ended: float, end: str) -> PlayStats:
    """Add a finished session to the pack's play time (``<state>/playtime.json``, written atomically)."""
    stats = load_stats(state)
    key = pack or ""
    st = stats.get(key, PlayStats())
    secs = max(0.0, ended - started)
    st.total_seconds += secs
    st.sessions += 1
    st.last_seconds = secs
    st.last_played = datetime.fromtimestamp(ended, timezone.utc).isoformat(timespec="seconds")
    st.last_end = end
    stats[key] = st
    p = Path(state) / STATS_NAME
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: v.__dict__ for k, v in stats.items()}, indent=1), encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        log.warning("could not save play time: %s", exc)
    log.info("game session: %s, %.0f s, %s", key or "(no pack)", secs, end)
    return st


def duration(seconds: float) -> str:
    """12 s / 7 min / 1 h 05 min."""
    s = int(round(max(0.0, seconds)))
    if s < 60:
        return f"{s} s"
    m = s // 60
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60:02d} min"


def clock(seconds: float) -> str:
    """0:42 / 12:05 / 1:02:03 (a running session)."""
    s = int(max(0.0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def when(iso: str | None, now: float | None = None) -> str:
    """"today 18:02" / "yesterday" / "3 days ago" / "2026-10-01" for a last-played time; "never" without one."""
    if not iso:
        return "never"
    try:
        t = datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return "never"
    now = time.time() if now is None else now
    local, today = datetime.fromtimestamp(t), datetime.fromtimestamp(now)
    days = (today.date() - local.date()).days
    if days <= 0:
        return f"today {local:%H:%M}"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return f"{local:%Y-%m-%d}"


# --------------------------------------------------------------------------------------------- the watch
class GameWatch:
    """The state machine behind Play / Starting… / Playing · Stop. ``poll()`` is called by a timer with what runs
    now; it returns an event when something changed: ("started", None), ("ended", (seconds, end)),
    ("gave-up", None) for a Play that never brought a game process up.

    It sees a game Leonida didn't start, too (started from Steam or the Rockstar launcher)."""

    def __init__(self, clock_fn=time.time):
        self.clock = clock_fn
        self.state = "idle"          # idle / starting / playing
        self.started: float | None = None
        self.asked: float | None = None
        self.names: list[str] = []

    def starting(self) -> None:
        """Play was clicked."""
        if self.state == "idle":
            self.state, self.asked = "starting", self.clock()

    def elapsed(self) -> float:
        return self.clock() - self.started if self.started is not None else 0.0

    def poll(self, game_running: list[str], launcher_running: bool = False) -> tuple[str, object] | None:
        now = self.clock()
        if game_running:
            self.names = list(game_running)
            if self.state != "playing":
                self.state, self.started = "playing", now
                return ("started", None)
            return None
        if self.state == "playing":
            started, self.state, self.started = self.started or now, "idle", None
            return ("ended", (started, now))
        if self.state == "starting" and not launcher_running and now - (self.asked or now) > START_TIMEOUT:
            self.state = "idle"
            return ("gave-up", None)
        return None
