"""Build LeonidaV.exe (GUI) and leonida.exe (CLI) with PyInstaller, plus SHA256SUMS.txt.

Run on Windows:  pip install -e ".[gui,build]"  then  python build/build_exe.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
DATA = f"{ROOT / 'leonida' / 'manifest'}{';' if sys.platform == 'win32' else ':'}leonida/manifest"


def build(name: str, script: str, windowed: bool) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--name", name,
           "--add-data", DATA, "--distpath", str(DIST), "--workpath", str(ROOT / "build" / "work"),
           "--specpath", str(ROOT / "build" / "work")]
    if windowed:
        cmd.append("--windowed")
    cmd.append(str(ROOT / script))
    subprocess.run(cmd, check=True)


def main() -> None:
    build("LeonidaV", "leonida/gui/app.py", windowed=True)
    build("leonida", "leonida/__main__.py", windowed=False)
    sums = []
    for f in sorted(DIST.glob("*.exe")):
        sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
    (DIST / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print("\n".join(sums))


if __name__ == "__main__":
    main()
