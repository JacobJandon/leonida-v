"""Shared app state for the CLI and the GUI: config, manifest, log, matches, checks."""

from __future__ import annotations

from pathlib import Path

from .checks import Finding, run_checks
from .detect import check_prerequisites, detect_gpus, exe_version, find_7zip, find_exe
from .installer import UI, Installer
from .log import InstallLog
from .manifest import Manifest, Mod, load_manifest
from .matcher import MatchResult, match_files, scan_folder
from .paths import LOG_NAME, Config, state_dir


class Session:
    def __init__(self, state: str | Path | None = None, manifest_dir: str | Path | None = None,
                 download_dir: str | None = None, game_dir: str | None = None):
        self.state = Path(state) if state else state_dir()
        self.config = Config.load(self.state)
        if download_dir:
            self.config.download_dir = download_dir
        if game_dir:
            self.config.game_dir = game_dir
        self.manifest: Manifest = load_manifest(manifest_dir)
        self.log = InstallLog(self.state / LOG_NAME)
        self._gpus: list[str] | None = None

    # -- selection -----------------------------------------------------------
    @property
    def profile_id(self) -> str:
        return self.config.profile or self.manifest.default_profile

    def mods(self, profile_id: str | None = None) -> list[Mod]:
        return self.manifest.resolve(profile_id or self.profile_id, self.config.add, self.config.remove, self.config.swaps)

    def game_dir(self) -> Path | None:
        return Path(self.config.game_dir) if self.config.game_dir else None

    def game_version(self) -> str | None:
        g = self.game_dir()
        exe = find_exe(g, self.manifest.exe_names) if g else None
        return exe_version(exe) if exe else None

    def gpus(self) -> list[str]:
        if self._gpus is None:
            self._gpus = detect_gpus()
        return self._gpus

    # -- downloads -------------------------------------------------------------
    def matches(self, mods: list[Mod] | None = None) -> MatchResult:
        files = scan_folder(self.config.downloads())
        return match_files(mods if mods is not None else self.mods(), files, self.config.assignments)

    # -- checks / install ----------------------------------------------------------
    def findings(self, mods: list[Mod] | None = None, profile_id: str | None = None) -> list[Finding]:
        mods = mods if mods is not None else self.mods(profile_id)
        return run_checks(
            self.manifest, mods, self.game_dir(),
            game_version=self.game_version(),
            gpu_names=self.gpus(),
            key_overrides=self.config.key_overrides,
            prerequisites=check_prerequisites(),
            profile_requires=self.manifest.profile(profile_id or self.profile_id).requires,
        )

    def installer(self, ui: UI, dry_run: bool = False) -> Installer:
        game = self.game_dir()
        if not game:
            raise RuntimeError("Game folder is not set")
        return Installer(self.manifest, game, self.state, self.log, ui, seven_zip=find_7zip(), dry_run=dry_run)

    def save(self) -> None:
        self.config.save(self.state)
