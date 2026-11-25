"""Update installed mods to the modpack's tested versions, one install step at a time, fully rollback-able.

For each changed mod (install order): make sure the new file is in the download folder and matches the modpack's
SHA-256 (auto mods are downloaded from the author's own source; browser/manual ones are reported), roll back that
mod's install step, install the new file through ``Installer`` (logged like any install), and record it in the
lockfile. Later steps that share files with the updated mod are rolled back first and reinstalled afterwards, so
``uninstall`` still returns the game folder to the baseline snapshot.

Everything is held when the new versions don't support the game build (``Mod.for_build``).
"""

from __future__ import annotations

import glob
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from . import downloader
from .downloader import DownloadError
from .installer import Installer
from .log import Step
from .manifest import Mod
from .matcher import build_lock, read_lock, sha256_file, write_lock
from .modpack import ADDED, REMOVED, SAME, UPDATED, Change, diff, entry_problem, section_for, verify_file
from .paths import LOCK_NAME

SKIP_FILE = "skipped-updates.json"

# ModUpdate.action
READY = "update"            # verified file is in the download folder: will be installed
DOWNLOAD = "download"       # will be downloaded from the author's own source, verified, then installed
GET_MANUALLY = "get"        # the user has to download it (browser/manual source); then run update again
REFUSED = "refused"         # file mismatch or a modpack entry that may not be used
SKIPPED = "skipped"         # the user chose to skip this version
NEW = "new"                 # in the modpack but not installed: install it with `leonida install`
GONE = "removed"            # installed but no longer in the modpack: left alone
CURRENT = "same"            # already the tested file


class ModUpdateError(DownloadError):
    """Updates are held or a mod update failed (the game folder was put back as it was)."""


@dataclass
class ModUpdate:
    mod_id: str
    name: str
    change: Change
    action: str
    message: str = ""
    mod: Mod | None = None       # resolved for the game build
    path: Path | None = None     # the verified new file (READY)

    @property
    def pending(self) -> bool:
        return self.action in (READY, DOWNLOAD)


@dataclass
class UpdatePlan:
    build: str | None
    modpack_build: str | None
    items: list[ModUpdate] = field(default_factory=list)
    held: str | None = None      # why nothing may be updated right now

    @property
    def pending(self) -> list[ModUpdate]:
        return [] if self.held else [i for i in self.items if i.pending]

    def summary(self) -> list[str]:
        lines = []
        if self.held:
            lines.append(f"HELD: {self.held}")
        for i in self.items:
            if i.action == CURRENT:
                continue
            ver = f" -> {i.change.new_version}" if i.change.new_version else ""
            lines.append(f"[{i.action}] {i.name}{ver}" + (f": {i.message}" if i.message else ""))
        return lines or ["Every installed mod is the modpack's tested version."]


# ------------------------------------------------------------------------------------------- skipped versions
def load_skips(state: Path) -> dict[str, str]:
    p = Path(state) / SKIP_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def skip_version(state: Path, mod_id: str, version: str | None) -> None:
    """Remember not to offer ``version`` of ``mod_id`` again (None = forget the skip)."""
    skips = load_skips(state)
    if version:
        skips[mod_id] = version
    else:
        skips.pop(mod_id, None)
    p = Path(state) / SKIP_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(skips, indent=2), encoding="utf-8")


# ------------------------------------------------------------------------------------------------------ plan
def installed_state(session) -> dict:
    """Lockfile-shaped record of what's installed: the lockfile entry, else the hash of the matched download."""
    installed = session.log.installed_mods()
    lock = read_lock(session.state / LOCK_NAME) or {}
    by_mod = {e["mod"]: e for e in lock.get("entries", []) if e.get("mod") in installed}
    missing = [m for m in session.mods() if m.id in installed and m.id not in by_mod]
    if missing:
        matched = session.matches(missing).matched
        for m in missing:
            p = matched.get(m.id)
            by_mod[m.id] = {"mod": m.id, "file": p.name if p else None,
                            "sha256": sha256_file(p) if p else None, "size": p.stat().st_size if p else None}
    for mid in installed - set(by_mod):  # installed but no longer selected/known
        by_mod[mid] = {"mod": mid, "file": None, "sha256": None, "size": None}
    return {"entries": list(by_mod.values())}


def plan_updates(session, modpack: dict, only: str | None = None) -> UpdatePlan:
    """What updating to ``modpack`` would do for the installed mods on the detected game build."""
    build = session.game_version()
    if build is None:
        return UpdatePlan(None, None, held="Can't read the game build, so the right mod versions can't be picked. "
                                           "Set the game folder (`leonida detect`) or pass --game-build.")
    pack_build, _section = section_for(modpack, build)
    if pack_build is None:
        have = ", ".join(modpack.get("builds", {})) or "none"
        return UpdatePlan(build, None, held=f"The modpack has no tested set for game build {build} (it has: {have}).")
    plan = UpdatePlan(build, pack_build)
    installed = session.log.installed_mods()
    skips = load_skips(session.state)
    manifest = session.manifest
    base = session.base_manifest
    downloads = session.config.downloads()
    changes = diff(installed_state(session), modpack, build)
    order = {m.id: m.order for m in base.mods.values()}
    for ch in sorted(changes, key=lambda c: (order.get(c.mod, 10**6), c.mod)):
        if only and ch.mod != only:
            continue
        mod = manifest.mods.get(ch.mod)
        item = ModUpdate(ch.mod, mod.name if mod else ch.mod, ch, CURRENT, mod=mod)
        plan.items.append(item)
        if ch.kind == SAME:
            continue
        if ch.kind == REMOVED:
            item.action, item.message = GONE, "no longer in the modpack; left installed"
            continue
        if ch.mod not in installed:
            item.action, item.message = NEW, "not installed (add it to your selection and run `leonida install`)"
            continue
        entry = ch.new
        problem = entry_problem(ch.mod, entry, base, build)
        if problem:
            item.action, item.message = REFUSED, problem
            continue
        if skips.get(ch.mod) == entry["version"]:
            item.action, item.message = SKIPPED, f"version {entry['version']} skipped (by you)"
            continue
        if mod.unsupported:
            plan.held = (f"{mod.name} {entry['version']} doesn't support game build {build}: {mod.unsupported} "
                         "Nothing is updated until every new version supports your game.")
        elif pack_build != build and base.mod(ch.mod).for_build(pack_build).variant != mod.variant:
            plan.held = (f"The modpack's {mod.name} was tested on game build {pack_build}, but build {build} needs "
                         "a different version of it. Nothing is updated until there's a tested set for your build.")
        if entry["version"] != mod.version:
            item.action = REFUSED
            item.message = (f"the modpack has version {entry['version']} but this Leonida knows {mod.version or '?'}"
                            "; update Leonida V first (`leonida self-update`)")
            continue
        path = downloads / entry["file"]
        if path.exists():
            bad = verify_file(path, entry)
            if bad:
                item.action, item.message = REFUSED, bad
            else:
                item.action, item.path = READY, path
        elif downloader.plan_for(mod).mode == "auto":
            item.action, item.message = DOWNLOAD, "from the author's release"
        else:
            item.action = GET_MANUALLY
            item.message = f"download {entry['file']} from {mod.page} into {downloads}, then run the update again"
    return plan


# ------------------------------------------------------------------------------------------------------- run
class _LogView:
    """The install log with some steps hidden from ``active_steps`` (lets Installer roll back one step that shares
    no files with the later ones)."""

    def __init__(self, log, hidden: set[int]):
        self._log, self._hidden = log, hidden

    def active_steps(self) -> list[Step]:
        return [s for s in self._log.active_steps() if s.id not in self._hidden]

    def __getattr__(self, name):
        return getattr(self._log, name)


@contextmanager
def _hiding(installer: Installer, hidden: set[int]) -> Iterator[None]:
    real = installer.log
    installer.log = _LogView(real, hidden)
    try:
        yield
    finally:
        installer.log = real


def _paths(step: Step) -> set[str]:
    """What a step owns, for "do later steps depend on it": its files and the folders it added from outside.
    A folder it only created (MKDIR) doesn't count: rolling that back removes it only when it's empty."""
    return {a.path.rstrip("/").lower() for a in step.actions if a.op != "mkdir"}


def _overlaps(a: set[str], b: set[str]) -> bool:
    return any(x == y or x.startswith(y + "/") or y.startswith(x + "/") for x in a for y in b)


def dependents(log, step: Step) -> list[Step]:
    """Later active steps that share files/folders with ``step`` (directly or through each other)."""
    touched = _paths(step)
    out = []
    for s in sorted(log.active_steps(), key=lambda s: s.id):
        if s.id > step.id and _overlaps(_paths(s), touched):
            out.append(s)
            touched |= _paths(s)
    return out


def _rollback_one(installer: Installer, step: Step) -> list[str]:
    later = {s.id for s in installer.log.active_steps() if s.id > step.id}
    with _hiding(installer, later):
        return installer.rollback(step.id)


def _record_lock(session, mod_id: str, path: Path) -> None:
    lock_path = session.state / LOCK_NAME
    lock = read_lock(lock_path) or build_lock(session.manifest.pack, session.manifest.version, {})
    entries = [e for e in lock.get("entries", []) if e.get("mod") != mod_id]
    entries.append({"mod": mod_id, "file": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)})
    lock["entries"] = sorted(entries, key=lambda e: e["mod"])
    write_lock(lock_path, lock)


def replace_mod(session, installer: Installer, mod: Mod, new_file: Path, old_file: Path | None = None) -> list[str]:
    """Swap the installed ``mod`` for ``new_file``: roll back its step (and later steps sharing its files),
    install the new file, reinstall those later steps. On failure everything is put back and ModUpdateError
    raised. Returns warnings."""
    log = session.log
    steps = [s for s in log.active_steps() if s.mod == mod.id and s.status == "done"]
    if not steps:
        raise ModUpdateError(f"{mod.name} isn't installed")
    step = steps[-1]
    deps = dependents(log, step)
    matched = session.matches([session.manifest.mods[d.mod] for d in deps if d.mod in session.manifest.mods]).matched
    reinstall = []
    for d in deps:
        if d.mod.startswith("settings:"):  # re-applied by the new install itself
            continue
        m = session.manifest.mods.get(d.mod)
        if m is None or d.mod not in matched:
            raise ModUpdateError(f"Can't update {mod.name}: {d.mod} was installed later and shares files with it, "
                                 "so it has to be reinstalled, but its download isn't in the download folder.")
        reinstall.append((m, matched[d.mod]))
    warnings: list[str] = []
    first_new_id = max((s.id for s in log.steps), default=0) + 1
    undone: list[str] = []
    try:
        for d in reversed(deps):
            warnings += _rollback_one(installer, d)
            undone.append(d.mod)
        warnings += _rollback_one(installer, step)
    except Exception as exc:  # put back what was already taken out, then stop
        again = [(m, p) for m, p in reinstall if m.id in undone]
        note = _restore(installer, log, first_new_id, None, again, warnings)
        raise ModUpdateError(f"Couldn't roll back {mod.name} to update it: {exc}.{note}") from None
    try:
        installer.install(mod, new_file)
        for m, p in reinstall:
            installer.install(m, p)
    except Exception as exc:  # any failure (bad archive, cancelled step, disk...): back to the previous version
        note = _restore(installer, log, first_new_id, (mod, old_file), reinstall, warnings)
        raise ModUpdateError(f"Updating {mod.name} failed: {exc}.{note}") from None
    if deps:
        warnings.append(f"Reinstalled after {mod.name} (they share files): " + ", ".join(m.name for m, _ in reinstall))
    return warnings


def _restore(installer: Installer, log, first_new_id: int, previous: tuple[Mod, Path | None] | None,
             reinstall: list[tuple[Mod, Path]], warnings: list[str]) -> str:
    """Undo every step made since ``first_new_id`` (newest first), then reinstall the previous version and the
    later mods that were taken out. Returns a sentence for the error message; never raises."""
    problems: list[str] = []

    def undo_new() -> None:
        for s in sorted((s for s in log.active_steps() if s.id >= first_new_id), key=lambda s: s.id, reverse=True):
            try:
                warnings.extend(installer.rollback(s.id))
            except Exception as exc:
                problems.append(f"rolling back step {s.id} ({exc})")
                return

    def put_back(m: Mod, path: Path, what: str) -> bool:
        before = max((s.id for s in log.steps), default=0)
        try:
            installer.install(m, path)
            return True
        except Exception as exc:
            problems.append(f"reinstalling {what} ({exc})")
            for s in [s for s in log.active_steps() if s.id > before]:  # the half-done attempt
                try:
                    warnings.extend(installer.rollback(s.id))
                except Exception as exc2:
                    problems.append(f"rolling back step {s.id} ({exc2})")
            return False

    undo_new()
    note = ""
    if previous is not None:
        mod, old_file = previous
        note = f" {mod.name} is now uninstalled; install it again with `leonida install`."
        if old_file and old_file.is_file() and not problems and put_back(mod, old_file, old_file.name):
            note = f" The previous version ({old_file.name}) was reinstalled."
    for m, p in reinstall:
        if problems or not put_back(m, p, m.name):
            break
    if problems:
        note += " Restoring didn't finish: " + "; ".join(problems) + ". Run `leonida status` and `leonida install`."
    return note


def run_updates(session, plan: UpdatePlan, ui, progress: Callable[[int, int | None], None] | None = None,
                cancel: Callable[[], bool] | None = None) -> list[str]:
    """Apply the plan's pending updates in install order. Returns a report (one line per mod).
    Raises ModUpdateError when the plan is held."""
    if plan.held:
        raise ModUpdateError(plan.held)
    installer = session.installer(ui)
    downloads = session.config.downloads()
    report: list[str] = []
    for item in plan.pending:
        mod, entry = item.mod, item.change.new
        path = item.path
        if item.action == DOWNLOAD:
            dl = downloader.plan_for(mod)
            if dl.source and dl.source.get("type") == "github":  # fetch exactly the tested asset
                dl.source = dict(dl.source, asset=glob.escape(entry["file"]))
            dl.filename = entry["file"]
            try:
                path = downloader.download(dl, downloads, progress=progress, cancel=cancel)
            except (DownloadError, OSError) as exc:
                report.append(f"{item.name}: not updated, download failed ({exc}). Get {entry['file']} from "
                              f"{mod.page} into {downloads} and run the update again.")
                continue
            try:
                bad = verify_file(path, entry)
            except OSError as exc:
                bad = f"couldn't read {path.name} ({exc})"
            if bad:
                report.append(f"{item.name}: not updated. {bad}")
                continue
        old = item.change.old_file
        old_path = downloads / old if old else None
        try:
            warnings = replace_mod(session, installer, mod, path, old_path)
        except ModUpdateError as exc:
            report.append(f"{item.name}: {exc}")
            continue
        report.append(f"{item.name}: updated to {entry['version']} ({path.name}). Test the game before playing on.")
        try:  # the mod IS updated; these only keep the records current
            _record_lock(session, mod.id, path)
            if path.name not in session.config.assignments:
                session.config.assignments[path.name] = mod.id  # so matching picks the new file even if renamed
                session.save()
        except (OSError, ValueError) as exc:
            warnings.append(f"couldn't update the lockfile/settings ({exc}); `leonida update --check` may offer "
                            "this update again")
        report += [f"  ! {w}" for w in warnings]
    return report


__all__ = [
    "ADDED", "CURRENT", "DOWNLOAD", "GET_MANUALLY", "GONE", "NEW", "READY", "REFUSED", "REMOVED", "SAME", "SKIPPED",
    "UPDATED", "ModUpdate", "ModUpdateError", "UpdatePlan", "dependents", "installed_state", "load_skips",
    "plan_updates", "replace_mod", "run_updates", "skip_version",
]
