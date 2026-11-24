from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from leonida.log import InstallLog
from leonida.manifest import load_manifest

os.environ.setdefault("LEONIDA_NO_OPEN", "1")
os.environ.setdefault("LEONIDA_FAKE_GPU", "")


def make_zip(path: Path, members: dict[str, bytes | str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data.encode() if isinstance(data, str) else data)
    return path


class AutoUI:
    """Non-interactive UI for tests. Callbacks simulate what a user/installer does."""

    def __init__(self, on_wait=None, on_launch=None, confirm=True, done=True):
        self.lines: list[str] = []
        self.on_wait = on_wait
        self.on_launch = on_launch
        self._confirm = confirm
        self._done = done

    def info(self, msg):
        self.lines.append(msg)

    def warn(self, msg):
        self.lines.append("WARN " + msg)

    def confirm(self, msg, default=True):
        return self._confirm

    def wait_done(self, title, steps, folder):
        if self.on_wait:
            self.on_wait(folder)
        return self._done

    def launch(self, path):
        if self.on_launch:
            self.on_launch(path)


@pytest.fixture
def manifest():
    return load_manifest()


@pytest.fixture
def game(tmp_path: Path) -> Path:
    g = tmp_path / "Grand Theft Auto V Enhanced"
    (g / "update").mkdir(parents=True)
    (g / "x64").mkdir()
    (g / "GTA5_Enhanced.exe").write_bytes(b"MZ fake exe")
    (g / "bink2w64.dll").write_bytes(b"original bink")
    (g / "update" / "update.rpf").write_bytes(b"RPF7" * 100)
    return g


@pytest.fixture
def state(tmp_path: Path) -> Path:
    s = tmp_path / "state"
    s.mkdir()
    return s


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    d = tmp_path / "Downloads" / "LeonidaV"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def log(state: Path) -> InstallLog:
    return InstallLog(state / "install-log.json")
