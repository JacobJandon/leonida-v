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
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "LeonidaV"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "leonida-v"


def default_download_dir() -> Path:
    override = os.environ.get("LEONIDA_DOWNLOAD_DIR")
    if override:
        return Path(override)
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
