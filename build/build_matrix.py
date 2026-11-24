"""Game-build matrix: for every known GTA V Enhanced build, which version of each mod Leonida uses, or why it can't.

    python build/build_matrix.py                 # table for every mod
    python build/build_matrix.py --profile core  # only one profile's mods
    python build/build_matrix.py --strict        # exit 1 if a profile's mod has no version on some build

Uses only the manifest (no network, no game folder). Run it after changing `gameBuilds` data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from leonida.manifest import load_manifest  # noqa: E402

# Enhanced builds Script Hook V's readme lists (plus 1013.20, which SHV treats as 1013.17), oldest first.
ENHANCED_BUILDS = (
    "1.0.811.8", "1.0.812.8", "1.0.813.11", "1.0.814.9", "1.0.889.15", "1.0.889.19", "1.0.889.22",
    "1.0.1013.17", "1.0.1013.20", "1.0.1013.29", "1.0.1013.33", "1.0.1013.34", "1.0.1158.13",
)


def cell(mod, latest) -> str:
    if getattr(mod, "unsupported", None):
        return "--"
    ver = (mod.version or "?").split(" (")[0][:15]
    return ver + ("*" if mod.version != latest.version else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", help="only this profile's mods")
    ap.add_argument("--builds", nargs="*", default=list(ENHANCED_BUILDS))
    ap.add_argument("--strict", action="store_true", help="exit 1 if a selected mod is unsupported on any build")
    a = ap.parse_args(argv)
    base = load_manifest()
    ids = [m.id for m in base.resolve(a.profile)] if a.profile else list(base.mods)
    per_build = {b: base.for_build(b) for b in a.builds}
    width = max(len(i) for i in ids) + 2
    head = "mod".ljust(width) + "".join(b.replace("1.0.", "").rjust(18) for b in a.builds)
    print(head)
    print("-" * len(head))
    gaps: list[str] = []
    for mid in ids:
        row = mid.ljust(width)
        for b in a.builds:
            m = per_build[b].mods[mid]
            row += cell(m, base.mods[mid]).rjust(18)
            if getattr(m, "unsupported", None):
                gaps.append(f"{mid} on {b}: {m.unsupported}")
        print(row)
    print("\n* = an older/other version is used on that build;  -- = no working version on that build")
    if gaps:
        print(f"\n{len(gaps)} gap(s):")
        for g in gaps:
            print("  " + g)
    return 1 if (a.strict and gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
