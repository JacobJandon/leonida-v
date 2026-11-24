"""Match downloaded files to mods, hash them, and keep the lockfile."""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .manifest import Mod

IGNORED_SUFFIXES = (".crdownload", ".part", ".tmp", ".download", ".partial")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def _specificity(pattern: str) -> int:
    return sum(1 for c in pattern if c not in "*?[]")


def best_pattern_score(mod: Mod, filename: str) -> int:
    """Highest specificity of the mod's patterns matching ``filename`` (0 = no match)."""
    name = filename.lower()
    return max(
        (_specificity(p) for p in mod.archive if fnmatch.fnmatchcase(name, p.lower())),
        default=0,
    )


@dataclass
class MatchResult:
    matched: dict[str, Path] = field(default_factory=dict)  # mod id -> file
    duplicates: dict[str, list[Path]] = field(default_factory=dict)  # mod id -> older extra files
    unmatched: list[Path] = field(default_factory=list)
    ambiguous: dict[Path, list[str]] = field(default_factory=dict)

    def missing(self, mods: Iterable[Mod]) -> list[Mod]:
        return [m for m in mods if m.id not in self.matched]


def scan_folder(folder: Path) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and not p.name.lower().endswith(IGNORED_SUFFIXES) and not p.name.startswith(".")
    )


def match_files(mods: Iterable[Mod], files: Iterable[Path],
                assignments: dict[str, str] | None = None) -> MatchResult:
    """Assign each file to the mod whose name pattern fits it most specifically."""
    mods = list(mods)
    by_id = {m.id: m for m in mods}
    assignments = {k.lower(): v for k, v in (assignments or {}).items()}
    result = MatchResult()
    candidates: dict[str, list[Path]] = {}

    for f in files:
        forced = assignments.get(f.name.lower())
        if forced and forced in by_id:
            candidates.setdefault(forced, []).insert(0, f)  # manual wins
            continue
        scored = [(best_pattern_score(m, f.name), m.id) for m in mods]
        scored = [s for s in scored if s[0] > 0]
        if not scored:
            result.unmatched.append(f)
            continue
        top = max(s[0] for s in scored)
        winners = [mid for score, mid in scored if score == top]
        if len(winners) > 1:
            result.ambiguous[f] = winners
            continue
        candidates.setdefault(winners[0], []).append(f)

    for mod_id, paths in candidates.items():
        forced = [p for p in paths if assignments.get(p.name.lower()) == mod_id]
        rest = sorted((p for p in paths if p not in forced), key=lambda p: p.stat().st_mtime, reverse=True)
        ordered = forced + rest
        result.matched[mod_id] = ordered[0]
        if len(ordered) > 1:
            result.duplicates[mod_id] = ordered[1:]
    return result


# --- lockfile -----------------------------------------------------------------
def build_lock(pack: str, version: str, matched: dict[str, Path]) -> dict:
    entries = []
    for mod_id, path in sorted(matched.items()):
        entries.append({
            "mod": mod_id,
            "file": path.name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return {
        "pack": pack,
        "version": version,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": entries,
    }


def write_lock(path: Path, lock: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2), encoding="utf-8")


def read_lock(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def verify_lock(lock: dict, matched: dict[str, Path]) -> list[str]:
    """Human-readable differences between the lockfile and the files on disk."""
    problems = []
    for e in lock.get("entries", []):
        p = matched.get(e["mod"])
        if p is None:
            problems.append(f"{e['mod']}: locked file {e['file']} is no longer in the download folder")
        elif p.stat().st_size != e["size"] or sha256_file(p) != e["sha256"]:
            problems.append(f"{e['mod']}: {p.name} differs from the locked file {e['file']}")
    return problems
