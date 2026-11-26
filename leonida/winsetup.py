"""Per-user install and uninstall of the Leonida V exe build (Windows; no administrator rights).

    install(payload_zip, install_dir=None, data_dir=None)  # Leonida-V-Setup-<ver>.exe runs this
    uninstall(delete_state=False, delete_downloads=False)  # "LeonidaV.exe --uninstall" (Apps & features) runs this
    registered()                                            # {"InstallDir", "DataDir", "Version"} or None
    data_dir_for_running_exe()                              # the data folder when this exe is the installed one
    sync_version()                                          # after a self-update: Apps & features shows the new one

Where things go:
  - the program:  %LOCALAPPDATA%\\Programs\\Leonida V (the release's LeonidaV folder, as is);
  - the data:     a folder the user picks, default %LOCALAPPDATA%\\Leonida V, holding State\\ (settings, install log,
                  backups) and Downloads\\ (the mods' own files). It's recorded in HKCU\\Software\\Leonida V so the
                  self-updater, which swaps the program folder, never loses it;
  - shortcuts:    Start menu and (optionally) desktop, "Leonida V";
  - Apps & features: HKCU\\...\\Uninstall\\LeonidaV, uninstalling with "LeonidaV.exe --uninstall".

It never touches a game folder: a folder holding GTA's exe (or inside one) is refused for the program and the
data, and uninstalling removes only the program, its shortcuts and registry entries, plus State / Downloads only
when the user says so. Mods already installed in the game stay; Leonida's Manage page undoes them (before
uninstalling, or later with the same data folder).

Tests and the end-to-end check put everything elsewhere: LEONIDA_REG_ROOT (a registry path under HKCU, default
"Software") and the shortcut folder overrides of leonida/shortcuts.py.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import PACK_NAME, __version__

log = logging.getLogger(__name__)

APP_KEY_NAME = "Leonida V"
UNINSTALL_ID = "LeonidaV"
GUI_EXE, CLI_EXE = "LeonidaV.exe", "leonida.exe"
PUBLISHER = "JacobJandon"
URL = "https://github.com/JacobJandon/leonida-v"
GAME_EXES = ("GTA5_Enhanced.exe", "GTA5.exe", "PlayGTAV.exe", "GTAVLauncher.exe")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SetupError(RuntimeError):
    """Installing or uninstalling was refused or failed; the message says why. Nothing was half-done."""


# ------------------------------------------------------------------------------------------------- places
def _local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def default_install_dir() -> Path:
    return _local() / "Programs" / PACK_NAME


def default_data_dir() -> Path:
    return _local() / PACK_NAME


def _reg_root() -> str:
    return os.environ.get("LEONIDA_REG_ROOT") or "Software"


def app_key() -> str:
    return f"{_reg_root()}\\{APP_KEY_NAME}"


def uninstall_key() -> str:
    root = _reg_root()
    if root == "Software":
        return f"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{UNINSTALL_ID}"
    return f"{root}\\Uninstall\\{UNINSTALL_ID}"


# ----------------------------------------------------------------------------------------------- registry
def _write_values(key: str, values: dict[str, object]) -> None:
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_WRITE) as k:
        for name, value in values.items():
            if isinstance(value, int):
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)
            else:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, str(value))


def _read_values(key: str) -> dict[str, object] | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            out, i = {}, 0
            while True:
                try:
                    name, value, _t = winreg.EnumValue(k, i)
                except OSError:
                    return out
                out[name] = value
                i += 1
    except OSError:
        return None


def _delete_key(key: str) -> None:
    import winreg

    with contextlib.suppress(OSError):
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


def registered() -> dict | None:
    """The installed copy's InstallDir / DataDir / Version (HKCU), or None when Leonida V isn't installed."""
    values = _read_values(app_key())
    return values if values and values.get("InstallDir") else None


def _same(a: Path | str, b: Path | str) -> bool:
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def running_installed() -> dict | None:
    """``registered()`` when this process is the installed exe (frozen, running from InstallDir), else None."""
    if not getattr(sys, "frozen", False):
        return None
    reg = registered()
    if reg and _same(Path(sys.executable).parent, reg["InstallDir"]):
        return reg
    return None


def data_dir_for_running_exe() -> Path | None:
    reg = running_installed()
    if reg and reg.get("DataDir"):
        return Path(str(reg["DataDir"]))
    # The installed exe (it runs from the usual program folder) whose registry entry couldn't be read: never start
    # over with an empty State; use the data folder it used last (kept even across an uninstall + reinstall).
    if getattr(sys, "frozen", False) and _same(Path(sys.executable).parent, default_install_dir()):
        found = find_data_dirs()
        if found:
            log.warning("the setup's registry entry couldn't be read; using the data folder found: %s", found[0])
            return found[0]
    return None


# --------------------------------------------------------------------------------------- the data folder, found
LAST_KEY_NAME = "Leonida V data"   # HKCU\Software\<this>: LastDataDir, kept by an uninstall that keeps the data
SKIP_TOP = {"windows", "program files", "program files (x86)", "programdata", "$recycle.bin", "system volume information",
            "recovery", "perflogs", "msocache", "intel", "amd", "nvidia"}


def last_key() -> str:
    return f"{_reg_root()}\\{LAST_KEY_NAME}"


def remember_data_dir(data_dir: Path | str) -> None:
    """Record the data folder so a later setup finds it (also after an uninstall that kept it)."""
    with contextlib.suppress(OSError):
        _write_values(last_key(), {"LastDataDir": str(data_dir)})


def is_data_dir(path: Path | str) -> bool:
    """A Leonida data folder: ``<path>\\State\\config.json`` is Leonida's (a JSON object with its keys)."""
    try:
        cfg = json.loads((Path(path) / "State" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(cfg, dict) and bool({"update_channel", "profile", "download_dir", "game_dir"} & set(cfg))


def _search_roots() -> list[Path]:
    """Where to look for data folders one level down: LEONIDA_DATA_SEARCH (tests: folders separated by os.pathsep),
    else every fixed drive's top level, but only with the real registry (never from a test's own registry root)."""
    env = os.environ.get("LEONIDA_DATA_SEARCH")
    if env is not None:
        return [Path(p) for p in env.split(os.pathsep) if p]
    if _reg_root() != "Software" or sys.platform != "win32":
        return []
    import ctypes
    import string

    roots, mask = [], ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i) and ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\") == 3:   # DRIVE_FIXED
            roots.append(Path(f"{letter}:\\"))
    return roots


def find_data_dirs() -> list[Path]:
    """Existing Leonida data folders, best first: the registered one, the last one recorded (it survives an
    uninstall that kept the data), the default folder, then any ``<drive>:\\<folder>`` holding one (e.g. D:\\Leonida
    after Windows was reinstalled). Read-only."""
    reg = registered() or {}
    last = (_read_values(last_key()) or {}).get("LastDataDir")
    candidates: list[Path] = [Path(str(p)) for p in (reg.get("DataDir"), last) if p]
    candidates.append(default_data_dir())
    for root in _search_roots():
        try:
            children = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for child in children:
            if child.name.lower() in SKIP_TOP or child.name.startswith(("$", ".")):
                continue
            with contextlib.suppress(OSError):
                if child.is_dir():
                    candidates.append(child)
    out, seen = [], set()
    for c in candidates:
        key = os.path.normcase(os.path.abspath(str(c)))
        if key in seen:
            continue
        seen.add(key)
        if is_data_dir(c):
            out.append(c)
    return out


def suggested_data_dir() -> Path:
    """The data folder the setup uses when none is given: the registered one, else one found, else the default."""
    reg = registered() or {}
    if reg.get("DataDir"):
        return Path(str(reg["DataDir"]))
    found = find_data_dirs()
    return found[0] if found else default_data_dir()


def sync_version() -> bool:
    """After a self-update the installed folder holds a new version: show it in Apps & features. True if changed."""
    reg = running_installed()
    if not reg or reg.get("Version") == __version__:
        return False
    try:
        _write_values(app_key(), {"Version": __version__})
        _write_values(uninstall_key(), {"DisplayVersion": __version__})
    except OSError:
        return False
    log.info("registered version %s -> %s", reg.get("Version"), __version__)
    return True


# ---------------------------------------------------------------------------------------------- checks
def game_folder_near(path: Path) -> Path | None:
    """The folder holding a GTA exe that ``path`` is (or is inside), else None."""
    p = Path(path).resolve()
    for folder in (p, *p.parents):
        try:
            if any((folder / exe).is_file() for exe in GAME_EXES):
                return folder
        except OSError:
            continue
    return None


def _check_place(path: Path, what: str) -> None:
    game = game_folder_near(path)
    if game:
        raise SetupError(f"{path} is inside the game folder ({game}). Pick a folder outside it for {what}: Leonida "
                         "never puts its own files in the game.")


def _check_install_dir(install_dir: Path) -> None:
    _check_place(install_dir, "the program")
    if install_dir.is_dir() and any(install_dir.iterdir()) and not (install_dir / GUI_EXE).is_file():
        raise SetupError(f"{install_dir} already has other files in it. Pick an empty folder (or the folder of an "
                         "earlier Leonida V).")


def leonida_running(install_dir: Path) -> list[str]:
    """Leonida exes running from ``install_dir`` (names), so setup can ask to close them first."""
    if sys.platform != "win32":
        return []
    script = ("Get-Process -Name LeonidaV,leonida -ErrorAction SilentlyContinue | "
              "ForEach-Object { $_.Path }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                             text=True, timeout=30, creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    mine = os.path.normcase(str(install_dir.resolve())) + os.sep
    return sorted({Path(line.strip()).name for line in out.splitlines()
                   if line.strip() and os.path.normcase(line.strip()).startswith(mine)})


# ---------------------------------------------------------------------------------------------- install
@dataclass
class SetupResult:
    install_dir: Path
    data_dir: Path
    version: str
    shortcuts: list[Path] = field(default_factory=list)
    upgraded: bool = False
    notes: list[str] = field(default_factory=list)


def _extract(payload: Path, dest: Path, progress: Callable[[int, int], None] | None) -> None:
    """Unzip the release's LeonidaV folder into ``dest`` (zip-slip safe; the top folder is flattened)."""
    with zipfile.ZipFile(payload) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        tops = {m.filename.replace("\\", "/").split("/")[0] for m in members}
        strip = next(iter(tops)) + "/" if len(tops) == 1 and all("/" in m.filename for m in members) else ""
        if not any(m.filename.replace("\\", "/").endswith(f"{strip}{GUI_EXE}") for m in members):
            raise SetupError(f"{payload.name} is not a Leonida V release (no {GUI_EXE}).")
        total = sum(m.file_size for m in members) or 1
        done = 0
        root = dest.resolve()
        for m in members:
            rel = m.filename.replace("\\", "/")[len(strip):]
            target = (dest / rel).resolve()
            if not str(target).startswith(str(root) + os.sep):
                raise SetupError(f"{payload.name} has an unsafe path: {m.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            done += m.file_size
            if progress:
                progress(done, total)


def _dir_size_kb(folder: Path) -> int:
    total = 0
    for p in folder.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total // 1024


def _prepare_data(data_dir: Path) -> None:
    from .paths import Config

    state, downloads = data_dir / "State", data_dir / "Downloads"
    state.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(parents=True, exist_ok=True)
    try:
        cfg = Config.load(state)
    except (OSError, ValueError, TypeError):
        cfg = Config()
    if not cfg.download_dir:
        cfg.download_dir = str(downloads)
        cfg.save(state)


def install(payload: Path, install_dir: Path | None = None, data_dir: Path | None = None, *,
            version: str = __version__, shortcuts: bool = True, desktop: bool = True,
            progress: Callable[[int, int], None] | None = None) -> SetupResult:
    """Install (or upgrade / repair) Leonida V for this user from the release zip ``payload``."""
    if sys.platform != "win32":
        raise SetupError("The Leonida V setup is for Windows.")
    install_dir = Path(install_dir or default_install_dir())
    data_dir = Path(data_dir or suggested_data_dir())
    _check_install_dir(install_dir)
    _check_place(data_dir, "your Leonida data")
    if _same(install_dir, data_dir) or str(data_dir.resolve()).lower().startswith(str(install_dir.resolve()).lower()
                                                                                    + os.sep):
        raise SetupError("The data folder can't be the program folder or inside it (updates replace the program "
                         "folder). Pick another one.")
    busy = leonida_running(install_dir)
    if busy:
        raise SetupError(f"Leonida V is running ({', '.join(busy)}). Close it, then run the setup again.")
    upgraded = (install_dir / GUI_EXE).is_file()
    staged = install_dir.with_name(install_dir.name + ".setup-new")
    old = install_dir.with_name(install_dir.name + ".setup-old")
    for leftover in (staged, old):
        shutil.rmtree(leftover, ignore_errors=True)
    try:
        _extract(Path(payload), staged, progress)
        if install_dir.exists():
            install_dir.rename(old)
        try:
            staged.rename(install_dir)
        except OSError:
            if old.exists():
                old.rename(install_dir)
            raise
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(staged, ignore_errors=True)
        raise SetupError(f"Installing into {install_dir} failed: {exc}. Nothing was changed.") from None
    shutil.rmtree(old, ignore_errors=True)
    _prepare_data(data_dir)
    exe = install_dir / GUI_EXE
    _write_values(app_key(), {"InstallDir": str(install_dir), "DataDir": str(data_dir), "Version": version})
    remember_data_dir(data_dir)
    _write_values(uninstall_key(), {
        "DisplayName": PACK_NAME, "DisplayVersion": version, "Publisher": PUBLISHER, "URLInfoAbout": URL,
        "InstallLocation": str(install_dir), "DisplayIcon": f"{exe},0",
        "UninstallString": f'"{exe}" --uninstall', "QuietUninstallString": f'"{exe}" --uninstall --silent',
        "NoModify": 1, "NoRepair": 1, "EstimatedSize": _dir_size_kb(install_dir),
    })
    result = SetupResult(install_dir, data_dir, version, upgraded=upgraded)
    if shortcuts:  # Start menu always, the desktop one when wanted
        from . import shortcuts as lnk

        try:
            result.shortcuts = lnk.create(exe, icon=f"{exe},0", workdir=install_dir, desktop=desktop)
        except lnk.ShortcutError as exc:
            result.notes.append(f"The shortcuts could not be made: {exc}")
    log.info("installed %s into %s (data %s)%s", version, install_dir, data_dir, " (upgrade)" if upgraded else "")
    return result


# -------------------------------------------------------------------------------------------- uninstall
_REMOVE_LATER = r"""@echo off
setlocal
set "DIR={dir}"
set /a N=0
:wait
"%SystemRoot%\System32\tasklist.exe" /FI "PID eq {pid}" /NH 2>nul | "%SystemRoot%\System32\find.exe" " {pid} " >nul || goto :remove
set /a N+=1
if %N% GEQ 120 goto :remove
ping -n 2 127.0.0.1 >nul
goto :wait
:remove
set /a N=0
:again
rmdir /s /q "%DIR%" >nul 2>&1
if not exist "%DIR%" goto :done
set /a N+=1
if %N% GEQ 30 goto :done
ping -n 2 127.0.0.1 >nul
goto :again
:done
(goto) 2>nul & del "%~f0" >nul 2>&1
"""


@dataclass
class UninstallResult:
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    later: Path | None = None     # the program folder, removed by a helper once this process has exited


def uninstall(delete_state: bool = False, delete_downloads: bool = False, *, remove_program_now: bool | None = None,
              pid: int | None = None) -> UninstallResult:
    """Remove the installed Leonida V: shortcuts, registry entries and the program folder. State and Downloads
    only when asked. The game is never touched. When this process runs from the program folder, the folder is
    removed by a small helper once it has exited (``remove_program_now`` forces either way, for tests)."""
    reg = registered()
    if not reg:
        raise SetupError("Leonida V isn't installed for this user (nothing in the registry).")
    install_dir = Path(str(reg["InstallDir"]))
    data_dir = Path(str(reg.get("DataDir") or default_data_dir()))
    if game_folder_near(install_dir):
        raise SetupError(f"Refusing: {install_dir} is inside a game folder.")
    res = UninstallResult()
    from . import shortcuts

    for folder in (shortcuts.start_menu_dir(), _desktop_or_none()):
        if folder is None:
            continue
        lnk = folder / f"{shortcuts.NAME}.lnk"
        try:
            if lnk.is_file() and _points_into(lnk, install_dir):
                lnk.unlink()
                res.removed.append(str(lnk))
        except OSError:
            continue
    for name, wanted in (("State", delete_state), ("Downloads", delete_downloads)):
        folder = data_dir / name
        if not folder.exists():
            continue
        if wanted and not game_folder_near(folder):
            shutil.rmtree(folder, ignore_errors=True)
            res.removed.append(str(folder))
        else:
            res.kept.append(str(folder))
    if data_dir.is_dir() and not any(data_dir.iterdir()):
        data_dir.rmdir()
    _delete_key(uninstall_key())
    _delete_key(app_key())
    if (data_dir / "State").is_dir():
        remember_data_dir(data_dir)      # kept: the next setup finds it and everything is back
    else:
        _delete_key(last_key())
    res.removed.append("registry entries")
    inside = getattr(sys, "frozen", False) and _same(Path(sys.executable).parent, install_dir)
    now = (not inside) if remove_program_now is None else remove_program_now
    if now:
        shutil.rmtree(install_dir, ignore_errors=True)
        res.removed.append(str(install_dir))
    else:
        bat = Path(os.environ.get("TEMP") or _local() / "Temp") / f"leonida-uninstall-{os.getpid()}.bat"
        bat.write_text(_REMOVE_LATER.format(dir=str(install_dir).replace("%", "%%"), pid=pid or os.getpid()),
                       encoding="utf-8", newline="\r\n")
        subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(bat.parent), close_fds=True,
                         creationflags=_NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        res.later = install_dir
    log.info("uninstalled: removed %s, kept %s", res.removed, res.kept)
    return res


def _desktop_or_none() -> Path | None:
    from . import shortcuts

    try:
        return shortcuts.desktop_dir()
    except Exception:  # noqa: BLE001 - no desktop folder: nothing to remove there
        return None


def _points_into(lnk: Path, install_dir: Path) -> bool:
    from . import shortcuts

    try:
        target = shortcuts.read(lnk).get("target", "")
    except shortcuts.ShortcutError:
        return False
    return os.path.normcase(target).startswith(os.path.normcase(str(install_dir.resolve())))


def summary_text(result: SetupResult) -> str:
    lines = [f"{PACK_NAME} {result.version} is installed{' (updated)' if result.upgraded else ''}.",
             f"Program: {result.install_dir}", f"Your data: {result.data_dir} (State and Downloads)"]
    lines += [f"Shortcut: {p}" for p in result.shortcuts]
    lines += result.notes
    return "\n".join(lines)


def write_receipt(result: SetupResult) -> None:
    """<data>\\State\\setup-receipt.json: what setup did (for support)."""
    with contextlib.suppress(OSError):
        (result.data_dir / "State" / "setup-receipt.json").write_text(json.dumps({
            "version": result.version, "install_dir": str(result.install_dir), "data_dir": str(result.data_dir),
            "shortcuts": [str(p) for p in result.shortcuts], "upgraded": result.upgraded}, indent=1),
            encoding="utf-8")
