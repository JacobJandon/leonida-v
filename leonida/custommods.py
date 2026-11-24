"""The user's own mods ("your own mods"): entries in ``<state>/custom-mods.json`` that become ordinary manifest mods.

Each entry describes a mod the user brings: a file on their disk or a page URL, how it installs (files spec, target
folder or the generic .asi/scripts rules, or a guided step list), and where it goes in the install order. It is
turned into a :class:`~leonida.manifest.Mod` (tier ``custom``) and merged into the session's manifest, so it gets
the same matching, logged install, rollback, conflict checks and online-safe handling as the curated mods.

Entry (JSON)::

    {"id": "my-trainer", "name": "My trainer", "file": "D:/mods/trainer.zip"     # or "page": "https://..."
     "archive": ["trainer*.zip"],          # how to recognise its download (default: the file's name)
     "method": "copy" | "generic" | "guided" | "run",   # default: copy when files/to are given, else generic
     "files": [{"match": "trainer.asi", "to": "."}],     # copy: what goes where (same as mods.json install.files)
     "steps": ["..."], "run": "setup.exe", "conflicts": ["*.asi"], "notes": "...",
     "order": 3,                           # position among the user's own mods (they install after the curated ones)
     "enabled": true}
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from .manifest import Manifest, ManifestError, Mod, _mod_from

FILE_NAME = "custom-mods.json"
ORDER_BASE = 10_000          # custom mods install after every curated mod
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$")
_KEYS = {"id", "name", "file", "page", "archive", "method", "files", "steps", "run", "conflicts", "notes", "order",
         "enabled", "createDirs"}


class CustomModError(ManifestError):
    """A custom mod entry is invalid."""


def path_of(state: Path) -> Path:
    return Path(state) / FILE_NAME


def load_entries(state: Path) -> list[dict]:
    p = path_of(state)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CustomModError(f"{p} can't be read: {exc}") from None
    entries = data.get("mods", []) if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise CustomModError(f"{p}: 'mods' must be a list")
    return [dict(e) for e in entries]


def save_entries(state: Path, entries: list[dict]) -> Path:
    p = path_of(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"mods": entries}, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
    return s or "mod"


def to_mod(entry: dict, index: int) -> Mod:
    """The manifest Mod for one entry (``index`` = its position, used when it has no ``order``)."""
    where = f"Your mod {entry.get('id', '?')!r}"
    if not isinstance(entry, dict):
        raise CustomModError("every custom mod entry must be an object")
    unknown = set(entry) - _KEYS
    if unknown:
        raise CustomModError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    mid = entry.get("id")
    if not isinstance(mid, str) or not _ID.match(mid):
        raise CustomModError(f"{where}: id must be lower-case letters, digits, '.', '-' or '_'")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CustomModError(f"{where}: give it a name")
    file, page = entry.get("file"), entry.get("page")
    if not file and not page:
        raise CustomModError(f"{where}: give a file on your disk or the mod's page")
    if page and not str(page).startswith(("https://", "http://")):
        raise CustomModError(f"{where}: page must be a web address")
    archive = entry.get("archive") or ([Path(file).name] if file else None)
    if not archive or not isinstance(archive, list) or not all(isinstance(a, str) and a for a in archive):
        raise CustomModError(f"{where}: with only a page, say how its download is named ('archive': [\"name*.zip\"])")
    files = entry.get("files") or []
    method = entry.get("method") or ("copy" if files else "generic")
    order = entry.get("order", index + 1)
    if not isinstance(order, int) or isinstance(order, bool) or order < 0:
        raise CustomModError(f"{where}: order must be a whole number")
    raw: dict[str, Any] = {
        "id": mid, "order": ORDER_BASE + order, "tier": "custom", "layer": "Your mods", "name": name.strip(),
        "author": "you", "version": "", "source": "custom", "page": page or (Path(file).absolute().as_uri() if file else ""),
        "archive": archive,
        "install": {"method": method, "files": files, "steps": entry.get("steps") or [
            f"Install {name} the way its readme says; Leonida records what changes in the game folder."],
            **({"run": entry["run"]} if entry.get("run") else {}),
            **({"createDirs": entry["createDirs"]} if entry.get("createDirs") else {})},
        "conflicts": entry.get("conflicts") or [],
        "notes": entry.get("notes", ""),
    }
    try:
        return _mod_from(raw)
    except ManifestError as exc:
        raise CustomModError(str(exc).replace(f"Mod {mid!r}", where)) from None


def merge(manifest: Manifest, entries: list[dict]) -> Manifest:
    """``manifest`` plus the enabled and disabled custom mods (the session decides which are selected)."""
    if not entries:
        return manifest
    mods = dict(manifest.mods)
    for i, e in enumerate(entries):
        m = to_mod(e, i)
        if m.id in mods:
            who = "a curated mod" if m.id in manifest.mods else "another of your mods"
            raise CustomModError(f"Your mod id {m.id!r} is already used by {who}")
        mods[m.id] = m
    return replace(manifest, mods=dict(sorted(mods.items(), key=lambda kv: kv[1].order)))


def enabled_ids(entries: list[dict]) -> list[str]:
    return [e["id"] for e in entries if e.get("enabled", True) and isinstance(e.get("id"), str)]


def file_of(entries: list[dict], mod_id: str) -> Path | None:
    """The file the user pointed at for this custom mod (matched directly, wherever it is), if it exists."""
    e = next((x for x in entries if x.get("id") == mod_id), None)
    if e and e.get("file") and Path(e["file"]).is_file():
        return Path(e["file"])
    return None


def add(state: Path, manifest: Manifest, *, name: str, file: str | None = None, page: str | None = None,
        archive: list[str] | None = None, files: list[str] | None = None, to: str = ".", method: str | None = None,
        order: int | None = None, mod_id: str | None = None, steps: list[str] | None = None,
        run: str | None = None, notes: str = "") -> dict:
    """Add (or replace, same id) a custom mod and save. ``files`` are file names to copy into ``to``."""
    entries = load_entries(state)
    mid = mod_id or slug(name)
    if mid in manifest.mods and mid not in {e.get("id") for e in entries}:
        mid = f"my-{mid}"
    entry: dict[str, Any] = {"id": mid, "name": name, "enabled": True}
    if file:
        entry["file"] = str(Path(file))
    if page:
        entry["page"] = page
    if archive:
        entry["archive"] = list(archive)
    if files:
        entry["files"] = [{"match": f, "to": to} for f in files]
    elif to not in (".", "") and method in (None, "copy"):
        raise CustomModError("--to needs --files: say which files go into that folder")
    if method:
        entry["method"] = method
    if run:
        entry["run"] = run
    if steps:
        entry["steps"] = list(steps)
    if notes:
        entry["notes"] = notes
    entries = [e for e in entries if e.get("id") != mid]
    entry["order"] = order if order is not None else max((e.get("order", 0) for e in entries), default=0) + 1
    entries.append(entry)
    merge(manifest, entries)  # validates the whole set
    save_entries(state, entries)
    return entry


def remove(state: Path, mod_id: str) -> bool:
    entries = load_entries(state)
    kept = [e for e in entries if e.get("id") != mod_id]
    if len(kept) == len(entries):
        return False
    save_entries(state, kept)
    return True


def export(state: Path, out: Path) -> Path:
    """Write the user's custom mods to ``out`` (to share with someone else)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mods": load_entries(state)}, indent=2), encoding="utf-8")
    return out
