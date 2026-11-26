"""Where Leonida V keeps its own state, and the user's saved settings."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_NAME = "config.json"
LOG_NAME = "install-log.json"
BASELINE_NAME = "baseline-snapshot.json"
LOCK_NAME = "leonida.lock"
BACKUPS_DIR = "backups"
EXTRACT_DIR = "extracted"


def state_dir() -> Path:
    """%LOCALAPPDATA%\\LeonidaV on Windows, ~/.local/share/leonida-v elsewhere (override: LEONIDA_STATE_DIR)."""
    override = os.environ.get("LEONIDA_STATE_DIR")
    if override:
        return Path(override)
    home = home_state_dir()
    from .relocate import pointed_state  # Settings > Move… leaves a pointer in the usual place

    return pointed_state(home) or home


def state_origin() -> str:
    """Why ``state_dir()`` is where it is (Leonida's log says it at every start)."""
    if os.environ.get("LEONIDA_STATE_DIR"):
        return "LEONIDA_STATE_DIR"
    home = home_state_dir()
    from .relocate import pointed_state

    if pointed_state(home):
        return f"moved there (pointer in {home})"
    if _installed_data_dir():
        return "the data folder of the installed Leonida V"
    return "the default folder" + (" (frozen exe, not the installed one)" if getattr(sys, "frozen", False) else "")


def _installed_data_dir() -> Path | None:
    """The data folder picked in setup, when this is the installed exe (leonida/winsetup.py), else None."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    try:
        from .winsetup import data_dir_for_running_exe

        return data_dir_for_running_exe()
    except Exception:  # noqa: BLE001 - a broken registry entry must never stop Leonida from starting
        import logging

        logging.getLogger("leonida").exception("couldn't read the installed copy's data folder")
        return None


def home_state_dir() -> Path:
    """The usual place of the state folder (where a moved one leaves its pointer, leonida/relocate.py). For the
    installed exe (Leonida-V-Setup) that's <the data folder picked in setup>\\State."""
    installed = _installed_data_dir()
    if installed:
        return installed / "State"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "LeonidaV"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "leonida-v"


def default_download_dir() -> Path:
    override = os.environ.get("LEONIDA_DOWNLOAD_DIR")
    if override:
        return Path(override)
    installed = _installed_data_dir()
    if installed:
        return installed / "Downloads"
    return Path.home() / "Downloads" / "LeonidaV"


@dataclass
class Config:
    game_dir: str | None = None
    download_dir: str | None = None
    profile: str | None = None
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    swaps: dict[str, str] = field(default_factory=dict)
    assignments: dict[str, str] = field(default_factory=dict)  # file name -> mod id
    key_overrides: dict[str, str] = field(default_factory=dict)  # "mod/action" -> key
    debug: bool = False                     # Settings > Debug mode: more detailed logs (leonida/logs.py when there)
    update_check: bool = True               # Settings: look for a newer Leonida once a day
    autodl_sites: dict[str, bool] = field(default_factory=dict)  # site -> follow its Download buttons (see autodl)
    disabled: list[str] = field(default_factory=list)  # mods switched off (rolled back, download kept; Enable reinstalls)
    on_game_start: str = "stay"             # Settings: "stay", "minimise" or "close" Leonida when GTA V starts
    seen_version: str | None = None         # the Leonida version whose "What's new" was shown
    update_channel: str = "stable"          # Settings: "stable" releases, or "beta" (pre-releases too)

    @classmethod
    def load(cls, directory: Path) -> Config:
        path = Path(directory) / CONFIG_NAME
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, directory: Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / CONFIG_NAME
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def downloads(self) -> Path:
        return Path(self.download_dir) if self.download_dir else default_download_dir()
