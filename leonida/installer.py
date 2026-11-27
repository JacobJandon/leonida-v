"""Plan and run install steps, log every file, and undo them exactly."""

from __future__ import annotations

import contextlib
import fnmatch
import json
import logging
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

log = logging.getLogger(__name__)

RUNNABLE_EXTS = (".exe", ".msi", ".bat", ".cmd")
SPACE_MARGIN = 512 * 2**20  # keep this much free on a drive after a step
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
        elif self.mod.method == "rpf":
            lines += [f"  by hand afterwards: {s}" for s in self.mod.steps]
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
    if "fivem" in low.replace(" ", ""):  # a FiveM server resource, never the story-mode files
        score += 3
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
                 *, seven_zip: Path | None = None, dry_run: bool = False, settings_for=None, gate=None):
        self.manifest = manifest
        self.game = Path(game_dir)
        self.state = Path(state_dir)
        self.log = log
        self.ui = ui
        self.seven_zip = seven_zip
        self.dry_run = dry_run
        self.settings_for = settings_for  # mod -> [settings.Wanted]: locked values written as part of its install
        self.gate = gate  # (mod, file, plan) -> None, or InstallError: Leonida's test place (quarantine.py)

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
        # ties broken by the path itself, so the same archive always installs the same folder
        best = min(prefixes, key=lambda p: (_variant_score("/".join(p)), "/".join(p).lower()))
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
        if self.gate is not None and archive is not None:
            self.gate(mod, Path(archive), plan)  # a flagged / quarantined download is never installed
        if mod.method == "generic":
            for line in plan.describe():
                self.ui.info(line)
            if not self.ui.confirm(f"Copy these {len(plan.copies)} file(s) for {mod.name}?"):
                raise InstallError(f"{mod.name}: cancelled")
        self.ensure_baseline()
        step = self.log.new_step(mod.id, mod.method)
        log.info("install step %d: %s (%s) from %s", step.id, mod.id, mod.method, archive.name if archive else "-")
        try:
            for d in mod.create_dirs:
                rel = PurePosixPath(d.replace("\\", "/")).as_posix()  # manifests use "\": a real path on any OS
                target = self.game / rel
                if not target.exists():
                    target.mkdir(parents=True)
                    step.actions.append(L.Action(L.MKDIR, rel))
            if mod.method in ("copy", "generic"):
                self._do_copies(step, plan)
            elif mod.method == "rpf":
                self._do_rpf(step, plan)
            else:
                self._do_external(step, plan)
            if self.settings_for is not None:
                self._write_settings(step, self.settings_for(mod))
            step.status = "done"
            log.info("step %d done: %s, %d logged change(s)", step.id, mod.id, len(step.actions))
        except BaseException as exc:
            log.error("step %d failed: %s: %s", step.id, mod.id, exc, exc_info=not isinstance(exc, InstallError))
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
            target = S.resolve(self.game, rel)   # {documents}/... (GTA's own settings.xml) or the game folder
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
            log.info("locked settings written: %s (%s)", rel, ", ".join(f"{w.key}={w.value}" for w in items))
            self.log.save()
        return changed

    def apply_settings(self, mod: Mod, wanted: list) -> L.Step | None:
        """Write a mod's locked settings again (e.g. after a variant switch) as a logged "settings:<mod>" step;
        None when every value is already right."""
        from . import settings as S

        pending = {f: items for f, items in S.by_file(wanted).items()
                   if S.render(S.resolve(self.game, f), items) is not None}
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
        from . import settings as S

        shutil.copy2(S.resolve(self.game, rel), dest)
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
            log.debug("%s %s%s", op, rel, f" (backup {backup})" if backup else "")
            self.log.save()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # ---- rpf: archives in mods\ (see leonida/rpf.py) ------------------------------------------------
    def _plan_rpf(self, mod: Mod, archive: Path, members: list[str], plan: StepPlan) -> None:
        from . import rpf as R

        if R.find_helper(self.state) is None:
            plan.problems.append("The RPF helper (LeonidaRpf.exe, built on CodeWalker) isn't set up yet: run "
                                 "`leonida tools codewalker` (it fetches CodeWalker from its author's GitHub and "
                                 "builds the helper on this PC).")
        names = {PurePosixPath(m.replace("\\", "/")).name.lower() for m in members}
        if archive.suffix.lower() == ".oiv":
            names.add(archive.name.lower())
        paths = [m.replace("\\", "/").lower() for m in members] + [archive.name.lower()]
        for op in mod.rpf:
            for key in ("put", "texture"):
                if key in op and op[key].lower() not in names:
                    plan.problems.append(f"{op[key]} not found in {archive.name}.")
            if "putdir" in op:
                want = "/" + "/".join(x for x in op["putdir"].replace("\\", "/").lower().split("/") if x) + "/"
                if not any(want in "/" + p for p in paths):
                    plan.problems.append(f"No folder {op['putdir']!r} in {archive.name}.")
            if "oiv" in op:
                pat = op["oiv"].replace("\\", "/").lower()
                if not any(fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, "*/" + pat)
                           or ("/" not in pat and fnmatch.fnmatch(PurePosixPath(p).name, pat)) for p in paths):
                    plan.problems.append(f"No .oiv matching {op['oiv']!r} in {archive.name}.")
                skip = f" (leaving out {', '.join(op['skip'])})" if op.get("skip") else ""
                plan.extra.append(f"  apply .oiv {op['oiv']} to copies in mods\\ (never the game's own archives){skip}")
                continue
            what = next(f"{k} {op[k]}" for k in ("put", "putdir", "texture", "dlclist", "xml", "delete") if k in op)
            plan.extra.append(f"  rpf mods\\{R.win(op['archive'])}: {what}" + (f" -> {op['to']}" if "to" in op else ""))

    def _do_rpf(self, step: L.Step, plan: StepPlan) -> None:
        """Copy/edit game archives in mods\\ with the RPF helper. Every archive is logged before it is touched: ADD
        when this step creates the mods\\ copy (rollback deletes it), RPF_EDIT with entry-level backups when the copy
        already exists (rollback puts back exactly the entries the step changed; see leonida/rpf.py)."""
        from . import rpf as R

        helper = R.find_helper(self.state)
        if helper is None:
            raise InstallError("The RPF helper (LeonidaRpf.exe) isn't set up yet: run `leonida tools codewalker`.")
        with tempfile.TemporaryDirectory(prefix="leonida-") as tmp:
            root = Path(tmp) / "download"
            root.mkdir()
            if plan.archive.suffix.lower() == ".oiv":
                shutil.copy2(plan.archive, root / plan.archive.name)
            else:
                extract(plan.archive, root, self.seven_zip)
            members = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
            try:
                work = R.manifest_work(list(plan.mod.rpf), root, members)
            except R.RpfError as exc:
                raise InstallError(f"{plan.mod.name}: {exc}") from None
            for line in work.describe():
                self.ui.info(line.strip())
            copies = [(root / c.src, c.dest) for c in plan.copies]
            self._check_space(work, [src for src, _dest in copies], plan.mod.name)
            self._place(step, copies)
            ops: list[dict] = []
            actions: list[tuple[L.Action, Path]] = []
            # an archive this step has just placed (a DLC pack's dlc.rpf from the download) is edited in place: no
            # entry backups, its ADD is re-hashed afterwards, so rollback deletes it as usual
            placed = {a.path.lower(): a for a in step.actions if a.op == L.ADD}
            edited = [(aw, R.mods_rel(aw.path)) for aw in work.archives.values()
                      if (self.game / R.mods_rel(aw.path)).is_file() and R.mods_rel(aw.path).lower() not in placed]
            edits = self._backup_entries(step, helper, edited) if edited else []
            for aw in work.archives.values():
                rel = R.mods_rel(aw.path)
                target = self.game / rel
                original = self.game / PurePosixPath(*PureWindowsPath(aw.path).parts)
                if any(e_rel == rel for _aw, e_rel in edited):
                    pass  # entry backups taken above; logged as RPF_EDIT
                elif rel.lower() in placed:
                    actions.append((placed[rel.lower()], target))   # this step's own copy: re-hashed after the edits
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
                        step.notes.append(f"created empty: {rel}")  # the game build has no such archive
                        self.ui.warn(f"The game has no {aw.path}; {plan.mod.name} was made for a newer game build, "
                                     f"so an empty one is made in mods for its files (as OpenIV does). The game only "
                                     f"loads it if that DLC pack exists in your version.")
                    else:
                        raise InstallError(f"{plan.mod.name}: the game has no {aw.path} to copy into mods.")
                    actions.append((action, target))
                ops += [{**op, "rpf": str(target)} for op in aw.ops]
            post = [{"op": "hash", "rpf": str(self.game / a.path), "entries": [r["entry"] for r in m["entries"]]}
                    for a, m in edits]
            if ops:
                self.ui.info(f"Editing {len(work.archives)} archive(s) with the RPF helper ({len(ops)} change(s)) ...")
                try:
                    results = R.run_helper(helper, self.game, ops + post)
                except R.RpfError as exc:
                    raise InstallError(f"{plan.mod.name}: {exc}") from None
                for (action, manifest), res in zip(edits, results[len(ops):], strict=True):
                    for rec in manifest["entries"]:
                        rec["after"] = res["hashes"].get(rec["entry"])
                    self._write_entry_manifest(action, manifest)
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
            for s in plan.mod.steps:  # what only a person can do (an in-game setting): shown, not done
                self.ui.info(f"By hand, after this step: {s}")

    def _backup_entries(self, step: L.Step, helper: list[str], edited: list) -> list[tuple[L.Action, dict]]:
        """Entry-level backups of archives that already have a mods\\ copy: one helper run hashes the entries the
        step writes and exports the existing ones into the step's backup folder; each archive is then logged as
        RPF_EDIT (backup = that folder, with entries.json) before anything is changed."""
        from . import rpf as R

        ops: list[dict] = []
        plans = []
        for aw, rel in edited:
            entries = R.touched_entries(aw.ops)
            folder = PurePosixPath(BACKUPS_DIR, f"step-{step.id}", "rpf-entries", rel).as_posix()
            target = str(self.game / rel)
            ops.append({"op": "hash", "rpf": target, "entries": entries})
            ops += [{"op": "export", "rpf": target, "entry": e, "out": str(self.state / folder / f"{i:05d}.bin")}
                    for i, e in enumerate(entries)]
            plans.append((rel, folder, entries))
        if not ops:
            return []
        self.ui.info(f"Backing up the entries this step changes in {len(edited)} archive copy(ies) ...")
        try:
            results = R.run_helper(helper, self.game, ops)
        except R.RpfError as exc:
            raise InstallError(f"{step.mod}: couldn't back up the archive entries it changes: {exc}") from None
        out, i = [], 0
        for rel, folder, entries in plans:
            hashed, exports = results[i], results[i + 1:i + 1 + len(entries)]
            i += 1 + len(entries)
            recs = []
            for n, (entry, exp) in enumerate(zip(entries, exports, strict=True)):
                recs.append({"entry": entry, "before": hashed["hashes"].get(entry),
                             "backup": f"{n:05d}.bin" if exp.get("exists") else None,
                             "created": (hashed.get("created") or {}).get(entry), "after": None})
            manifest = {"archive": rel, "encryption": hashed.get("encryption"), "entries": recs}
            action = L.Action(L.RPF_EDIT, rel, None, folder)
            self._write_entry_manifest(action, manifest)
            step.actions.append(action)
            out.append((action, manifest))
        self.log.save()
        return out

    def _write_entry_manifest(self, action: L.Action, manifest: dict) -> None:
        from . import rpf as R

        p = self.state / action.backup / R.ENTRY_MANIFEST
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    def _check_space(self, work, copies: list[Path] | None = None, name: str = "This step") -> None:
        """Refuse a step that would fill the drive: the mods\\ archive copies, new data inside archives and entry
        backups (see rpf.space_items), plus the files it copies, counted per drive (game folder / Leonida's state)."""
        from . import rpf as R

        items = R.space_items(self.game, work)
        loose = sum(p.stat().st_size for p in copies or [] if p.is_file())
        if loose:
            items.append(("files it copies into the game folder", loose, "game"))
        drives: dict[Path, list[tuple[str, int]]] = {}
        for what, n, where in items:
            base = self.game if where == "game" else self.state
            drive = Path(base.resolve().anchor or base)
            drives.setdefault(drive, []).append((what, n))
        for drive, parts in drives.items():
            need = sum(n for _w, n in parts)
            free = shutil.disk_usage(drive).free
            if free < need + SPACE_MARGIN:
                detail = "; ".join(f"{w}: {_size(n)}" for w, n in sorted(parts, key=lambda x: -x[1]) if n)
                raise InstallError(f"{name} needs about {_size(need)} on {drive} ({detail}), but only {_size(free)} "
                                   f"is free there (Leonida keeps {_size(SPACE_MARGIN)} spare). Free up space on "
                                   f"{drive} and try again; nothing was changed.")

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
        if not step.actions and not self.ui.confirm(
                f"Leonida saw no change in the game folder for {mod.name}. If you did its steps somewhere Leonida "
                "doesn't watch, count it as installed; if not, do the steps first.\n\nCount it as installed?"):
            step.notes.append("No change seen in the game folder; not counted as installed.")
            raise InstallError(f"{mod.name}: no change seen in the game folder; do its steps, then install it again")

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
        log.info("rollback step %d: %s (%d change(s))%s", step.id, step.mod, len(step.actions),
                 " [dry run]" if self.dry_run else "")
        warnings: list[str] = []
        orphans = self.state / "orphans" / f"step-{step.id}"
        from . import settings as S

        for a in reversed(step.actions):
            target = S.resolve(self.game, a.path.rstrip("/"))   # {documents}/... for GTA's own settings.xml
            if self.dry_run:
                self.ui.info(f"undo {a.op} {a.path}")
                continue
            log.debug("undo %s %s", a.op, a.path)
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
            elif a.op == L.RPF_EDIT:
                warnings += self._undo_rpf_edit(step, a)
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
        for w in warnings:
            log.warning("rollback step %d: %s", step.id, w)
        if not self.dry_run:
            self._remove_created_dirs(step, baseline if "files" in baseline else None)
            step.status = "rolled-back"
            step.notes.append(f"Rolled back at {L.now()}")
            self.log.save()
        return warnings

    def _undo_rpf_edit(self, step: L.Step, a: L.Action) -> list[str]:
        """Put back exactly the archive entries an RPF_EDIT changed, delete the ones it added (and the folders /
        nested archives it created), then check every entry against its hash from before the step."""
        from . import rpf as R

        target = self.game / a.path
        try:
            manifest = json.loads((self.state / a.backup / R.ENTRY_MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return [f"{a.path}: the entry backups are missing; restore it by verifying game files"]
        if not target.is_file():
            return [f"{a.path} is gone; nothing to put back"]
        helper = R.find_helper(self.state)
        if helper is None:
            return [f"{a.path}: the RPF helper isn't installed, so its entries couldn't be put back"]
        recs = manifest["entries"]
        entries = [r["entry"] for r in recs]
        created = sorted({r["created"] for r in recs if r.get("created")}, key=lambda c: (c.count("\\"), c))
        top = [c for c in created if not any(c.lower().startswith(o.lower() + "\\") for o in created if o != c)]
        rpf = str(target)
        ops: list[dict] = [{"op": "hash", "rpf": rpf, "entries": entries}]
        for r in reversed(recs):
            if r.get("created"):
                continue  # inside a folder / nested archive the step created: removed with it below
            if r["before"] is None:
                ops.append({"op": "delete", "rpf": rpf, "entry": r["entry"]})
            else:
                ops.append({"op": "put", "rpf": rpf, "entry": r["entry"], "createArchives": False,
                            "src": str(self.state / a.backup / r["backup"])})
        ops += [{"op": "delete", "rpf": rpf, "entry": c} for c in top]
        ops.append({"op": "hash", "rpf": rpf, "entries": entries})
        try:
            results = R.run_helper(helper, self.game, ops)
        except R.RpfError as exc:
            return [f"{a.path}: couldn't put its entries back: {exc}"]
        now, done = results[0]["hashes"], results[-1]["hashes"]
        warnings = [f"{a.path}: {r['entry']} was changed after the install; the version from before it is back"
                    for r in recs if r.get("after") is not None and now.get(r["entry"]) != r["after"]]
        bad = [r["entry"] for r in recs if done.get(r["entry"]) != r["before"]]
        if bad:
            warnings.append(f"{a.path}: {len(bad)} entr{'y' if len(bad) == 1 else 'ies'} didn't come back as they "
                            f"were: {', '.join(bad[:5])}")
        # the archive's bytes changed (entries moved); the steps that own it now match these bytes
        new_hash = sha256_file(target)
        for other in self.log.active_steps():
            for o in other.actions:
                if other.id != step.id and o.path.lower() == a.path.lower() and o.sha256:  # paths may differ in case
                    o.sha256 = new_hash
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
                        known.add(a.path.replace("\\", "/").rstrip("/").lower())
        candidates: set[PurePosixPath] = set()
        for a in step.actions:
            if a.op not in (L.ADD, L.EXT_ADD, L.MKDIR):
                continue
            # older logs wrote createDirs with backslashes ("mods\\update\\x64"): one name to PurePosixPath
            p = PurePosixPath(a.path.replace("\\", "/").rstrip("/"))
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
        log.info("uninstall: %d active step(s)", len(self.log.active_steps()))
        warnings: list[str] = []
        for step in reversed(self.log.active_steps()):
            warnings += self.rollback(step.id)
        baseline = load_snapshot(self.baseline_path)
        residual = diff(baseline, take_snapshot(self.game)) if baseline else None
        return warnings, residual


def _size(n: int) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{max(n, 0) / 2**20:.0f} MB"
