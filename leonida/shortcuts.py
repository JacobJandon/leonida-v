"""Start menu / desktop shortcuts for Leonida V (Windows). Stdlib only: the .lnk files are written by Windows' own
WScript.Shell COM object through PowerShell.

    create(target, icon=..., workdir=..., minimized=True)   -> the .lnk files made
    python -m leonida.shortcuts --target Start-Leonida.bat --icon leonida.ico --minimized --marker State\\.shortcuts

Start-Leonida.bat calls it once (first run, with a marker file) for the portable kit; ``leonida --create-shortcuts``
does the same for the frozen build (target LeonidaV.exe). Folders: LEONIDA_STARTMENU_DIR / LEONIDA_DESKTOP_DIR
override them (tests); LEONIDA_NO_SHORTCUTS=1 makes none, LEONIDA_NO_DESKTOP_SHORTCUT=1 skips the desktop one.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

NAME = "Leonida V"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PS_CREATE = r"""
$ErrorActionPreference = 'Stop'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK_PATH)
$s.TargetPath = $env:LNK_TARGET
$s.Arguments = $env:LNK_ARGS
$s.WorkingDirectory = $env:LNK_WORKDIR
if ($env:LNK_ICON) { $s.IconLocation = $env:LNK_ICON }
$s.WindowStyle = [int]$env:LNK_STYLE
$s.Description = $env:LNK_DESC
$s.Save()
"""
_PS_READ = r"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK_PATH)
"$($s.TargetPath)|$($s.Arguments)|$($s.WorkingDirectory)|$($s.IconLocation)|$($s.WindowStyle)"
"""


class ShortcutError(RuntimeError):
    pass


def _powershell(script: str, env: dict[str, str]) -> str:
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    cmd = [str(exe) if exe.is_file() else "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-Command", script]
    try:
        p = subprocess.run(cmd, env={**os.environ, **env}, capture_output=True, text=True, timeout=60,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShortcutError(f"PowerShell could not run: {exc}") from None
    if p.returncode != 0:
        raise ShortcutError((p.stderr or p.stdout).strip()[-400:] or f"PowerShell exit code {p.returncode}")
    return p.stdout.strip()


def start_menu_dir() -> Path:
    override = os.environ.get("LEONIDA_STARTMENU_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Microsoft" / "Windows" / \
        "Start Menu" / "Programs"


def desktop_dir() -> Path:
    override = os.environ.get("LEONIDA_DESKTOP_DIR")
    if override:
        return Path(override)
    try:  # the real Desktop folder (it may be redirected, e.g. to OneDrive)
        found = _powershell("[Environment]::GetFolderPath('Desktop')", {})
        if found:
            return Path(found)
    except ShortcutError:
        pass
    return Path.home() / "Desktop"


def create(target: Path, *, icon: Path | str | None = None, workdir: Path | None = None, args: str = "",
           minimized: bool = False, desktop: bool = True, name: str = NAME) -> list[Path]:
    """Make "<name>.lnk" in the Start menu (and on the desktop). Returns the files made; [] when switched off or
    not on Windows."""
    if sys.platform != "win32" or os.environ.get("LEONIDA_NO_SHORTCUTS") == "1":
        return []
    folders = [start_menu_dir()]
    if desktop and os.environ.get("LEONIDA_NO_DESKTOP_SHORTCUT") != "1":
        folders.append(desktop_dir())
    target = Path(target).resolve()
    made = []
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
        lnk = folder / f"{name}.lnk"
        _powershell(_PS_CREATE, {
            "LNK_PATH": str(lnk), "LNK_TARGET": str(target), "LNK_ARGS": args,
            "LNK_WORKDIR": str(Path(workdir).resolve() if workdir else target.parent),
            "LNK_ICON": str(icon) if icon else "", "LNK_STYLE": "7" if minimized else "1",
            "LNK_DESC": "Leonida V: GTA VI-style GTA V Enhanced, story mode only",
        })
        made.append(lnk)
    return made


def read(lnk: Path) -> dict[str, str]:
    """TargetPath, Arguments, WorkingDirectory, IconLocation and WindowStyle of a .lnk (for checks and tests)."""
    out = _powershell(_PS_READ, {"LNK_PATH": str(lnk)}).split("|")
    return dict(zip(("target", "args", "workdir", "icon", "style"), out, strict=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m leonida.shortcuts", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, type=Path, help="what the shortcut starts")
    ap.add_argument("--icon", help="an .ico file (or exe,index)")
    ap.add_argument("--workdir", type=Path)
    ap.add_argument("--args", default="")
    ap.add_argument("--minimized", action="store_true", help="run minimized (for a .bat: no console in the way)")
    ap.add_argument("--no-desktop", action="store_true")
    ap.add_argument("--marker", type=Path, help="only once: skip when this file exists, write it afterwards")
    a = ap.parse_args(argv)
    if a.marker and a.marker.exists():
        return 0
    try:
        made = create(a.target, icon=a.icon, workdir=a.workdir, args=a.args, minimized=a.minimized,
                      desktop=not a.no_desktop)
    except ShortcutError as exc:
        print(f"Could not create the shortcuts: {exc}", file=sys.stderr)
        return 1
    for lnk in made:
        print(f"Shortcut: {lnk}")
    if a.marker:
        a.marker.parent.mkdir(parents=True, exist_ok=True)
        a.marker.write_text("\n".join(str(m) for m in made) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
