"""Shared app state for the CLI and the GUI: config, manifest, log, matches, checks."""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import custommods
from . import manifest as _manifest_mod
from . import settings as settings_mod
from .checks import INFO, WARNING, Finding, run_checks
from .detect import check_prerequisites, detect_gpus, edition_of, exe_version, find_7zip, find_exe
from .installer import UI, Installer
from .log import InstallLog
from .manifest import Manifest, ManifestError, Mod, load_manifest
from .matcher import MatchResult, match_files, scan_folder
from .members import ListingCache, apply_rules
from .packs import PackChoice, load_choice, save_choice
from .paths import LOG_NAME, Config, state_dir

PAID_STATE = "paid-status.json"


class Session:
    """``manifest`` is resolved automatically for the game build (``Manifest.for_build``) and then for the user's
    selection (``Manifest.for_selection``: whenSelected/whenMissing values), so every mod list, match, check,
    install and modpack sees the final values. ``base_manifest`` is the manifest set as written, for the game's edition:
    GTA5_Enhanced.exe -> mods.json, GTA5.exe -> mods-legacy.json (``edition`` overrides, CLI ``--edition``).
    ``game_build`` overrides build detection (CLI ``--game-build``, for testing other builds)."""

    def __init__(self, state: str | Path | None = None, manifest_dir: str | Path | None = None,
                 download_dir: str | None = None, game_dir: str | None = None, game_build: str | None = None,
                 edition: str | None = None):
        self.state = Path(state) if state else state_dir()
        self.config = Config.load(self.state)
        if download_dir:
            self.config.download_dir = download_dir
        if game_dir:
            self.config.game_dir = game_dir
        self.manifest_dir = manifest_dir
        if edition is not None:
            _manifest_mod.manifest_files(edition)  # validates the name
        self.edition_override = edition
        self._manifests: dict[str, Manifest] = {}
        self._edition_cache: tuple[str | None, str | None] | None = None
        self._custom_cache: tuple[tuple, Manifest] | None = None
        self._choice_cache: tuple[tuple, PackChoice | None] | None = None
        self.game_build_override = game_build
        self.log = InstallLog(self.state / LOG_NAME)
        self._gpus: list[str] | None = None
        self._listings: ListingCache | None = None
        self._version_cache: tuple[tuple, str | None] | None = None
        self._resolved: tuple[tuple, Manifest] | None = None

    # -- edition ---------------------------------------------------------------
    @property
    def game_edition(self) -> str | None:
        """The edition of the game in the game folder (from its exe), None without a game."""
        g = self.game_dir()
        key = str(g) if g else None
        if self._edition_cache is None or self._edition_cache[0] != key:
            self._edition_cache = (key, edition_of(g))
        return self._edition_cache[1]

    @property
    def edition(self) -> str:
        """The edition whose mod list is used: the override, else the game folder's, else Enhanced."""
        return self.edition_override or self.game_edition or "enhanced"

    def manifest_for(self, edition: str) -> Manifest:
        """The manifest set of ``edition`` as written (loaded once)."""
        if edition not in self._manifests:
            self._manifests[edition] = load_manifest(self.manifest_dir, edition)
        return self._manifests[edition]

    @property
    def base_manifest(self) -> Manifest:
        """The edition's manifest set as written, plus the user's own mods (custom-mods.json)."""
        raw = self.manifest_for(self.edition)
        p = custommods.path_of(self.state)
        stamp = (id(raw), p.stat().st_mtime_ns if p.is_file() else None)
        if self._custom_cache is None or self._custom_cache[0] != stamp:
            self._custom_cache = (stamp, custommods.merge(raw, custommods.load_entries(self.state)))
        return self._custom_cache[1]

    def custom_entries(self) -> list[dict]:
        return custommods.load_entries(self.state)

    @base_manifest.setter
    def base_manifest(self, value: Manifest) -> None:
        self._manifests[value.edition] = value
        self._resolved = None

    def edition_mismatch(self) -> str | None:
        """Why the mod list and the game folder don't go together (None when they do)."""
        game = self.game_edition
        if game and game != self.edition:
            names = {"enhanced": "GTA V Enhanced (GTA5_Enhanced.exe)", "legacy": "GTA V Legacy (GTA5.exe)"}
            return (f"The game folder holds {names[game]}, but the mod list in use is for {names[self.edition]}. "
                    "Their mods don't mix: drop --edition, or pick the other game folder.")
        return None

    # -- manifest for this game build -----------------------------------------------
    @property
    def manifest(self) -> Manifest:
        build = self.game_version()
        try:
            sel = self.selection_ids()
        except ManifestError:  # a bad saved selection: mods() reports it; the manifest still works
            sel = None
        key = (self.edition, build, sel, _manifest_mod._today())  # a publicSince date can pass while open
        if self._resolved is None or self._resolved[0] != key:
            m = self.base_manifest.for_build(build)
            self._resolved = (key, m.for_selection(sel) if sel is not None else m)
        return self._resolved[1]

    @manifest.setter
    def manifest(self, value: Manifest) -> None:
        self.base_manifest = value
        self._resolved = None

    # -- selection -----------------------------------------------------------
    # -- modpack --------------------------------------------------------------
    def pack_choice(self) -> PackChoice:
        """The chosen pack, add-ons and variant for this edition (pack.json; else the old profile choice carries
        over: the pack with that id, else the default pack)."""
        base = self.base_manifest
        f = self.state / "pack.json"
        key = (self.edition, f.stat().st_mtime_ns if f.is_file() else None)
        if self._choice_cache is None or self._choice_cache[0] != key:
            self._choice_cache = (key, load_choice(self.state, self.edition))
        choice = self._choice_cache[1]
        if choice is not None and choice.pack in base.packs:
            return choice
        old = self.config.profile
        return PackChoice(old if old in base.packs else (base.default_pack or base.default_profile))

    def choose_pack(self, pack_id: str, addons=None, variant: str | None = None) -> PackChoice:
        """Save a pack choice (``addons`` None = the pack's defaults). Raises ManifestError for unknown ids."""
        base = self.base_manifest
        pack = base.get_pack(pack_id)
        if addons is not None:
            allowed = {a.id for lst in base.addons_for(pack_id).values() for a in lst}
            bad = [a for a in addons if a not in allowed]
            if bad:
                raise ManifestError(f"Not an add-on of {pack.name}: {', '.join(bad)}")
        if variant is not None and pack.variant(variant) is None:
            raise ManifestError(f"{pack.name} has no variant {variant!r}")
        choice = PackChoice(pack_id, tuple(addons) if addons is not None else None, variant)
        save_choice(self.state, self.edition, choice)
        self._choice_cache = None
        self.config.profile = pack_id  # older code paths read the profile
        self.save()
        self._resolved = None
        return choice

    def chosen_addons(self) -> tuple[str, ...]:
        c = self.pack_choice()
        base = self.base_manifest
        return c.addons if c.addons is not None else (base.packs[c.pack].default_addons if c.pack in base.packs else ())

    @property
    def profile_id(self) -> str:
        """The chosen pack (packs include the old profiles); for a plain profile choice, that profile."""
        base = self.base_manifest
        c = self.pack_choice()
        if c.pack in base.profiles:
            return c.pack
        return self.config.profile if self.config.profile in base.profiles else base.default_profile

    def _choice(self) -> tuple[list[str], list[str], dict[str, str]]:
        """The saved additions/removals/swaps that exist in this edition's mod list (a config used with the other
        edition's game folder may name mods this list doesn't have)."""
        known = self.base_manifest.mods
        add = [i for i in self.config.add if i in known]
        add += [i for i in custommods.enabled_ids(self.custom_entries()) if i in known and i not in add]
        remove = [i for i in self.config.remove if i in known]
        swaps = {a: b for a, b in self.config.swaps.items() if a in known and b in known}
        return add, remove, swaps

    def _resolve(self, manifest: Manifest, pid: str) -> list[Mod]:
        """A pack with the user's add-ons/variant if it's the chosen one (else its defaults), or a profile."""
        if pid == self.profile_id and pid in manifest.packs:
            c = self.pack_choice()
            return manifest.resolve_pack(pid, self.chosen_addons(), c.variant, *self._choice())
        return manifest.resolve_pack(pid, None, None, *self._choice())

    def selection_ids(self, profile_id: str | None = None) -> frozenset[str]:
        """Selected mod ids (pack + add-ons + additions/removals/swaps + your own mods), before any skips."""
        mods = self._resolve(self.base_manifest, profile_id or self.profile_id)
        return frozenset(m.id for m in mods)

    def mods(self, profile_id: str | None = None) -> list[Mod]:
        """The mods to download/check/install, in order: resolved for the game build and the selection, without
        the ones the selection makes unnecessary (``Mod.not_needed``)."""
        pid = profile_id or self.profile_id
        if pid == self.profile_id:
            manifest = self.manifest
        else:
            manifest = self.base_manifest.for_build(self.game_version()).for_selection(self.selection_ids(pid))
        chosen = self._resolve(manifest, pid)
        return [m for m in chosen if not m.not_needed]

    def not_needed(self, profile_id: str | None = None) -> list[Mod]:
        """Selected mods the selection makes unnecessary (shown with their reason, not installed)."""
        pid = profile_id or self.profile_id
        manifest = self.manifest if pid == self.profile_id else \
            self.base_manifest.for_build(self.game_version()).for_selection(self.selection_ids(pid))
        return [m for m in self._resolve(manifest, pid) if m.not_needed]

    def game_dir(self) -> Path | None:
        return Path(self.config.game_dir) if self.config.game_dir else None

    def game_version(self) -> str | None:
        """The game build: the override, else the exe's file version (cached per game folder)."""
        if self.game_build_override:
            return self.game_build_override
        g = self.game_dir()
        key = (str(g) if g else None, os.environ.get("LEONIDA_FAKE_GAME_VERSION"))
        if self._version_cache is None or self._version_cache[0] != key:
            exe = find_exe(g, self.base_manifest.exe_names) if g else None
            self._version_cache = (key, exe_version(exe) if exe else None)
        return self._version_cache[1]

    def refresh_game_version(self) -> str | None:
        """Re-read the exe (e.g. after the game was updated while the app is open)."""
        self._version_cache = None
        return self.game_version()

    def gpus(self) -> list[str]:
        if self._gpus is None:
            self._gpus = detect_gpus()
        return self._gpus

    # -- downloads -------------------------------------------------------------
    def listing_cache(self) -> ListingCache:
        """Archive listings for the requireMembers/rejectMembers checks, cached in the state folder."""
        if self._listings is None:
            self._listings = ListingCache(self.state, find_7zip())
        return self._listings

    def matches(self, mods: list[Mod] | None = None) -> MatchResult:
        """Downloads matched to mods by name, then checked inside against requireMembers/rejectMembers
        (files of the wrong edition are in ``result.wrong`` with the reason, never in ``matched``)."""
        mods = mods if mods is not None else self.mods()
        files = scan_folder(self.config.downloads())
        result = self._match_names(mods, files)
        entries = self.custom_entries()
        for m in mods:  # your own mods with a file on disk: that file, wherever it is
            if m.tier == "custom":
                f = custommods.file_of(entries, m.id)
                if f is not None:
                    result.matched[m.id] = f
        return apply_rules(result, mods, self.listing_cache())

    def _match_names(self, mods: list[Mod], files: list[Path]) -> MatchResult:
        """Match names against every known mod, then keep the selected ones: a file that belongs to a mod outside
        the selection (a better-fitting name, or the user's assignment) goes to ``others``, not to the closest
        selected mod (where its contents would then be "the wrong edition")."""
        selected = {m.id for m in mods}
        known = list(mods) + [m for m in self.manifest.mods.values() if m.id not in selected]
        full = match_files(known, files, self.config.assignments)
        out = MatchResult(unmatched=list(full.unmatched))
        for mid, path in full.matched.items():
            if mid in selected:
                out.matched[mid] = path
                if mid in full.duplicates:
                    out.duplicates[mid] = list(full.duplicates[mid])
            else:
                for p in [path, *full.duplicates.get(mid, [])]:
                    out.others[p] = mid
        for path, ids in full.ambiguous.items():
            mine = [i for i in ids if i in selected]
            if len(mine) == 1:  # only one of the equally good fits is selected: it's that one's file
                if mine[0] in out.matched:
                    out.duplicates.setdefault(mine[0], []).append(path)
                else:
                    out.matched[mine[0]] = path
            elif mine:
                out.ambiguous[path] = mine
            else:
                out.others[path] = ids[0]
        return out

    # -- checks / install ----------------------------------------------------------
    def findings(self, mods: list[Mod] | None = None, profile_id: str | None = None) -> list[Finding]:
        mods = mods if mods is not None else self.mods(profile_id)
        found = run_checks(
            self.manifest, mods, self.game_dir(),
            game_version=self.game_version(),
            gpu_names=self.gpus(),
            key_overrides=self.config.key_overrides,
            prerequisites=check_prerequisites(),
            profile_requires=self.manifest.profile(profile_id or self.profile_id).requires,
            installed_paths={a.path.rstrip("/").lower() for st in self.log.active_steps() for a in st.actions},
            game_edition=self.game_edition,
        )
        for d in self.settings_drift():
            found.append(Finding(WARNING, "setting-drift", d.message(), d.wanted.mod))
        for m in self.turned_free():
            found.append(Finding(INFO, "now-free", f"{m.name} is free now: the author's public release came out on "
                                 f"{m.free_since}, and Leonida uses it from now on ({m.page}).", m.id))
        return found

    def turned_free(self, record: bool = True) -> list[Mod]:
        """Paid mods whose public release came out since the last time this was asked (their publicSince date
        passed). The answer is remembered in <state>/paid-status.json when ``record``; the first run only records."""
        path = self.state / PAID_STATE
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            previous = previous if isinstance(previous, dict) else {}
        except (OSError, ValueError):
            previous = None
        paid = [m for m in self.manifest.mods.values() if m.tier == "paid"]
        now = {m.id: ("free" if m.free_since else "paid") for m in paid}
        newly = [] if previous is None else [m for m in paid if now[m.id] == "free" and previous.get(m.id) == "paid"]
        if record and now != previous:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(now, indent=1), encoding="utf-8")
            except OSError:
                pass  # only a convenience: the next run says it again
        return newly

    def installer(self, ui: UI, dry_run: bool = False) -> Installer:
        game = self.game_dir()
        if not game:
            raise RuntimeError("Game folder is not set")
        return Installer(self.manifest, game, self.state, self.log, ui, seven_zip=find_7zip(), dry_run=dry_run,
                         settings_for=self.settings_for)

    # -- locked settings (settings.py) -------------------------------------------------
    def settings_for(self, mod: Mod) -> list[settings_mod.Wanted]:
        """The locked values of ``mod`` for the chosen pack, variant and selection (unlocked keys left out)."""
        base = self.base_manifest
        pid = self.profile_id
        pack = base.packs.get(pid)
        variant = pack.variant(self.pack_choice().variant) if pack else None
        current = self.manifest.mods.get(mod.id, mod)
        return settings_mod.wanted_for(current, pid, variant, set(self.selection_ids()),
                                       settings_mod.unlocked(self.state))

    def installed_settings(self) -> list[settings_mod.Wanted]:
        """Locked values of every installed mod."""
        installed = self.log.installed_mods()
        return [w for m in self.manifest.mods.values() if m.id in installed for w in self.settings_for(m)]

    def settings_drift(self) -> list[settings_mod.Drift]:
        game = self.game_dir()
        return settings_mod.drift(game, self.installed_settings()) if game else []

    def apply_settings(self, ui: UI, dry_run: bool = False) -> list[str]:
        """Write the locked values of every installed mod again (variant switch, drift); logged, no reinstall."""
        inst = self.installer(ui, dry_run=dry_run)
        installed = self.log.installed_mods()
        report = []
        for m in self.manifest.mods.values():
            if m.id in installed:
                step = inst.apply_settings(m, self.settings_for(m))
                if step is not None:
                    report.append(f"{m.name}: {', '.join(a.path for a in step.actions)}")
        return report

    def save(self) -> None:
        self.config.save(self.state)
