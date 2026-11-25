"""One-page acceptance matrix: every edition x game build x modpack through the whole user flow on a fake game.

    python build/acceptance_report.py            # all combinations
    python build/acceptance_report.py --keep     # keep the work folders (to look at a failure)

Each row runs tests/acceptance_flow.py: choose the pack -> get (fixture downloads) -> check -> install (+ settings)
-> verify (fake mod logs) -> switch variant -> switch pack -> add a custom mod -> uninstall == baseline.
Nothing touches a real game or Leonida's real state. Exit code 0 when every row passes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "tests", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ.setdefault("LEONIDA_NO_OPEN", "1")

import acceptance_flow as A  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", help="folder for the fake games (default: a temp folder)")
    ap.add_argument("--keep", action="store_true", help="keep the work folders")
    ap.add_argument("--notes", action="store_true", help="print every note, not only the first")
    args = ap.parse_args(argv)
    base = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="leonida-accept-"))
    base.mkdir(parents=True, exist_ok=True)

    rows = []
    for i, (edition, build, pack) in enumerate(A.combos()):
        work = base / f"{i:02d}"  # short: Windows paths stay under 260 characters
        t = time.time()
        res = A.run(work, edition, build, pack)
        rows.append((res, time.time() - t))
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)

    print("Leonida V acceptance: choose -> get -> check -> install -> verify -> variant -> pack -> custom -> uninstall")
    print()
    print(f"{'edition / build':24} {'pack':12} {'result':20} {'mods':>4} {'time':>6}  detail")
    print("-" * 110)
    for res, secs in rows:
        detail = res.detail if not res.ok else (res.notes[0] if res.notes else "")
        print(f"{res.edition + ' ' + res.build:24} {res.pack:12} {res.label:20} {res.mods:4} {secs:5.1f}s  "
              f"{detail[:60]}")
        if not res.ok and len(res.detail) > 60:
            print(f"{'':4}{res.detail[:400]}")
        if args.notes:
            for n in res.notes[1:] if res.ok else res.notes:
                print(f"{'':70}{n[:60]}")
    passed = sum(r.ok for r, _ in rows)
    print("-" * 110)
    print(f"{passed} of {len(rows)} passed")
    if not args.work and not args.keep:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
