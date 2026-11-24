"""Record what the game folder looks like, and diff two records."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .matcher import sha256_file

# Folders mods live in: walked fully. Everything else at the top level is recorded but not walked.
MANAGED_DIRS = ("scripts", "mods", "onigiri", "menyooStuff", "plugins")
HASH_LIMIT = 64 * 1024 * 1024  # files bigger than this are compared by size + mtime only
IGNORE_TOP = ("_LeonidaV_offline",)


def _record(path: Path) -> list:
    st = path.stat()
    digest = sha256_file(path) if st.st_size <= HASH_LIMIT else None
    return [st.st_size, st.st_mtime_ns, digest]


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def take_snapshot(game_dir: Path, managed: tuple[str, ...] = MANAGED_DIRS) -> dict:
    root = Path(game_dir)
    files: dict[str, list] = {}
    top_dirs: list[str] = []
    managed_lower = {m.lower() for m in managed}
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if entry.name in IGNORE_TOP:
            continue
        if entry.is_file():
            files[_rel(entry, root)] = _record(entry)
        elif entry.is_dir():
            top_dirs.append(entry.name)
            if entry.name.lower() in managed_lower:
                for dirpath, dirnames, filenames in os.walk(entry):
                    dirnames.sort()
                    for fn in sorted(filenames):
                        p = Path(dirpath) / fn
                        files[_rel(p, root)] = _record(p)
                    if not filenames and not dirnames:
                        files[_rel(Path(dirpath), root) + "/"] = [0, 0, "dir"]
    return {
        "root": str(root),
        "taken": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "managed": list(managed),
        "top_dirs": top_dirs,
        "files": files,
    }


@dataclass
class Diff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    added_dirs: list[str] = field(default_factory=list)
    removed_dirs: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.added_dirs or self.removed_dirs)

    def summary(self) -> str:
        return (f"{len(self.added)} added, {len(self.changed)} changed, {len(self.removed)} removed"
                + (f", top-level folders +{len(self.added_dirs)}/-{len(self.removed_dirs)}"
                   if self.added_dirs or self.removed_dirs else ""))


def _same(a: list, b: list) -> bool:
    if a[2] == "dir" or b[2] == "dir":
        return a[2] == b[2]
    if a[0] != b[0]:
        return False
    if a[2] and b[2]:
        return a[2] == b[2]
    return a[1] == b[1]


def diff(before: dict, after: dict) -> Diff:
    fb, fa = before["files"], after["files"]
    d = Diff()
    d.added = sorted(k for k in fa if k not in fb)
    d.removed = sorted(k for k in fb if k not in fa)
    d.changed = sorted(k for k in fa if k in fb and not _same(fb[k], fa[k]))
    tb, ta = set(before.get("top_dirs", [])), set(after.get("top_dirs", []))
    d.added_dirs = sorted(ta - tb)
    d.removed_dirs = sorted(tb - ta)
    return d


def save_snapshot(snap: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap), encoding="utf-8")


def load_snapshot(path: Path) -> dict | None:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
