"""Load and validate the Leonida V manifest (mods.json, profiles.json, hotkeys.json)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

TIERS = ("core", "optional", "alternative", "paid")
METHODS = ("copy", "generic", "run", "guided")


class ManifestError(ValueError):
    """The manifest files are missing, malformed or inconsistent."""


@dataclass(frozen=True)
class FileSpec:
    match: str
    to: str = "."
    type: str = "file"  # "file" or "dir"
    optional: bool = False


@dataclass(frozen=True)
class Mod:
    id: str
    order: int
    tier: str
    layer: str
    name: str
    author: str
    version: str
    source: str
    page: str
    archive: tuple[str, ...]
    method: str
    files: tuple[FileSpec, ...] = ()
    steps: tuple[str, ...] = ()
    run: str | None = None
    create_dirs: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    slot: str | None = None
    replaces: str | None = None
    warnings: tuple[dict, ...] = ()
    requires: dict = field(default_factory=dict)
    notes: str = ""

    @property
    def automatic(self) -> bool:
        """True when the app places the files itself (copy/generic)."""
        return self.method in ("copy", "generic")

    @property
    def manual_download(self) -> bool:
        return self.source in ("discord", "patreon", "shop", "nexus-login")


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    description: str
    include: tuple[str, ...]
    requires: dict = field(default_factory=dict)


@dataclass
class Manifest:
    pack: str
    version: str
    tested_build: str
    exe_names: tuple[str, ...]
    online_safe_items: tuple[str, ...]
    prerequisites: tuple[dict, ...]
    mods: dict[str, Mod]
    profiles: dict[str, Profile]
    default_profile: str
    hotkeys: tuple[dict, ...]

    # ---- lookups -------------------------------------------------------
    def mod(self, mod_id: str) -> Mod:
        try:
            return self.mods[mod_id]
        except KeyError:
            raise ManifestError(f"Unknown mod id: {mod_id!r}") from None

    def profile(self, profile_id: str) -> Profile:
        try:
            return self.profiles[profile_id]
        except KeyError:
            raise ManifestError(
                f"Unknown profile: {profile_id!r}. Known: {', '.join(self.profiles)}"
            ) from None

    def ordered(self, ids: Iterable[str]) -> list[Mod]:
        return sorted((self.mod(i) for i in set(ids)), key=lambda m: m.order)

    # ---- profile resolution -------------------------------------------
    def _expand(self, token: str, seen: set[str]) -> set[str]:
        if token.startswith("@tier:"):
            tier = token.split(":", 1)[1]
            return {m.id for m in self.mods.values() if m.tier == tier}
        if token.startswith("@profile:"):
            pid = token.split(":", 1)[1]
            if pid in seen:
                raise ManifestError(f"Profile include loop at {pid!r}")
            out: set[str] = set()
            for t in self.profile(pid).include:
                out |= self._expand(t, seen | {pid})
            return out
        self.mod(token)
        return {token}

    def resolve(
        self,
        profile_id: str | None = None,
        add: Iterable[str] = (),
        remove: Iterable[str] = (),
        swaps: dict[str, str] | None = None,
    ) -> list[Mod]:
        """Mods for a profile, plus/minus extras, with slot swaps applied, in install order."""
        pid = profile_id or self.default_profile
        ids: set[str] = set()
        for token in self.profile(pid).include:
            ids |= self._expand(token, {pid})
        ids |= {self.mod(a).id for a in add}
        ids -= set(remove)
        for old, new in (swaps or {}).items():
            a, b = self.mod(old), self.mod(new)
            if not a.slot or a.slot != b.slot:
                raise ManifestError(f"Cannot swap {old!r} for {new!r}: they do not share a slot")
            if old in ids:
                ids.discard(old)
                ids.add(new)
        return self.ordered(ids)


# ---------------------------------------------------------------------------
def _read_json(directory: Path | None, name: str) -> dict[str, Any]:
    try:
        if directory is not None:
            text = (Path(directory) / name).read_text(encoding="utf-8")
        else:
            text = resources.files(__package__).joinpath(name).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ManifestError(f"Manifest file not found: {name}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{name} is not valid JSON: {exc}") from None


def _mod_from(raw: dict[str, Any]) -> Mod:
    for key in ("id", "order", "tier", "layer", "name", "page", "archive", "install"):
        if key not in raw:
            raise ManifestError(f"Mod entry {raw.get('id', '?')!r} is missing {key!r}")
    inst = raw["install"]
    method = inst.get("method")
    if method not in METHODS:
        raise ManifestError(f"Mod {raw['id']!r}: unknown install method {method!r}")
    if raw["tier"] not in TIERS:
        raise ManifestError(f"Mod {raw['id']!r}: unknown tier {raw['tier']!r}")
    files = tuple(
        FileSpec(
            match=f["match"],
            to=f.get("to", "."),
            type=f.get("type", "file"),
            optional=bool(f.get("optional", False)),
        )
        for f in inst.get("files", [])
    )
    if method == "copy" and not files:
        raise ManifestError(f"Mod {raw['id']!r}: method 'copy' needs a 'files' list")
    if method == "run" and not inst.get("run"):
        raise ManifestError(f"Mod {raw['id']!r}: method 'run' needs a 'run' file name")
    for spec in files:
        if spec.type not in ("file", "dir"):
            raise ManifestError(f"Mod {raw['id']!r}: file spec type must be 'file' or 'dir'")
        if Path(spec.to).is_absolute() or ".." in Path(spec.to).parts:
            raise ManifestError(f"Mod {raw['id']!r}: 'to' must stay inside the game folder")
    return Mod(
        id=raw["id"],
        order=int(raw["order"]),
        tier=raw["tier"],
        layer=raw["layer"],
        name=raw["name"],
        author=raw.get("author", ""),
        version=raw.get("version", ""),
        source=raw.get("source", "direct"),
        page=raw["page"],
        archive=tuple(raw["archive"]),
        method=method,
        files=files,
        steps=tuple(inst.get("steps", [])),
        run=inst.get("run"),
        create_dirs=tuple(inst.get("createDirs", [])),
        conflicts=tuple(raw.get("conflicts", [])),
        slot=raw.get("slot"),
        replaces=raw.get("replaces"),
        warnings=tuple(raw.get("warnings", [])),
        requires=dict(raw.get("requires", {})),
        notes=raw.get("notes", ""),
    )


def load_manifest(directory: str | Path | None = None) -> Manifest:
    """Load the bundled manifest, or one from ``directory`` (for development/overrides)."""
    d = Path(directory) if directory else None
    mods_raw = _read_json(d, "mods.json")
    prof_raw = _read_json(d, "profiles.json")
    keys_raw = _read_json(d, "hotkeys.json")

    mods: dict[str, Mod] = {}
    orders: dict[int, str] = {}
    for raw in mods_raw.get("mods", []):
        mod = _mod_from(raw)
        if mod.id in mods:
            raise ManifestError(f"Duplicate mod id {mod.id!r}")
        if mod.order in orders:
            raise ManifestError(f"Mods {orders[mod.order]!r} and {mod.id!r} share order {mod.order}")
        mods[mod.id] = mod
        orders[mod.order] = mod.id
    mods = dict(sorted(mods.items(), key=lambda kv: kv[1].order))

    for mod in mods.values():
        if mod.replaces and mod.replaces not in mods:
            raise ManifestError(f"Mod {mod.id!r} replaces unknown mod {mod.replaces!r}")
        for w in mod.warnings:
            if w.get("with") not in mods:
                raise ManifestError(f"Mod {mod.id!r} has a warning about unknown mod {w.get('with')!r}")

    profiles = {
        p["id"]: Profile(
            id=p["id"],
            name=p.get("name", p["id"]),
            description=p.get("description", ""),
            include=tuple(p.get("include", [])),
            requires=dict(p.get("requires", {})),
        )
        for p in prof_raw.get("profiles", [])
    }
    default = prof_raw.get("default", next(iter(profiles), ""))
    if default not in profiles:
        raise ManifestError(f"Default profile {default!r} is not defined")

    for k in keys_raw.get("keys", []):
        if k.get("mod") not in mods:
            raise ManifestError(f"hotkeys.json refers to unknown mod {k.get('mod')!r}")

    manifest = Manifest(
        pack=mods_raw.get("pack", "Leonida V"),
        version=mods_raw.get("version", "0"),
        tested_build=mods_raw.get("testedGameBuild", ""),
        exe_names=tuple(mods_raw.get("gameExeNames", ["GTA5_Enhanced.exe"])),
        online_safe_items=tuple(mods_raw.get("onlineSafeItems", [])),
        prerequisites=tuple(mods_raw.get("prerequisites", [])),
        mods=mods,
        profiles=profiles,
        default_profile=default,
        hotkeys=tuple(keys_raw.get("keys", [])),
    )
    # Resolve every profile once so bad includes fail at load time.
    for pid in profiles:
        manifest.resolve(pid)
    return manifest
