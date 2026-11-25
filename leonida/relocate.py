"""Move Leonida's own folders: the state folder (install log, backups, settings) and the downloads folder.

The state folder's usual place (%LOCALAPPDATA%\\LeonidaV) keeps a pointer, ``moved-to.txt``, naming the new place;
``paths.state_dir()`` follows it (LEONIDA_STATE_DIR still wins). Moving copies everything first and checks the
copy (every file, same size) before anything is removed from the old place; a file that can't be copied stops the
move and the old folder stays as it was. Files Windows keeps open (Leonida's own log) are left behind and listed.
Stdlib only.
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

POINTER = "moved-to.txt"


class MoveError(RuntimeError):
    pass


@dataclass
class MoveReport:
    target: Path
    copied: int = 0
    left: list[str] = field(default_factory=list)     # could not be removed from the old place (in use)

    def lines(self) -> list[str]:
        out = [f"Copied {self.copied} file(s) to {self.target}."]
        if self.left:
            out.append(f"{len(self.left)} file(s) in use stay in the old place: " + ", ".join(self.left[:5]))
        return out


def _check_target(src: Path, dst: Path) -> None:
    s, d = src.resolve(), dst.resolve()
    if s == d:
        raise MoveError("That's the folder it's in already.")
    if d.is_relative_to(s) or s.is_relative_to(d):
        raise MoveError("Pick a folder outside the current one (and not one that holds it).")
    if d.exists() and any(d.iterdir()):
        raise MoveError(f"{d} isn't empty: pick an empty or new folder.")
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".leonida-write-test"
        probe.write_text("x")
        probe.unlink()
    except OSError as exc:
        raise MoveError(f"Leonida can't write to {d}: {exc.strerror or exc}") from None


def _copy_all(src: Path, dst: Path, skip: tuple[str, ...] = ()) -> list[Path]:
    """Copy every file (not ``skip`` names at the top); raises MoveError (and removes the partial copy) on failure."""
    copied = []
    try:
        for root, dirs, files in os.walk(src):
            rel = Path(root).relative_to(src)
            if rel == Path("."):
                dirs[:] = [d for d in dirs if d not in skip]
                files = [f for f in files if f not in skip]
            (dst / rel).mkdir(parents=True, exist_ok=True)
            for f in files:
                a, b = Path(root) / f, dst / rel / f
                shutil.copy2(a, b)
                if b.stat().st_size != a.stat().st_size:
                    raise OSError(f"{a.name} was copied incomplete")
                copied.append(rel / f)
    except OSError as exc:
        shutil.rmtree(dst, ignore_errors=True)
        raise MoveError(f"Couldn't copy {getattr(exc, 'filename', None) or exc}: {exc.strerror or exc}. Nothing "
                        "was moved.") from None
    return copied


def _remove_copied(src: Path, rels: list[Path]) -> list[str]:
    left = []
    for rel in rels:
        try:
            (src / rel).unlink()
        except OSError:
            left.append(str(rel))
    for root, _dirs, _files in sorted(os.walk(src), key=lambda t: -len(t[0])):
        if Path(root) != src:
            with contextlib.suppress(OSError):  # still holds a file in use
                Path(root).rmdir()
    return left


def move_state(current: Path, target: Path, home: Path) -> MoveReport:
    """Move the state folder ``current`` to ``target`` and point ``home`` (the usual place) at it. Restart Leonida
    afterwards: the running one still has the old place open."""
    current, target, home = Path(current), Path(target), Path(home)
    _check_target(current, target)
    rels = _copy_all(current, target, skip=(POINTER,))
    home.mkdir(parents=True, exist_ok=True)
    (home / POINTER).write_text(str(target), encoding="utf-8")
    left = _remove_copied(current, rels)
    log.info("state folder moved: %s -> %s (%d files, %d left)", current, target, len(rels), len(left))
    return MoveReport(target, len(rels), left)


def pointed_state(home: Path) -> Path | None:
    """Where ``home``'s pointer says the state folder is (None without one, or when that folder is gone)."""
    try:
        target = Path((Path(home) / POINTER).read_text(encoding="utf-8").strip())
    except OSError:
        return None
    return target if target.is_dir() else None


def move_downloads(current: Path, target: Path) -> MoveReport:
    """Move the downloaded files to ``target`` (a new or empty folder)."""
    current, target = Path(current), Path(target)
    _check_target(current, target)
    if not current.is_dir():
        return MoveReport(target)
    rels = _copy_all(current, target)
    left = _remove_copied(current, rels)
    log.info("downloads moved: %s -> %s (%d files)", current, target, len(rels))
    return MoveReport(target, len(rels), left)
