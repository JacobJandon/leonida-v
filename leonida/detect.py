"""Find GTA V Enhanced, read its version, and check the PC (GPU, prerequisites, 7-Zip)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import string
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

GAME_DIR_NAMES = (
    "Grand Theft Auto V Enhanced",
    "GTAV Enhanced",
    "GTA V Enhanced",
    "GTAVEnhanced",
    # GTA V Legacy (the original PC version): Steam / Rockstar "Grand Theft Auto V", Epic "GTAV"
    "Grand Theft Auto V",
    "GTAV",
    "GTA V",
)
ENHANCED, LEGACY = "enhanced", "legacy"
EDITIONS = (ENHANCED, LEGACY)
# The exe tells the edition apart: GTA5_Enhanced.exe (DirectX 12, builds 1.0.8xx-1.0.1xxx) vs GTA5.exe (Legacy,
# DirectX 11, builds 1.0.3xxx).
EDITION_EXES = {ENHANCED: ("GTA5_Enhanced.exe",), LEGACY: ("GTA5.exe",)}
EDITION_NAMES = {ENHANCED: "GTA V Enhanced", LEGACY: "GTA V Legacy"}
ALL_EXES = tuple(e for names in EDITION_EXES.values() for e in names)


@dataclass(frozen=True)
class GameInstall:
    path: Path
    source: str  # steam / epic / rockstar / common / manual
    exe: Path
    version: str | None
    edition: str | None = None  # "enhanced" / "legacy" (from the exe)

    @property
    def edition_name(self) -> str:
        return EDITION_NAMES.get(self.edition or "", "GTA V")


def find_exe(directory: Path, exe_names: tuple[str, ...]) -> Path | None:
    directory = Path(directory)
    if not directory.is_dir():
        return None
    lower = {p.name.lower(): p for p in directory.iterdir() if p.is_file()}
    for name in exe_names:
        hit = lower.get(name.lower())
        if hit:
            return hit
    return None


def is_game_dir(directory: Path, exe_names: tuple[str, ...]) -> bool:
    return find_exe(directory, exe_names) is not None


def edition_of_exe(exe: Path | str | None) -> str | None:
    """"enhanced" / "legacy" from the exe's file name, None for anything else."""
    name = Path(exe).name.lower() if exe else ""
    return next((ed for ed, names in EDITION_EXES.items() if name in {n.lower() for n in names}), None)


def edition_of(directory: Path | str | None) -> str | None:
    """The edition of the game in ``directory`` (Enhanced wins if a folder somehow holds both exes), or None."""
    if not directory:
        return None
    for ed in EDITIONS:
        if find_exe(Path(directory), EDITION_EXES[ed]):
            return ed
    return None


# --- version ---------------------------------------------------------------
def parse_version(text: str | None) -> tuple[int, ...] | None:
    if not text:
        return None
    nums = re.findall(r"\d+", text)
    return tuple(int(n) for n in nums) if nums else None


def compare_versions(a: str | None, b: str | None) -> int | None:
    """-1 if a<b, 0 if equal, 1 if a>b, None if either is unknown."""
    va, vb = parse_version(a), parse_version(b)
    if va is None or vb is None:
        return None
    length = max(len(va), len(vb))
    va += (0,) * (length - len(va))
    vb += (0,) * (length - len(vb))
    return (va > vb) - (va < vb)


def exe_version(exe: Path) -> str | None:
    """File version of a Windows exe (e.g. '1.0.1158.13'); None elsewhere or on failure."""
    override = os.environ.get("LEONIDA_FAKE_GAME_VERSION")
    if override:
        return override
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        ver = ctypes.WinDLL("version", use_last_error=True)
        size = ver.GetFileVersionInfoSizeW(str(exe), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(exe), 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None

        class VSFixedFileInfo(ctypes.Structure):
            _fields_ = [(n, wintypes.DWORD) for n in (
                "dwSignature", "dwStrucVersion", "dwFileVersionMS", "dwFileVersionLS",
                "dwProductVersionMS", "dwProductVersionLS", "dwFileFlagsMask", "dwFileFlags",
                "dwFileOS", "dwFileType", "dwFileSubtype", "dwFileDateMS", "dwFileDateLS")]

        info = ctypes.cast(ptr, ctypes.POINTER(VSFixedFileInfo)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:  # noqa: BLE001 - version is best effort
        return None


def file_description(path: Path) -> str | None:
    """'<FileDescription or ProductName>, <CompanyName>' from a Windows DLL/exe's version info (read-only);
    None elsewhere, without version info, or on failure. Used to tell the user what an unknown DLL is."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        ver = ctypes.WinDLL("version", use_last_error=True)
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return None
        ptr, length = ctypes.c_void_p(), wintypes.UINT()
        langs = []
        if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) and length.value:
            arr = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * (length.value // 2))).contents
            langs = [f"{arr[i]:04x}{arr[i + 1]:04x}" for i in range(0, len(arr) - 1, 2)]
        langs += ["040904b0", "040904e4"]

        def value(name: str) -> str | None:
            for lang in langs:
                p, n = ctypes.c_void_p(), wintypes.UINT()
                if ver.VerQueryValueW(buf, f"\\StringFileInfo\\{lang}\\{name}", ctypes.byref(p), ctypes.byref(n)) and n.value:
                    text = ctypes.wstring_at(p, n.value).rstrip("\0").strip()
                    if text:
                        return text
            return None

        what = value("FileDescription") or value("ProductName")
        company = value("CompanyName")
        parts = [x for x in (what, company) if x]
        return ", ".join(parts)[:120] or None
    except Exception:  # noqa: BLE001 - best effort
        return None


# --- store discovery ---------------------------------------------------------
def parse_vdf_library_paths(text: str) -> list[str]:
    """Library folder paths from Steam's libraryfolders.vdf."""
    return [m.replace("\\\\", "\\") for m in re.findall(r'"path"\s+"([^"]+)"', text)]


def _registry_views() -> tuple[int, ...]:
    """Open flags for the 64-bit and the 32-bit registry view.

    A 32-bit Python is silently redirected to WOW6432Node unless it asks for the 64-bit view, so try both.
    """
    import winreg

    return (winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ | winreg.KEY_WOW64_32KEY)


def _winreg_value(root_name: str, key: str, value: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    root = getattr(winreg, root_name)
    for access in _registry_views():
        try:
            with winreg.OpenKey(root, key, 0, access) as k:
                return str(winreg.QueryValueEx(k, value)[0])
        except OSError:
            continue
    return None


def _winreg_subkeys(root_name: str, key: str) -> list[str]:
    """Subkey names of `key` across both registry views (no duplicates)."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []
    root = getattr(winreg, root_name)
    names: list[str] = []
    for access in _registry_views():
        try:
            with winreg.OpenKey(root, key, 0, access) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    if sub not in names:
                        names.append(sub)
        except OSError:
            continue
    return names


def _steam_candidates() -> list[Path]:
    steam = _winreg_value("HKEY_CURRENT_USER", r"Software\Valve\Steam", "SteamPath")
    roots = [Path(steam)] if steam else []
    out: list[Path] = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        libs = [root]
        if vdf.exists():
            libs += [Path(p) for p in parse_vdf_library_paths(vdf.read_text(encoding="utf-8", errors="ignore"))]
        for lib in libs:
            out += [lib / "steamapps" / "common" / n for n in GAME_DIR_NAMES]
    return out


def _epic_candidates(manifest_dir: Path | None = None) -> list[Path]:
    base = manifest_dir or Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    out: list[Path] = []
    if base.is_dir():
        for item in base.glob("*.item"):
            try:
                data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, json.JSONDecodeError):
                continue
            name = str(data.get("DisplayName", "")).lower()
            loc = data.get("InstallLocation")
            if loc and ("grand theft auto v" in name or "gta" in name):
                out.append(Path(loc))
    return out


def _rockstar_candidates() -> list[Path]:
    if sys.platform != "win32":
        return []
    out: list[Path] = []
    base = r"SOFTWARE\Rockstar Games"  # both registry views are searched, so WOW6432Node is covered
    for sub in _winreg_subkeys("HKEY_LOCAL_MACHINE", base):
        val = _winreg_value("HKEY_LOCAL_MACHINE", f"{base}\\{sub}", "InstallFolder")
        if val and Path(val) not in out:
            out.append(Path(val))
    return out


def _common_candidates() -> list[Path]:
    if sys.platform != "win32":
        return []
    out: list[Path] = []
    for letter in string.ascii_uppercase[2:8]:  # C: .. H:
        drive = Path(f"{letter}:\\")
        if not drive.exists():
            continue
        for parent in (
            drive / "Program Files" / "Rockstar Games",
            drive / "Program Files" / "Epic Games",
            drive / "Program Files (x86)" / "Steam" / "steamapps" / "common",
            drive / "SteamLibrary" / "steamapps" / "common",
            drive / "Games",
        ):
            out += [parent / n for n in GAME_DIR_NAMES]
    return out


def detect_games(exe_names: tuple[str, ...] | None = None, extra: list[Path] | None = None) -> list[GameInstall]:
    """Every folder that holds a GTA V exe, best guess first, each with its edition. ``exe_names`` None = both
    editions (GTA5_Enhanced.exe and GTA5.exe), so a PC with both lists both."""
    exe_names = exe_names or ALL_EXES
    found: list[GameInstall] = []
    seen: set[str] = set()
    groups = [
        ("manual", extra or []),
        ("steam", _steam_candidates()),
        ("epic", _epic_candidates()),
        ("rockstar", _rockstar_candidates()),
        ("common", _common_candidates()),
    ]
    for source, paths in groups:
        for p in paths:
            try:
                key = str(Path(p).resolve()).lower()
            except OSError:
                continue
            if key in seen:
                continue
            exe = find_exe(Path(p), exe_names)
            if exe:
                seen.add(key)
                found.append(GameInstall(Path(p), source, exe, exe_version(exe), edition_of_exe(exe)))
    for g in found:
        log.info("game found (%s): %s, %s, build %s", g.source, g.path, g.edition, g.version)
    if not found:
        log.info("no GTA V game folder found")
    return found


# --- PC checks ----------------------------------------------------------------
SOCIAL_CLUB_FILES = ("socialclub.dll", "libcef.dll", "resources.pak")


def social_club_problem(folder: Path | str | None = None) -> str | None:
    """Rockstar's Social Club, which every GTA V start needs (Steam, Epic and Rockstar copies alike), is missing
    files, e.g. half-way through one of Rockstar's own updates: the game then sits on its loading screen or never
    starts (seen on the owner's PC on 2026-11-27 after a restart: an empty Social Club folder, "Required file did not
    exist: resources.pak"). None when it looks complete, or off Windows."""
    if folder is None:
        if sys.platform != "win32":
            return None
        folder = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Rockstar Games" / "Social Club"
    folder = Path(folder)
    missing = [f for f in SOCIAL_CLUB_FILES if not (folder / f).is_file()]
    if not missing:
        return None
    where = str(folder)
    what = "isn't installed" if len(missing) == len(SOCIAL_CLUB_FILES) else f"is missing {', '.join(missing)}"
    return (f"Rockstar's Social Club ({where}) {what}, so GTA can't start or stays on its loading screen. Open the "
            "Rockstar Games Launcher and let it finish its update (or reinstall Social Club from Rockstar), then "
            "try again.")


def detect_gpus() -> list[str]:
    override = os.environ.get("LEONIDA_FAKE_GPU")
    if override is not None:
        return [g for g in override.split(";") if g]
    if sys.platform != "win32":
        return []
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            check=False, capture_output=True, text=True, timeout=20,
        )
        gpus = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        log.info("GPU(s): %s", ", ".join(gpus) or "none reported")
        return gpus
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("GPU detection failed: %s", exc)
        return []


def is_rtx50(gpu_names: list[str]) -> bool:
    return any(re.search(r"RTX\s*50\d0", g, re.IGNORECASE) for g in gpu_names)


def check_prerequisites() -> dict[str, bool | None]:
    """True/False on Windows; None where it can't be checked."""
    if sys.platform != "win32":
        return {"dotnet48": None, "vcredist": None}
    release = _winreg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release")
    dotnet = int(release) >= 528040 if release and release.isdigit() else False
    vc = None
    for key in (r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"):
        val = _winreg_value("HKEY_LOCAL_MACHINE", key, "Installed")
        if val is not None:
            vc = val == "1"
            break
    return {"dotnet48": dotnet, "vcredist": bool(vc)}


def find_7zip() -> Path | None:
    hit = shutil.which("7z") or shutil.which("7za")
    if hit:
        return Path(hit)
    if sys.platform == "win32":
        # In a 32-bit Python %ProgramFiles% is "Program Files (x86)"; %ProgramW6432% is the real 64-bit folder.
        bases = [_winreg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\7-Zip", "Path64"),
                 _winreg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\7-Zip", "Path")]
        bases += [str(Path(os.environ[v]) / "7-Zip") for v in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
                  if os.environ.get(v)]
        bases += [r"C:\Program Files\7-Zip", r"C:\Program Files (x86)\7-Zip"]
        for base in bases:
            if base and (Path(base) / "7z.exe").exists():
                return Path(base) / "7z.exe"
    return None


def python_bits() -> int:
    """64 or 32: the GUI (PySide6) only ships 64-bit Windows wheels."""
    return struct.calcsize("P") * 8
