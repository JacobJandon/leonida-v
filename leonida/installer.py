"""Plan and run install steps, log every file, and undo them exactly."""

from __future__ import annotations

import contextlib
import fnmatch
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol

from . import log as L
from .archive import ArchiveError, extract, is_archive, list_members
from .manifest import FileSpec, Manifest, Mod
from .matcher import sha256_file
from .members import has_rules, member_problem, wrong_message
from .paths import BACKUPS_DIR, BASELINE_NAME, EXTRACT_DIR
from .snapshot import HASH_LIMIT, diff, load_snapshot, save_snapshot, take_snapshot

RUNNABLE_EXTS = (".exe", ".msi", ".bat", ".cmd")
PRE_BACKUP_DIRS = ("scripts",)  # small files here (and at the top level) are backed up before run/guided steps


def windows_launch_command(path: Path) -> str:
    """cmd.exe line that runs an .exe/.msi/.bat/.cmd, safe for spaces, parentheses and '&' in the path.

    `cmd /c "x"` strips the outer quotes when the path holds special characters such as '&', which splits the
    path apart. Wrapping it in a second pair of quotes leaves the inner pair intact (see `cmd /?`).
    Pass the result as a string, not a list, so Python does not escape the quotes.
    """
    return f'cmd /d /c ""{path}""'


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
    wrong: str | None = None   # the file fails the mod's requireMembers/rejectMembers: never installed
    extra: list[str] = field(default_factory=list)  # method rpf: what happens inside the archives

    def describe(self) -> list[str]:
        lines = [f"{self.mod.name} [{self.mod.method}] from {self.archive.name if self.archive else '(no file)'}"]
        lines += [f"  copy {c.src} -> {c.dest}" for c in self.copies]
        if self.run_target:
            lines.append(f"  run {self.run_target}")
        lines += self.extra
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
                 *, seven_zip: Path | None = None, dry_run: bool = False, settings_for=None):
        self.manifest = manifest
        self.game = Path(game_dir)
        self.state = Path(state_dir)
        self.log = log
        self.ui = ui
        self.seven_zip = seven_zip
        self.dry_run = dry_run
        self.settings_for = settings_for  # mod -> [settings.Wanted]: locked values written as part of its install

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
        if mod.method == "rpf" and not (is_archive(archive) or archive.suffix.lower() == ".oiv"):
            plan.problems.append(f"{archive.name} is not a .zip/.7z/.rar archive or an .oiv package.")
            return plan
        members: list[str] = []
        if is_archive(archive):
            try:
                members = list_members(archive, self.seven_zip)
            except ArchiveError as exc:
                plan.problems.append(str(exc))
                return plan
        if has_rules(mod):
            reason = member_problem(mod, members) if is_archive(archive) else \
                f"{archive.name} is not an archive, so Leonida can't check that it's the right edition"
            if reason:
                plan.wrong = wrong_message(mod, reason)
                plan.problems.append(f"{archive.name}: {plan.wrong}")
                return plan
        if mod.method in ("copy", "rpf"):
            for spec in mod.files:
                plan.copies += self._plan_spec(spec, members, plan)
        if mod.method == "rpf":
            self._plan_rpf(mod, archive, members, plan)
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
        if plan.wrong:
            raise InstallError(f"{mod.name}: {archive.name if archive else 'the file'}: {plan.wrong}")
        if plan.problems and mod.method in ("copy", "generic", "run", "rpf"):
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
            elif mod.method == "rpf":
                self._do_rpf(step, plan)
            else:
                self._do_external(step, plan)
            if self.settings_for is not None:
                self._write_settings(step, self.settings_for(mod))
            step.status = "done"
        except BaseException:
            step.status = "failed"
            step.notes.append("Step failed part-way; use rollback to undo what was placed.")
            raise
        finally:
            step.finished = L.now()
            self.log.save()
        return step

    # ---- locked settings (leonida/settings.py) ------------------------------------
    def _write_settings(self, step: L.Step, wanted: list) -> list[str]:
        """Write the locked values into this step: a file this step placed keeps its action (new checksum); any other
        file is backed up first (REPLACE), so rollback restores the user's file. Returns the files changed."""
        from . import settings as S

        changed = []
        for file, items in S.by_file(wanted).items():
            rel = PurePosixPath(file).as_posix()
            target = self.game / rel
            data = S.render(target, items)
            if data is None:
                continue
            mine = next((a for a in step.actions if a.path.lower() == rel.lower() and a.op in
                         (L.ADD, L.EXT_ADD, L.REPLACE, L.EXT_CHANGE)), None)
            if mine is not None:
                target.write_bytes(data)
                mine.sha256 = sha256_file(target)
            elif target.exists():
                backup = self._backup(step, rel, "settings")
                step.actions.append(L.Action(L.REPLACE, rel, None, backup))
                self.log.save()
                target.write_bytes(data)
                step.actions[-1].sha256 = sha256_file(target)
            else:
                step.actions.append(L.Action(L.ADD, rel))
                self.log.save()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                step.actions[-1].sha256 = sha256_file(target)
            changed.append(rel)
            self.log.save()
        return changed

    def apply_settings(self, mod: Mod, wanted: list) -> L.Step | None:
        """Write a mod's locked settings again (e.g. after a variant switch) as a logged "settings:<mod>" step;
        None when every value is already right."""
        from . import settings as S

        pending = {f: items for f, items in S.by_file(wanted).items() if S.render(self.game / f, items) is not None}
        if not pending:
            return None
        if self.dry_run:
            for f, items in pending.items():
                self.ui.info(f"set {', '.join(f'{w.key}={w.value}' for w in items)} in {f}")
            return None
        self.ensure_baseline()
        step = self.log.new_step(f"settings:{mod.id}", "settings")
        try:
            self._write_settings(step, [w for items in pending.values() for w in items])
            step.status = "done"
        except BaseException:
            step.status = "failed"
            step.notes.append("Writing settings failed part-way; use rollback to undo what was written.")
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
            self._place(step, [(Path(tmp) / c.src, c.dest) for c in plan.copies])

    def _place(self, step: L.Step, copies: list[tuple[Path, str]]) -> None:
        """Copy (source file, game-relative POSIX dest) pairs into the game folder: logged first, replaced files
        backed up, identical files left alone."""
        for src, rel in copies:
            dest = self.game / rel
            new_hash = sha256_file(src)
            if dest.exists():
                if dest.is_file() and sha256_file(dest) == new_hash:
                    step.notes.append(f"{rel} already identical; left as is")
                    continue
                backup = self._backup(step, rel)
                op = L.REPLACE
            else:
                backup, op = None, L.ADD
            # log first: if the copy fails half-way, rollback still knows about the (partial) file
            step.actions.append(L.Action(op, rel, new_hash, backup))
            self.log.save()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # ---- rpf: archives in mods\ (see leonida/rpf.py) ------------------------------------------------
    def _plan_rpf(self, mod: Mod, archive: Path, members: list[str], plan: StepPlan) -> None:
        from . import rpf as R

        if R.find_helper(self.state) is None:
            plan.problems.append("The RPF helper (LeonidaRpf.exe, built on CodeWalker) isn't installed: "
                                 "run `python build/build_rpf_helper.py`.")
        names = {PurePosixPath(m.replace("\\", "/")).name.lower() for m in members}
        if archive.suffix.lower() == ".oiv":
            names.add(archive.name.lower())
        for op in mod.rpf:
            if "put" in op and op["put"].lower() not in names:
                plan.problems.append(f"{op['put']} not found in {archive.name}.")
            if "oiv" in op:
                if not any(fnmatch.fnmatch(n, op["oiv"].lower()) for n in names):
                    plan.problems.append(f"No .oiv matching {op['oiv']!r} in {archive.name}.")
                plan.extra.append(f"  apply .oiv {op['oiv']} to copies in mods\\ (never the game's own archives)")
                continue
            what = next(f"{k} {op[k]}" for k in ("put", "dlclist", "xml", "delete") if k in op)
            plan.extra.append(f"  rpf mods\\{R.win(op['archive'])}: {what}" + (f" -> {op['to']}" if "to" in op else ""))

    def _do_rpf(self, step: L.Step, plan: StepPlan) -> None:
        """Copy/edit game archives in mods\\ with the RPF helper; every archive is logged (ADD when this step
        creates the mods\\ copy, REPLACE with a full backup when it already existed) before it is touched."""
        from . import rpf as R

        helper = R.find_helper(self.state)
        if helper is None:
            raise InstallError("The RPF helper (LeonidaRpf.exe) isn't installed: run `python build/build_rpf_helper.py`.")
        with tempfile.TemporaryDirectory(prefix="leonida-") as tmp:
            root = Path(tmp) / "download"
            root.mkdir()
            if plan.archive.suffix.lower() == ".oiv":
                shutil.copy2(plan.archive, root / plan.archive.name)
            else:
                extract(plan.archive, root, self.seven_zip)
            members = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
            self._place(step, [(root / c.src, c.dest) for c in plan.copies])
            try:
                work = R.manifest_work(list(plan.mod.rpf), root, members)
            except R.RpfError as exc:
                raise InstallError(f"{plan.mod.name}: {exc}") from None
            for line in work.describe():
                self.ui.info(line.strip())
            self._check_space(work)
            ops: list[dict] = []
            actions: list[tuple[L.Action, Path]] = []
            for aw in work.archives.values():
                rel = R.mods_rel(aw.path)
                target = self.game / rel
                original = self.game / PurePosixPath(*PureWindowsPath(aw.path).parts)
                if target.is_file():
                    backup = self._backup(step, rel)            # whole archive: rollback restores it exactly
                    action = L.Action(L.REPLACE, rel, None, backup)
                    step.actions.append(action)
                    self.log.save()
                else:
                    action = L.Action(L.ADD, rel, None, None)   # log first: rollback deletes even a partial copy
                    step.actions.append(action)
                    self.log.save()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if original.is_file():
                        self.ui.info(f"Copying {aw.path} into mods ({original.stat().st_size / 2**30:.1f} GB) ...")
                        shutil.copy2(original, target)
                    elif aw.create:
                        ops.append({"op": "create", "rpf": str(target)})
                        self.ui.warn(f"The game has no {aw.path}; {plan.mod.name} was made for a newer game build, "
                                     f"so an empty one is made in mods for its files (as OpenIV does). The game only "
                                     f"loads it if that DLC pack exists in your version.")
                    else:
                        raise InstallError(f"{plan.mod.name}: the game has no {aw.path} to copy into mods.")
                actions.append((action, target))
                ops += [{**op, "rpf": str(target)} for op in aw.ops]
            if ops:
                self.ui.info(f"Editing {len(actions)} archive(s) with the RPF helper ({len(ops)} change(s)) ...")
                try:
                    R.run_helper(helper, self.game, ops)
                except R.RpfError as exc:
                    raise InstallError(f"{plan.mod.name}: {exc}") from None
            for action, target in actions:
                action.sha256 = sha256_file(target)
            self.log.save()
            self._place(step, list(work.loose_adds))
            for rel in work.loose_deletes:
                target = self.game / rel
                if target.is_file():
                    backup = self._backup(step, rel)
                    step.actions.append(L.Action(L.EXT_REMOVE, rel, sha256_file(target), backup))
                    self.log.save()
                    target.unlink()

    def _check_space(self, work) -> None:
        from . import rpf as R

        need = R.space_needed(self.game, work)
        if not need:
            return
        for where in {Path(self.game.anchor or self.game), Path(self.state.resolve().anchor or self.state)}:
            free = shutil.disk_usage(where).free
            if free < need + 512 * 2**20:
                raise InstallError(f"Not enough disk space on {where}: this step copies or backs up "
                                   f"{need / 2**30:.1f} GB of game archives (mods copies and their backups), "
                                   f"and only {free / 2**30:.1f} GB is free.")

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
        try:
            if mod.method == "run" and plan.run_target:
                target = (folder / plan.run_target) if folder and is_archive(plan.archive) else plan.archive
                self.ui.info(f"Starting {target.name} ...")
                self.ui.launch(target)
            done = self.ui.wait_done(mod.name, list(mod.steps), folder)
        except BaseException:
            # the installer/user may already have changed the game folder: log it so rollback can undo it
            self._record_external(step, before, saved)
            step.notes.append("The step was interrupted.")
            raise
        self._record_external(step, before, saved)
        if not done:
            step.notes.append("User did not confirm the step as done.")
            raise InstallError(f"{mod.name}: not confirmed as done (changes so far are logged; you can roll back)")

    def _record_external(self, step: L.Step, before: dict, saved: dict[str, str]) -> None:
        after = take_snapshot(self.game)
        d = diff(before, after)
        existed = {str(q).lower() for k in before.get("files", {}) for q in PurePosixPath(k.rstrip("/")).parents}
        existed |= {k.lower() for k in before.get("top_dirs", [])}
        for rel in d.added:
            if rel.endswith("/"):
                if rel.rstrip("/").lower() in existed:
                    continue  # a folder that was there (with files) and is now empty: not something the step added
                step.actions.append(L.Action(L.EXT_ADD, rel))
            else:
                step.actions.append(L.Action(L.EXT_ADD, rel, after["files"][rel][2]))
        for rel in d.changed:
            step.actions.append(L.Action(L.EXT_CHANGE, rel, after["files"][rel][2], saved.get(rel)))
        for rel in d.removed:
            if rel.endswith("/") and (self.game / rel.rstrip("/")).is_dir():
                continue  # an empty folder that now has files in it: nothing was removed
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
            elif a.op == L.EXT_REMOVE and a.path.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)  # an empty folder the step removed comes back
            elif a.op in (L.REPLACE, L.EXT_CHANGE, L.EXT_REMOVE):
                if a.backup and (self.state / a.backup).exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(self.state / a.backup, target)
                else:
                    warnings.append(f"{a.path}: no backup (file was too big); restore it by verifying game files")
            elif a.op == L.MKDIR:
                if not target.is_dir():
                    continue  # already gone (an undo above removed it once it was empty)
                try:
                    target.rmdir()
                except OSError:
                    warnings.append(f"{a.path}: folder not empty, left in place")
        if not self.dry_run:
            self._remove_created_dirs(step, baseline if "files" in baseline else None)
            step.status = "rolled-back"
            step.notes.append(f"Rolled back at {L.now()}")
            self.log.save()
        return warnings

    def _remove_created_dirs(self, step: L.Step, baseline: dict | None) -> None:
        """Remove the now-empty folders this step created, deepest first: every folder of its actions' paths that
        wasn't there at the baseline and that no other active step created. Never removes a non-empty folder."""
        if baseline is None:  # no baseline to tell what existed before: leave folders alone
            return
        known: set[str] = {d.lower() for d in baseline.get("top_dirs", [])}
        for key in baseline.get("files", {}):
            p = PurePosixPath(key.rstrip("/"))
            if key.endswith("/"):
                known.add(str(p).lower())
            known.update(str(q).lower() for q in p.parents if str(q) != ".")
        for other in self.log.active_steps():
            if other.id != step.id:
                for a in other.actions:
                    if a.op == L.MKDIR or a.path.endswith("/"):
                        known.add(a.path.rstrip("/").lower())
        candidates: set[PurePosixPath] = set()
        for a in step.actions:
            if a.op not in (L.ADD, L.EXT_ADD, L.MKDIR):
                continue
            p = PurePosixPath(a.path.rstrip("/"))
            if a.op == L.MKDIR or a.path.endswith("/"):
                candidates.add(p)
            candidates.update(q for q in p.parents if str(q) != ".")
        for d in sorted(candidates, key=lambda q: len(q.parts), reverse=True):
            if str(d).lower() in known:
                continue
            target = self.game / d
            with contextlib.suppress(OSError):
                if target.is_dir() and not any(target.iterdir()):
                    target.rmdir()

    def uninstall(self) -> tuple[list[str], object]:
        warnings: list[str] = []
        for step in reversed(self.log.active_steps()):
            warnings += self.rollback(step.id)
        baseline = load_snapshot(self.baseline_path)
        residual = diff(baseline, take_snapshot(self.game)) if baseline else None
        return warnings, residual
