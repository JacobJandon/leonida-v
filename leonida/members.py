"""Check what's inside a downloaded archive against a mod's ``requireMembers`` / ``rejectMembers`` rules.

Some authors serve the Legacy build under the same file name as the Enhanced one (gta5-mods' main Download button
often gives the "(current)" Legacy file), so the name alone can't tell them apart. The rules look inside:
``require_members`` globs must each match at least one member path, ``reject_members`` globs must match none
(case-insensitive, over the whole POSIX member path; ``*`` crosses folders). A file that fails is never matched
or installed and is reported as "wrong edition/version of <mod>: <reason>".

Listing a 500 MB .rar takes time, so listings are cached in ``<state>/archive-listings.json`` by
(path, size, mtime): the Get page re-scans the download folder every few seconds without re-listing anything.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from .archive import ArchiveError, is_archive, list_members

CACHE_NAME = "archive-listings.json"
MAX_ENTRIES = 300


def has_rules(mod) -> bool:
    return bool(getattr(mod, "require_members", ()) or getattr(mod, "reject_members", ()))


def member_problem(mod, members: list[str]) -> str | None:
    """Why these archive members don't fit the mod's rules (None = they fit)."""
    low = [m.replace("\\", "/").lstrip("/").lower() for m in members]
    for pattern in getattr(mod, "reject_members", ()):
        p = pattern.lower()
        hit = next((m for m, lm in zip(members, low, strict=True) if fnmatch.fnmatchcase(lm, p)), None)
        if hit is not None:
            return f"it contains {hit} (matches {pattern!r}, which this mod must not have)"
    for pattern in getattr(mod, "require_members", ()):
        p = pattern.lower()
        if not any(fnmatch.fnmatchcase(lm, p) for lm in low):
            return f"it has no file matching {pattern!r}"
    return None


def wrong_message(mod, reason: str) -> str:
    return f"wrong edition/version of {mod.name}: {reason}"


class ListingCache:
    """Archive member lists cached by (path, size, mtime) in ``<state>/archive-listings.json``."""

    def __init__(self, state_dir: Path | None, seven_zip: Path | None = None):
        self.path = Path(state_dir) / CACHE_NAME if state_dir else None
        self.seven_zip = seven_zip
        self._data: dict[str, list[str]] | None = None

    def _load(self) -> dict[str, list[str]]:
        if self._data is None:
            self._data = {}
            if self.path and self.path.is_file():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self._data = {k: v for k, v in data.items() if isinstance(v, list)}
                except (OSError, ValueError):
                    pass
        return self._data

    def _save(self) -> None:
        if not self.path or self._data is None:
            return
        items = list(self._data.items())[-MAX_ENTRIES:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(dict(items)), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # only a cache

    @staticmethod
    def key(path: Path) -> str:
        st = Path(path).stat()
        return f"{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}"

    def members(self, path: Path) -> list[str]:
        """The archive's member paths (cached). Raises ArchiveError when it can't be listed."""
        data = self._load()
        key = self.key(path)
        if key in data:
            return data[key]
        members = list_members(Path(path), self.seven_zip)
        stale = [k for k in data if k.rsplit("|", 2)[0] == key.rsplit("|", 2)[0]]
        for k in stale:  # the same file changed: drop its old listing
            del data[k]
        data[key] = members
        self._save()
        return members


def check_file(mod, path: Path, cache: ListingCache) -> str | None:
    """None when ``path`` fits the mod's member rules (or the mod has none), else the reason it doesn't."""
    if not has_rules(mod):
        return None
    if not is_archive(path):
        return f"{Path(path).name} is not an archive, so Leonida can't check that it's the right edition"
    try:
        members = cache.members(path)
    except (ArchiveError, OSError) as exc:
        return f"Leonida can't read what's inside it ({exc})"
    return member_problem(mod, members)


def apply_rules(result, mods, cache: ListingCache):
    """Drop matched files that fail their mod's member rules: an older duplicate that fits takes over; failing
    files go to ``result.wrong`` ({file: (mod id, reason)}) and ``result.unmatched``. Returns ``result``."""
    by_id = {m.id: m for m in mods}
    for mod_id in list(result.matched):
        mod = by_id.get(mod_id)
        if mod is None or not has_rules(mod):
            continue
        candidates = [result.matched[mod_id], *result.duplicates.get(mod_id, [])]
        good = []
        for path in candidates:
            reason = check_file(mod, path, cache)
            if reason is None:
                good.append(path)
            else:
                result.wrong[path] = (mod_id, reason)
                if path not in result.unmatched:
                    result.unmatched.append(path)
        if good:
            result.matched[mod_id] = good[0]
            if len(good) > 1:
                result.duplicates[mod_id] = good[1:]
            else:
                result.duplicates.pop(mod_id, None)
        else:
            del result.matched[mod_id]
            result.duplicates.pop(mod_id, None)
    return result
