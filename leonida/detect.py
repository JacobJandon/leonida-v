"""Find GTA V Enhanced, read its version, and check the PC (GPU, prerequisites, 7-Zip)."""

from __future__ import annotations

import json
import os
import re
import shutil
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GAME_DIR_NAMES = (
    "Grand Theft Auto V Enhanced",
    "GTAV Enhanced",
    "GTA V Enhanced",
    "GTAVEnhanced",
)


@dataclass(frozen=True)
class GameInstall:
    path: Path
    source: str  # steam / epic / rockstar / common / manual
    exe: Path
    version: str | None


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


# --- store discovery ---------------------------------------------------------
def parse_vdf_library_paths(text: str) -> list[str]:
    """Library folder paths from Steam's libraryfolders.vdf."""
    return [m.replace("\\\\", "\\") for m in re.findall(r'"path"\s+"([^"]+)"', text)]


def _winreg_value(root_name: str, key: str, value: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        root = getattr(winreg, root_name)
        with winreg.OpenKey(root, key) as k:
            return str(winreg.QueryValueEx(k, value)[0])
    except OSError:
        return None


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
    try:
        import winreg

        for base in (r"SOFTWARE\WOW6432Node\Rockstar Games", r"SOFTWARE\Rockstar Games"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                    i = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(k, i)
                        except OSError:
                            break
                        i += 1
                        val = _winreg_value("HKEY_LOCAL_MACHINE", f"{base}\\{sub}", "InstallFolder")
                        if val:
                            out.append(Path(val))
            except OSError:
                continue
    except ImportError:
        pass
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


def detect_games(exe_names: tuple[str, ...], extra: list[Path] | None = None) -> list[GameInstall]:
    """Every folder that holds a GTA V Enhanced exe, best guess first."""
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
                found.append(GameInstall(Path(p), source, exe, exe_version(exe)))
    return found


# --- PC checks ----------------------------------------------------------------
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
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
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
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            p = Path(base) / "7-Zip" / "7z.exe"
            if p.exists():
                return p
    return None
