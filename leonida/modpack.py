"""The modpack lockfile (``modpack.json``): the exact mod files tested per game build, published with each release.

Format (schema 1)::

    {
      "schema": 1,
      "pack": "Leonida V", "version": "<mods.json version>", "leonida": "<kit version that built it>",
      "created": "2026-11-24T12:00:00+00:00",
      "builds": {
        "1.0.1013.20": {                      # the game build the set was tested on
          "created": "...",
          "mods": {
            "scripthookv": {
              "version": "1.0.3411.0",
              "file": "ScriptHookV_1.0.3411.0.zip", "size": 123456, "sha256": "<64 hex>",
              "source": {"page": "https://...", "download": {<mods.json download spec>} | null},
              "redistributable": false            # true only if mods.json records the author's permission
              # "proof": "https://...", "mirror": "https://..."   only when redistributable
            }
          }
        }
      }
    }

Files always come from the author's own source (``source``). A modpack entry may only say ``redistributable`` / carry
a ``mirror`` when this Leonida's mods.json has ``redistribution.allowed`` with a proof URL for that mod, and its
``source`` must point at the same place as mods.json (same GitHub repo / host), so a modpack can't redirect
downloads elsewhere. Every downloaded file is checked against the entry's size and SHA-256 before it is installed.
The release's SHA256SUMS.txt lists modpack.json, and ``fetch_latest`` refuses a modpack that doesn't match it.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__, downloader
from .downloader import DownloadError
from .manifest import Manifest, ManifestError, _check_download, build_key
from .matcher import sha256_file

SCHEMA = 1
ASSET = "modpack.json"
MAX_BYTES = 2 * 1024 * 1024
_BUILD_RE = re.compile(r"^\d+(\.\d+){1,3}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ADDED, REMOVED, UPDATED, SAME = "added", "removed", "updated", "same"


class ModpackError(DownloadError):
    """The modpack is missing, malformed, tampered with, or points somewhere it may not."""


@dataclass
class Change:
    mod: str
    kind: str                    # added | removed | updated | same
    old_file: str | None = None
    old_sha256: str | None = None
    new: dict | None = None      # the modpack entry (None for "removed")

    @property
    def new_version(self) -> str | None:
        return (self.new or {}).get("version")

    @property
    def new_file(self) -> str | None:
        return (self.new or {}).get("file")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------------------- build
def entry_for(mod, path: Path) -> dict:
    """The modpack entry for ``mod`` (already resolved for the build) and its downloaded file."""
    entry = {
        "version": mod.version,
        "file": path.name,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "source": {"page": mod.page, "download": dict(mod.download) if mod.download else None},
        "redistributable": mod.redistributable,
    }
    if mod.redistributable:
        entry["proof"] = mod.redistribution["proof"]
    return entry


def build_modpack(session, profile_id: str | None = None) -> dict:
    """A modpack with one section: the current game build and the matched downloads of the selected mods.

    Mods that aren't downloaded or don't run on this build are left out (compare with ``session.mods()``)."""
    build = session.game_version()
    if build_key(build) is None:
        raise ModpackError("Can't read the game build, so the modpack can't say what it was tested on. "
                           "Set the game folder (`leonida detect`) or pass --game-build.")
    mods = [m for m in session.mods(profile_id) if not m.unsupported]
    matched = session.matches(mods).matched
    entries = {m.id: entry_for(m, matched[m.id]) for m in mods if m.id in matched}
    now = _now()
    return {
        "schema": SCHEMA,
        "pack": session.manifest.pack,
        "version": session.manifest.version,
        "leonida": __version__,
        "created": now,
        "builds": {build: {"created": now, "mods": entries}},
    }


def merge(base: dict | None, new: dict) -> dict:
    """``base`` plus ``new``'s build sections (``new`` wins for a build both have). Used to combine modpacks
    made on PCs with different game builds into one release file."""
    out = json.loads(json.dumps(base)) if base else {}
    builds = dict(out.get("builds", {}))
    builds.update(json.loads(json.dumps(new.get("builds", {}))))
    out.update({k: v for k, v in new.items() if k != "builds" and not k.startswith("_")})
    out["builds"] = dict(sorted(builds.items(), key=lambda kv: build_key(kv[0]) or ()))
    return out


# ---------------------------------------------------------------------------------------------- validate
def _https(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def validate(data: Any) -> dict:
    """Check the structure of a modpack; returns it unchanged or raises ModpackError."""
    if not isinstance(data, dict):
        raise ModpackError("modpack.json is not a JSON object")
    if data.get("schema") != SCHEMA:
        raise ModpackError(f"modpack.json schema {data.get('schema')!r} is not supported (expected {SCHEMA}); "
                           "update Leonida V")
    builds = data.get("builds")
    if not isinstance(builds, dict) or not builds:
        raise ModpackError("modpack.json has no 'builds'")
    for build, section in builds.items():
        if not isinstance(build, str) or not _BUILD_RE.match(build):
            raise ModpackError(f"modpack.json: {build!r} is not a game build")
        mods = section.get("mods") if isinstance(section, dict) else None
        if not isinstance(mods, dict):
            raise ModpackError(f"modpack.json build {build}: 'mods' must be an object")
        for mod_id, e in mods.items():
            where = f"modpack.json build {build}, mod {mod_id!r}"
            if not isinstance(e, dict):
                raise ModpackError(f"{where}: must be an object")
            if not isinstance(e.get("version"), str):
                raise ModpackError(f"{where}: 'version' must be a string")
            name = e.get("file")
            if not isinstance(name, str) or not name or downloader._safe_name(name) != name:
                raise ModpackError(f"{where}: 'file' must be a plain file name")
            if not isinstance(e.get("size"), int) or isinstance(e.get("size"), bool) or e["size"] < 0:
                raise ModpackError(f"{where}: 'size' must be a whole number of bytes")
            if not isinstance(e.get("sha256"), str) or not _SHA_RE.match(e["sha256"]):
                raise ModpackError(f"{where}: 'sha256' must be 64 lowercase hex characters")
            src = e.get("source")
            if not isinstance(src, dict) or not _https(src.get("page")):
                raise ModpackError(f"{where}: 'source.page' must be the author's https page")
            if src.get("download") is not None:
                try:
                    _check_download(src["download"], where)
                except ManifestError as exc:
                    raise ModpackError(str(exc)) from None
            if not isinstance(e.get("redistributable", False), bool):
                raise ModpackError(f"{where}: 'redistributable' must be true or false")
            if "mirror" in e and not (e.get("redistributable") and _https(e["mirror"])):
                raise ModpackError(f"{where}: a 'mirror' needs redistributable: true and an https URL")
    return data


def _host(url: str | None) -> str:
    return (urllib.parse.urlsplit(url or "").hostname or "").lower()


def entry_problem(mod_id: str, entry: dict, manifest: Manifest, build: str | None) -> str | None:
    """Why this entry may not be used with this Leonida's mods.json (None = fine)."""
    try:
        mod = manifest.mod(mod_id).for_build(build)
    except ManifestError:
        return f"{mod_id} isn't in this Leonida's mod list; update Leonida V (`leonida self-update`)."
    if (entry.get("redistributable") or entry.get("mirror")) and not mod.redistributable:
        return (f"The modpack wants to re-host {mod.name}, but mods.json has no redistribution permission for it; "
                "the file has to come from the author's page.")
    src = entry.get("source") or {}
    dl, ours = src.get("download"), mod.download
    if dl:
        same = bool(ours) and dl.get("type") == ours.get("type") and (
            (dl.get("type") == "github" and str(dl.get("repo", "")).lower() == str(ours.get("repo", "")).lower())
            or (dl.get("type") == "direct" and _host(dl.get("url")) == _host(ours.get("url"))))
        if not same:
            return f"The modpack's download for {mod.name} doesn't point at the author's source in mods.json."
    if _host(src.get("page")) != _host(mod.page):
        return f"The modpack's page for {mod.name} ({src.get('page')}) isn't the author's page in mods.json."
    return None


# ------------------------------------------------------------------------------------------------- query
def section_for(modpack: dict, build: str | None) -> tuple[str | None, dict | None]:
    """The section for ``build``: an exact match, else the newest section for an older build (its versions are
    then checked per mod with ``Mod.for_build``). (None, None) when nothing fits."""
    key = build_key(build)
    if key is None:
        return None, None
    builds = modpack.get("builds", {})
    for b, section in builds.items():
        if build_key(b) == key:
            return b, section
    older = sorted((b for b in builds if build_key(b) < key), key=build_key)
    return (older[-1], builds[older[-1]]) if older else (None, None)


def diff(current_lock: dict | None, modpack: dict, build: str | None = None) -> list[Change]:
    """Compare a lockfile (``matcher.build_lock`` format) with the modpack section for ``build``.

    ``build`` None -> the modpack's newest build. Raises ModpackError when the modpack has nothing for the build."""
    if build is None:
        builds = sorted(modpack.get("builds", {}), key=build_key)
        build = builds[-1] if builds else None
    _, section = section_for(modpack, build)
    if section is None:
        have = ", ".join(modpack.get("builds", {})) or "none"
        raise ModpackError(f"The modpack has no tested set for game build {build} (it has: {have}).")
    old = {e["mod"]: e for e in (current_lock or {}).get("entries", [])}
    new = section["mods"]
    out: list[Change] = []
    for mod_id in sorted(set(old) | set(new)):
        o, n = old.get(mod_id), new.get(mod_id)
        if n is None:
            kind = REMOVED
        elif o is None:
            kind = ADDED
        else:
            kind = SAME if (o.get("sha256") or "").lower() == n["sha256"] else UPDATED
        out.append(Change(mod_id, kind, o.get("file") if o else None, o.get("sha256") if o else None, n))
    return out


def verify_file(path: Path, entry: dict) -> str | None:
    """None if ``path`` is exactly the file the modpack lists, else what's wrong (the file is left alone)."""
    path = Path(path)
    if not path.is_file():
        return f"{path.name} is not in the download folder."
    size = path.stat().st_size
    if size != entry["size"]:
        return (f"{path.name} is {size} bytes but the modpack's tested file is {entry['size']} bytes: it's a "
                "different file. It was kept but not installed.")
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        return (f"{path.name} doesn't match the modpack's SHA-256 (expected {entry['sha256'][:12]}..., got "
                f"{actual[:12]}...). It was kept but not installed; download it again from the author's page.")
    return None


# ------------------------------------------------------------------------------------------- read/write
def load_file(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModpackError(f"Could not read {path}: {exc}") from None
    return validate(data)


def write_file(path: Path, data: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def fetch_latest(timeout: float = 15) -> dict | None:
    """``modpack.json`` from the latest Leonida V release, verified against its SHA256SUMS. None when there is no
    release or the release has no modpack. The result carries ``_release`` = {tag, page, verified}."""
    from .updater import REPO, _parse_sums

    base = downloader.GITHUB_API.rstrip("/")
    release = downloader._github_json(f"{base}/repos/{REPO}/releases/latest", REPO, timeout)
    if not release:
        return None
    assets = {str(a.get("name", "")).lower(): a for a in release.get("assets") or [] if a.get("browser_download_url")}
    asset = assets.get(ASSET)
    if not asset:
        return None
    sums_asset = next((a for n, a in assets.items() if n.startswith("sha256sums")), None)
    try:
        with downloader._open(asset["browser_download_url"], timeout) as r:
            raw = r.read(MAX_BYTES + 1)
        sums = {}
        if sums_asset:
            with downloader._open(sums_asset["browser_download_url"], timeout) as r:
                sums = _parse_sums(r.read(256 * 1024).decode("utf-8", errors="replace"))
    except DownloadError:
        raise
    except Exception as exc:
        raise ModpackError(f"Could not download the modpack: {exc}") from None
    if len(raw) > MAX_BYTES:
        raise ModpackError("modpack.json is too large")
    expected = {k.lower(): v for k, v in sums.items()}.get(ASSET)
    if expected and hashlib.sha256(raw).hexdigest() != expected:
        raise ModpackError("modpack.json doesn't match the release's SHA256SUMS.txt: it may have been tampered "
                           "with. Not using it.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ModpackError(f"modpack.json is not valid JSON: {exc}") from None
    validate(data)
    data["_release"] = {"tag": release.get("tag_name"), "page": release.get("html_url"), "verified": bool(expected)}
    return data
