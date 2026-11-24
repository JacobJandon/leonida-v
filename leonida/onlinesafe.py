"""The online-safe switch: move every mod file out of the game folder, and back."""

from __future__ import annotations

import contextlib
import fnmatch
import json
import shutil
from pathlib import Path

OFFLINE_DIR = "_LeonidaV_offline"
RECORD = "moved.json"


class OnlineSafeError(RuntimeError):
    pass


def mod_items(game_dir: Path, patterns: tuple[str, ...]) -> list[Path]:
    """Top-level entries in the game folder that match the online-safe patterns."""
    game_dir = Path(game_dir)
    pats = [p.lower() for p in patterns]
    out = []
    for entry in sorted(game_dir.iterdir(), key=lambda p: p.name.lower()):
        if entry.name == OFFLINE_DIR:
            continue
        if any(fnmatch.fnmatchcase(entry.name.lower(), p) for p in pats):
            out.append(entry)
    return out


def status(game_dir: Path, patterns: tuple[str, ...]) -> str:
    """'mods-on', 'online-safe' (mods moved out), 'clean' (no mods at all) or 'mixed'."""
    off = Path(game_dir) / OFFLINE_DIR / RECORD
    present = mod_items(game_dir, patterns)
    if off.exists():
        return "mixed" if present else "online-safe"
    return "mods-on" if present else "clean"


def go_online_safe(game_dir: Path, patterns: tuple[str, ...], dry_run: bool = False) -> list[str]:
    game_dir = Path(game_dir)
    off = game_dir / OFFLINE_DIR
    if (off / RECORD).exists():
        raise OnlineSafeError("Mods are already moved out. Use `leonida online-safe off` to bring them back.")
    items = mod_items(game_dir, patterns)
    names = [p.name for p in items]
    if dry_run or not items:
        return names
    off.mkdir(exist_ok=True)
    moved: list[str] = []
    try:
        for p in items:
            shutil.move(str(p), str(off / p.name))
            moved.append(p.name)
    finally:
        (off / RECORD).write_text(json.dumps({"moved": moved}, indent=2), encoding="utf-8")
    return moved


def restore_mods(game_dir: Path, dry_run: bool = False) -> list[str]:
    game_dir = Path(game_dir)
    off = game_dir / OFFLINE_DIR
    rec = off / RECORD
    if not rec.exists():
        raise OnlineSafeError("Nothing to restore: mods are not in online-safe storage.")
    moved = json.loads(rec.read_text(encoding="utf-8")).get("moved", [])
    clashes = [n for n in moved if (game_dir / n).exists()]
    if clashes:
        raise OnlineSafeError("These already exist in the game folder, so nothing was moved back: "
                              + ", ".join(clashes))
    if dry_run:
        return moved
    for name in moved:
        src = off / name
        if src.exists():
            shutil.move(str(src), str(game_dir / name))
    rec.unlink()
    with contextlib.suppress(OSError):
        off.rmdir()
    return moved
