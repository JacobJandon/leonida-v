"""Plan and run install steps, log every file, and undo them exactly."""

from __future__ import annotations

import contextlib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

from . import log as L
from .archive import ArchiveError, extract, is_archive, list_members
from .manifest import FileSpec, Manifest, Mod
from .matcher import sha256_file
from .paths import BACKUPS_DIR, BASELINE_NAME, EXTRACT_DIR
from .snapshot import HASH_LIMIT, diff, load_snapshot, save_snapshot, take_snapshot

RUNNABLE_EXTS = (".exe", ".msi", ".bat", ".cmd")
PRE_BACKUP_DIRS = ("scripts",)  # small files here (and at the top level) are backed up before run/guided steps


class InstallError(RuntimeError):
    pass


class UI(Protocol):
    def info(self, msg: str) -> None: ...
    def warn(self, msg: str) -> None: ...
    def confirm(self, msg: str, default: bool = True) -> bool: ...
    def wait_done(self, title: str, steps: list[str], folder: Path | None) -> bool: ...
    def launch(self, path: Path) -> None: ...


@dataclass
class Copy:
    src: str        # member path inside the archive (POSIX)
    dest: str       # path relative to the game folder (POSIX)


@dataclass
class StepPlan:
    mod: Mod
    archive: Path | None
    copies: list[Copy] = field(default_factory=list)
    run_target: str | None = None
    problems: list[str] = field(default_factory=list)

    def describe(self) -> list[str]:
        lines = [f"{self.mod.name} [{self.mod.method}] from {self.archive.name if self.archive else '(no file)'}"]
        lines += [f"  copy {c.src} -> {c.dest}" for c in self.copies]
        if self.run_target:
            lines.append(f"  run {self.run_target}")
        if self.mod.method == "guided":
            lines += [f"  step: {s}" for s in self.mod.steps]
        lines += [f"  PROBLEM: {p}" for p in self.problems]
        return lines


def _parts(member: str) -> tuple[str, ...]:
    return PurePosixPath(member).parts


def _variant_score(member: str) -> tuple[int, int]:
    """Prefer paths mentioning Enhanced, avoid Legacy, then the shallowest."""
    low = member.lower()
    score = 0
    if "enhanced" in low or "gen9" in low:
        score -= 2
    if "legacy" in low:
        score += 2
    return score, len(_parts(member))


def _prefer_enhanced(members: list[str]) -> list[str]:
    has_enh = any("enhanced" in m.lower() for m in members)
    has_leg = any("legacy" in m.lower() for m in members)
    if has_enh and has_leg:
        return [m for m in members if "legacy" not in m.lower()]
    return members


def _join(to: str, *rest: str) -> str:
    base = PurePosixPath(to.replace("\\", "/"))
    out = base.joinpath(*rest)
    s = str(out)
    return s[2:] if s.startswith("./") else s


class Installer:
    def __init__(self, manifest: Manifest, game_dir: Path, state_dir: Path, log: L.InstallLog, ui: UI,
                 *, seven_zip: Path | None = None, dry_run: bool = False):
        self.manifest = manifest
        self.game = Path(game_dir)
        self.state = Path(state_dir)
        self.log = log
        self.ui = ui
        self.seven_zip = seven_zip
        self.dry_run = dry_run

    # ---- baseline ---------------------------------------------------------
    @property
    def baseline_path(self) -> Path:
        return self.state / BASELINE_NAME

    def ensure_baseline(self) -> dict:
        snap = load_snapshot(self.baseline_path)
        if snap is None:
            snap = take_snapshot(self.game)
            if not self.dry_run:
                save_snapshot(snap, self.baseline_path)
                self.ui.info(f"Baseline snapshot saved ({len(snap['files'])} files recorded).")
        return snap

    # ---- planning ---------------------------------------------------------
    def plan(self, mod: Mod, archive: Path | None) -> StepPlan:
        plan = StepPlan(mod, archive)
        if archive is None:
            plan.problems.append("No downloaded file matched this mod. Run `leonida get` or `leonida assign`.")
            return plan
        if mod.method in ("copy", "generic") and not is_archive(archive):
            plan.problems.append(f"{archive.name} is not a .zip/.7z/.rar archive.")
            return plan
        members: list[str] = []
        if is_archive(archive):
            try:
                members = list_members(archive, self.seven_zip)
            except ArchiveError as exc:
                plan.problems.append(str(exc))
                return plan
        if mod.method == "copy":
            for spec in mod.files:
                plan.copies += self._plan_spec(spec, members, plan)
        elif mod.method == "generic":
            plan.copies = self._plan_generic(members)
            if not plan.copies:
                plan.problems.append("Nothing recognisable (.asi/.ini or a scripts folder) in the archive; "
                                     "install it by hand from the extracted folder.")
        elif mod.method == "run":
            if is_archive(archive):
                hits = sorted((m for m in members if _parts(m)[-1].lower() == (mod.run or "").lower()),
                              key=_variant_score)
                if hits:
                    plan.run_target = hits[0]
                else:
                    plan.problems.append(f"{mod.run} not found in {archive.name}.")
            elif archive.suffix.lower() in RUNNABLE_EXTS:
                plan.run_target = archive.name
        return plan

    def _plan_spec(self, spec: FileSpec, members: list[str], plan: StepPlan) -> list[Copy]:
        want = spec.match.lower()
        if spec.type == "file":
            hits = sorted((m for m in members if _parts(m)[-1].lower() == want), key=_variant_score)
            if not hits:
                if not spec.optional:
                    plan.problems.append(f"{spec.match} not found in the archive.")
                return []
            return [Copy(hits[0], _join(spec.to, _parts(hits[0])[-1]))]
        # directory spec: copy everything under the best-matching folder of that name
        prefixes: set[tuple[str, ...]] = set()
        for m in members:
            parts = _parts(m)
            for i, seg in enumerate(parts[:-1]):
                if seg.lower() == want:
                    prefixes.add(parts[: i + 1])
        if not prefixes:
            if not spec.optional:
                plan.problems.append(f"Folder {spec.match} not found in the archive.")
            return []
        best = min(prefixes, key=lambda p: _variant_score("/".join(p)))
        out = []
        for m in members:
            parts = _parts(m)
            if parts[: len(best)] == best:
                out.append(Copy(m, _join(spec.to, best[-1], *parts[len(best):])))
        return out

    def _plan_generic(self, members: list[str]) -> list[Copy]:
        members = _prefer_enhanced(members)
        out: list[Copy] = []
        asi_stems: set[str] = set()
        for m in members:
            parts = _parts(m)
            low = [p.lower() for p in parts]
            if "scripts" in low[:-1]:
                i = low.index("scripts")
                out.append(Copy(m, _join("scripts", *parts[i + 1:])))
            elif low[-1].endswith(".asi"):
                out.append(Copy(m, parts[-1]))
                asi_stems.add(PurePosixPath(low[-1]).stem)
        for m in members:
            parts = _parts(m)
            low = [p.lower() for p in parts]
            if "scripts" not in low[:-1] and low[-1].endswith(".ini") and PurePosixPath(low[-1]).stem in asi_stems:
                out.append(Copy(m, parts[-1]))
        # de-duplicate destinations (first, i.e. preferred variant, wins)
        seen: set[str] = set()
        uniq = []
        for c in out:
            if c.dest.lower() not in seen:
                seen.add(c.dest.lower())
                uniq.append(c)
        return uniq

    # ---- executing ----------------------------------------------------------
    def install(self, mod: Mod, archive: Path | None) -> L.Step | None:
        plan = self.plan(mod, archive)
        if self.dry_run:
            for line in plan.describe():
                self.ui.info(line)
            return None
        if plan.problems and mod.method in ("copy", "generic", "run"):
            raise InstallError(f"{mod.name}: " + " ".join(plan.problems))
        if mod.method == "generic":
            for line in plan.describe():
                self.ui.info(line)
            if not self.ui.confirm(f"Copy these {len(plan.copies)} file(s) for {mod.name}?"):
                raise InstallError(f"{mod.name}: cancelled")
        self.ensure_baseline()
        step = self.log.new_step(mod.id, mod.method)
        try:
            for d in mod.create_dirs:
                target = self.game / d
                if not target.exists():
                    target.mkdir(parents=True)
                    step.actions.append(L.Action(L.MKDIR, PurePosixPath(d).as_posix()))
            if mod.method in ("copy", "generic"):
                self._do_copies(step, plan)
            else:
                self._do_external(step, plan)
            step.status = "done"
        except BaseException:
            step.status = "failed"
            step.notes.append("Step failed part-way; use rollback to undo what was placed.")
            raise
        finally:
            step.finished = L.now()
            self.log.save()
        return step

    def _backup(self, step: L.Step, rel: str, tag: str = "") -> str:
        dest_rel = PurePosixPath(BACKUPS_DIR, f"step-{step.id}", tag, rel).as_posix()
        dest = self.state / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.game / rel, dest)
        return dest_rel

    def _do_copies(self, step: L.Step, plan: StepPlan) -> None:
        with tempfile.TemporaryDirectory(prefix="leonida-") as tmp:
            extract(plan.archive, Path(tmp), self.seven_zip)
            for c in plan.copies:
                src = Path(tmp) / c.src
                dest = self.game / c.dest
                new_hash = sha256_file(src)
                if dest.exists():
                    if dest.is_file() and sha256_file(dest) == new_hash:
                        step.notes.append(f"{c.dest} already identical; left as is")
                        continue
                    backup = self._backup(step, c.dest)
                    op = L.REPLACE
                else:
                    backup, op = None, L.ADD
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                step.actions.append(L.Action(op, c.dest, new_hash, backup))
                self.log.save()

    def _pre_backup(self, step: L.Step) -> dict[str, str]:
        """Back up small top-level files and scripts/ before a step we can't see into."""
        saved: dict[str, str] = {}
        candidates = [p for p in self.game.iterdir() if p.is_file()]
        for d in PRE_BACKUP_DIRS:
            if (self.game / d).is_dir():
                candidates += [p for p in (self.game / d).rglob("*") if p.is_file()]
        for p in candidates:
            if p.stat().st_size <= HASH_LIMIT:
                rel = p.relative_to(self.game).as_posix()
                saved[rel] = self._backup(step, rel, "pre")
        return saved

    def _do_external(self, step: L.Step, plan: StepPlan) -> None:
        mod = plan.mod
        before = take_snapshot(self.game)
        saved = self._pre_backup(step)
        folder = None
        if plan.archive and is_archive(plan.archive):
            folder = self.state / EXTRACT_DIR / mod.id
            if folder.exists():
                shutil.rmtree(folder)
            extract(plan.archive, folder, self.seven_zip)
        elif plan.archive:
            folder = plan.archive.parent
        if mod.method == "run" and plan.run_target:
            target = (folder / plan.run_target) if folder and is_archive(plan.archive) else plan.archive
            self.ui.info(f"Starting {target.name} ...")
            self.ui.launch(target)
        done = self.ui.wait_done(mod.name, list(mod.steps), folder)
        after = take_snapshot(self.game)
        d = diff(before, after)
        for rel in d.added:
            if rel.endswith("/"):
                step.actions.append(L.Action(L.EXT_ADD, rel))
            else:
                step.actions.append(L.Action(L.EXT_ADD, rel, after["files"][rel][2]))
        for rel in d.changed:
            step.actions.append(L.Action(L.EXT_CHANGE, rel, after["files"][rel][2], saved.get(rel)))
        for rel in d.removed:
            step.actions.append(L.Action(L.EXT_REMOVE, rel, None, saved.get(rel)))
        for name in d.added_dirs:
            if not any(a.path.split("/")[0] == name for a in step.actions):
                step.actions.append(L.Action(L.EXT_ADD, name + "/"))
        # drop pre-backups nobody needs
        needed = {a.backup for a in step.actions if a.backup}
        for b in saved.values():
            if b not in needed:
                (self.state / b).unlink(missing_ok=True)
        step.notes.append(f"Changes seen: {d.summary()}")
        if not done:
            step.notes.append("User did not confirm the step as done.")
            raise InstallError(f"{mod.name}: not confirmed as done (changes so far are logged; you can roll back)")

    # ---- undo -------------------------------------------------------------
    def _remove_empty_parents(self, path: Path, keep_top: set[str]) -> None:
        parent = path.parent
        while parent != self.game and self.game in parent.parents:
            rel_top = parent.relative_to(self.game).parts[0]
            if parent.parent == self.game and rel_top in keep_top:
                break
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def rollback(self, step_id: int) -> list[str]:
        step = self.log.get(step_id)
        if step.status == "rolled-back":
            return [f"Step {step_id} is already rolled back."]
        later = [s for s in self.log.active_steps() if s.id > step_id]
        if later:
            raise InstallError(f"Roll back later steps first: {', '.join(str(s.id) for s in later)}")
        baseline = load_snapshot(self.baseline_path) or {"top_dirs": []}
        keep_top = set(baseline.get("top_dirs", []))
        warnings: list[str] = []
        orphans = self.state / "orphans" / f"step-{step.id}"
        for a in reversed(step.actions):
            target = self.game / a.path.rstrip("/")
            if self.dry_run:
                self.ui.info(f"undo {a.op} {a.path}")
                continue
            if a.op in (L.ADD, L.EXT_ADD):
                if a.path.endswith("/"):
                    if target.is_dir() and a.path.rstrip("/").count("/") == 0 and a.op == L.EXT_ADD:
                        shutil.rmtree(target)
                    elif target.is_dir():
                        with contextlib.suppress(OSError):
                            target.rmdir()
                    continue
                if not target.exists():
                    continue
                if a.sha256 and target.is_file() and sha256_file(target) != a.sha256:
                    dest = orphans / a.path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(dest))
                    warnings.append(f"{a.path} was edited after install; moved to {dest} instead of deleting")
                else:
                    target.unlink()
                self._remove_empty_parents(target, keep_top)
            elif a.op in (L.REPLACE, L.EXT_CHANGE, L.EXT_REMOVE):
                if a.backup and (self.state / a.backup).exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(self.state / a.backup, target)
                else:
                    warnings.append(f"{a.path}: no backup (file was too big); restore it by verifying game files")
            elif a.op == L.MKDIR:
                try:
                    target.rmdir()
                except OSError:
                    warnings.append(f"{a.path}: folder not empty, left in place")
        if not self.dry_run:
            step.status = "rolled-back"
            step.notes.append(f"Rolled back at {L.now()}")
            self.log.save()
        return warnings

    def uninstall(self) -> tuple[list[str], object]:
        warnings: list[str] = []
        for step in reversed(self.log.active_steps()):
            warnings += self.rollback(step.id)
        baseline = load_snapshot(self.baseline_path)
        residual = diff(baseline, take_snapshot(self.game)) if baseline else None
        return warnings, residual
