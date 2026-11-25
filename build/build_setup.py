"""Build Leonida-V-Setup-<version>.exe: the per-user installer around a release's LeonidaV-<version>-win64.zip.

    python build/build_exe.py --release          # first: dist/LeonidaV-<ver>-win64.zip
    python build/build_setup.py [--zip PATH]     # -> dist/Leonida-V-Setup-<ver>.exe
    python build/build_setup.py --smoke          # also install + uninstall it silently into a temp folder

One file (PyInstaller --onefile, windowed). Inside: build/entry_setup.py, leonida/winsetup.py + setupui.py (stdlib
and ctypes only; no Qt) and the win64 zip with its SHA-256 (payload/payload.json), checked before anything is
written. The setup installs for the current user without administrator rights: see leonida/winsetup.py.
Silent: /S [--dir D] [--data D] [--no-desktop] [--no-shortcuts] [--launch] [--log FILE] (winget, tests).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build" / "work-setup"
ICON = ROOT / "leonida" / "gui" / "assets" / "leonida.ico"
EXCLUDES = ["PySide6", "shiboken6", "tkinter", "_tkinter", "unittest", "pydoc_data", "pytest", "_pytest", "pip",
            "setuptools", "pkg_resources", "lib2to3", "test", "tests"]


def version() -> str:
    text = (ROOT / "leonida" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def setup_name(ver: str) -> str:
    return f"Leonida-V-Setup-{ver}.exe"


def version_file(ver: str, folder: Path) -> Path:
    nums = [int(n) for n in re.match(r"\d+(?:\.\d+)*", ver).group(0).split(".")]
    nums = (nums + [0, 0, 0, 0])[:4]
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(nums)}, prodvers={tuple(nums)}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'JacobJandon'), StringStruct('FileDescription', 'Leonida V setup'),
    StringStruct('FileVersion', '{ver}'), StringStruct('InternalName', 'Leonida-V-Setup'),
    StringStruct('LegalCopyright', 'MIT License'), StringStruct('OriginalFilename', '{setup_name(ver)}'),
    StringStruct('ProductName', 'Leonida V'), StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""
    path = folder / "setup-version.txt"
    path.write_text(text, encoding="utf-8")
    return path


def build(zip_path: Path, out_dir: Path = DIST, ver: str | None = None) -> Path:
    ver = ver or version()
    if not zip_path.is_file():
        sys.exit(f"{zip_path} not found: run python build/build_exe.py --release first.")
    WORK.mkdir(parents=True, exist_ok=True)
    payload = Path(tempfile.mkdtemp(prefix="payload-", dir=WORK)) / "payload"
    payload.mkdir()
    shutil.copy2(zip_path, payload / zip_path.name)
    (payload / "payload.json").write_text(json.dumps({"file": zip_path.name, "sha256": sha256(zip_path),
                                                       "version": ver}), encoding="utf-8")
    name = setup_name(ver)[:-4]
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
           "--name", name, "--icon", str(ICON), "--add-data", f"{payload}{os.pathsep}payload",
           "--paths", str(ROOT), "--distpath", str(out_dir), "--workpath", str(WORK / "build"),
           "--specpath", str(WORK), "--version-file", str(version_file(ver, WORK)),
           "--hidden-import", "leonida.winsetup", "--hidden-import", "leonida.setupui",
           "--hidden-import", "leonida.shortcuts", "--hidden-import", "leonida.paths",
           *[x for m in EXCLUDES for x in ("--exclude-module", m)],
           str(ROOT / "build" / "entry_setup.py")]
    subprocess.run(cmd, check=True, cwd=ROOT)
    shutil.rmtree(payload.parent, ignore_errors=True)
    exe = out_dir / setup_name(ver)
    print(f"Setup: {exe} ({exe.stat().st_size / 2**20:.1f} MB)")
    return exe


def smoke(exe: Path) -> bool:
    """Install it silently into a temp folder (own registry root and shortcut folders), start the installed CLI,
    then uninstall: the real setup and uninstaller, nothing in the user's real places."""
    tmp = Path(tempfile.mkdtemp(prefix="leonida-setup-smoke-"))
    env = dict(os.environ, LEONIDA_REG_ROOT=f"Software\\LeonidaV-smoke-{os.getpid()}",
               LEONIDA_STARTMENU_DIR=str(tmp / "startmenu"), LEONIDA_DESKTOP_DIR=str(tmp / "desktop"),
               LEONIDA_NO_OPEN="1")
    install, data = tmp / "Programs" / "Leonida V", tmp / "Leonida V"
    ok = True
    try:
        p = subprocess.run([str(exe), "/S", "--dir", str(install), "--data", str(data), "--log", str(tmp / "setup.log")],
                           env=env, timeout=600)
        ok &= p.returncode == 0 and (install / "LeonidaV.exe").is_file() and (data / "State" / "config.json").is_file()
        print("install:", "ok" if ok else f"FAILED (exit {p.returncode})")
        v = subprocess.run([str(install / "leonida.exe"), "--version"], env=env, capture_output=True, text=True,
                           timeout=120)
        print("installed leonida.exe --version:", v.stdout.strip() or v.stderr.strip())
        u = subprocess.run([str(install / "LeonidaV.exe"), "--uninstall", "--silent"], env=env, timeout=120)
        print("uninstall exit:", u.returncode)
        ok &= u.returncode == 0
    finally:
        subprocess.run(["reg", "delete", f"HKCU\\{env['LEONIDA_REG_ROOT']}", "/f"], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", type=Path, help="the release's win64 zip (default: dist/LeonidaV-<ver>-win64.zip)")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    ver = version()
    exe = build(a.zip or DIST / f"LeonidaV-{ver}-win64.zip", ver=ver)
    if a.smoke and not smoke(exe):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
