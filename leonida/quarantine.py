"""Leonida's test place: every download is checked before it can be installed.

  1. Malware scan with Windows Defender (MpCmdRun.exe -Scan -ScanType 3 -File <path> -DisableRemediation). A threat
     moves the file to ``<downloads>/_quarantine/`` with a ``<name>.reason.txt`` and it is never installed. No
     Defender (or a scan error): the file is "not scanned" and Leonida warns, but doesn't block.
  2. Static inspection, nothing is run: the archive's listing (zip / .oiv built in, 7z / rar via 7-Zip).
     Blocking flags ("flagged": never installed without ``--force-unsafe``):
       * a program or script (.exe .bat .cmd .ps1 .vbs .js .scr .com .msi) that the mod's manifest entry doesn't
         expect (its copies, its ``run`` installer, its rpf sources), or a file named like ``x.zip.exe``;
       * absolute or ``..`` paths (they'd land outside the game folder), and password-protected archives.
     Notes (shown, not blocking): unexpected .dll files and archives inside the archive.
  3. Trial install (``leonida scan``): the mod is installed with the real Installer into a throwaway fake game built
     from the real game's top-level names (0-byte stubs, the folders the mod needs) and a temporary state; the change
     list is reported, everything is rolled back and the fake game must equal its starting snapshot. Hand-made
     (guided), installer (run) and archive-editing (rpf) mods have nothing to try there: nothing of theirs runs.

Results are cached in ``<state>/scan-results.json`` by (path, size, mtime) with the file's sha256. Statuses:
"ok" (scanned, nothing found), "flagged", "quarantined", "not-scanned" (no Defender; inspection still applies).
Never writes or runs anything from a download, never writes test signatures.
"""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

CACHE_NAME = "scan-results.json"
QUARANTINE_DIR = "_quarantine"
DEFENDER_ENV = "LEONIDA_DEFENDER"   # path of MpCmdRun.exe (tests: a stub); "off" = no Defender
OK, FLAGGED, QUARANTINED, NOT_SCANNED = "ok", "flagged", "quarantined", "not-scanned"
LABELS = {OK: "scanned OK", FLAGGED: "flagged", QUARANTINED: "quarantined", NOT_SCANNED: "not scanned"}
PROGRAMS = (".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".scr", ".com", ".msi")
LIBRARIES = (".dll",)
ARCHIVES = (".zip", ".7z", ".rar")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class ScanResult:
    path: str
    size: int
    mtime_ns: int
    sha256: str
    status: str = NOT_SCANNED
    defender: str = "unavailable"        # clean | threat | unavailable | error
    threat: str = ""
    flags: list[str] = field(default_factory=list)    # blocking findings
    notes: list[str] = field(default_factory=list)    # shown, not blocking
    outside: list[str] = field(default_factory=list)  # members that would land outside the game folder
    trial: list[str] | None = None                    # the trial install's change list (None = not tried)
    trial_ok: bool | None = None
    scanned_at: str = ""

    @property
    def label(self) -> str:
        return LABELS.get(self.status, self.status)

    @property
    def blocked(self) -> bool:
        return self.status in (FLAGGED, QUARANTINED)

    def lines(self) -> list[str]:
        out = [f"{Path(self.path).name}: {self.label}"
               + (f" (Defender: {self.threat})" if self.threat else "")
               + ("" if self.defender != "unavailable" else " (Windows Defender not available)")]
        out += [f"  ! {f}" for f in self.flags]
        out += [f"  - {n}" for n in self.notes]
        out += [f"  outside the game folder: {o}" for o in self.outside]
        if self.trial is not None:
            out.append(f"  trial install: {'rolled back cleanly' if self.trial_ok else 'did NOT roll back cleanly'}"
                       f", {len(self.trial)} change(s)")
            out += [f"    {c}" for c in self.trial]
        return out


class ScanError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------- Defender
def defender_exe() -> Path | None:
    """MpCmdRun.exe ($LEONIDA_DEFENDER, "off" = none; else Program Files, else the newest platform folder)."""
    env = os.environ.get(DEFENDER_ENV)
    if env is not None:
        return None if env.strip().lower() in ("", "off", "0", "none") else Path(env)
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"
    if pf.is_file():
        return pf
    platform = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows Defender" / "Platform"
    found = sorted(platform.glob("*/MpCmdRun.exe")) if platform.is_dir() else []
    return found[-1] if found else None


_THREAT = re.compile(r"^\s*Threat\s*:\s*(.+?)\s*$", re.M | re.I)


def defender_scan(path: Path, exe: Path | None = None, timeout: float = 600) -> tuple[str, str]:
    """("clean" | "threat" | "unavailable" | "error", detail). MpCmdRun exits 2 both for a threat and for a failed
    scan, so the verdict comes from its output: "found no threats" / "Threat : <name>" / "found N threats"."""
    exe = exe or defender_exe()
    if exe is None or not Path(exe).is_file():
        return "unavailable", "Windows Defender (MpCmdRun.exe) not found"
    args = [str(exe), "-Scan", "-ScanType", "3", "-File", str(Path(path).resolve()), "-DisableRemediation"]
    if Path(exe).suffix.lower() == ".py":  # tests: a stub Defender written in Python
        import sys

        args = [sys.executable, *args]
    try:
        res = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout,
                             creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "error", f"Defender didn't run: {exc}"
    out = (res.stdout or "") + (res.stderr or "")
    threats = _THREAT.findall(out)
    if threats or re.search(r"found [1-9]\d* threats?", out, re.I):
        return "threat", ", ".join(dict.fromkeys(threats)) or "a threat"
    if res.returncode == 0 or re.search(r"found no threats", out, re.I):
        return "clean", ""
    detail = next((ln.strip() for ln in out.splitlines() if "fail" in ln.lower()), out.strip()[-200:])
    return "error", detail or f"exit code {res.returncode}"


# ----------------------------------------------------------------------------------------- static inspection
@dataclass
class Member:
    name: str
    encrypted: bool = False


def list_archive(path: Path, seven_zip: Path | None = None) -> list[Member]:
    """Every file in a zip / .oiv / 7z / rar with its "encrypted" mark. Never extracts or runs anything."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".zip", ".oiv"):
        try:
            with zipfile.ZipFile(path) as zf:
                return [Member(i.filename, bool(i.flag_bits & 0x1)) for i in zf.infolist() if not i.is_dir()]
        except zipfile.BadZipFile as exc:
            raise ScanError(f"not a valid zip: {exc}") from None
    if ext in (".7z", ".rar"):
        if not seven_zip:
            raise ScanError(f"install 7-Zip to look inside {ext} files")
        # a made-up password: a header-encrypted archive then fails instead of asking for one
        res = subprocess.run([str(seven_zip), "l", "-slt", "-ba", "-pLeonidaNoPassword", str(path)],
                             capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                             creationflags=_NO_WINDOW)
        text = (res.stdout or "") + (res.stderr or "")
        if res.returncode != 0:
            if re.search(r"wrong password|encrypted|password", text, re.I):
                return [Member("(the file list itself is password-protected)", True)]
            raise ScanError(f"7-Zip could not list it: {(res.stderr or '').strip()[:200]}")
        out, cur = [], {}
        for line in (res.stdout or "").splitlines() + [""]:
            if " = " in line:
                k, v = line.split(" = ", 1)
                cur[k.strip()] = v
            elif not line.strip() and cur:
                attrs = cur.get("Attributes", "")
                if cur.get("Path") and cur.get("Folder") != "+" and not attrs.startswith("D"):
                    out.append(Member(cur["Path"], cur.get("Encrypted") == "+"))
                cur = {}
        return out
    raise ScanError(f"{path.name} is not an archive")


def _norm(name: str) -> str:
    return name.replace("\\", "/")


def _escapes(name: str) -> bool:
    n = _norm(name)
    return n.startswith("/") or bool(re.match(r"^[A-Za-z]:", n)) or ".." in PurePosixPath(n).parts


def _double_ext(name: str) -> bool:
    """``x.zip.exe`` / ``readme.txt.scr``: a harmless-looking name with a program's extension at the end."""
    parts = PurePosixPath(_norm(name)).name.lower().split(".")
    return len(parts) >= 3 and "." + parts[-1] in PROGRAMS and len(parts[-2]) in (2, 3, 4) and parts[-2].isalnum() \
        and "." + parts[-2] in (".zip", ".rar", ".7z", ".txt", ".pdf", ".doc", ".jpg", ".png", ".mp4", ".ini",
                                ".asi", ".dll", ".oiv", ".rpf", ".xml")


def expected_members(mod, members: list[str], plan=None) -> set[str]:
    """Members the mod's manifest entry says it uses: the install plan's copies, its run installer, its rpf
    sources (put / putdir / texture / oiv)."""
    exp: set[str] = set()
    if plan is not None:
        exp |= {_norm(c.src).lower() for c in plan.copies}
        if plan.run_target:
            exp.add(_norm(plan.run_target).lower())
    if mod is None:
        return exp
    if getattr(mod, "run", None):
        exp |= {m.lower() for m in members if fnmatch.fnmatch(PurePosixPath(m).name.lower(), mod.run.lower())}
    for op in getattr(mod, "rpf", ()) or ():
        for key in ("oiv", "put", "texture"):
            if key in op:
                pat = str(op[key]).lower()
                exp |= {m.lower() for m in members if fnmatch.fnmatch(PurePosixPath(m).name.lower(), pat)}
        if "putdir" in op:
            d = _norm(str(op["putdir"])).lower().strip("/")
            exp |= {m.lower() for m in members if f"/{d}/" in "/" + m.lower()}
    return exp


def inspect(path: Path, mod=None, plan=None, seven_zip: Path | None = None) -> tuple[list[str], list[str], list[str]]:
    """(flags, notes, outside) for a download, from its name and its archive listing."""
    path = Path(path)
    flags, notes, outside = [], [], []
    if _double_ext(path.name):
        flags.append(f"the file name {path.name!r} hides a program behind another extension")
    ext = path.suffix.lower()
    if ext not in ARCHIVES + (".oiv",):
        if ext in PROGRAMS:
            run_ok = mod is not None and getattr(mod, "method", "") == "run" and (
                not getattr(mod, "run", None) or fnmatch.fnmatch(path.name.lower(), mod.run.lower()))
            # the author ships the mod as its own setup program and the manifest says so (e.g. OpenIV's installer)
            named = mod is not None and any(p.lower().endswith(ext) and fnmatch.fnmatch(path.name.lower(), p.lower())
                                            for p in getattr(mod, "archive", ()) for ext in PROGRAMS)
            if not (run_ok or named):
                flags.append(f"{path.name} is a program, and this mod doesn't install with one")
        return flags, notes, outside
    try:
        members = list_archive(path, seven_zip)
    except ScanError as exc:
        notes.append(f"couldn't look inside: {exc}")
        return flags, notes, outside
    names = [_norm(m.name) for m in members]
    exp = expected_members(mod, names, plan)
    if any(m.encrypted for m in members):
        flags.append("password-protected: Leonida can't see what's inside")
    for m in names:
        low = m.lower()
        suffix = PurePosixPath(low).suffix
        if _escapes(m):
            flags.append(f"{m}: an absolute or '..' path (it would land outside the game folder)")
            outside.append(m)
        if _double_ext(m):
            flags.append(f"{m}: a program hidden behind another extension")
        elif suffix in PROGRAMS and low not in exp:
            flags.append(f"{m}: a program or script this mod's install doesn't use")
        elif suffix in LIBRARIES and low not in exp:
            notes.append(f"{m}: a .dll the install doesn't copy (optional extra?)")
        elif suffix in ARCHIVES and low not in exp:
            notes.append(f"{m}: an archive inside the archive")
    if ext == ".oiv" or any(PurePosixPath(n).suffix.lower() == ".oiv" for n in names):
        outside += _oiv_outside(path, names)
    return flags, notes, sorted(set(outside))


def _oiv_outside(path: Path, names: list[str]) -> list[str]:
    """Targets in an .oiv's assembly.xml that leave the game folder (absolute / '..' paths). Only plain .oiv files
    (zips) are read; an .oiv inside a 7z/rar is listed but not opened."""
    import xml.etree.ElementTree as ET

    out = []
    try:
        with zipfile.ZipFile(path) as zf:
            packages = [zf.read("assembly.xml")] if "assembly.xml" in zf.namelist() else []
            for n in names:
                if n.lower().endswith(".oiv"):
                    import io

                    with zipfile.ZipFile(io.BytesIO(zf.read(n))) as inner:
                        if "assembly.xml" in inner.namelist():
                            packages.append(inner.read("assembly.xml"))
    except (zipfile.BadZipFile, KeyError, OSError):
        return out
    for data in packages:
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            continue
        for el in root.iter():
            target = (el.text or "").strip() if el.tag in ("add", "replace") else el.get("path", "")
            # OpenIV paths are relative to the game (or the archive) even with a leading "\": only a drive, a share
            # or ".." leaves the game folder
            rel = _norm(target)
            if target and (rel.startswith("//") or re.match(r"^/?[A-Za-z]:", rel)
                           or ".." in PurePosixPath(rel.lstrip("/")).parts):
                out.append(f".oiv -> {target}")
    return out


# --------------------------------------------------------------------------------------------- trial install
class _TrialUI:
    """Answers yes, never runs anything (a run-method installer isn't started), records the lines."""

    def __init__(self):
        self.lines: list[str] = []

    def info(self, msg):
        self.lines.append(msg)

    def warn(self, msg):
        self.lines.append("! " + msg)

    def confirm(self, msg, default=True):
        return True

    def wait_done(self, title, steps, folder):
        return True

    def launch(self, path):
        self.lines.append(f"(not started: {Path(path).name})")


def trial_install(mod, path: Path, manifest, game_dir: Path | None, seven_zip: Path | None = None
                  ) -> tuple[list[str] | None, bool | None, str]:
    """Install ``mod`` from ``path`` into a throwaway fake game, report the change list, roll back, compare.
    Returns (changes, rolled back cleanly, why it wasn't tried)."""
    if mod is None:
        return None, None, "no mod for this file"
    if mod.method not in ("copy", "generic"):
        return None, None, f"a {mod.method} mod: nothing of it runs in the trial"
    from .installer import Installer
    from .log import InstallLog
    from .snapshot import diff, take_snapshot

    with tempfile.TemporaryDirectory(prefix="leonida-trial-") as tmp:
        game = Path(tmp) / "game"
        game.mkdir()
        real = Path(game_dir) if game_dir else None
        if real is not None and real.is_dir():
            for p in real.iterdir():  # names only: nothing of the real game is read or copied
                if p.is_dir():
                    (game / p.name).mkdir(exist_ok=True)
                else:
                    (game / p.name).touch()
        before = take_snapshot(game)  # the mod's own folders (createDirs) are made, and logged, by the installer
        state = Path(tmp) / "state"
        inst = Installer(manifest, game, state, InstallLog(state / "install-log.json"), _TrialUI(),
                         seven_zip=seven_zip)
        try:
            step = inst.install(mod, Path(path))
        except Exception as exc:  # noqa: BLE001 - a failing trial is a finding, not a crash
            return [f"the trial install failed: {exc}"], False, ""
        changes = [f"{a.op} {a.path}" for a in step.actions] if step else []
        warnings, residual = inst.uninstall()
        clean = (residual is not None and residual.empty and diff(before, take_snapshot(game)).empty
                 and not warnings)
        return changes, clean, ""


# --------------------------------------------------------------------------------------------- the test place
def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class TestPlace:
    """Scans downloads and remembers the results (``<state>/scan-results.json``)."""

    __test__ = False  # not a pytest class

    def __init__(self, state: Path, downloads: Path, seven_zip: Path | None = None):
        self.state, self.downloads, self.seven_zip = Path(state), Path(downloads), seven_zip
        self.cache_path = self.state / CACHE_NAME
        self._cache: dict[str, dict] | None = None

    # -- cache
    @staticmethod
    def key(path: Path) -> str:
        st = Path(path).stat()
        return f"{os.path.normcase(str(Path(path).resolve()))}|{st.st_size}|{st.st_mtime_ns}"

    def _load(self) -> dict[str, dict]:
        if self._cache is None:
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self._cache = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._cache = {}
        return self._cache

    def _save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._load(), indent=1), encoding="utf-8")
            tmp.replace(self.cache_path)
        except OSError:
            pass

    def cached(self, path: Path) -> ScanResult | None:
        """The stored result for this exact file (same path, size and mtime), or None."""
        try:
            raw = self._load().get(self.key(path))
        except OSError:
            return None
        if not isinstance(raw, dict):
            return None
        try:
            return ScanResult(**raw)
        except TypeError:
            return None

    def status(self, path: Path) -> str | None:
        r = self.cached(path)
        return r.status if r else None

    # -- scanning
    def scan(self, path: Path, mod=None, plan=None, manifest=None, game_dir: Path | None = None,
             trial: bool = False, move: bool = True) -> ScanResult:
        path = Path(path)
        st = path.stat()
        res = ScanResult(str(path), st.st_size, st.st_mtime_ns, sha256_of(path),
                         scanned_at=time.strftime("%Y-%m-%d %H:%M"))
        key = self.key(path)
        res.defender, detail = defender_scan(path)
        if res.defender == "threat":
            res.threat = detail
        elif res.defender == "error":
            res.notes.append(f"Defender couldn't scan it: {detail}")
        res.flags, notes, res.outside = inspect(path, mod, plan, self.seven_zip)
        res.notes += notes
        if trial and res.defender != "threat" and not res.flags and manifest is not None:
            res.trial, res.trial_ok, why = trial_install(mod, path, manifest, game_dir, self.seven_zip)
            if why:
                res.notes.append(f"no trial install: {why}")
            elif res.trial_ok is False:
                res.flags.append("the trial install didn't roll back to the starting folder")
        if res.defender == "threat":
            res.status = QUARANTINED
            if move:
                res.path = str(self.quarantine(path, f"Windows Defender: {res.threat}"))
        elif res.flags:
            res.status = FLAGGED
        elif res.defender == "clean":
            res.status = OK
        else:
            res.status = NOT_SCANNED
        self._load()[key] = asdict(res)
        if res.status == QUARANTINED and move:  # remember the moved file too
            with contextlib.suppress(OSError):
                self._load()[self.key(Path(res.path))] = asdict(res)
        self._save()
        return res

    def ensure(self, path: Path, mod=None, plan=None) -> ScanResult:
        """The cached result, or a fresh scan (Defender + inspection; the trial install is ``leonida scan``'s)."""
        return self.cached(path) or self.scan(path, mod, plan)

    def quarantine(self, path: Path, reason: str) -> Path:
        q = self.downloads / QUARANTINE_DIR
        q.mkdir(parents=True, exist_ok=True)
        dest = q / path.name
        n = 1
        while dest.exists():
            dest = q / f"{path.stem}.{n}{path.suffix}"
            n += 1
        shutil.move(str(path), str(dest))
        dest.with_name(dest.name + ".reason.txt").write_text(
            f"{path.name} was moved here by Leonida V on {time.strftime('%Y-%m-%d %H:%M')}.\n{reason}\n"
            "Leonida never installs it. Delete it, or ask the mod's author.\n", encoding="utf-8")
        return dest
