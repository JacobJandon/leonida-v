"""Real-file end-to-end install test (opt-in; never part of the normal pytest run, never touches the real game).

    python build/e2e_real_install.py [--downloads D:\\Leonida\\Downloads] [--build 1.0.1013.20] [--keep]

Copies the real downloaded archives for Script Hook V .NET Enhanced and Menyoo into a temp folder, makes a fake
game folder (GTA5_Enhanced.exe stub + the usual top-level files/folders), then:
  baseline -> install both with Installer -> check every file landed where the manifest says (byte-identical to the
  archive member) -> verify() sees "not seen yet" -> rollback Menyoo -> uninstall -> the folder equals the baseline
  (both Leonida's own snapshot diff and an independent full walk with SHA-256 of every file).
It also reports manifest `files` specs that don't fit the real archive layout: missing members, and files at the
archive's top level that look like they belong in the game folder but no spec copies.

pytest runs it too when LEONIDA_E2E_DOWNLOADS points at the downloads folder (tests/test_verify.py).
Exit code 0 = everything passed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leonida.log import InstallLog  # noqa: E402
from leonida.manifest import Manifest, Mod, load_manifest  # noqa: E402

REAL_GAME = Path(r"D:\Games\Grand Theft Auto V Enhanced")
DEFAULT_DOWNLOADS = Path(r"D:\Leonida\Downloads")
# mod id -> archive glob in the downloads folder (the real files the owner downloaded)
ARCHIVES = {"shvdne": "ScriptHookVDotNetEnhanced-v*.zip", "menyoo": "MenyooSP*.zip"}
# Top-level archive files that never belong in the game folder (docs, licences, debug symbols)
DOC_SUFFIXES = (".txt", ".md", ".pdf", ".pdb", ".xml", ".url", ".png", ".jpg", ".html")


class QuietUI:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, msg: str) -> None:
        self.lines.append(msg)

    def warn(self, msg: str) -> None:
        self.lines.append("WARN " + msg)

    def confirm(self, msg: str, default: bool = True) -> bool:
        return True

    def wait_done(self, title: str, steps: list[str], folder: Path | None) -> bool:
        return True

    def launch(self, path: Path) -> None:
        raise AssertionError(f"e2e must not launch anything: {path}")


@dataclass
class Report:
    ok: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)       # test failures
    manifest_issues: list[str] = field(default_factory=list)  # manifest data vs. the real archive

    def check(self, cond: bool, what: str) -> bool:
        (self.ok if cond else self.problems).append(what)
        return cond

    @property
    def passed(self) -> bool:
        return not self.problems


def full_walk(root: Path) -> dict[str, str]:
    """Every file and empty folder under root -> sha256 ('dir' for empty folders). Independent of leonida.snapshot."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root).as_posix()
        if not dirnames and not filenames and rel != ".":
            out[rel + "/"] = "dir"
        for fn in filenames:
            p = Path(dirpath) / fn
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def make_fake_game(game: Path) -> None:
    game.mkdir(parents=True)
    (game / "GTA5_Enhanced.exe").write_bytes(b"MZ" + b"\0" * 62 + b"leonida e2e stub, not the game")
    for name in ("PlayGTAV.exe", "common.rpf", "x64a.rpf", "dstorage.dll", "version.dll"):
        (game / name).write_bytes(f"stub {name}".encode())
    for d in ("update", "x64", "_Redist", "BattlEye"):
        (game / d).mkdir()
        (game / d / "stub.bin").write_bytes(b"stub")
    (game / "update" / "update.rpf").write_bytes(b"stub update.rpf")


def manifest_vs_archive(mod: Mod, members: list[str], rep: Report) -> None:
    """Report spec/archive mismatches for a copy-method mod (manifest data problems, not test failures)."""
    names = {PurePosixPath(m).name.lower() for m in members if not m.endswith("/")}
    dirs = {seg.lower() for m in members for seg in PurePosixPath(m).parts[:-1]}
    covered: set[str] = set()
    for spec in mod.files:
        found = spec.match.lower() in (dirs if spec.type == "dir" else names)
        if spec.type == "dir":
            covered |= {m.lower() for m in members if spec.match.lower() in [s.lower() for s in PurePosixPath(m).parts[:-1]]}
        else:
            covered |= {m.lower() for m in members if PurePosixPath(m).name.lower() == spec.match.lower()}
        if not found:
            kind = "folder" if spec.type == "dir" else "file"
            sev = "optional, so skipped" if spec.optional else "REQUIRED: the install fails"
            rep.manifest_issues.append(f"{mod.id}: {kind} '{spec.match}' is not in the archive ({sev}).")
    for m in members:
        p = PurePosixPath(m)
        if m.endswith("/") or len(p.parts) != 1 or m.lower() in covered:
            continue
        if p.suffix.lower() in DOC_SUFFIXES:
            continue
        rep.manifest_issues.append(f"{mod.id}: top-level archive file '{m}' is not copied by any spec.")


def run(downloads: Path = DEFAULT_DOWNLOADS, build: str = "1.0.1013.20", keep: bool = False,
        workdir: Path | None = None) -> Report:
    from leonida.archive import list_members
    from leonida.installer import Installer
    from leonida.verify import NOT_SEEN, verify

    rep = Report()
    base: Manifest = load_manifest()
    manifest = base.for_build(build)
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="leonida-e2e-"))
    if tmp.resolve() == REAL_GAME.resolve() or REAL_GAME in tmp.resolve().parents:
        raise SystemExit("Refusing to run inside the real game folder.")
    try:
        dl, game, state = tmp / "Downloads", tmp / "Game", tmp / "State"
        dl.mkdir(parents=True)
        archives: dict[str, Path] = {}
        for mod_id, glob in ARCHIVES.items():
            hits = sorted(downloads.glob(glob))
            if not rep.check(bool(hits), f"{mod_id}: real archive {glob} present in {downloads}"):
                continue
            archives[mod_id] = Path(shutil.copy2(hits[-1], dl / hits[-1].name))
        if rep.problems:
            return rep
        make_fake_game(game)
        before = full_walk(game)
        log = InstallLog(state / "install-log.json")
        ui = QuietUI()
        inst = Installer(manifest, game, state, log, ui)
        baseline = inst.ensure_baseline()
        rep.check(baseline["files"].get("GTA5_Enhanced.exe") is not None, "baseline snapshot recorded the game exe")

        steps = {}
        for mod_id, archive in archives.items():
            mod = manifest.mods[mod_id]
            members = list_members(archive)
            manifest_vs_archive(mod, members, rep)
            try:
                step = inst.install(mod, archive)
            except Exception as exc:  # noqa: BLE001 - report, keep going
                rep.problems.append(f"{mod_id}: install failed: {exc}")
                continue
            steps[mod_id] = step
            rep.check(step is not None and step.status == "done", f"{mod_id}: install step {step.id} done")
            check_landed(mod, archive, members, game, rep)
            for d in mod.create_dirs:
                rep.check((game / d).is_dir(), f"{mod_id}: created folder {d}/")

        results = verify(game, [manifest.mods[m] for m in steps], log)
        seen = {r.mod: r.status for r in results if r.mod}
        rep.check(all(seen.get(m) == NOT_SEEN for m in steps),
                  f"verify() before any game start says 'not seen yet' for {', '.join(steps)}: {seen}")

        if "menyoo" in steps:
            warns = inst.rollback(steps["menyoo"].id)
            rep.check(not warns, f"menyoo: rollback without warnings {warns or ''}".strip())
            rep.check(not (game / "Menyoo.asi").exists() and not (game / "menyooStuff").exists(),
                      "menyoo: rollback removed Menyoo.asi and menyooStuff/")
            if "shvdne" in steps:
                rep.check((game / "ScriptHookVDotNet.asi").is_file(), "shvdne: still installed after rolling back menyoo")

        warns, residual = inst.uninstall()
        rep.check(not warns, f"uninstall without warnings {warns or ''}".strip())
        rep.check(residual is not None and residual.empty,
                  f"Leonida snapshot diff after uninstall is empty ({residual.summary() if residual else 'no baseline'})")
        after = full_walk(game)
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
        rep.check(not (added or removed or changed),
                  f"full walk after uninstall equals the baseline (added {added}, removed {removed}, changed {changed})")
    finally:
        if keep:
            print(f"Kept work folder: {tmp}")
        elif not workdir:
            shutil.rmtree(tmp, ignore_errors=True)
    return rep


def check_landed(mod: Mod, archive: Path, members: list[str], game: Path, rep: Report) -> None:
    """Every spec'd file is in the game folder where `to` says, byte-identical to the archive member."""
    with zipfile.ZipFile(archive) as zf:
        for spec in mod.files:
            want = spec.match.lower()
            if spec.type == "dir":
                picked = [m for m in members if not m.endswith("/")
                          and want in [s.lower() for s in PurePosixPath(m).parts[:-1]]]
                for m in picked:
                    parts = PurePosixPath(m).parts
                    i = [s.lower() for s in parts].index(want)
                    dest = game / spec.to / Path(*parts[i:])
                    if not dest.is_file() or dest.read_bytes() != zf.read(m):
                        rep.problems.append(f"{mod.id}: {m} did not land at {dest.relative_to(game)}")
                        break
                else:
                    rep.check(bool(picked) or spec.optional,
                              f"{mod.id}: folder {spec.match}/ -> {spec.to} ({len(picked)} files, byte-identical)")
                continue
            hits = [m for m in members if PurePosixPath(m).name.lower() == want]
            if not hits:
                rep.check(spec.optional, f"{mod.id}: {spec.match} (optional, not in archive)")
                continue
            dest = game / spec.to / PurePosixPath(hits[0]).name
            rep.check(dest.is_file() and dest.read_bytes() == zf.read(hits[0]),
                      f"{mod.id}: {spec.match} -> {(Path(spec.to) / dest.name).as_posix()} (byte-identical)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--downloads", type=Path, default=Path(os.environ.get("LEONIDA_E2E_DOWNLOADS") or DEFAULT_DOWNLOADS))
    ap.add_argument("--build", default="1.0.1013.20", help="game build to resolve the manifest for")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder for inspection")
    args = ap.parse_args()
    rep = run(args.downloads, args.build, args.keep)
    for line in rep.ok:
        print("  ok    " + line)
    for line in rep.problems:
        print("  FAIL  " + line)
    for line in rep.manifest_issues:
        print("  MANIFEST  " + line)
    print("PASSED" if rep.passed else "FAILED", f"({len(rep.ok)} ok, {len(rep.problems)} failed, "
          f"{len(rep.manifest_issues)} manifest note(s))")
    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
