"""Whole-product acceptance flow on a fake game folder (used by tests/test_acceptance.py and build/acceptance_report.py).

For one (edition, game build, modpack) it runs what a user does, through the product's own API:

  choose  the pack with its default add-ons and a variant
  get     every selected mod "downloaded": fixture archives built from the manifest so they look like the real ones
          (names matching ``archive``, the ``files`` the copy steps need, ``requireMembers`` present, no ``rejectMembers``)
  check   ``Session.findings()``: no errors
  install every mod through ``Installer`` (locked settings included); guided/run steps are done by a UI stub that
          makes the step's file changes the way a person following the steps would (new files in the mods/onigiri/
          scripts folders the steps name)
  verify  the mods' logs written the way the real mods write them, then ``verify_session``: nothing FAILED
  variant switch the variant (settings re-applied, no drift)
  pack    switch to another pack: the mods that left are rolled back, new ones installed
  custom  add one of "your own mods" and install it
  uninstall everything: the game folder equals the starting folder byte for byte

Nothing touches a real game or Leonida's real state: everything lives under the given work folder.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import traceback
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from leonida import custommods, packs
from leonida import session as session_mod
from leonida.manifest import load_manifest
from leonida.matcher import match_files
from leonida.members import member_problem
from leonida.session import Session
from leonida.verify import FAILED, verify_session

STEPS = ("setup", "choose", "get", "check", "install", "verify", "variant", "pack", "custom", "uninstall")
EDITION_BUILDS = {"enhanced": ("1.0.1013.20", "1.0.1158.13"), "legacy": ("1.0.3411.0",)}
EXE = {"enhanced": "GTA5_Enhanced.exe", "legacy": "GTA5.exe"}


@dataclass
class Result:
    edition: str
    build: str
    pack: str
    ok: bool = False
    step: str = ""            # the step that failed ("" when ok)
    detail: str = ""
    notes: list[str] = field(default_factory=list)
    mods: int = 0

    @property
    def label(self) -> str:
        return "PASS" if self.ok else f"FAIL at {self.step}"


class StepFailed(AssertionError):
    def __init__(self, step: str, detail: str):
        super().__init__(f"{step}: {detail}")
        self.step, self.detail = step, detail


def combos() -> list[tuple[str, str, str]]:
    out = []
    for edition, builds in EDITION_BUILDS.items():
        packs_ = list(load_manifest(edition=edition).packs)
        out += [(edition, b, p) for b in builds for p in packs_]
    return out


# ------------------------------------------------------------------------------------------ fake game & fixtures
def make_game(root: Path, edition: str) -> Path:
    g = root / ("Grand Theft Auto V Enhanced" if edition == "enhanced" else "Grand Theft Auto V")
    (g / "update" / "x64").mkdir(parents=True)
    (g / "x64").mkdir()
    (g / EXE[edition]).write_bytes(b"MZ fake game exe")
    (g / "PlayGTAV.exe").write_bytes(b"MZ launcher")
    (g / "bink2w64.dll").write_bytes(b"original bink")
    (g / "update" / "update.rpf").write_bytes(b"RPF7" * 256)
    (g / "x64" / "data.rpf").write_bytes(b"RPF7" * 64)
    return g


def fingerprint(folder: Path) -> dict[str, str]:
    """Every file (sha256) and every folder of ``folder``: the byte-for-byte comparison."""
    out = {}
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<dir>"
    return out


def _render(pattern: str) -> str:
    """A concrete name a glob matches: [abc] -> a, * and ? -> x."""
    return re.sub(r"\[!?\^?(.)[^\]]*\]", r"\1", pattern).replace("*", "x").replace("?", "x")


def fixture_name(mod) -> str:
    """A download name that matches one of the mod's archive patterns, as a .zip when the mod needs an archive."""
    import fnmatch

    needs_archive = mod.method in ("copy", "generic", "run") or mod.require_members or mod.reject_members
    names = [_render(p) for p in mod.archive]
    for name in names:  # a .zip first: the test can build those for real (.rar can't be made here)
        if name.lower().endswith(".zip"):
            return name
    for pat, name in zip(mod.archive, names, strict=True):
        for cand in (name + ".zip", re.sub(r"\.(7z|rar)x?$", ".zip", name, flags=re.I)):
            if cand.lower().endswith(".zip") and fnmatch.fnmatchcase(cand.lower(), pat.lower()):
                return cand
    if not needs_archive:  # .oiv / .exe / .xml downloads that guided steps use as they are
        plain = next((n for n in names if not n.lower().endswith((".rar", ".7z"))), None)
        if plain:
            return plain
    return f"{mod.id}-fixture.zip"  # nothing fits: an assignment makes it this mod's file


def fixture_members(mod) -> dict[str, str]:
    members: dict[str, str] = {}
    for spec in mod.files:
        if spec.type == "dir":
            members[f"{mod.id}-pkg/{spec.match}/{mod.id}.dat"] = f"{mod.id} data"
        else:
            members[f"{mod.id}-pkg/{spec.match}"] = f"{mod.id}:{spec.match}"
    if mod.method == "generic":
        members[f"{mod.id}-pkg/{mod.id}.asi"] = f"{mod.id} asi"
        members[f"{mod.id}-pkg/scripts/{mod.id}.dll"] = f"{mod.id} script"
    if mod.method == "run" and mod.run:
        members[f"{mod.id}-pkg/{mod.run}"] = "@echo off"
    for pat in mod.require_members:
        members[_render(pat)] = f"{mod.id} required"
    if not members:
        members[f"{mod.id}-pkg/readme.txt"] = f"{mod.id} readme"
    problem = member_problem(mod, list(members))
    if problem:  # e.g. a rendered name that a rejectMembers pattern also catches
        raise StepFailed("get", f"can't build a fixture for {mod.id}: {problem}")
    return members


def write_fixture(downloads: Path, mod) -> Path:
    path = downloads / fixture_name(mod)
    downloads.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".zip" or mod.method in ("copy", "generic", "run"):
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in fixture_members(mod).items():
                zf.writestr(name, data)
    else:  # .oiv / .exe / .xml downloads used by guided steps
        path.write_bytes(f"{mod.id} download".encode())
    return path


# ------------------------------------------------------------------------------------------------- the user
class StubUI:
    """Says yes, and does guided/run steps the way a person following them would: the files the steps put into
    mods/ (OpenIV/.oiv/rpf), onigiri/ (NVE) or scripts/ appear there."""

    def __init__(self, game: Path):
        self.game = game
        self.lines: list[str] = []
        self.done: list[str] = []

    def info(self, msg):
        self.lines.append(msg)

    def warn(self, msg):
        self.lines.append("WARN " + msg)

    def confirm(self, msg, default=True):
        return True

    def launch(self, path):
        self.lines.append(f"ran {Path(path).name}")

    def wait_done(self, title, steps, folder):
        text = " ".join(steps).lower()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "mod"
        if "onigiri" in text:
            target = self.game / "onigiri" / slug
        elif any(w in text for w in ("openiv", ".oiv", "rpf", "mods folder", "mods\\")):
            target = self.game / "mods" / "leonida-acceptance" / slug
        else:
            target = self.game / "scripts" / slug
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{slug}.txt").write_text(f"{title}: done as the steps say\n", encoding="utf-8")
        self.done.append(title)
        return True


def write_logs(s: Session, game: Path) -> list[Path]:
    """The logs the real mods write at a game start, for what is installed (formats as verify.py documents them)."""
    placed = [a.path for st in s.log.active_steps() for a in st.actions]
    asis = sorted({Path(p).name for p in placed if p.lower().endswith(".asi")})
    scripts = sorted({Path(p).name for p in placed if p.lower().startswith("scripts/") and p.lower().endswith(".dll")})
    installed = s.log.installed_mods()
    logs = {}
    logs["ScriptHookV.log"] = ("SCRIPT HOOK (build Nov 24 2026, v1.0.3889.0)\nINIT: Registering script threads\n"
                               + "".join(f"Registering script '{a}'\n" for a in asis)
                               + "INIT: Success, game version is VER_EN_1_0_1013_17\n")
    logs["asiloader.log"] = "".join(f'"{a}" => 0x7ff6a0000000\n' for a in asis)
    if "shvdne" in installed or scripts:
        logs["ScriptHookVDotNet.log"] = ("[00:00:01] [INFO] ScriptHookV .Net Enhanced 3.9.0.6 (1.1.0.6)\n"
                                         + "".join(f"[00:00:02] [INFO] Found 1 script(s) in {d} resolved to API version"
                                                   f" 3.7.0.\n[00:00:02] [INFO] Started script {Path(d).stem}.Main.\n"
                                                   for d in scripts))
    if "menyoo" in installed:
        logs["menyooLog.txt"] = "Menyoo Version: 2.0\nGame Version: 1.0.1013.17\nINIT - GTAMemory Init Done\n"
    if "directstoragefix" in installed:
        logs["DirectStorageFix.log"] = "[info] Game build: 1013\n[info] Init finished\n"
    out = []
    for name, text in logs.items():
        (game / name).write_text(text, encoding="utf-8")
        out.append(game / name)
    return out


@contextlib.contextmanager
def fake_pc(rtx50: bool):
    """Prerequisites present and the GPU the pack needs, without looking at the real PC."""
    real = session_mod.check_prerequisites
    old_gpu = os.environ.get("LEONIDA_FAKE_GPU")
    session_mod.check_prerequisites = lambda: {"dotnet48": True, "vcredist": True}
    os.environ["LEONIDA_FAKE_GPU"] = "NVIDIA GeForce RTX 5080" if rtx50 else "NVIDIA GeForce GTX 1070"
    try:
        yield
    finally:
        session_mod.check_prerequisites = real
        if old_gpu is None:
            os.environ.pop("LEONIDA_FAKE_GPU", None)
        else:
            os.environ["LEONIDA_FAKE_GPU"] = old_gpu


# ------------------------------------------------------------------------------------------------- the flow
def run(work: Path, edition: str, build: str, pack: str, manifest_dir: Path | None = None) -> Result:
    res = Result(edition, build, pack)
    step = "setup"
    try:
        game = make_game(work, edition)
        before = fingerprint(game)
        state, downloads = work / "state", work / "downloads"
        s = Session(state, manifest_dir, download_dir=str(downloads), game_dir=str(game), game_build=build)
        if s.edition != edition:
            raise StepFailed(step, f"the session picked {s.edition}")
        base = s.base_manifest
        with fake_pc(rtx50=(base.get_pack(pack).requires or {}).get("gpu") == "rtx50"):
            # choose ------------------------------------------------------------------------------------
            step = "choose"
            pk = base.get_pack(pack)
            variants = [v.id for v in pk.variants]
            first_variant = variants[0] if variants else None
            s.choose_pack(pack, None, first_variant)
            gone = [m for m in s.manifest.resolve_pack(pack, s.chosen_addons(), first_variant) if m.unsupported]
            if gone:  # the app greys these out on this build: the user can't pick them
                s.config.remove = sorted({*s.config.remove, *(m.id for m in gone)})
                res.notes.append("not for this build (left out): " + ", ".join(m.id for m in gone))
            mods = s.mods()
            res.mods = len(mods)
            # get ---------------------------------------------------------------------------------------
            step = "get"
            for m in s.manifest.mods.values():
                f = write_fixture(downloads, m)
                if m.id not in match_files([m], [f]).matched or set(
                        match_files(list(s.manifest.mods.values()), [f]).matched) != {m.id}:
                    s.config.assignments[f.name] = m.id  # a name others also fit: the user assigns it
            s.save()
            got = s.matches(mods)
            missing = [m.id for m in got.missing(mods)]
            if missing:
                raise StepFailed(step, f"no usable download for {missing}; wrong files: "
                                       f"{[(p.name, w) for p, w in got.wrong.items()]}")
            for p, (mid, why) in got.wrong.items():  # another mod's file that also fits this mod's name
                res.notes.append(f"{p.name} isn't {mid} ({why})")
            # check -------------------------------------------------------------------------------------
            step = "check"
            errors = [f for f in s.findings() if f.level == "error"]
            if errors:
                raise StepFailed(step, "; ".join(f"{f.code}: {f.message}" for f in errors[:5]))
            # install -----------------------------------------------------------------------------------
            step = "install"
            ui = StubUI(game)
            inst = s.installer(ui)
            for m in mods:
                inst.install(m, got.matched[m.id])
            if s.log.installed_mods() != {m.id for m in mods}:
                raise StepFailed(step, f"installed {sorted(s.log.installed_mods())}")
            drift = s.settings_drift()  # the locked values are written inside each mod's own step: none yet
            if drift:
                raise StepFailed(step, "settings not written at install: " +
                                 "; ".join(d.message() for d in drift[:3]))
            if s.apply_settings(ui):
                raise StepFailed(step, "settings had to be re-applied after install")
            locked = s.installed_settings()
            if locked:
                res.notes.append(f"locked settings written: {len(locked)}")
            # verify ------------------------------------------------------------------------------------
            step = "verify"
            logs = write_logs(s, game)
            failed = [r for r in verify_session(s) if r.status == FAILED]
            if failed:
                raise StepFailed(step, "; ".join(r.message for r in failed[:5]))
            for p in logs:  # the game's logs aren't Leonida's files: moved aside like `leonida playtest` does
                p.replace(state / f"log-{p.name}")
            # variant -----------------------------------------------------------------------------------
            step = "variant"
            if len(variants) > 1:
                s.choose_pack(pack, None, variants[-1])
                changed = s.apply_settings(ui)
                if changed:
                    res.notes.append(f"variant {variants[-1]}: settings re-applied for {len(changed)} mod(s)")
                if s.settings_drift():
                    raise StepFailed(step, "settings drift after switching the variant")
            else:
                res.notes.append("no variants to switch")
            # pack --------------------------------------------------------------------------------------
            step = "pack"
            other = next((p for p in base.packs if p != pack), None)
            if other is not None:
                before_ids = {m.id for m in s.mods()}
                s.choose_pack(other)
                after = s.mods()
                leaving = (before_ids - {m.id for m in after}) & s.log.installed_mods()
                report = packs.rollback_mods(s, ui, leaving)
                kept = [ln for ln in report if ": kept" in ln or "couldn't" in ln]
                res.notes += kept
                got = s.matches(after)
                new = [m for m in after if m.id not in s.log.installed_mods() and not m.unsupported]
                for m in new:
                    if m.id not in got.matched:
                        raise StepFailed(step, f"no download for {m.id}")
                    inst.install(m, got.matched[m.id])
            # custom ------------------------------------------------------------------------------------
            step = "custom"
            mine = work / "my mods" / "MyTweak.zip"
            mine.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(mine, "w") as zf:
                zf.writestr("MyTweak/mytweak.asi", "my own mod")
            custommods.add(state, s.manifest_for(edition), name="My tweak", file=str(mine), files=["mytweak.asi"])
            m = s.manifest.mod("my-tweak")
            inst.install(m, s.matches([m]).matched["my-tweak"])
            # uninstall ---------------------------------------------------------------------------------
            step = "uninstall"
            warnings, residual = inst.uninstall()
            if residual is not None and not residual.empty:
                raise StepFailed(step, f"left behind: {residual.summary()}; {warnings[:3]}")
            after_fp = fingerprint(game)
            if after_fp != before:
                diffs = sorted(set(before.items()) ^ set(after_fp.items()))[:6]
                raise StepFailed(step, f"not byte for byte the starting folder: {diffs}")
            if warnings:
                res.notes += warnings[:3]
        res.ok = True
    except StepFailed as exc:
        res.step, res.detail = exc.step, exc.detail
    except Exception as exc:  # a crash is a failure of the step it happened in
        res.step = step
        res.detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}"
    return res
