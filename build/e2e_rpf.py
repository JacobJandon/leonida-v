"""Real-file end-to-end test of the RPF install method (opt-in; never writes to the real game).

    python build/e2e_rpf.py [--downloads D:\\Leonida\\Downloads] [--build 1.0.1013.20] [--keep] [--only mapfixes,visualv]
    python build/e2e_rpf.py --space          # disk estimate for the Showcase pack, from the real files (no install)

It needs the built helper (python build/build_rpf_helper.py, or LEONIDA_RPF_HELPER), the real game (read only: its
GTA5_Enhanced.exe gives CodeWalker the keys, and the entries the packages touch are read out of its archives) and the
real downloads. The mods and their install specs come from mods.json (every mod with the "rpf" method), resolved for
the game build and the Showcase pack's selection (Resource Extensions selected: the HUD leaves gameconfig.xml alone).

In a temp folder it makes a fake game:
  - GTA5_Enhanced.exe: a copy (CodeWalker derives the archive keys from it);
  - every game archive a package edits: a compact OPEN archive holding the REAL entries it touches, read from the game
    (an entry inside a nested archive brings that whole real nested archive, NG-encrypted as the game has it);
  - update\\x64\\dlcpacks\\mpApartment\\dlc.rpf: a copy of the REAL 0.5 GB NG-encrypted archive, so encryption
    conversion and nested edits also run on a whole real archive;
  - archives the game doesn't have (e.g. patch2026_01 on 1.0.1013.20) are left out: createIfNotExist makes them.
Then it installs the mods one by one (the first step on an archive copies it into mods; later steps make entry-level
backups) and checks each step's result inside the archives (every file a step puts in is there, by entry hash; the
dlclist.xml lines; gameconfig.xml stays the game's own). It rolls the steps back newest first and, after each one,
checks that every entry of every mods archive has the hash it had after the step before (archives the step created
are gone), then that uninstall leaves the folder equal to the baseline (Leonida's snapshot and an independent SHA-256
walk) and that the real game's archives are untouched. Exit code 0 = everything passed.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.e2e_real_install import QuietUI, Report, full_walk  # noqa: E402
from leonida import rpf as R  # noqa: E402
from leonida.archive import extract  # noqa: E402
from leonida.detect import find_7zip  # noqa: E402
from leonida.installer import Installer  # noqa: E402
from leonida.log import InstallLog  # noqa: E402
from leonida.manifest import load_manifest  # noqa: E402
from leonida.matcher import match_files, scan_folder  # noqa: E402
from leonida.snapshot import diff, take_snapshot  # noqa: E402

REAL_GAME = Path(r"D:\Games\Grand Theft Auto V Enhanced")
DOWNLOADS = Path(r"D:\Leonida\Downloads")
BUILD = "1.0.1013.20"
PACK = "video-setup"                      # the Showcase pack: the selection the specs are resolved for
REAL_NG = "update\\x64\\dlcpacks\\mpApartment\\dlc.rpf"
ALWAYS = {"update\\update.rpf": [R.DLCLIST, "common\\data\\gameconfig.xml"]}


# ------------------------------------------------------------------------------------------- the mods
def rpf_mods(build: str, only: list[str] | None = None):
    base = load_manifest()
    rpf_ids = {i for i, m in base.mods.items() if m.method == "rpf"}
    selection = set(base.pack_mod_ids(PACK)) | rpf_ids | {"resourceextensions", "openrpf"}
    manifest = base.for_build(build).for_selection(selection)
    mods = [m for m in manifest.mods.values() if m.method == "rpf" and not m.unsupported and not m.not_needed
            and (not only or m.id in only)]
    return manifest, sorted(mods, key=lambda m: m.order)


def find_downloads(mods, downloads: Path) -> dict[str, Path]:
    return match_files(mods, scan_folder(downloads), {}).matched


def unpack(mod, src: Path, work_dir: Path, seven) -> tuple[Path, list[str]]:
    root = work_dir / mod.id
    if not root.exists():
        root.mkdir(parents=True)
        if src.suffix.lower() == ".oiv":
            shutil.copy2(src, root / src.name)
        else:
            extract(src, root, seven)
    return root, [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".unpacked" not in str(p)]


def work_of(mod, src: Path, work_dir: Path, seven) -> R.Work:
    root, members = unpack(mod, src, work_dir, seven)
    return R.manifest_work(list(mod.rpf), root, members)


def expected_hash(src: Path) -> str:
    """The entry hash the helper reports for a file put into an archive (see LeonidaRpf's EntryHash)."""
    data = src.read_bytes()
    if len(data) >= 16 and data[:4] == b"RSC7":
        body = zlib.decompressobj(-15).decompress(data[16:])
        return hashlib.sha256(b"R" + data[8:16] + body).hexdigest()
    return hashlib.sha256(b"B" + data).hexdigest()


def units(entries: list[str]) -> set[str]:
    """What to read out of the real archive for these entries: the entry itself, or the outermost nested archive."""
    out = set()
    for e in entries:
        parts = e.split("\\")
        i = next((k for k, p in enumerate(parts[:-1]) if p.lower().endswith(".rpf")), None)
        out.add("\\".join(parts[: i + 1]) if i is not None else e)
    return out


# ------------------------------------------------------------------------------------------- the fake game
def make_fake_game(game: Path, helper: list[str], works: dict[str, R.Work], tmp: Path, rep: Report) -> dict:
    game.mkdir(parents=True)
    shutil.copy2(REAL_GAME / "GTA5_Enhanced.exe", game / "GTA5_Enhanced.exe")
    for name in ("PlayGTAV.exe", "common.rpf"):
        (game / name).write_bytes(b"stub")
    touched: dict[str, list[str]] = {}
    spelling: dict[str, str] = {}  # packages spell the same archive differently (mpHeist / mpheist)
    for w in works.values():
        for aw in w.archives.values():
            arc = spelling.setdefault(aw.path.lower(), aw.path)
            touched.setdefault(arc, []).extend(R.touched_entries(aw.ops))
    for arc, extra in ALWAYS.items():
        touched.setdefault(spelling.get(arc.lower(), arc), []).extend(extra)
    real_dir = tmp / "real-entries"
    reads, puts, real_hashes = [], [], {}
    for arc, entries in touched.items():
        real = REAL_GAME / PurePosixPath(*PureWindowsPath(arc).parts)
        if not real.is_file() or arc.lower() == REAL_NG.lower():
            continue
        for k, unit in enumerate(sorted(units(entries))):
            out = real_dir / arc.replace("\\", "_") / f"{k:05d}.bin"
            reads.append({"op": "export", "rpf": str(real), "entry": unit, "out": str(out)})
            puts.append((arc, unit, out))
        reads.append({"op": "hash", "rpf": str(real), "entries": list(ALWAYS.get(arc, []))})
    results = R.run_helper(helper, REAL_GAME, reads)  # read only: CodeWalker opens the game's archives with OpenRead
    real_hashes = {r["rpf"]: r["hashes"] for r in results if r["op"] == "hash"}
    found = {(Path(op["rpf"]), op["entry"]) for op, r in zip(reads, results, strict=True)
             if op["op"] == "export" and r.get("exists")}
    ops = []
    made = set()
    for arc in sorted(touched):
        real = REAL_GAME / PurePosixPath(*PureWindowsPath(arc).parts)
        target = game / PurePosixPath(*PureWindowsPath(arc).parts)
        if not real.is_file():
            continue  # not in this game build: the package's createIfNotExist makes it in mods
        target.parent.mkdir(parents=True, exist_ok=True)
        if arc.lower() == REAL_NG.lower():
            shutil.copy2(real, target)
            continue
        ops.append({"op": "create", "rpf": str(target)})
        made.add(arc)
    n_real = 0
    for arc, unit, out in puts:
        real = REAL_GAME / PurePosixPath(*PureWindowsPath(arc).parts)
        if (real, unit) in found:
            ops.append({"op": "put", "rpf": str(game / PurePosixPath(*PureWindowsPath(arc).parts)), "entry": unit,
                        "src": str(out)})
            n_real += 1
    R.run_helper(helper, game, ops)
    size = sum(p.stat().st_size for p in game.rglob("*") if p.is_file())
    rep.check(True, f"fake game: {len(made)} compact archives with {n_real} real entries / nested archives read from "
                    f"the game, plus the real NG {REAL_NG} ({size / 2**30:.2f} GB in all)")
    return {"real_hashes": real_hashes, "touched": touched}


def archive_hashes(helper, game: Path, edited: set[str]) -> dict[str, dict]:
    """Every entry hash of every mods\\ archive the packages edit (``edited``: mods-relative POSIX paths, lower)."""
    arcs = sorted(game / rel for rel in edited if (game / rel).is_file())
    if not arcs:
        return {}
    res = R.run_helper(helper, game, [{"op": "hash", "rpf": str(p), "all": True} for p in arcs])
    return {p.relative_to(game).as_posix().lower(): r["hashes"] for p, r in zip(arcs, res, strict=True)}


def loose_state(game: Path, edited: set[str]) -> dict:
    """Leonida's snapshot of everything else (the dlc packs copied whole, scripts, ...): edited archives are compared
    by entry instead, since their bytes change with the layout."""
    snap = take_snapshot(game)
    snap["files"] = {k: v for k, v in snap.get("files", {}).items() if k.lower() not in edited}
    return snap


# ------------------------------------------------------------------------------------------- checks per step
def check_step(rep: Report, helper, game: Path, mod, work: R.Work, info: dict, tmp: Path) -> None:
    # every file the step put into an archive is there, by entry hash (later steps may replace some again)
    for aw in work.archives.values():
        target = game / R.mods_rel(aw.path)
        if not aw.ops:
            continue
        if not rep.check(target.is_file(), f"{mod.id}: mods\\{aw.path} exists"):
            continue
        puts = {op["entry"]: expected_hash(Path(op["src"])) for op in aw.ops if op["op"] == "put"}
        ytds = [op["entry"] for op in aw.ops if op["op"] == "ytd"]
        res = R.run_helper(helper, game, [{"op": "hash", "rpf": str(target), "entries": list(puts) + ytds}])[0]
        bad = [e for e, h in puts.items() if res["hashes"].get(e) != h]
        if puts:
            rep.check(not bad, f"{mod.id}: {len(puts) - len(bad)}/{len(puts)} files put into mods\\{aw.path} match "
                               f"the package byte for byte {bad[:3] or ''}".rstrip())
        for e in ytds:
            real = info["real_hashes"].get(str(REAL_GAME / PurePosixPath(*PureWindowsPath(aw.path).parts)), {})
            rep.check(res["hashes"].get(e) not in (None, real.get(e)), f"{mod.id}: texture replaced inside {e}")


def check_lists(rep: Report, helper, game: Path, mods, works, info, tmp: Path) -> None:
    mods_update = game / "mods" / "update" / "update.rpf"
    if not mods_update.is_file():
        return
    out = tmp / "dlclist-now.xml"
    R.run_helper(helper, game, [{"op": "extract", "rpf": str(mods_update), "entry": R.DLCLIST, "out": str(out)}])
    items = [i.text for i in ET.fromstring(out.read_bytes().decode("utf-8-sig")).iter("Item")]
    want = []
    for m in mods:
        want += [op["dlclist"] for op in m.rpf if "dlclist" in op]
        for aw in works[m.id].archives.values():
            for op in aw.ops:
                if op["op"] == "xml" and op["entry"].lower() == R.DLCLIST.lower():
                    for e in op["edits"]:
                        if e["type"] == "add" and "<Item>" in e.get("xml", ""):
                            want.append(e["xml"].split("<Item>")[1].split("</Item>")[0])
    missing = [w for w in want if items.count(w) != 1]
    rep.check(not missing, f"dlclist.xml has each of the {len(set(want))} packs' lines once {missing[:3] or ''}".rstrip())
    real = info["real_hashes"].get(str(REAL_GAME / "update" / "update.rpf"), {})
    now = R.run_helper(helper, game, [{"op": "hash", "rpf": str(mods_update), "entries": ["common\\data\\gameconfig.xml"]}])
    rep.check(now[0]["hashes"].get("common\\data\\gameconfig.xml") == real.get("common\\data\\gameconfig.xml"),
              "gameconfig.xml in mods\\update\\update.rpf is the game's own (Resource Extensions: the HUD's pool "
              "edits are left out, as its guide says)")


# ------------------------------------------------------------------------------------------- run
def run(downloads: Path = DOWNLOADS, build: str = BUILD, keep: bool = False, only: list[str] | None = None) -> Report:
    rep = Report()
    helper = R.find_helper()
    if helper is None:
        rep.problems.append("RPF helper not built: python build/build_rpf_helper.py")
        return rep
    real_stats = {}
    tmp = Path(tempfile.mkdtemp(prefix="leonida-e2e-rpf-"))
    seven = find_7zip()
    try:
        manifest, mods = rpf_mods(build, only)
        files = find_downloads(mods, downloads)
        for m in mods:
            rep.check(m.id in files, f"{m.id}: download found ({files[m.id].name if m.id in files else 'missing'})")
        mods = [m for m in mods if m.id in files]
        works = {m.id: work_of(m, files[m.id], tmp / "pkgs", seven) for m in mods}
        for w in works.values():
            for aw in w.archives.values():
                real = REAL_GAME / PurePosixPath(*PureWindowsPath(aw.path).parts)
                if real.is_file():
                    st = real.stat()
                    real_stats[aw.path] = (st.st_size, st.st_mtime_ns)
        game, state = tmp / "Game", tmp / "State"
        info = make_fake_game(game, helper, works, tmp, rep)
        before_walk = full_walk(game)
        log = InstallLog(state / "install-log.json")
        inst = Installer(manifest, game, state, log, QuietUI(), seven_zip=find_7zip())
        edited = {R.mods_rel(aw.path).lower() for w in works.values() for aw in w.archives.values()}
        history = [(archive_hashes(helper, game, edited), loose_state(game, edited))]
        steps = []
        for mod in mods:
            src = files[mod.id]
            plan = inst.plan(mod, src)
            if not rep.check(not plan.problems, f"{mod.id}: plan ok {plan.problems or ''}".rstrip()):
                continue
            t0 = time.monotonic()
            try:
                step = inst.install(mod, src)
            except Exception as exc:  # noqa: BLE001 - report and go on
                rep.problems.append(f"{mod.id}: install failed: {exc}")
                if log.steps and log.steps[-1].status == "failed":
                    rep.check(not inst.rollback(log.steps[-1].id), f"{mod.id}: the failed step rolled back cleanly")
                continue
            kinds = sorted({a.op for a in step.actions})
            backups = sum(p.stat().st_size for p in (state / "backups" / f"step-{step.id}").rglob("*") if p.is_file()) \
                if (state / "backups" / f"step-{step.id}").is_dir() else 0
            rep.check(step.status == "done", f"{mod.id}: installed in {time.monotonic() - t0:.0f} s "
                                             f"({len(step.actions)} logged changes: {', '.join(kinds)}; "
                                             f"backups {backups / 2**20:.1f} MB)")
            check_step(rep, helper, game, mod, works[mod.id], info, tmp)
            steps.append(step)
            history.append((archive_hashes(helper, game, edited), loose_state(game, edited)))
        check_lists(rep, helper, game, [m for m in mods if any(s.mod == m.id for s in steps)], works, info, tmp)
        enc = R.run_helper(helper, game, [{"op": "list", "rpf": str(game / "mods" / "update" / "update.rpf")}])[0]
        rep.check(enc["encryption"] == "OPEN", f"mods\\update\\update.rpf is OPEN (OpenRPF format): {enc['encryption']}")
        # roll back newest first: after each one, the archives and files are as they were after the step before
        for k in range(len(steps), 0, -1):
            step = steps[k - 1]
            warns = inst.rollback(step.id)
            arcs, loose = archive_hashes(helper, game, edited), loose_state(game, edited)
            want_arcs, want_loose = history[k - 1]
            same_arcs = arcs == want_arcs
            if not same_arcs:
                extra = sorted(set(arcs) ^ set(want_arcs))
                changed = sorted({f"{a}:{e}" for a in set(arcs) & set(want_arcs)
                                  for e in set(arcs[a]) | set(want_arcs[a]) if arcs[a].get(e) != want_arcs[a].get(e)})
                detail = f"archives {extra[:3]} entries {changed[:3]}"
            d = diff(want_loose, loose)
            rep.check(not warns and same_arcs and d.empty,
                      f"rollback {step.mod}: every entry of {len(want_arcs)} mods archive(s) back to its hash, files "
                      f"as before {warns or ''}{'' if same_arcs else detail}{'' if d.empty else d.summary()}".rstrip())
        _w, residual = inst.uninstall()
        rep.check(residual is not None and residual.empty, f"snapshot after uninstall equals the baseline "
                                                           f"({residual.summary() if residual else 'no baseline'})")
        after_walk = full_walk(game)
        changed = sorted(k for k in set(before_walk) | set(after_walk) if before_walk.get(k) != after_walk.get(k))
        rep.check(not changed, f"full SHA-256 walk equals the baseline (differences: {changed[:5]})")
        moved = [a for a, s in real_stats.items()
                 if (lambda st: (st.st_size, st.st_mtime_ns))(
                     (REAL_GAME / PurePosixPath(*PureWindowsPath(a).parts)).stat()) != s]
        rep.check(not moved, f"the real game's {len(real_stats)} archives read are untouched (size and time) {moved}")
    finally:
        if keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return rep


# ------------------------------------------------------------------------------------------- disk estimate
def space_estimate(downloads: Path = DOWNLOADS, build: str = BUILD) -> list[tuple[str, int, int, int, int]]:
    """Showcase pack on ``build``, from the real files: (mod, mods copies, new data in archives, entry backups, loose
    files) in bytes, per rpf mod in install order. Archive sizes are the real game's (stat only)."""
    manifest, mods = rpf_mods(build)
    files = find_downloads(mods, downloads)
    seven = find_7zip()
    copied: set[str] = set()
    rows = []
    with tempfile.TemporaryDirectory(prefix="leonida-space-") as tmp:
        state = Path(tmp) / "State"
        inst = Installer(manifest, Path(tmp) / "Game", state, InstallLog(state / "log.json"), QuietUI(), seven_zip=seven)
        for m in mods:
            if m.id not in files:
                rows.append((m.id + " (no download)", 0, 0, 0, 0))
                continue
            w = work_of(m, files[m.id], Path(tmp) / "pkgs", seven)
            plan = inst.plan(m, files[m.id])
            root = Path(tmp) / "pkgs" / m.id
            loose = sum((root / c.src).stat().st_size for c in plan.copies if (root / c.src).is_file())
            loose += sum(src.stat().st_size for src, _ in w.loose_adds)
            copies = new = backups = 0
            for aw in w.archives.values():
                add = sum(Path(op["src"]).stat().st_size for op in aw.ops if op.get("src"))
                new += add
                if aw.path.lower() in copied:
                    backups += add
                else:
                    real = REAL_GAME / PurePosixPath(*PureWindowsPath(aw.path).parts)
                    copies += real.stat().st_size if real.is_file() else 0
                    copied.add(aw.path.lower())
            rows.append((m.id, copies, new, backups, loose))
    return rows


def print_space(rows) -> None:
    gb = 2**30
    print(f"{'mod':22} {'mods copies':>12} {'new data':>10} {'backups':>10} {'loose':>10}")
    for r in rows:
        print(f"{r[0]:22} {r[1] / gb:11.2f}G {r[2] / gb:9.2f}G {r[3] / gb:9.3f}G {r[4] / gb:9.2f}G")
    t = [sum(r[i] for r in rows) for i in range(1, 5)]
    print(f"{'total':22} {t[0] / gb:11.2f}G {t[1] / gb:9.2f}G {t[2] / gb:9.3f}G {t[3] / gb:9.2f}G   "
          f"= {sum(t) / gb:.1f} GB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--downloads", type=Path, default=DOWNLOADS)
    ap.add_argument("--build", default=BUILD)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--only", help="comma-separated mod ids")
    ap.add_argument("--space", action="store_true", help="print the disk estimate for the Showcase pack and exit")
    args = ap.parse_args()
    if args.space:
        print_space(space_estimate(args.downloads, args.build))
        return 0
    t0 = time.monotonic()
    rep = run(downloads=args.downloads, build=args.build, keep=args.keep,
              only=args.only.split(",") if args.only else None)
    for line in rep.ok:
        print("  ok    " + line)
    for line in rep.problems:
        print("  FAIL  " + line)
    print("PASSED" if rep.passed else "FAILED", f"({len(rep.ok)} ok, {len(rep.problems)} failed) in "
          f"{time.monotonic() - t0:.0f} s")
    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
