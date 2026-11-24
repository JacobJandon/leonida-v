"""Shared app state for the CLI and the GUI: config, manifest, log, matches, checks."""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import manifest as _manifest_mod
from .checks import INFO, Finding, run_checks
from .detect import check_prerequisites, detect_gpus, exe_version, find_7zip, find_exe
from .installer import UI, Installer
from .log import InstallLog
from .manifest import Manifest, ManifestError, Mod, load_manifest
from .matcher import MatchResult, match_files, scan_folder
from .members import ListingCache, apply_rules
from .paths import LOG_NAME, Config, state_dir

PAID_STATE = "paid-status.json"


class Session:
    """``manifest`` is resolved automatically for the game build (``Manifest.for_build``) and then for the user's
    selection (``Manifest.for_selection``: whenSelected/whenMissing values), so every mod list, match, check,
    install and modpack sees the final values. ``base_manifest`` is mods.json as written. ``game_build`` overrides
    detection (CLI ``--game-build``, for testing other builds)."""

    def __init__(self, state: str | Path | None = None, manifest_dir: str | Path | None = None,
                 download_dir: str | None = None, game_dir: str | None = None, game_build: str | None = None):
        self.state = Path(state) if state else state_dir()
        self.config = Config.load(self.state)
        if download_dir:
            self.config.download_dir = download_dir
        if game_dir:
            self.config.game_dir = game_dir
        self.base_manifest: Manifest = load_manifest(manifest_dir)
        self.game_build_override = game_build
        self.log = InstallLog(self.state / LOG_NAME)
        self._gpus: list[str] | None = None
        self._listings: ListingCache | None = None
        self._version_cache: tuple[tuple, str | None] | None = None
        self._resolved: tuple[tuple, Manifest] | None = None

    # -- manifest for this game build -----------------------------------------------
    @property
    def manifest(self) -> Manifest:
        build = self.game_version()
        try:
            sel = self.selection_ids()
        except ManifestError:  # a bad saved selection: mods() reports it; the manifest still works
            sel = None
        key = (build, sel)
        key = (*key, _manifest_mod._today())  # a publicSince date can pass while the app is open
        if self._resolved is None or self._resolved[0] != key:
            m = self.base_manifest.for_build(build)
            self._resolved = (key, m.for_selection(sel) if sel is not None else m)
        return self._resolved[1]

    @manifest.setter
    def manifest(self, value: Manifest) -> None:
        self.base_manifest = value
        self._resolved = None

    # -- selection -----------------------------------------------------------
    @property
    def profile_id(self) -> str:
        return self.config.profile or self.base_manifest.default_profile

    def selection_ids(self, profile_id: str | None = None) -> frozenset[str]:
        """Selected mod ids (profile + additions/removals/swaps), before any whenSelected/whenMissing skips."""
        mods = self.base_manifest.resolve(profile_id or self.profile_id, self.config.add, self.config.remove,
                                          self.config.swaps)
        return frozenset(m.id for m in mods)

    def mods(self, profile_id: str | None = None) -> list[Mod]:
        """The mods to download/check/install, in order: resolved for the game build and the selection, without
        the ones the selection makes unnecessary (``Mod.not_needed``)."""
        pid = profile_id or self.profile_id
        if pid == self.profile_id:
            manifest = self.manifest
        else:
            manifest = self.base_manifest.for_build(self.game_version()).for_selection(self.selection_ids(pid))
        chosen = manifest.resolve(pid, self.config.add, self.config.remove, self.config.swaps)
        return [m for m in chosen if not m.not_needed]

    def not_needed(self, profile_id: str | None = None) -> list[Mod]:
        """Selected mods the selection makes unnecessary (shown with their reason, not installed)."""
        pid = profile_id or self.profile_id
        manifest = self.manifest if pid == self.profile_id else \
            self.base_manifest.for_build(self.game_version()).for_selection(self.selection_ids(pid))
        return [m for m in manifest.resolve(pid, self.config.add, self.config.remove, self.config.swaps) if m.not_needed]

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
        return apply_rules(match_files(mods, files, self.config.assignments), mods, self.listing_cache())

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
        )
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
        return Installer(self.manifest, game, self.state, self.log, ui, seven_zip=find_7zip(), dry_run=dry_run)

    def save(self) -> None:
        self.config.save(self.state)
