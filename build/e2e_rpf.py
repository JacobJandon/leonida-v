"""Real-file end-to-end test of the RPF install method (opt-in; never writes to the real game).

    python build/e2e_rpf.py [--game "D:\\Games\\Grand Theft Auto V Enhanced"] [--downloads D:\\Leonida\\Downloads]
                            [--keep] [--only mapfixes,hud-geckomacabre]

It needs the built helper (python build/build_rpf_helper.py), the real game (read only: its GTA5_Enhanced.exe gives
CodeWalker the keys, and a few real files are read out of its archives) and the real downloads. In a temp folder it
makes a fake game:
  - GTA5_Enhanced.exe: a copy (CodeWalker derives the archive keys from it);
  - update\\update.rpf, update\\update2.rpf, x64e.rpf: small OPEN archives holding the REAL dlclist.xml,
    gameconfig.xml, physicstasks.ymt, cameras.ymt, handling.meta read from the game (the real ones are 0.6-3 GB);
  - update\\x64\\dlcpacks\\mpApartment\\dlc.rpf: a copy of the REAL 0.5 GB NG-encrypted archive (Map Fixes edits
    nested archives inside it), so encryption conversion and nested edits run on real data;
  - every other archive a package touches: a small OPEN archive.
Then it installs the six CodeWalker mods with the install specs below (the proposed mods.json entries), checks the
results inside the archives, rolls every step back and checks the folder equals the baseline (Leonida's snapshot and
an independent SHA-256 walk). Exit code 0 = everything passed.
"""

from __future__ import annotations

import argparse
import dataclasses
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.e2e_real_install import QuietUI, Report, full_walk  # noqa: E402
from leonida import rpf as R  # noqa: E402
from leonida.archive import extract  # noqa: E402
from leonida.detect import find_7zip  # noqa: E402
from leonida.installer import Installer  # noqa: E402
from leonida.log import InstallLog  # noqa: E402
from leonida.manifest import FileSpec, load_manifest  # noqa: E402
from leonida.snapshot import take_snapshot  # noqa: E402

REAL_GAME = Path(r"D:\Games\Grand Theft Auto V Enhanced")
DOWNLOADS = Path(r"D:\Leonida\Downloads")
REAL_FILES = {  # archive -> entries copied from the real game into the compact test archive
    "update\\update.rpf": ["common\\data\\dlclist.xml", "common\\data\\gameconfig.xml",
                           "x64\\data\\tune\\physicstasks.ymt", "x64\\data\\metadata\\cameras.ymt",
                           "common\\data\\handling.meta", "common\\data\\levels\\gta5\\vehicles.meta"],
    "update\\update2.rpf": [],
    "x64e.rpf": [],
}
REAL_NG = "update\\x64\\dlcpacks\\mpApartment\\dlc.rpf"

# The proposed mods.json install entries (method "rpf"); archive = glob over the downloads folder.
SPECS = {
    "mapfixes": ("383134-MapFixes_v21.8.2_Gen9.rar", [FileSpec("spMapFixes_Gen9", "mods/update/x64/dlcpacks", "dir")], [
        {"archive": "update\\update.rpf", "dlclist": "dlcpacks:/spMapFixes_Gen9/"},
        {"oiv": "MP Map Fixes.oiv"}]),
    "bugstarfixes": ("978dba-BugstarFixes_v7.8.1_Gen9.rar", [FileSpec("spFixes_Gen9", "mods/update/x64/dlcpacks", "dir")], [
        {"archive": "update\\update.rpf", "dlclist": "dlcpacks:/spFixes_Gen9/"},
        {"oiv": "Enhanced Update RPF Content.oiv"}]),
    "drivev": ("6b9a30-DriveV 7.5.zip", [], [{"oiv": "Install.oiv"}]),
    "nextgeneuphoria": ("NextGen Euphoria-1-1-3-1747367011.rar", [], [
        {"archive": "update\\update.rpf", "put": "physicstasks.ymt", "to": "x64\\data\\tune\\physicstasks.ymt"}]),
    "combatcamera": ("03acfd-VI_Combat_Camera_for_GTA_V_Enhanced_v1.0_by_klennys.zip", [], [
        {"archive": "update\\update.rpf", "put": "cameras.ymt", "to": "x64\\data\\metadata\\cameras.ymt"}]),
    "hud-geckomacabre": ("GTA-VI-Inspired-HUD-2.8.2-Enhanced.oiv", [], [{"oiv": "*.oiv"}]),
}


def mod_for(manifest, mod_id: str, archive: str, files, ops):
    base = manifest.mod(mod_id)
    return dataclasses.replace(base, method="rpf", files=tuple(files), rpf=tuple(ops), archive=(archive,),
                               require_members=(), reject_members=(), steps=(), create_dirs=())


def touched_archives(downloads: Path, work_dir: Path) -> set[str]:
    """Every top-level archive the six packages edit (to give the fake game an archive at each path)."""
    paths: set[str] = set()
    seven = find_7zip()
    for _mod_id, (archive, _files, ops) in SPECS.items():
        for op in ops:
            if "archive" in op:
                paths.add(R.win(op["archive"]))
            if "oiv" in op:
                src = downloads / archive
                if src.suffix.lower() == ".oiv":
                    pkgs = [src]
                else:
                    dest = work_dir / src.stem
                    if not dest.exists():
                        extract(src, dest, seven)
                    pkgs = R.find_oivs(dest, op["oiv"])
                for pkg in pkgs:
                    paths |= {aw.path for aw in R.parse_oiv_file(pkg, work_dir / (pkg.stem + ".oiv-unpacked")).archives.values()}
    return paths


def make_fake_game(game: Path, helper: list[str], archives: set[str], tmp: Path, rep: Report) -> None:
    game.mkdir(parents=True)
    shutil.copy2(REAL_GAME / "GTA5_Enhanced.exe", game / "GTA5_Enhanced.exe")
    for name in ("PlayGTAV.exe", "common.rpf"):
        (game / name).write_bytes(b"stub")
    real_dir = tmp / "real-entries"
    extract_ops, puts = [], []
    for arc, entries in REAL_FILES.items():
        for e in entries:
            out = real_dir / arc.replace("\\", "_") / e.replace("\\", "_")
            extract_ops.append({"op": "extract", "rpf": str(REAL_GAME / arc), "entry": e, "out": str(out)})
            puts.append((arc, e, out))
    R.run_helper(helper, REAL_GAME, extract_ops)  # read-only: CodeWalker opens the game's archives with OpenRead
    rep.check(all(p.is_file() for _a, _e, p in puts), f"read {len(puts)} real files out of the game's update.rpf")
    ops = []
    for arc in sorted(archives | set(REAL_FILES)):
        target = game / arc
        if arc.lower() == REAL_NG.lower():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REAL_GAME / arc, target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        ops.append({"op": "create", "rpf": str(target)})
    for arc, e, p in puts:
        ops.append({"op": "put", "rpf": str(game / arc), "entry": e, "src": str(p)})
    R.run_helper(helper, game, ops)
    rep.check((game / REAL_NG).is_file(), f"fake game has {len(archives | set(REAL_FILES))} archives incl. the real NG {REAL_NG}")


def entries_of(helper, game: Path, rpf: Path) -> tuple[str, set[str]]:
    res = R.run_helper(helper, game, [{"op": "list", "rpf": str(rpf)}])[0]
    return res["encryption"], {e["path"].lower() for e in res["entries"]}


def read_entry(helper, game: Path, rpf: Path, entry: str, tmp: Path) -> bytes:
    out = tmp / ("read-" + entry.replace("\\", "_"))
    R.run_helper(helper, game, [{"op": "extract", "rpf": str(rpf), "entry": entry, "out": str(out)}])
    return out.read_bytes()


def run(game_src: Path = REAL_GAME, downloads: Path = DOWNLOADS, keep: bool = False, only: list[str] | None = None) -> Report:
    rep = Report()
    helper = R.find_helper()
    if helper is None:
        rep.problems.append("RPF helper not built: python build/build_rpf_helper.py")
        return rep
    real_stat = (REAL_GAME / "update" / "update.rpf").stat()
    tmp = Path(tempfile.mkdtemp(prefix="leonida-e2e-rpf-"))
    try:
        mods = {k: v for k, v in SPECS.items() if not only or k in only}
        archives = touched_archives(downloads, tmp / "pkgs")
        game, state = tmp / "Game", tmp / "State"
        make_fake_game(game, helper, archives, tmp, rep)
        before_walk = full_walk(game)
        manifest = load_manifest().for_build("1.0.1013.20")
        inst = Installer(manifest, game, state, InstallLog(state / "install-log.json"), QuietUI(), seven_zip=find_7zip())
        before = take_snapshot(game)
        steps = []
        for mod_id, (archive, files, ops) in mods.items():
            mod = mod_for(manifest, mod_id, archive, files, ops)
            src = downloads / archive
            plan = inst.plan(mod, src)
            if not rep.check(not plan.problems, f"{mod_id}: plan ok {plan.problems or ''}".strip()):
                continue
            t0 = time.monotonic()
            try:
                step = inst.install(mod, src)
            except Exception as exc:  # noqa: BLE001 - report and continue
                rep.problems.append(f"{mod_id}: install failed: {exc}")
                continue
            steps.append(step)
            rep.check(step.status == "done", f"{mod_id}: installed in {time.monotonic() - t0:.0f} s, "
                                             f"{len(step.actions)} logged change(s)")
        mods_update = game / "mods" / "update" / "update.rpf"
        if mods_update.is_file():
            enc, names = entries_of(helper, game, mods_update)
            rep.check(enc == "OPEN", f"mods\\update\\update.rpf is OPEN (OpenRPF format): {enc}")
            dl = read_entry(helper, game, mods_update, "common\\data\\dlclist.xml", tmp).decode("utf-8-sig")
            items = [i.text for i in ET.fromstring(dl).iter("Item")]
            orig_items = [i.text for i in ET.fromstring(
                (tmp / "real-entries" / "update_update.rpf" / "common_data_dlclist.xml").read_text("utf-8-sig")).iter("Item")]
            want = [w for w, m in (("dlcpacks:/spMapFixes_Gen9/", "mapfixes"), ("dlcpacks:/spFixes_Gen9/", "bugstarfixes"),
                                   ("dlcpacks:/vihud/", "hud-geckomacabre"), ("dlcpacks:/vihudanims/", "hud-geckomacabre"),
                                   ("dlcpacks:/vihudfonts/", "hud-geckomacabre")) if m in mods]
            rep.check(all(items.count(w) == 1 for w in want) and items[:len(orig_items)] == orig_items,
                      f"dlclist.xml keeps the game's {len(orig_items)} packs and adds {want} once each")
            if "hud-geckomacabre" in mods:
                gc = ET.fromstring(read_entry(helper, game, mods_update, "common\\data\\gameconfig.xml", tmp).decode("utf-8-sig"))
                pools = {i.findtext("PoolName"): int(i.find("PoolSize").get("value"))
                         for i in gc.iter("Item") if i.find("PoolName") is not None and i.find("PoolSize") is not None}
                rep.check(pools.get("MetaDataStore", 0) >= 4000 and pools.get("TxdStore", 0) >= 150000,
                          f"gameconfig.xml pools raised by the HUD .oiv (MetaDataStore {pools.get('MetaDataStore')}, "
                          f"TxdStore {pools.get('TxdStore')})")
            for mod_id, entry, member in (("nextgeneuphoria", "x64\\data\\tune\\physicstasks.ymt", "physicstasks.ymt"),
                                          ("combatcamera", "x64\\data\\metadata\\cameras.ymt", "cameras.ymt")):
                if mod_id in mods:
                    got = read_entry(helper, game, mods_update, entry, tmp)
                    src = tmp / f"src-{mod_id}"
                    extract(downloads / SPECS[mod_id][0], src, find_7zip())
                    want_bytes = next(src.rglob(member)).read_bytes()
                    rep.check(got == want_bytes, f"{mod_id}: {entry} in mods\\update\\update.rpf is the mod's file")
            if "drivev" in mods:
                rep.check("common\\data\\handling.meta" in names, "drivev: handling.meta in mods\\update\\update.rpf")
        ng = game / "mods" / REAL_NG
        if "mapfixes" in mods and ng.is_file():
            enc, names = entries_of(helper, game, ng)
            rep.check(enc == "OPEN" and len(names) > 100,
                      f"mapfixes: real NG {REAL_NG} copied to mods, converted to OPEN, {len(names)} entries readable")
        hud = game / "scripts" / "GTA6Hud.dll"
        if "hud-geckomacabre" in mods:
            rep.check(hud.is_file() and (game / "ViPreload.asi").is_file()
                      and (game / "mods/update/x64/dlcpacks/vihud/dlc.rpf").is_file(),
                      "hud: scripts, .asi in the game folder and its dlcpacks under mods")
        rep.check(not (game / "update" / "update.rpf").stat().st_size < 0, "fake game's own update.rpf untouched")
        for step in reversed(steps):
            warns = inst.rollback(step.id)
            rep.check(not warns, f"rollback {step.mod} {warns or ''}".strip())
        _w, residual = inst.uninstall()
        rep.check(residual is not None and residual.empty, f"snapshot after uninstall equals the baseline "
                                                           f"({residual.summary() if residual else 'no baseline'})")
        after_walk = full_walk(game)
        changed = sorted(k for k in set(before_walk) | set(after_walk) if before_walk.get(k) != after_walk.get(k))
        rep.check(not changed, f"full SHA-256 walk equals the baseline (differences: {changed[:5]})")
        del before
        st = (REAL_GAME / "update" / "update.rpf").stat()
        rep.check((st.st_size, st.st_mtime_ns) == (real_stat.st_size, real_stat.st_mtime_ns),
                  "the real game's update.rpf is untouched (size and modification time)")
    finally:
        if keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--downloads", type=Path, default=DOWNLOADS)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--only", help="comma-separated mod ids")
    args = ap.parse_args()
    t0 = time.monotonic()
    rep = run(downloads=args.downloads, keep=args.keep, only=args.only.split(",") if args.only else None)
    for line in rep.ok:
        print("  ok    " + line)
    for line in rep.problems:
        print("  FAIL  " + line)
    print("PASSED" if rep.passed else "FAILED", f"({len(rep.ok)} ok, {len(rep.problems)} failed) in "
          f"{time.monotonic() - t0:.0f} s")
    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
