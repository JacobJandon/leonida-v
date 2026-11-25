"""Compile Leonida's in-game menu the way Script Hook V .NET does, against the real API (developers; Windows).

    python build/check_menu.py [--game "D:\\Games\\Grand Theft Auto V Enhanced"]

Script Hook V .NET compiles scripts\\LeonidaMenu.3.cs with the C# 5 rules. This compiles leonida/menu/LeonidaMenu.cs
with .NET Framework's own csc.exe -langversion:5 against the game's ScriptHookVDotNet3.dll (read only) and
System.Windows.Forms, and checks that every native it calls is in that DLL's Hash list (leonida/nativenames.py).
tests/test_menu.py does the same against tests/menu_api_stub.cs, so CI catches C# 6+ syntax without the game.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))

from check_probe import compile_cs5, csc_path  # noqa: E402

from leonida.menu import script_text  # noqa: E402


def forms_dll() -> Path | None:
    csc = csc_path()
    if csc is None:
        return None
    dll = csc.parent / "System.Windows.Forms.dll"
    return dll if dll.is_file() else None


def natives_missing(game: Path) -> list[str]:
    from leonida.nativenames import native_names

    names = set(native_names(game).values())
    used = sorted(set(re.findall(r"Hash\.([A-Z0-9_]+)", script_text())))
    return [u for u in used if u not in names] if names else []


def check(game: Path) -> tuple[bool, str]:
    api = game / "ScriptHookVDotNet3.dll"
    if not api.is_file():
        return False, f"{api} isn't there"
    forms = forms_dll()
    if forms is None:
        return False, "csc.exe / System.Windows.Forms.dll (.NET Framework 4) not found"
    with tempfile.TemporaryDirectory(prefix="leonida-menu-check-") as tmp:
        src = Path(tmp) / "LeonidaMenu.3.cs"
        src.write_text(script_text(), encoding="utf-8")
        ok, out = compile_cs5([src], [api, forms], Path(tmp) / "LeonidaMenu.dll")
    missing = natives_missing(game)
    if missing:
        return False, f"natives not in this Script Hook V .NET: {', '.join(missing)}\n{out}"
    return ok, out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", type=Path, default=Path(r"D:\Games\Grand Theft Auto V Enhanced"))
    a = ap.parse_args()
    ok, out = check(a.game)
    print(out.strip() or "(no compiler output)")
    print("LeonidaMenu compiles with C# 5 against the real API, every native exists" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
