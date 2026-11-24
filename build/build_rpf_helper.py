"""Build Leonida's RPF helper (LeonidaRpf.exe) from CodeWalker's own source. Windows only.

    python build/build_rpf_helper.py [--dotnet PATH] [--commit SHA] [--install-to STATE_TOOLS_DIR]

What it does (nothing is re-hosted; everything comes from its authors):
  1. a .NET 8 SDK: --dotnet, or `dotnet` on PATH with an SDK, or a portable one installed with Microsoft's
     dotnet-install.ps1 into build/codewalker/.dotnet (no system install);
  2. CodeWalker's source (github.com/dexyfex/CodeWalker) at a pinned commit, into build/codewalker/.cw-src;
  3. `dotnet build` of build/codewalker/LeonidaRpf (net48 console app on CodeWalker.Core; NuGet restores SharpDX);
  4. the output in build/codewalker/bin/ (and a copy in --install-to, e.g. %LOCALAPPDATA%\\LeonidaV\\tools\\LeonidaRpf).

CodeWalker has no licence file ("source released for educational purposes only"): this builds a local copy on the
user's own PC from the author's published source. Leonida does not ship or re-host CodeWalker binaries.
leonida/rpf.py finds the helper in $LEONIDA_RPF_HELPER, <state>/tools/LeonidaRpf/ or build/codewalker/bin/.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CW = ROOT / "build" / "codewalker"
PROJECT = CW / "LeonidaRpf"
BIN = CW / "bin"
SRC = CW / ".cw-src"
SDK_DIR = CW / ".dotnet"
# dexyfex/CodeWalker master as of 2025-04-11 ("ModManager progress"): has GTA V Enhanced (gen9) key loading.
COMMIT = "485d56bec00262ed7fa472261cce7bbc6202b96e"
SOURCE_URL = "https://codeload.github.com/dexyfex/CodeWalker/zip/{commit}"
DOTNET_INSTALL = "https://dot.net/v1/dotnet-install.ps1"


def find_dotnet(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    on_path = shutil.which("dotnet")
    if on_path:
        sdks = subprocess.run([on_path, "--list-sdks"], capture_output=True, text=True).stdout
        if any(line.startswith(("8.", "9.", "10.")) for line in sdks.splitlines()):
            return Path(on_path)
    local = SDK_DIR / "dotnet.exe"
    if not local.is_file():
        print(f"Installing a portable .NET 8 SDK into {SDK_DIR} (Microsoft's dotnet-install.ps1) ...")
        SDK_DIR.mkdir(parents=True, exist_ok=True)
        script = SDK_DIR / "dotnet-install.ps1"
        script.write_bytes(urllib.request.urlopen(DOTNET_INSTALL, timeout=60).read())
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                        "-Channel", "8.0", "-InstallDir", str(SDK_DIR), "-NoPath"], check=True)
    return local


def fetch_source(commit: str) -> Path:
    marker = SRC / ".commit"
    if marker.is_file() and marker.read_text().strip() == commit:
        return SRC
    print(f"Downloading CodeWalker source {commit[:10]} from GitHub ...")
    data = urllib.request.urlopen(SOURCE_URL.format(commit=commit), timeout=120).read()
    if SRC.exists():
        shutil.rmtree(SRC)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        top = z.namelist()[0].split("/")[0]
        for m in z.infolist():
            rel = m.filename[len(top) + 1:]
            if not rel or not rel.startswith("CodeWalker.Core/") and rel not in ("Readme_Src.txt", "Notice.txt"):
                continue
            target = SRC / rel
            if m.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(m))
    marker.write_text(commit)
    return SRC


def build(dotnet: Path, src: Path) -> Path:
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
    if BIN.exists():
        shutil.rmtree(BIN)
    subprocess.run([str(dotnet), "build", str(PROJECT / "LeonidaRpf.csproj"), "-c", "Release", "-nologo",
                    f"-p:CodeWalkerSrc={src}", "-o", str(BIN)], check=True, env=env)
    exe = BIN / "LeonidaRpf.exe"
    if not exe.is_file():
        sys.exit("Build finished but LeonidaRpf.exe is missing.")
    for junk in BIN.glob("*.pdb"):
        junk.unlink()
    return exe


def main() -> None:
    if sys.platform != "win32":
        sys.exit("The RPF helper is built on Windows only.")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dotnet", help="dotnet.exe with a .NET 8+ SDK")
    ap.add_argument("--commit", default=COMMIT, help="CodeWalker commit to build from")
    ap.add_argument("--install-to", type=Path, help="also copy the helper here (e.g. <state>/tools/LeonidaRpf)")
    args = ap.parse_args()
    exe = build(find_dotnet(args.dotnet), fetch_source(args.commit))
    print(f"Built {exe}")
    if args.install_to:
        if args.install_to.exists():
            shutil.rmtree(args.install_to)
        shutil.copytree(BIN, args.install_to)
        print(f"Installed to {args.install_to}")


if __name__ == "__main__":
    main()
