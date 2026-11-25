"""After the game has been started once: read the mods' own log files and say which installed mods really loaded.

    results = verify_session(session)            # what the install log says is installed
    results = verify(game_dir, mods, install_log)

Each result is a :class:`VerifyResult` (Finding-like: ``level`` / ``code`` / ``message`` / ``mod``) with a ``status``:
OK (a log shows it loaded), FAILED (a log shows an error; ``line`` holds that log line), WARN (loaded with a problem,
or no proof either way), NOT_SEEN (no log written since this mod was installed: start the game first) or NO_LOG
(the mod writes nothing Leonida can read; check it in game). Read-only: it never writes into the game folder.

Log formats (sources in the comments next to each pattern): Script Hook V's ScriptHookV.log and its ASI loader's
asiloader.log, Script Hook V .NET (Enhanced)'s ScriptHookVDotNet.log, Menyoo's menyooLog.txt, DirectStorageFix.log,
Resource Extensions' optional ResourceExtensions.log and Ultimate ASI Loader's optional <loader>.log.
OpenRPF and NVE's onigiri loader write no log of their own; only asiloader.log can show that their .asi loaded.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .checks import ERROR, INFO, WARNING
from .log import ADD, EXT_ADD, InstallLog
from .manifest import Mod

OK, FAILED, WARN, NOT_SEEN, NO_LOG = "ok", "failed", "warning", "not-seen", "no-log"
_LEVEL = {OK: INFO, FAILED: ERROR, WARN: WARNING, NOT_SEEN: INFO, NO_LOG: INFO}
CLOCK_SLACK = 5.0                 # seconds: a log written this close to the install still counts as "after" it
MAX_LOG_BYTES = 8 * 1024 * 1024   # only the tail of bigger logs is read
MAX_LINES_PER_KIND = 8            # cap repeated failures of one kind per mod


@dataclass(frozen=True)
class VerifyResult:
    status: str
    code: str
    message: str
    mod: str | None = None   # mod id; None = about the logs in general
    log: str | None = None   # log file the result comes from (relative to the game folder)
    line: str | None = None  # the log line behind the result

    @property
    def level(self) -> str:
        return _LEVEL[self.status]


@dataclass
class LogFile:
    rel: str      # path relative to the game folder, as found on disk
    mtime: float  # POSIX seconds
    lines: list[str]

    def written(self) -> str:
        return datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d %H:%M")

    def find(self, pattern: re.Pattern) -> list[str]:
        return [ln for ln in self.lines if pattern.search(ln)]

    def first(self, pattern: re.Pattern) -> str | None:
        return next((ln for ln in self.lines if pattern.search(ln)), None)


class Logs:
    """Log files in the game folder, looked up case-insensitively by relative path. Read-only, cached."""

    def __init__(self, game_dir: Path):
        self.game = Path(game_dir)
        self._cache: dict[str, LogFile | None] = {}

    def path(self, rel: str) -> Path | None:
        path = self.game
        for part in PurePosixPath(rel).parts:
            if not path.is_dir():
                return None
            exact = path / part
            if exact.exists():
                path = exact
                continue
            path = next((p for p in path.iterdir() if p.name.lower() == part.lower()), None)
            if path is None:
                return None
        return path

    def get(self, rel: str) -> LogFile | None:
        key = rel.lower()
        if key not in self._cache:
            self._cache[key] = self._read(rel)
        return self._cache[key]

    def _read(self, rel: str) -> LogFile | None:
        path = self.path(rel)
        if path is None or not path.is_file():
            return None
        st = path.stat()
        with path.open("rb") as f:
            if st.st_size > MAX_LOG_BYTES:
                f.seek(st.st_size - MAX_LOG_BYTES)
            data = f.read()
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = data.decode("utf-16", errors="replace")
        else:
            text = data.decode("utf-8", errors="replace").lstrip("\ufeff")
        return LogFile(path.relative_to(self.game).as_posix(), st.st_mtime,
                       [ln.rstrip() for ln in text.splitlines() if ln.strip()])


# ------------------------------------------------------------------ install log helpers
def _parse_time(s: str | None) -> float | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def install_times(log: InstallLog | None) -> dict[str, float]:
    """mod id -> when its latest finished install step ended (POSIX seconds)."""
    out: dict[str, float] = {}
    for s in log.steps if log else []:
        if s.status == "done":
            t = _parse_time(s.finished or s.started)
            if t is not None:
                out[s.mod] = max(out.get(s.mod, 0.0), t)
    return out


def placed_files(log: InstallLog | None) -> dict[str, list[str]]:
    """mod id -> files its finished steps placed (relative POSIX paths), incl. files a guided/run step added."""
    out: dict[str, list[str]] = {}
    for s in log.steps if log else []:
        if s.status == "done":
            out.setdefault(s.mod, []).extend(a.path for a in s.actions
                                             if a.op in (ADD, EXT_ADD) and not a.path.endswith("/"))
    return out


# ------------------------------------------------------------------ per-mod context
@dataclass
class Ctx:
    logs: Logs
    mod: Mod
    installed_at: float | None
    asi: list[str]      # .asi file names of this mod in the game folder
    scripts: list[str]  # files this mod put in scripts/ (Script Hook V .NET scripts)

    def fresh(self, lf: LogFile | None) -> bool:
        return lf is not None and (self.installed_at is None or lf.mtime + CLOCK_SLACK >= self.installed_at)

    def result(self, status: str, code: str, message: str, lf: LogFile | None = None,
               line: str | None = None) -> VerifyResult:
        return VerifyResult(status, code, message, self.mod.id, lf.rel if lf else None, line)

    def not_seen(self, *names: str) -> VerifyResult:
        present = [lf for lf in (self.logs.get(n) for n in names) if lf]
        if present:
            lf = max(present, key=lambda x: x.mtime)
            return self.result(NOT_SEEN, "log-older-than-install",
                               f"{self.mod.name}: {lf.rel} is from {lf.written()}, before this mod was installed. "
                               "Start the game once, then check again.", lf)
        return self.result(NOT_SEEN, "no-log-yet",
                           f"{self.mod.name}: no {' / '.join(names)} yet. Start the game once, then check again.")


def _q(name: str) -> str:
    return re.escape(name)


# ------------------------------------------------------------------ Script Hook V
# ScriptHookV.log (game folder, rewritten at every start). Real Enhanced log pasted in itsjustcurtis/MenyooSP#643:
#   [02:39:17] INIT: Success, game version is VER_EN_1_0_1158_13
#   [02:39:17] INIT: Registering script 'Menyoo.asi' (0x00007FFDEC11EB20)
#   [02:40:52] CORE: Launching main() for 'Menyoo.asi' (0x00007FFDEC11EB20), id 4
#   [04:05:26] CORE: An exception occurred while executing 'Menyoo.asi', id 4
# Legacy builds print tags like VER_1_0_2245_0_STEAM (scripthookvdotnet/scripthookvdotnet#987).
# Unknown build (scripthookvdotnet/scripthookvdotnet#599): "[11:47:26] FATAL: Unknown game version".
SHV_LOG = "ScriptHookV.log"
SHV_SUCCESS = re.compile(r"success,?\s+game version is\s*(?P<ver>\S+)?", re.I)
SHV_UNKNOWN = re.compile(r"unknown game version", re.I)
SHV_FATAL = re.compile(r"\bFATAL:|\bERROR:", re.I)
SHV_HEADER = re.compile(r"SCRIPT HOOK \(build [^,]+,\s*v(?P<ver>[\d.]+(?:/[\d.]+)?)\)", re.I)

# asiloader.log, written by Script Hook V's ASI loader (xinput1_4.dll on Enhanced, dinput8.dll on Legacy). Real
# Enhanced logs (Parik27/V.Rainbomizer#141, itsjustcurtis/MenyooSP#282); no timestamps:
#   ASI: Loading "E:\...\Grand Theft Auto V Enhanced\NativeTrainer.asi"
#        "NativeTrainer.asi" => 00007FFDA8B80000
#        "V.Rainbomizer.asi" failed to load
ASI_LOG = "asiloader.log"
# Ultimate ASI Loader writes <loader name>.log only with [GlobalSets] DebugLog=1 (ThirteenAG/Ultimate-ASI-Loader,
# source/loader/plugins/plugins.cpp: "plugin %ls: %s%s" -> "plugin C:\...\X.asi: loaded" / ": error 126").
UAL_LOGS = ("dinput8.log", "version.log", "winmm.log", "dsound.log", "xinput1_4.log", "d3d11.log")
# .asi names of mods installed by their own installer or a guided step, looked for when the file is in the game folder
KNOWN_ASI = {"openrpf": ("OpenRPF.asi",), "nve": ("onigiri.asi",), "directstoragefix": ("DirectStorageFix.asi",),
             "resourceextensions": ("ResourceExtensions.asi",)}


def game_version_from_shv(tag: str | None) -> str | None:
    """'VER_EN_1_0_1158_13' -> '1.0.1158.13 (Enhanced)'; 'VER_1_0_2245_0_STEAM' -> '1.0.2245.0'."""
    if not tag:
        return None
    nums = re.findall(r"\d+", tag)
    if len(nums) < 3:
        return tag
    ver = ".".join(nums)
    return f"{ver} (Enhanced)" if "_EN_" in tag.upper() else ver


def check_scripthookv(c: Ctx) -> list[VerifyResult]:
    lf = c.logs.get(SHV_LOG)
    if not c.fresh(lf):
        return [c.not_seen(SHV_LOG)]
    line = lf.first(SHV_UNKNOWN)
    if line:
        return [c.result(FAILED, "shv-unknown-version",
                         f"{c.mod.name} does not support this game build ('Unknown game version'), so no script mod "
                         "will run. Get the Script Hook V release made for your build, or update the game.", lf, line)]
    line = lf.first(SHV_SUCCESS)
    if line:
        ver = game_version_from_shv(SHV_SUCCESS.search(line).group("ver"))
        hdr = lf.first(SHV_HEADER)
        own = f" Script Hook V v{SHV_HEADER.search(hdr).group('ver')}." if hdr else ""
        return [c.result(OK, "shv-ok", f"{c.mod.name} works on this game build" + (f": {ver}." if ver else ".") + own,
                         lf, line)]
    line = lf.first(SHV_FATAL)
    if line:
        return [c.result(FAILED, "shv-error", f"{c.mod.name} stopped with an error.", lf, line)]
    return [c.result(WARN, "shv-no-verdict",
                     f"{c.mod.name}: {lf.rel} has no 'Success, game version is ...' line. The game may have closed "
                     "early; start it again and wait for story mode to load.", lf)]


def check_asi(c: Ctx) -> list[VerifyResult]:
    """Did the ASI loader load this mod's .asi files, and did Script Hook V run them without an exception?"""
    if not c.asi:
        return []
    shv, loader = c.logs.get(SHV_LOG), c.logs.get(ASI_LOG)
    ual = [lf for lf in (c.logs.get(n) for n in UAL_LOGS) if c.fresh(lf)]
    loaders = ([loader] if c.fresh(loader) else []) + ual
    shv_fresh = c.fresh(shv)
    if not loaders and not shv_fresh:
        return [c.not_seen(ASI_LOG, SHV_LOG)]
    out: list[VerifyResult] = []
    for asi in c.asi:
        name = PurePosixPath(asi).name
        n = _q(name)
        loaded = re.compile(rf'"{n}"\s*=>\s*(?:0x)?[0-9a-f]+|plugin\s.*[\\/]{n}:\s*loaded', re.I)
        failed = re.compile(rf'"{n}"\s+failed to load|plugin\s.*[\\/]{n}:\s*error.*', re.I)
        shv_ran = re.compile(rf"(registering script|launching main\(\) for|started thread)\s+'{n}'", re.I)
        shv_exc = re.compile(rf"exception occurred while executing '{n}'", re.I)
        fail = next(((lf, ln) for lf in loaders for ln in lf.find(failed)), None)
        exc = shv.first(shv_exc) if shv_fresh else None
        ok = next(((lf, ln) for lf in loaders for ln in lf.find(loaded)), None)
        ran = shv.first(shv_ran) if shv_fresh else None
        if fail:
            out.append(c.result(FAILED, "asi-failed", f"{c.mod.name}: {name} failed to load. Usually a missing "
                                "Visual C++ runtime, a wrong-game (Legacy) build of the mod, or a blocked file.", *fail))
        elif exc:
            out.append(c.result(FAILED, "asi-exception", f"{c.mod.name}: {name} crashed while running "
                                "(Script Hook V caught an exception).", shv, exc))
        elif ok or ran:
            lf, ln = ok if ok else (shv, ran)
            out.append(c.result(OK, "asi-loaded", f"{c.mod.name}: {name} loaded.", lf, ln))
        elif loaders:
            lf = loaders[0]
            out.append(c.result(WARN, "asi-not-loaded",
                                f"{c.mod.name}: {name} is not in {lf.rel}, so the loader did not load it. "
                                "Is it in the folder with GTA5_Enhanced.exe?", lf))
        else:
            out.append(c.result(NOT_SEEN, "asi-not-mentioned",
                                f"{c.mod.name}: {name} is not mentioned in {SHV_LOG}, and there is no {ASI_LOG} to "
                                "check whether the loader loaded it.", shv))
    return out


# ------------------------------------------------------------------ Script Hook V .NET
# ScriptHookVDotNet.log next to ScriptHookVDotNet.asi, cleared at every start (Chiheb-Bacha/ScriptHookVDotNetEnhanced
# source/core/DllMain.cpp "Clear log from previous runs"). Line format from source/core/Log.cs:
# "[HH:mm:ss] [INFO] " / "[ERROR] " / "[WARNING] " / "[DEBUG] " + message. Messages (source/core/ScriptDomain.cs,
# source/core/Script.cs): "ScriptHookV .Net Enhanced 3.9.0.6 (1.1.0.6)", "Found 1 script(s) in X.dll resolved to API
# version ...", "Started script NS.Class.", "Aborted script NS.Class.", "Failed to instantiate script NS.Class because
# constructor threw an exception: ...", "Failed to load assembly X.dll: ...", "Failed to load script assembly ...",
# "Failed to compile X.cs ...", "Failed to load scripts in X.dll because ScriptHookVDotNet3.dll is missing ...",
# "Blocking script! Script NS.Class (file name: X.dll) was terminated ...". Real log: fredakilla/Quadcopter-Redux-Guide#5:
#   [18:52:53] [INFO] Found 1 script(s) in GTA5-Quadcopter.dll resolved to API version 3.7.0 (target API version: 3.6.0).
#   [18:53:28] [ERROR] The exception was thrown while executing the script Quadcopter.MainScript from "G:\...\GTA5-Quadcopter.dll".
#   [18:53:28] [WARNING] Aborted script Quadcopter.MainScript.
SHVDN_LOG = "ScriptHookVDotNet.log"
SHVDN_VERSION = re.compile(r"ScriptHookV \.Net Enhanced (?P<api>[\d.]+)(?: \((?P<ver>[\d.]+)\))?"
                           r"|Community Script Hook V \.NET (?P<old>[\d.]+)", re.I)
SHVDN_ERROR = re.compile(r"\[ERROR\]", re.I)
SHVDN_FOUND = re.compile(r"Found (?P<n>\d+) script\(s\) in (?P<file>.+?\.(?:dll|cs|vb))\b", re.I)
SHVDN_SCRIPT = re.compile(r"(?:Instantiating|Started|Aborted|Paused|Resumed) script (?P<cls>[\w.+`]+?)\.?(?: \.\.\.)?$", re.I)
SHVDN_FAIL = re.compile(r"Failed to (?:instantiate script|load (?:script )?assembly|load scripts in|compile)"
                        r"|exception was thrown while executing the script|Blocking script!|Aborted script", re.I)
# A line that names its file says whose it is: "(file name: X.dll)", 'from "...\\X.dll"', "script(s) in X.dll",
# "scripts in X.dll", "assembly X.dll", "compile(d) X.cs". File names may have spaces ("All MP Vehicles in SP.dll").
SHVDN_NAMED = re.compile(r'\(file name: (?P<a>[^)]+)\)|from "(?P<b>[^"]+)"'
                         r'|scripts?(?:\(s\))? in (?P<c>[^"]+?\.(?:dll|cs|vb))\b'
                         r'|\bassembly (?P<d>[^":]+?\.(?:dll|cs|vb))\b|\bcompiled? (?P<e>[^":]+?\.(?:cs|vb))\b', re.I)
SHVDN_CLASS_FILE = re.compile(r'script (?P<cls>[\w.+`]+) (?:\(file name: (?P<a>[^)]+)\)|from "(?P<b>[^"]+)")', re.I)
SHVDN_CLASS = re.compile(r"\bscript (?P<cls>[\w+`]+(?:\.[\w+`]+)*)", re.I)


def _base(path: str) -> str:
    return PurePosixPath(path.strip().replace("\\", "/")).name


def _named_files(ln: str) -> list[str]:
    return [_base(v) for m in SHVDN_NAMED.finditer(ln) for v in m.groupdict().values() if v]


def _stem_key(file_name: str) -> str:
    """'MapUpdates.3.cs' -> 'mapupdates', 'GTA6Hud.dll' -> 'gta6hud' (what a script's namespace or name looks like)."""
    return file_name.split(".")[0].lower()


def _shvdn_owner_map(lf: LogFile) -> dict[str, str]:
    """script class -> the file it came from. Script Hook V .NET Enhanced first lists every file ("Found N script(s)
    in F": the .cs files, then the .dll files), then starts all the scripts, mostly file by file, so neither the line
    order alone nor the class names alone say whose a script is (All MP Vehicles in SP.dll's scripts are SpawnMP,
    TrafficMP, ...; ViCrouch.dll's is ViExtras.Crouch). In this order of trust:
    1. a line that names both ("Script NS.Class (file name: X.dll)", 'the script NS.Class from "...\\X.dll"');
    2. a file whose name matches exactly as many started scripts as it has ("Found 6 script(s) in
       EnableAllinteriors.dll" and six EnableAllinteriors.* scripts);
    3. the scripts left, in the order they started, filled into the files left in the order they were found, by their
       counts, only when the two add up exactly (an older log that starts each file's scripts right after its
       "Found" line works the same way).
    A script the log doesn't place stays without a file (its failures are listed as unknown, never guessed)."""
    owners: dict[str, str] = {}
    found: dict[str, int] = {}
    classes: list[str] = []
    for ln in lf.lines:
        m = SHVDN_FOUND.search(ln)
        if m:
            found[_base(m.group("file"))] = found.get(_base(m.group("file")), 0) + int(m.group("n"))
            continue
        m = SHVDN_CLASS_FILE.search(ln)
        if m:
            owners.setdefault(m.group("cls"), _base(m.group("a") or m.group("b")))
        m = SHVDN_SCRIPT.search(ln)
        if m and re.search(r"\b(?:Instantiating|Started) script", ln, re.I) and m.group("cls") not in classes:
            classes.append(m.group("cls"))
    left = {f: n - sum(1 for c in classes if owners.get(c) == f) for f, n in found.items()}
    # 2. the file's name is the script's namespace (or the script's name), and the counts agree
    for f, n in left.items():
        if n <= 0:
            continue
        named = [c for c in classes if c not in owners and _stem_key(c) == _stem_key(f)]
        if len(named) == n:
            for c in named:
                owners[c] = f
            left[f] = 0
    # 3. the rest by order and counts
    rest = [c for c in classes if c not in owners]
    slots = [f for f, n in left.items() for _ in range(max(n, 0))]
    if rest and len(rest) == len(slots):
        owners.update(zip(rest, slots, strict=True))
    return owners


def _line_mentions_file(ln: str, file_name: str, owners: dict[str, str]) -> bool:
    """Is this log line about ``file_name``? A line that names a file belongs to that file only; otherwise the
    script class it names must belong to ``file_name`` (see ``_shvdn_owner_map``)."""
    named = _named_files(ln)
    if named:
        return any(n.lower() == file_name.lower() for n in named)
    if re.search(rf"(?<![\w.-]){_q(file_name)}(?![\w])", ln, re.I):
        return True
    m = SHVDN_SCRIPT.search(ln) or SHVDN_CLASS.search(ln)
    return bool(m and owners.get(m.group("cls"), "").lower() == file_name.lower())


def _unclaimed_failures(lf: LogFile) -> list[str]:
    """Script failure lines that name no file and whose script class has no known file: nobody's check can claim
    them, so Script Hook V .NET's own check lists them (instead of a guess at the wrong mod)."""
    owners = _shvdn_owner_map(lf)
    out = []
    for ln in lf.lines:
        if not SHVDN_FAIL.search(ln) or _named_files(ln):
            continue
        m = SHVDN_SCRIPT.search(ln) or SHVDN_CLASS.search(ln)
        if not (m and m.group("cls") in owners):
            out.append(ln)
    return out


def check_shvdn(c: Ctx) -> list[VerifyResult]:
    lf = c.logs.get(SHVDN_LOG)
    asi = [r for r in check_asi(c) if r.status in (FAILED, WARN)]  # the .NET log is the better proof that it loaded
    if not c.fresh(lf):
        return asi + [c.not_seen(SHVDN_LOG)]
    out = list(asi)
    ver_line = lf.first(SHVDN_VERSION)
    if ver_line:
        m = SHVDN_VERSION.search(ver_line)
        ver = m.group("ver") or m.group("api") or m.group("old")
        out.append(c.result(OK, "shvdn-ok", f"{c.mod.name} {ver} started.", lf, ver_line))
    elif lf.lines:
        out.append(c.result(OK, "shvdn-ok", f"{c.mod.name} started (it wrote {lf.rel}).", lf, lf.lines[0]))
    # Script failures belong to the mod that placed the script; only the ones nobody claims are listed here.
    errors = [ln for ln in lf.find(SHVDN_ERROR) if not re.search(r"script|assembly|compile", ln, re.I)]
    for ln in errors[:MAX_LINES_PER_KIND]:
        out.append(c.result(FAILED, "shvdn-error", f"{c.mod.name} logged an error.", lf, ln))
    for ln in _unclaimed_failures(lf)[:MAX_LINES_PER_KIND]:
        out.append(c.result(WARN, "script-failed-unknown", f"{c.mod.name}: a script failed, and the log doesn't say "
                            "which file it came from.", lf, ln))
    return out


def check_scripts(c: Ctx) -> list[VerifyResult]:
    """.NET scripts this mod put in scripts/: did Script Hook V .NET load and run them?"""
    files = [PurePosixPath(p).name for p in c.scripts
             if p.lower().endswith((".dll", ".cs", ".vb")) and p.count("/") == 1
             and not PurePosixPath(p).name.lower().startswith(("scripthookvdotnet", "nativeui", "lemonui"))]
    if not files:
        return []
    lf = c.logs.get(SHVDN_LOG)
    if not c.fresh(lf):
        return [c.not_seen(SHVDN_LOG)]
    owners = _shvdn_owner_map(lf)
    out: list[VerifyResult] = []
    for name in files:
        lines = [ln for ln in lf.lines if _line_mentions_file(ln, name, owners)]
        bad = [ln for ln in lines if SHVDN_FAIL.search(ln) or SHVDN_ERROR.search(ln)]
        found = next((ln for ln in lines if SHVDN_FOUND.search(ln)), None)
        if bad:
            out.append(c.result(FAILED, "script-failed", f"{c.mod.name}: script {name} failed.", lf, bad[0]))
        elif found:
            out.append(c.result(OK, "script-loaded", f"{c.mod.name}: script {name} loaded.", lf, found))
        else:
            out.append(c.result(WARN, "script-not-mentioned",
                                f"{c.mod.name}: {lf.rel} doesn't mention {name}, so Script Hook V .NET did not load "
                                "it. Is it directly in the scripts folder, and is it a script for this game?", lf))
    return out


# ------------------------------------------------------------------ Menyoo
# menyooLog.txt in the game folder, rewritten at every start (itsjustcurtis/MenyooSP, Solution/source/Util/FileLogger.cpp
# `FileLogger menyooLogObject("menyooLog.txt")`). Header + "[HH:MM:SS] LEVEL - message"; real log, MenyooSP#643:
#   Menyoo Version: 2.4.4
#   Game Version: Enhanced b1158.13
#   [02:39:17] INIT - GTAMemory Init Done
# Unrecognised builds print "Game Version: ... Unknown". Errors: "ERROR - Pattern not found: ...", "Unable to get
# MODULEINFO from GTA5_Enhanced.exe". The release zip ships a placeholder menyoolog.txt that starts "Menyoo failed to
# initialise." (Leonida doesn't copy it; if it is there, Menyoo never overwrote it).
MENYOO_LOG = "menyooLog.txt"
MENYOO_VERSION = re.compile(r"^Menyoo Version:\s*(?P<ver>\S+)", re.I)
MENYOO_GAME = re.compile(r"^Game Version:\s*(?P<game>.+)$", re.I)
MENYOO_INIT = re.compile(r"INIT - (GTAMemory Init Done|Deferred menu init done)", re.I)
MENYOO_ERROR = re.compile(r"\bERROR - |Unable to get MODULEINFO", re.I)
MENYOO_PLACEHOLDER = re.compile(r"Menyoo failed to initiali[sz]e", re.I)


def check_menyoo(c: Ctx) -> list[VerifyResult]:
    lf = c.logs.get(MENYOO_LOG)
    asi = check_asi(c)
    problems = [r for r in asi if r.status in (FAILED, WARN)]
    if lf and lf.first(MENYOO_PLACEHOLDER):
        return problems + [c.result(WARN, "menyoo-placeholder",
                                    f"{c.mod.name}: {lf.rel} is still the placeholder from Menyoo's zip, so Menyoo has "
                                    "not run. Check Script Hook V and asiloader.log.", lf, lf.lines[0])]
    if not c.fresh(lf):
        return problems + [r for r in asi if r.status == OK] + [c.not_seen(MENYOO_LOG)]
    out = list(problems)
    ver = lf.first(MENYOO_VERSION)
    game = lf.first(MENYOO_GAME)
    init = lf.first(MENYOO_INIT)
    if game and re.search(r"\bunknown\b", game, re.I):
        out.append(c.result(WARN, "menyoo-unknown-build",
                            f"{c.mod.name} doesn't know this game build; some features may not work.", lf, game))
    for ln in lf.find(MENYOO_ERROR)[:MAX_LINES_PER_KIND]:
        out.append(c.result(FAILED, "menyoo-error", f"{c.mod.name} logged an error.", lf, ln))
    if init:
        v = MENYOO_VERSION.search(ver).group("ver") if ver else ""
        out.append(c.result(OK, "menyoo-ok", f"{c.mod.name} {v} started.".replace("  ", " "), lf, init))
    elif not out:
        out.append(c.result(WARN, "menyoo-no-init",
                            f"{c.mod.name}: {lf.rel} has no 'Init Done' line yet. Load into story mode and check again.", lf))
    return out


# ------------------------------------------------------------------ DirectStorageFix
# DirectStorageFix.log, deleted and recreated in the game folder at every start (else %APPDATA%), spdlog pattern
# "[%H:%M:%S.%e] [%l] %v" (alloc8or/DirectStorageFix src/log.cpp, src/dllmain.cpp). Messages: "Init started",
# "Game build: {}.{}", "Init finished"; stops: "Module name is not GTA5_Enhanced.exe. Stopping.",
# "Game build < 1013. Stopping.", "DirectStorage not enabled ({}). Stopping."; errors: "Unknown game build",
# "Failed to find fiDeviceDirectStorage::RegisterFile", "Failed to initialize MinHook ({})", "Failed to create hook ...",
# "Failed to enable hooks ({})".
DSF_LOG = "DirectStorageFix.log"
DSF_OK = re.compile(r"\bInit finished\b", re.I)
DSF_STOP = re.compile(r"Stopping\.", re.I)
DSF_ERROR = re.compile(r"\[(?:error|critical)\]|Unknown game build|Failed to ", re.I)
DSF_BUILD = re.compile(r"Game build:\s*(?P<b>[\d.]+)", re.I)


def check_directstoragefix(c: Ctx) -> list[VerifyResult]:
    lf = c.logs.get(DSF_LOG)
    problems = [r for r in check_asi(c) if r.status in (FAILED, WARN)]
    if not c.fresh(lf):
        return problems + [c.not_seen(DSF_LOG)]
    err, stop, ok = lf.first(DSF_ERROR), lf.first(DSF_STOP), lf.first(DSF_OK)
    if err:
        return problems + [c.result(FAILED, "dsf-error", f"{c.mod.name} could not hook the game.", lf, err)]
    if stop:
        why = ("this game build doesn't need it" if "1013" in stop
               else "DirectStorage is off, so there is nothing to fix" if "not enabled" in stop.lower() else "see the log line")
        return problems + [c.result(WARN, "dsf-stopped", f"{c.mod.name} switched itself off: {why}.", lf, stop)]
    if ok:
        b = lf.first(DSF_BUILD)
        build = f" (game build {DSF_BUILD.search(b).group('b')})" if b else ""
        return problems + [c.result(OK, "dsf-ok", f"{c.mod.name} is active{build}.", lf, ok)]
    return problems + [c.result(WARN, "dsf-no-verdict", f"{c.mod.name}: {lf.rel} has no 'Init finished' line.", lf)]


# ------------------------------------------------------------------ Resource Extensions
# Optional ResourceExtensions.log (off by default; 2.4 changelog on gta5-mods.com/scripts/resource-extensions: "added
# optional ResourceExtensions.log to monitor RE/game versions and activation", "Partially Active means only part of a
# group is supported on your game version"). The exact line format isn't published, so only these words are used.
RE_LOG = "ResourceExtensions.log"
RE_PARTIAL = re.compile(r"partially active|unsupported|inactive|not supported|disabled", re.I)
RE_ERROR = re.compile(r"\berror\b|\bfailed\b", re.I)


def check_resourceextensions(c: Ctx) -> list[VerifyResult]:
    out = check_asi(c)
    lf = c.logs.get(RE_LOG)
    if not c.fresh(lf):
        return out
    for ln in lf.find(RE_ERROR)[:MAX_LINES_PER_KIND]:
        out.append(c.result(FAILED, "re-error", f"{c.mod.name} logged an error.", lf, ln))
    partial = lf.find(RE_PARTIAL)
    if partial:
        out.append(c.result(WARN, "re-partial", f"{c.mod.name}: {len(partial)} feature group(s) not fully active on "
                            "this game build; those limits stay vanilla.", lf, partial[0]))
    return out


# ------------------------------------------------------------------ dispatch
def check_default(c: Ctx) -> list[VerifyResult]:
    return check_asi(c) + check_scripts(c)


Checker = Callable[[Ctx], list[VerifyResult]]
CHECKERS: dict[str, Checker] = {
    "scripthookv": check_scripthookv,
    "shvdne": check_shvdn,
    "menyoo": lambda c: check_menyoo(c) + check_scripts(c),
    "directstoragefix": check_directstoragefix,
    "resourceextensions": check_resourceextensions,
}
GENERAL_LOGS = (SHV_LOG, ASI_LOG, SHVDN_LOG)


def _asi_names(mod: Mod, files: list[str], logs: Logs) -> list[str]:
    names = {p for p in files if p.lower().endswith(".asi") and "/" not in p}
    names |= {s.match for s in mod.files if s.type == "file" and s.match.lower().endswith(".asi") and s.to in (".", "")}
    names |= {n for n in KNOWN_ASI.get(mod.id, ()) if logs.path(n) is not None}
    seen: dict[str, str] = {}
    for n in sorted(names, key=str.lower):
        seen.setdefault(n.lower(), n)
    return list(seen.values())


def verify(game_dir: Path | str, mods: Iterable[Mod], log: InstallLog | None = None) -> list[VerifyResult]:
    """Results for the given (installed) mods, in their order, then general notes (mod=None) about old logs."""
    logs = Logs(Path(game_dir))
    times = install_times(log)
    placed = placed_files(log)
    out: list[VerifyResult] = []
    for mod in mods:
        files = placed.get(mod.id, [])
        c = Ctx(logs, mod, times.get(mod.id), _asi_names(mod, files, logs),
                [p for p in files if p.lower().startswith("scripts/")])
        res = CHECKERS.get(mod.id, check_default)(c)
        out += res or [c.result(NO_LOG, "no-log", f"{mod.name}: writes no log Leonida can read; check it in game.")]
    if times:
        last = max(times.values())
        for name in GENERAL_LOGS:
            lf = logs.get(name)
            if lf and lf.mtime + CLOCK_SLACK < last:
                out.append(VerifyResult(NOT_SEEN, "start-game-first",
                                        f"{lf.rel} is from {lf.written()}, older than the last install step. "
                                        "Start the game first, then check again.", None, lf.rel))
    return out


def verify_session(session) -> list[VerifyResult]:
    """verify() for what the session's install log says is installed (empty list when nothing is)."""
    game = session.game_dir()
    installed = session.log.installed_mods()
    if not game or not installed:
        return []
    mods = sorted((m for m in session.manifest.mods.values() if m.id in installed), key=lambda m: m.order)
    return verify(game, mods, session.log)
