"""Compile the in-game probe offline the way Script Hook V .NET does (opt-in; reads the game folder).

    python build/check_probe.py [--game "D:\\Games\\Grand Theft Auto V Enhanced"]

Renders leonida/probe/LeonidaProbe.cs the way `leonida playtest --deep` does (sample DLC packs and car) and compiles
it with .NET Framework's own C# compiler (csc.exe, part of Windows) with **-langversion:5**, referencing the game's
ScriptHookVDotNet3.dll (read only, never copied into the game folder), into a temp folder. Script Hook V .NET
compiles .cs scripts with the C# 5 rules: a newer feature (an exception filter, $"" strings, ?. ...) fails in the
game with "Failed to compile LeonidaProbe.3.cs", so it has to fail here first. Exit code 0 = it compiles.

tests/test_probe.py compiles it the same way against a small stub of the API (no game needed).
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

from leonida.probe import Plan, render  # noqa: E402

REAL_GAME = Path(r"D:\Games\Grand Theft Auto V Enhanced")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def csc_path() -> Path | None:
    """.NET Framework 4's C# compiler (64-bit, else 32-bit), or None (not Windows)."""
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for fw in ("Framework64", "Framework"):
        p = windir / "Microsoft.NET" / fw / "v4.0.30319" / "csc.exe"
        if p.is_file():
            return p
    return None


def compile_cs5(sources: list[Path], references: list[Path], out: Path, csc: Path | None = None) -> tuple[bool, str]:
    """csc -langversion:5 -target:library; (ok, compiler output)."""
    csc = csc or csc_path()
    if csc is None:
        return False, "csc.exe (.NET Framework 4) not found"
    args = [str(csc), "-nologo", "-langversion:5", "-target:library", "-warn:0", f"-out:{out}",
            *[f"-reference:{r}" for r in references], *[str(s) for s in sources]]
    p = subprocess.run(args, capture_output=True, text=True, errors="replace", creationflags=_NO_WINDOW)
    return p.returncode == 0 and out.is_file(), (p.stdout + p.stderr).strip()


def check(game: Path) -> tuple[bool, str]:
    api = game / "ScriptHookVDotNet3.dll"
    if not api.is_file():
        return False, f"{api} isn't there"
    plan = Plan(packs={"vihud": "hud-geckomacabre", "mmd_jason_duval_houses": "jasonhouse"}, car="sultan")
    with tempfile.TemporaryDirectory(prefix="leonida-probe-check-") as tmp:
        src = Path(tmp) / "LeonidaProbe.3.cs"
        src.write_text(render(plan), encoding="utf-8")
        return compile_cs5([src], [api], Path(tmp) / "LeonidaProbe.dll")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", type=Path, default=REAL_GAME)
    args = ap.parse_args()
    ok, out = check(args.game)
    if out:
        print(out)
    print("The probe compiles with C# 5 against the game's Script Hook V .NET API." if ok
          else "The probe does NOT compile the way Script Hook V .NET compiles it.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
