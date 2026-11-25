"""Compile the in-game probe offline against the game's own Script Hook V .NET API (opt-in; reads the game folder).

    python build/check_probe.py [--game "D:\\Games\\Grand Theft Auto V Enhanced"] [--dotnet path\\to\\dotnet.exe]

Renders leonida/probe/LeonidaProbe.cs the way `leonida playtest --deep` does (sample DLC packs and car) and builds it
as a .NET Framework 4.8 library referencing the game's ScriptHookVDotNet3.dll (read only, never copied into the game
folder), in a temp folder. Script Hook V .NET compiles the probe in the game the same way, so a mistake in the API
calls shows up here instead of as "Failed to compile" in ScriptHookVDotNet.log. Needs a .NET 8 SDK (the same one
build_rpf_helper.py uses). Exit code 0 = it compiles.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.build_rpf_helper import find_dotnet  # noqa: E402
from leonida.probe import Plan, render  # noqa: E402

REAL_GAME = Path(r"D:\Games\Grand Theft Auto V Enhanced")
CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net48</TargetFramework>
    <OutputType>Library</OutputType>
    <LangVersion>latest</LangVersion>
    <Nullable>disable</Nullable>
    <PlatformTarget>x64</PlatformTarget>
    <TreatWarningsAsErrors>false</TreatWarningsAsErrors>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="ScriptHookVDotNet3"><HintPath>{api}</HintPath><Private>false</Private></Reference>
  </ItemGroup>
</Project>
"""


def check(game: Path, dotnet: Path) -> tuple[bool, str]:
    api = game / "ScriptHookVDotNet3.dll"
    if not api.is_file():
        return False, f"{api} isn't there"
    plan = Plan(packs={"vihud": "hud-geckomacabre", "mmd_jason_duval_houses": "jasonhouse"}, car="sultan")
    with tempfile.TemporaryDirectory(prefix="leonida-probe-check-") as tmp:
        proj = Path(tmp)
        (proj / "Probe.csproj").write_text(CSPROJ.format(api=api), encoding="utf-8")
        (proj / "LeonidaProbe.cs").write_text(render(plan), encoding="utf-8")
        env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
        p = subprocess.run([str(dotnet), "build", str(proj / "Probe.csproj"), "-c", "Release", "-nologo",
                            "-o", str(proj / "out")], capture_output=True, text=True, errors="replace", env=env)
        lines = [ln for ln in p.stdout.splitlines() if " error " in ln or " warning CS" in ln]
        return p.returncode == 0 and (proj / "out" / "Probe.dll").is_file(), "\n".join(lines) or p.stdout[-800:]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", type=Path, default=REAL_GAME)
    ap.add_argument("--dotnet")
    args = ap.parse_args()
    ok, out = check(args.game, find_dotnet(args.dotnet))
    if out:
        print(out)
    print("The probe compiles against the game's Script Hook V .NET API." if ok else "The probe does NOT compile.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
