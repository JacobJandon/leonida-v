"""Load and validate the Leonida V manifest (mods.json, profiles.json, hotkeys.json).

Editions: GTA V Enhanced and GTA V Legacy each have their own manifest set (most mods only run on one):
  enhanced: mods.json, profiles.json, hotkeys.json                    (GTA5_Enhanced.exe, builds 1.0.8xx-1.0.1xxx)
  legacy:   mods-legacy.json, profiles-legacy.json, hotkeys-legacy.json  (GTA5.exe, builds 1.0.3xxx)
``load_manifest(directory, edition)`` reads the set of that edition; the Session picks it from the game folder's exe.
Everything below (gameBuilds, whenSelected, freeRoute, member rules, ...) works the same in both sets.

Modpacks (optional modpacks.json / modpacks-legacy.json; without it every profile is a pack with the same id):
  {"default": "core",
   "categories": [{"id": "graphics", "name": "Graphics", "description": "..."}],
   "addons": [{"id": "interiors", "name": "Open interiors", "category": "world", "mods": ["enableallinteriors"],
               "description": "...", "picture": "https://..."}],
   "packs": [{"id": "plus", "name": "Leonida Plus", "description": "...", "picture": "https://...",
              "base": ["@profile:core", "mapupdates"],          # same tokens as a profile's include
              "defaultAddons": ["interiors"], "categories": ["graphics", "world"],   # [] = every category
              "requires": {"gpu": "rtx50"},
              "variants": [{"id": "balanced", "name": "Balanced", "description": "...", "addons": ["..."],
                            "settings": {...}}],               # settings: see "Locked settings"
              "defaultVariant": "balanced"}]}
  Every pack is also available as a profile with the same id (base + default add-ons), so profile-based code and old
  configs keep working. Unknown keys, unknown ids/mods/categories and add-ons outside the pack's categories are
  rejected.

mods.json schema (top level)
----------------------------
  "edition": "enhanced" | "legacy"                       optional; must match the file set it's in
  "pack", "version", "gameExeNames": [...] (default: the edition's exe), "prerequisites": [...], "onlineSafeItems": [...]
  "testedGameBuilds": ["1.0.1013.20", "1.0.1158.13"]   game builds the whole set was tested on (list)
  "testedGameBuild":  "1.0.1158.13"                     legacy single value; still read and merged in
  "mods": [ <mod>, ... ]

<mod> (required: id, order, tier, layer, name, page, archive, install)
  "id", "order" (unique int = install order), "tier" (core|optional|alternative|paid), "layer", "name",
  "author", "version", "source" (direct|github-release|nexus|nexus-login|discord|patreon|shop|...),
  "page" (https), "archive": ["glob*.zip", ...]  file-name patterns that identify the download,
  "install": {"method": copy|generic|run|guided|rpf, "files": [{"match", "to", "type": file|dir, "optional"}],
              "steps": [...], "run": "setup.exe", "createDirs": [...],
              "rpf": [...]},      method rpf: edits copies of game archives in mods/ (see leonida/rpf.py):
                                  {"archive": "update\\update.rpf", "put": <file in the download>, "to": <path inside>}
                                  {"archive": ..., "dlclist": "dlcpacks:/name/"}   adds the dlclist.xml line
                                  {"archive": ..., "xml": <path inside>, "edits": [{"type": add|replace|remove,
                                   "xpath": ..., "append": Last|First, "xml": "<Item/>"}]}
                                  {"archive": ..., "delete": <path inside>}
                                  {"oiv": "Install.oiv"}   applies an OpenIV package (glob over the download)
  "conflicts", "slot", "replaces", "warnings": [{"with": <mod id>, "message"}], "requires", "notes",
  "image": "https://..."                       preview picture on the author's page (fetched at runtime)
  "download": {"type": "github", "repo": "owner/name", "asset": "glob*.zip", "tag": "v1.2"}   tag optional
            | {"type": "direct", "url": "https://...", "file": "name.zip"}
            | {"type": "leonida", "package": "menu"}   Leonida's own files (leonida/menu): made locally, never fetched
            (omit -> the author's page opens in the app and the user clicks Download)
  "redistribution": {"allowed": true, "proof": "https://..."}   the author allows re-uploads (licence or written
            permission at the proof URL). Only then may a Leonida release/modpack carry the file itself; otherwise
            the modpack points at the author's own source. Omit = not allowed (the default for GTA mods).

Game-build compatibility (all optional; builds are dotted numbers like "1.0.1013.20", compared numerically,
bounds inclusive). The game can't always be updated, so every mod says which builds its versions support:
  "minGameBuild": "1.0.1013.17"   the top-level (latest) version needs at least this build; omit = any
  "maxGameBuild": "1.0.1158.99"   upper bound for the top-level version; omit = no known upper bound
  "gameBuilds": [                 other versions for builds outside min/max; the FIRST entry containing the build wins
      {"min": "1.0.889.0", "max": "1.0.1013.16",          both optional (open-ended)
       "version": "1.0.3411.0", "page": "https://...", "image": "https://...", "source": "...",
       "archive": ["..."], "download": {...}, "files": [...], "steps": [...], "run": "...",
       "createDirs": [...], "method": "copy", "notes": "..."},   any of these replace the top-level value
      {"min": "1.0.700.0", "max": "1.0.812.99",
       "unsupported": "No version of X works on this build: ..."}  this range can't run the mod at all
  ]
Resolution (``Mod.for_build``): build inside the top-level min/max -> the top-level mod; else the first
``gameBuilds`` entry containing it (overrides applied, ``variant`` = its index); else unsupported with the reason
"needs game build >= X" (or the entry's ``unsupported`` text). Unreadable build -> the top-level mod.
An entry that lies completely inside the top-level range is never used, so it is rejected at load time.

Archive contents and the author's version list (optional): tell the right edition's file from the wrong one when
their names can't (e.g. a Legacy build behind the same file name as the Enhanced one)
  "requireMembers": ["Enhanced/*", "*_g9/*"]   every pattern must match at least one file inside the archive
  "rejectMembers":  ["Legacy/*"]               no file inside the archive may match any pattern
    Patterns are globs over the archive's member paths ("folder/sub/file.ext", forward slashes), matched
    case-insensitively against the WHOLE path; "*" also crosses folders, so "*legacy/*" finds a Legacy folder at
    any depth and "Legacy/*" only at the top. A downloaded file that fails is not matched or installed and is
    reported as "wrong edition/version of <mod>: <reason>". Both keys are also allowed in gameBuilds entries and
    whenSelected/whenMissing overrides (they replace the top-level lists).
  "pick": {"versionLabel": "21.8.2 Enhanced"}  which entry of the author's "All Versions" list to download (exact
  "pick": {"versionMatch": "(?i)enhanced"}     label, case-insensitive) or the first whose label matches the regex;
                                               exactly one of the two. Also allowed in gameBuilds entries.

Locked settings (optional, "settings"; see leonida/settings.py and docs/SETTINGS.md): the config files a mod reads
and the keys Leonida writes and watches, with values per pack / variant / selection:
  "settings": [{"file": "ScriptHookVDotNet.ini", "format": "ini", "create": false,
                "keys": {"ReloadKeyBinding": {"value": "None", "whenSelected": {"enableallinteriors": "Insert"},
                                              "packs": {"showcase": "..."}, "variants": {"ultra": "..."},
                                              "why": "..."},
                         "ConsoleKeyBinding": "F4"}}]
  file: relative to the game folder; format: ini | xml | json (default from the extension); keys: ini "Section/Key"
  (or "Key"), xml "Child/Sub" or "Child/@attr", json "a/b/c". Also allowed in gameBuilds entries (replaces).

Free routes for paid mods (optional, "freeRoute"): how to get a paid mod's job done without paying. Leonida never
uses leaked, cracked or re-uploaded copies: every page/download here must be the author's own free release.
  {"type": "alternative", "mod": "<id>"}            use this free mod instead (must exist, can't itself be paid)
  {"type": "publicSince", "date": "YYYY-MM-DD", "page": "https://...", "download": {...},
   "version": "...", "archive": [...], "source": "direct"}   early access until that date, then the author's public
                                                    release: from that date the mod resolves like a free mod (its
                                                    top-level version takes this page/download/source/version/
                                                    archive; source defaults to "direct"). Only page is required.
  {"type": "freeEdition", "version": "...", "page": "https://...", "download": {...}, "archive": [...]}
                                                    an official free (lite/older) edition the author publishes;
                                                    shown to the user, the mod itself stays the paid version
  {"type": "none", "reason": "..."}                 no free route (yet), and why
Every type may also carry "notes". Unknown keys, missing required keys, bad dates and http pages are rejected.
The publicSince switch applies to the top-level version only (a gameBuilds variant keeps its own page), and is
part of ``for_build``, so it holds through re-resolution. ``Mod.is_paid`` is false once it has applied (the tier
stays "paid", so @tier:paid profile tokens keep working); ``Mod.free_since`` holds the date.

Selection-dependent values (optional): change how a mod installs depending on which OTHER mods the user selected
  "whenSelected": {"nve": {"files": [...], "steps": [...], "notes": "..."}}   applied when "nve" is in the selection
  "whenMissing":  {"nve": {"skip": "Not needed: NVE's onigiri folder does this job."}}   applied when it isn't
Keys allowed in each override: files, steps, warnings, method, run, createDirs, notes (each REPLACES the value),
or "skip": "<reason>" (optionally with notes) = the mod isn't needed with this selection: it is left out of the
install list, matching, checks and modpacks, and the GUI shows the reason. The selection is the profile plus the
user's additions/removals/swaps, BEFORE any skips. Conditions are applied after the game-build resolution, so they
also override a gameBuilds variant's values. Several matching conditions apply in file order (all whenSelected
entries, then all whenMissing entries); a later one wins for the same key. Mod ids must exist and can't be the
mod itself; unknown keys and empty overrides are rejected.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path
from typing import Any

TIERS = ("core", "optional", "alternative", "paid", "custom")  # custom: the user's own mods (custommods.py)
METHODS = ("copy", "generic", "run", "guided", "rpf")
_BUILD_RE = re.compile(r"^\d+(\.\d+){1,3}$")
# gameBuilds entry key -> Mod field it overrides
_OVERRIDES = {
    "version": "version", "page": "page", "image": "image", "source": "source", "archive": "archive",
    "download": "download", "files": "files", "steps": "steps", "run": "run", "createDirs": "create_dirs",
    "method": "method", "notes": "notes", "requireMembers": "require_members", "rejectMembers": "reject_members",
    "pick": "pick", "rpf": "rpf", "settings": "settings",
}
_ENTRY_KEYS = {"min", "max", "unsupported", *_OVERRIDES}
# freeRoute type -> (required keys, optional keys)
_FREE_ROUTES = {
    "alternative": ({"mod"}, {"notes"}),
    "publicSince": ({"date", "page"}, {"download", "version", "archive", "source", "notes"}),
    "freeEdition": ({"version", "page"}, {"download", "archive", "notes"}),
    "none": ({"reason"}, {"notes"}),
}


def _today() -> _dt.date:
    """Today's date (a function so tests can move the clock)."""
    return _dt.date.today()
# whenSelected/whenMissing override key -> Mod field
_COND_OVERRIDES = {
    "files": "files", "steps": "steps", "warnings": "warnings", "method": "method", "run": "run",
    "createDirs": "create_dirs", "notes": "notes", "skip": "not_needed",
    "requireMembers": "require_members", "rejectMembers": "reject_members", "rpf": "rpf",
}


class ManifestError(ValueError):
    """The manifest files are missing, malformed or inconsistent."""


# ------------------------------------------------------------------------------------------- game builds
def build_key(build: str | None) -> tuple[int, ...] | None:
    """Sortable key for a game build ("1.0.1013.20" -> (1, 0, 1013, 20)); None if unreadable."""
    nums = re.findall(r"\d+", str(build or ""))
    if not nums:
        return None
    key = [int(n) for n in nums[:4]]
    return tuple(key + [0] * (4 - len(key)))


def in_build_range(build: str | None, lo: str | None, hi: str | None) -> bool:
    key = build_key(build)
    if key is None:
        return False
    return (lo is None or key >= build_key(lo)) and (hi is None or key <= build_key(hi))


def _range_text(lo: str | None, hi: str | None) -> str:
    if lo and hi:
        return f"{lo} to {hi}"
    if lo:
        return f"{lo} or newer"
    if hi:
        return f"up to {hi}"
    return "any build"


@dataclass(frozen=True)
class FileSpec:
    match: str
    to: str = "."
    type: str = "file"  # "file" or "dir"
    optional: bool = False


@dataclass(frozen=True)
class GameBuild:
    """One ``gameBuilds`` entry: another version of the mod (overrides) or an unsupported range."""
    min: str | None = None
    max: str | None = None
    unsupported: str | None = None
    overrides: dict = field(default_factory=dict)  # Mod field name -> value

    @property
    def label(self) -> str:
        return _range_text(self.min, self.max)

    def contains(self, build: str | None) -> bool:
        return in_build_range(build, self.min, self.max)


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
    # Preview picture shown in the GUI chooser: a URL on the author's own page (fetched and cached at runtime,
    # never stored in this repo). None -> the GUI may try the page's og:image.
    image: str | None = None
    # How the kit may fetch the file at runtime, from the author's own release/page, into the user's Downloads:
    #   {"type": "github", "repo": "owner/name", "asset": "glob*.zip"[, "tag": "v1"]}  GitHub release asset
    #   {"type": "direct", "url": "https://...", "file": "name.zip"}    stable direct link the author publishes
    # None -> "browser": the user clicks Download on the author's page inside the app and the file is captured.
    download: dict | None = None
    # {"allowed": bool, "proof": "https://..."}: may Leonida re-host this file? (see the module docstring)
    redistribution: dict | None = None
    # Game-build compatibility (see the module docstring).
    min_game_build: str | None = None
    max_game_build: str | None = None
    game_builds: tuple[GameBuild, ...] = ()
    # Set by for_build(): why this mod can't run on that build (None = it can).
    unsupported: str | None = None
    # Set by for_build(): index of the gameBuilds entry in use (None = the top-level version).
    variant: int | None = None
    # Set by for_build(): the mod as written in mods.json, so resolving again always starts from it.
    base: Mod | None = field(default=None, repr=False, compare=False)
    # Selection-dependent values from mods.json: ((other mod id, {Mod field: value}), ...).
    when_selected: tuple[tuple[str, dict], ...] = ()
    when_missing: tuple[tuple[str, dict], ...] = ()
    # Set by for_selection(): conditions that applied ("+nve" = because nve is selected, "-nve" = because it isn't),
    # and why the mod isn't needed with this selection (None = it is needed).
    conditions: tuple[str, ...] = ()
    not_needed: str | None = None
    # Set by for_selection(): the selection it was resolved for and the mod before the conditions were applied.
    selection: frozenset | None = field(default=None, repr=False, compare=False)
    pre_selection: Mod | None = field(default=None, repr=False, compare=False)
    # How to get a paid mod for free (see the module docstring), and the date its publicSince route applied.
    free_route: dict | None = None
    free_since: str | None = None
    # Globs over the archive's member paths: all of require_members must match a member, none of reject_members
    # may (tells e.g. the Enhanced build from a Legacy one with the same file name). See the module docstring.
    require_members: tuple[str, ...] = ()
    reject_members: tuple[str, ...] = ()
    # Which entry of the author's "All Versions" list to download: {"versionLabel": ...} or {"versionMatch": ...}.
    pick: dict | None = None
    # Locked settings: [{"file", "format", "create", "keys": {path: rule}}] (see leonida/settings.py).
    settings: tuple[dict, ...] = ()
    # Method "rpf": edits to copies of game archives in mods\ (leonida/rpf.py; checked by rpf.check_ops).
    rpf: tuple[dict, ...] = ()

    @property
    def automatic(self) -> bool:
        """True when the app places the files itself (copy/generic)."""
        return self.method in ("copy", "generic")

    @property
    def manual_download(self) -> bool:
        return self.source in ("discord", "patreon", "shop", "nexus-login")

    @property
    def is_paid(self) -> bool:
        """Paid right now: tier "paid" and no publicSince date has passed yet."""
        return self.tier == "paid" and self.free_since is None

    @property
    def redistributable(self) -> bool:
        """True only when mods.json records the author's permission with a proof URL."""
        r = self.redistribution or {}
        return r.get("allowed") is True and str(r.get("proof", "")).startswith("https://")

    @property
    def supported_builds(self) -> str:
        """Human-readable build range of the top-level version."""
        src = self.base or self
        return _range_text(src.min_game_build, src.max_game_build)

    def for_build(self, build: str | None) -> Mod:
        """This mod as it applies to game ``build``: the top-level version, an older/other variant, or a copy with
        ``unsupported`` set. Unknown build -> the top-level version. Safe to call on an already resolved mod
        (a mod resolved for a selection keeps that selection's values)."""
        res = self._build_variant(build)
        return res.for_selection(self.selection) if self.selection is not None else res

    def for_selection(self, selected: Iterable[str]) -> Mod:
        """This mod with its whenSelected/whenMissing values applied for the selected mod ids (call it after
        ``for_build``). Safe to call again with another selection."""
        start = self.pre_selection or self
        if not start.when_selected and not start.when_missing:
            return start
        sel = frozenset(selected)
        values: dict = {}
        applied: list[str] = []
        for other, ov in start.when_selected:
            if other in sel:
                values.update(ov)
                applied.append("+" + other)
        for other, ov in start.when_missing:
            if other not in sel:
                values.update(ov)
                applied.append("-" + other)
        return replace(start, **values, conditions=tuple(applied), selection=sel,
                       base=start.base or start, pre_selection=start)

    def _build_variant(self, build: str | None) -> Mod:
        src = self.base or self
        if build_key(build) is None or in_build_range(build, src.min_game_build, src.max_game_build):
            return src._gone_public()
        for i, gb in enumerate(src.game_builds):
            if gb.contains(build):
                if gb.unsupported:
                    return replace(src, unsupported=gb.unsupported, variant=i, base=src)
                return replace(src, **gb.overrides, variant=i, base=src)
        lo, hi = src.min_game_build, src.max_game_build
        key = build_key(build)
        if lo and key < build_key(lo):
            reason = f"{src.name} needs game build {lo} or newer (this game is {build})."
        else:
            reason = f"{src.name} supports game builds up to {hi} so far (this game is {build})."
        return replace(src, unsupported=reason, base=src)

    def _gone_public(self) -> Mod:
        """The top-level version switched to its author's public release once a publicSince date has passed."""
        fr = self.free_route or {}
        if fr.get("type") != "publicSince" or _dt.date.fromisoformat(fr["date"]) > _today():
            return self
        values: dict = {"page": fr["page"], "download": dict(fr["download"]) if fr.get("download") else None,
                        "source": fr.get("source", "direct"), "free_since": fr["date"]}
        if fr.get("version"):
            values["version"] = fr["version"]
        if fr.get("archive"):
            values["archive"] = tuple(fr["archive"])
        return replace(self, **values, base=self.base or self)


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    description: str
    include: tuple[str, ...]
    requires: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class Addon:
    id: str
    name: str
    category: str
    mods: tuple[str, ...]
    description: str = ""
    picture: str | None = None


@dataclass(frozen=True)
class Variant:
    id: str
    name: str
    description: str = ""
    addons: tuple[str, ...] = ()            # extra add-ons this variant turns on
    settings: dict = field(default_factory=dict)
    requires: dict = field(default_factory=dict)   # {"gpu": "rtx" | "rtx50"}: what the PC needs (a recommendation)


@dataclass(frozen=True)
class Pack:
    id: str
    name: str
    description: str
    base: tuple[str, ...]                   # profile-style tokens: mod ids, @tier:x, @profile:x
    default_addons: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()        # add-on categories offered with this pack; () = all
    picture: str | None = None
    requires: dict = field(default_factory=dict)
    variants: tuple[Variant, ...] = ()
    default_variant: str | None = None

    def variant(self, variant_id: str | None) -> Variant | None:
        vid = variant_id or self.default_variant
        return next((v for v in self.variants if v.id == vid), None)


@dataclass
class Manifest:
    pack: str
    version: str
    tested_build: str                      # newest tested build (kept for display/back-compat)
    exe_names: tuple[str, ...]
    online_safe_items: tuple[str, ...]
    prerequisites: tuple[dict, ...]
    mods: dict[str, Mod]
    profiles: dict[str, Profile]
    default_profile: str
    hotkeys: tuple[dict, ...]
    tested_builds: tuple[str, ...] = ()    # every build the set was tested on
    game_build: str | None = None          # set by for_build(): the build the mods are resolved for
    edition: str = "enhanced"              # "enhanced" / "legacy": which game this mod list is for
    packs: dict[str, Pack] = field(default_factory=dict)
    addons: dict[str, Addon] = field(default_factory=dict)
    categories: dict[str, Category] = field(default_factory=dict)
    default_pack: str = ""
    source_profiles: dict[str, Profile] = field(default_factory=dict)  # profiles.json as written (no packs)

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

    # ---- game builds ---------------------------------------------------
    def for_build(self, build: str | None) -> Manifest:
        """A copy whose mods are all resolved for game ``build`` (see ``Mod.for_build``)."""
        return replace(self, mods={k: m.for_build(build) for k, m in self.mods.items()}, game_build=build)

    def for_selection(self, selected: Iterable[str]) -> Manifest:
        """A copy whose mods have their whenSelected/whenMissing values applied for these selected mod ids."""
        sel = frozenset(selected)
        return replace(self, mods={k: m.for_selection(sel) for k, m in self.mods.items()})

    def free_route_text(self, mod_id: str) -> str:
        """One line on how to get this mod for free (or that there's no free route)."""
        m = self.mod(mod_id)
        fr = m.free_route
        if m.free_since:
            return f"free since {m.free_since} (the author's public release)"
        if not fr:
            return "no free route recorded yet"
        kind = fr["type"]
        if kind == "alternative":
            alt = self.mods.get(fr["mod"])
            return f"use the free {alt.name if alt else fr['mod']} instead"
        if kind == "publicSince":
            return f"goes public on {fr['date']} ({fr['page']}); Leonida switches to it by itself then"
        if kind == "freeEdition":
            return f"official free edition {fr['version']}: {fr['page']}"
        return f"none ({fr['reason']})"

    def is_tested(self, build: str | None) -> bool:
        key = build_key(build)
        return key is not None and any(build_key(t) == key for t in self.tested_builds)

    def newer_than_tested(self, build: str | None) -> bool:
        key = build_key(build)
        keys = [build_key(t) for t in self.tested_builds]
        return key is not None and bool(keys) and all(key > k for k in keys)

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
            # profiles.json's own profile first: a pack with the same id is built on top of it
            prof = self.source_profiles.get(pid) or self.profile(pid)
            for t in prof.include:
                out |= self._expand(t, seen | {pid})
            return out
        self.mod(token)
        return {token}

    # ---- packs -----------------------------------------------------------
    def get_pack(self, pack_id: str) -> Pack:
        try:
            return self.packs[pack_id]
        except KeyError:
            raise ManifestError(f"Unknown modpack: {pack_id!r}. Known: {', '.join(self.packs)}") from None

    def addons_for(self, pack_id: str) -> dict[str, list[Addon]]:
        """The add-ons offered with a pack, by category id (in the categories' order)."""
        pack = self.get_pack(pack_id)
        allowed = pack.categories or tuple(self.categories)
        out: dict[str, list[Addon]] = {c: [] for c in allowed}
        for a in self.addons.values():
            if a.category in out:
                out[a.category].append(a)
        return {c: lst for c, lst in out.items() if lst}

    def pack_mod_ids(self, pack_id: str, addons: Iterable[str] | None = None, variant: str | None = None) -> set[str]:
        """Mod ids of a pack: its base, the chosen add-ons (None = its defaults) and its variant's add-ons."""
        pack = self.get_pack(pack_id)
        ids: set[str] = set()
        for token in pack.base:  # @profile:<its own id> means profiles.json's profile, not a loop
            ids |= self._expand(token, set())
        chosen = list(pack.default_addons if addons is None else addons)
        v = pack.variant(variant)
        if v is not None:
            chosen += list(v.addons)
        for aid in chosen:
            if aid in self.addons:  # an add-on that no longer exists is skipped
                ids |= set(self.addons[aid].mods)
        return ids

    def resolve_pack(self, pack_id: str | None = None, addons: Iterable[str] | None = None,
                     variant: str | None = None, add: Iterable[str] = (), remove: Iterable[str] = (),
                     swaps: dict[str, str] | None = None) -> list[Mod]:
        """Mods for a pack with the chosen add-ons and variant, plus/minus extras and swaps, in install order.
        A plain profile id (not a pack) resolves like ``resolve``."""
        pid = pack_id or self.default_pack or self.default_profile
        if pid not in self.packs:
            return self.resolve(pid, add, remove, swaps)
        return self._apply_choice(self.pack_mod_ids(pid, addons, variant), add, remove, swaps)

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
        return self._apply_choice(ids, add, remove, swaps)

    def _apply_choice(self, ids: set[str], add: Iterable[str], remove: Iterable[str],
                      swaps: dict[str, str] | None) -> list[Mod]:
        ids = set(ids)
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


def _check_build(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _BUILD_RE.match(value.strip()):
        raise ManifestError(f"{where}: game build must look like '1.0.1013.20', got {value!r}")
    return value.strip()


def _check_range(lo: str | None, hi: str | None, where: str) -> None:
    if lo and hi and build_key(lo) > build_key(hi):
        raise ManifestError(f"{where}: min {lo} is greater than max {hi}")


def _parse_files(raw_files: Any, where: str) -> tuple[FileSpec, ...]:
    if not isinstance(raw_files, list):
        raise ManifestError(f"{where}: 'files' must be a list")
    files = []
    for f in raw_files:
        if not isinstance(f, dict) or not f.get("match"):
            raise ManifestError(f"{where}: every file spec needs a 'match'")
        spec = FileSpec(match=f["match"], to=f.get("to", "."), type=f.get("type", "file"),
                        optional=bool(f.get("optional", False)))
        if spec.type not in ("file", "dir"):
            raise ManifestError(f"{where}: file spec type must be 'file' or 'dir'")
        if Path(spec.to).is_absolute() or ".." in Path(spec.to).parts:
            raise ManifestError(f"{where}: 'to' must stay inside the game folder")
        files.append(spec)
    return tuple(files)


def _check_download(dl: Any, where: str) -> dict | None:
    if dl is None:
        return None
    kind = dl.get("type") if isinstance(dl, dict) else None
    if kind == "github":
        if not dl.get("repo") or not dl.get("asset"):
            raise ManifestError(f"{where}: github download needs 'repo' and 'asset'")
        if "tag" in dl and (not isinstance(dl["tag"], str) or not dl["tag"].strip()):
            raise ManifestError(f"{where}: github download 'tag' must be a non-empty string")
    elif kind == "direct":
        if not str(dl.get("url", "")).startswith("https://") or not dl.get("file"):
            raise ManifestError(f"{where}: direct download needs an https 'url' and a 'file' name")
    elif kind == "leonida":   # Leonida's own files (the in-game menu): made locally, never fetched
        if dl.get("package") not in ("menu",):
            raise ManifestError(f"{where}: leonida download needs 'package': 'menu'")
    else:
        raise ManifestError(f"{where}: download type must be 'github', 'direct' or 'leonida'")
    return dict(dl)


def _check_https(value: Any, what: str, where: str) -> str | None:
    if value is None:
        return None
    if not str(value).startswith("https://"):
        raise ManifestError(f"{where}: {what} must be an https URL")
    return str(value)


def _check_redistribution(value: Any, where: str) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("allowed"), bool):
        raise ManifestError(f"{where}: redistribution must be {{\"allowed\": true|false, \"proof\": \"https://...\"}}")
    unknown = set(value) - {"allowed", "proof", "notes"}
    if unknown:
        raise ManifestError(f"{where}: redistribution has unknown key(s) {', '.join(sorted(unknown))}")
    if value["allowed"] and not str(value.get("proof", "")).startswith("https://"):
        raise ManifestError(f"{where}: redistribution allowed needs an https 'proof' URL (licence or permission)")
    return dict(value)


_SCALAR = (str, int, float, bool)


def _check_settings(value: Any, where: str) -> tuple[dict, ...]:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{where}: 'settings' must be a non-empty list of files")
    out = []
    for spec in value:
        w = f"{where} settings[{spec.get('file', '?') if isinstance(spec, dict) else '?'!r}]"
        if not isinstance(spec, dict):
            raise ManifestError(f"{w}: must be an object")
        unknown = set(spec) - {"file", "format", "create", "keys"}
        if unknown:
            raise ManifestError(f"{w}: unknown key(s) {', '.join(sorted(unknown))}")
        file = spec.get("file")
        if not isinstance(file, str) or not file.strip():
            raise ManifestError(f"{w}: 'file' is required")
        file = file.replace("\\", "/")
        if Path(file).is_absolute() or ".." in Path(file).parts:
            raise ManifestError(f"{w}: 'file' must stay inside the game folder")
        fmt = spec.get("format")
        if fmt is not None and fmt not in ("ini", "xml", "json"):
            raise ManifestError(f"{w}: format must be ini, xml or json")
        if not isinstance(spec.get("create", False), bool):
            raise ManifestError(f"{w}: 'create' must be true or false")
        keys = spec.get("keys")
        if not isinstance(keys, dict) or not keys:
            raise ManifestError(f"{w}: 'keys' must name at least one key")
        for k, rule in keys.items():
            kw = f"{w} key {k!r}"
            if not isinstance(k, str) or not k.strip() or k.startswith("/") or k.endswith("/"):
                raise ManifestError(f"{kw}: not a valid key path")
            if isinstance(rule, _SCALAR):
                continue
            if not isinstance(rule, dict):
                raise ManifestError(f"{kw}: give a value or {{\"value\": ..., \"packs\": ..., \"variants\": ...}}")
            bad = set(rule) - {"value", "packs", "variants", "whenSelected", "why", "choices"}
            if bad:
                raise ManifestError(f"{kw}: unknown key(s) {', '.join(sorted(bad))}")
            if "choices" in rule and (not isinstance(rule["choices"], list) or not rule["choices"]
                                      or not all(isinstance(x, _SCALAR) for x in rule["choices"])):
                raise ManifestError(f"{kw}: 'choices' must list the values a player may pick")
            if not set(rule) & {"value", "packs", "variants", "whenSelected"}:
                raise ManifestError(f"{kw}: give a value")
            if "value" in rule and not isinstance(rule["value"], _SCALAR):
                raise ManifestError(f"{kw}: 'value' must be text, a number or true/false")
            for sub in ("packs", "variants", "whenSelected"):
                m = rule.get(sub, {})
                if not isinstance(m, dict) or not all(isinstance(x, _SCALAR) for x in m.values()):
                    raise ManifestError(f"{kw}: {sub!r} must map ids to values")
            if not isinstance(rule.get("why", ""), str):
                raise ManifestError(f"{kw}: 'why' must be text")
        out.append({**spec, "file": file})
    return tuple(out)


def _check_pick(value: Any, where: str) -> dict:
    if not isinstance(value, dict) or len(value) != 1 or not set(value) <= {"versionLabel", "versionMatch"}:
        raise ManifestError(f"{where}: pick must be {{\"versionLabel\": \"...\"}} or {{\"versionMatch\": \"regex\"}}")
    (key, text), = value.items()
    if not isinstance(text, str) or not text.strip():
        raise ManifestError(f"{where}: pick {key!r} must be a non-empty string")
    if key == "versionMatch":
        try:
            re.compile(text)
        except re.error as exc:
            raise ManifestError(f"{where}: pick versionMatch is not a valid regex: {exc}") from None
    return {key: text.strip() if key == "versionLabel" else text}


def _check_free_route(value: Any, mod_id: str) -> dict | None:
    if value is None:
        return None
    where = f"Mod {mod_id!r} freeRoute"
    kind = value.get("type") if isinstance(value, dict) else None
    if kind not in _FREE_ROUTES:
        raise ManifestError(f"{where}: type must be one of {', '.join(_FREE_ROUTES)}")
    required, optional = _FREE_ROUTES[kind]
    missing = required - set(value)
    if missing:
        raise ManifestError(f"{where}: a {kind!r} route needs {', '.join(sorted(missing))}")
    unknown = set(value) - required - optional - {"type"}
    if unknown:
        raise ManifestError(f"{where}: unknown key(s) {', '.join(sorted(unknown))} for a {kind!r} route")
    out = dict(value)
    for key in ("mod", "reason", "version", "source", "notes"):
        if key in out and (not isinstance(out[key], str) or not out[key].strip()):
            raise ManifestError(f"{where}: {key!r} must be a non-empty string")
    if "date" in out:
        if not isinstance(out["date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", out["date"]):
            raise ManifestError(f"{where}: date must be YYYY-MM-DD")
        try:
            _dt.date.fromisoformat(out["date"])
        except ValueError:
            raise ManifestError(f"{where}: {out['date']} is not a real date") from None
    if "page" in out:
        _check_https(out["page"], "page", where)
    if "download" in out:
        out["download"] = _check_download(out["download"], where)
    arch = out.get("archive", ["ok"])
    if not isinstance(arch, list) or not arch or not all(isinstance(a, str) for a in arch):
        raise ManifestError(f"{where}: 'archive' must be a non-empty list of strings")
    if kind == "alternative" and out["mod"] == mod_id:
        raise ManifestError(f"{where}: a mod can't be its own free alternative")
    return out


def _parse_rpf(v: Any, where: str) -> tuple[dict, ...]:
    from ..rpf import check_ops

    try:
        check_ops(v, where)
    except ValueError as exc:
        raise ManifestError(str(exc)) from None
    return tuple(dict(op) for op in v)


def _check_install(method: str, files: tuple, run: str | None, where: str, rpf: tuple = ()) -> None:
    if method not in METHODS:
        raise ManifestError(f"{where}: unknown install method {method!r}")
    if method == "rpf" and not rpf:
        raise ManifestError(f"{where}: method 'rpf' needs an 'rpf' list (archive edits or an .oiv)")
    if method == "copy" and not files:
        raise ManifestError(f"{where}: method 'copy' needs a 'files' list")
    if method == "run" and not run:
        raise ManifestError(f"{where}: method 'run' needs a 'run' file name")


def _parse_override(key: str, v: Any, where: str) -> Any:
    """Validate one override value (gameBuilds entry or whenSelected/whenMissing) and convert it."""
    if key in ("page", "image"):
        return _check_https(v, key, where)
    if key == "download":
        return _check_download(v, where)
    if key == "files":
        return _parse_files(v, where)
    if key in ("archive", "steps", "createDirs", "requireMembers", "rejectMembers"):
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ManifestError(f"{where}: {key!r} must be a list of strings")
        if key in ("archive", "requireMembers", "rejectMembers") and (not v or not all(x.strip() for x in v)):
            raise ManifestError(f"{where}: {key!r} can't be empty or hold empty patterns")
        if key in ("requireMembers", "rejectMembers"):
            return tuple(x.strip().replace("\\", "/") for x in v)
        return tuple(v)
    if key == "pick":
        return _check_pick(v, where)
    if key == "settings":
        return _check_settings(v, where)
    if key == "rpf":
        return _parse_rpf(v, where)
    if key == "warnings":
        if not isinstance(v, list) or not all(isinstance(w, dict) and isinstance(w.get("with"), str)
                                              and isinstance(w.get("message"), str) for w in v):
            raise ManifestError(f"{where}: 'warnings' must be a list of {{\"with\": <mod id>, \"message\": ...}}")
        return tuple(dict(w) for w in v)
    if key == "skip" and (not isinstance(v, str) or not v.strip()):
        raise ManifestError(f"{where}: 'skip' must be a non-empty reason")
    if not isinstance(v, str):
        raise ManifestError(f"{where}: {key!r} must be a string")
    return v.strip() if key == "skip" else v


def _parse_conditions(raw: Any, base: Mod, name: str) -> tuple[tuple[str, dict], ...]:
    if raw is None:
        return ()
    where = f"Mod {base.id!r} {name}"
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: must be an object {{\"<mod id>\": {{...}}}}")
    out = []
    for other, values in raw.items():
        w = f"{where}[{other!r}]"
        if other == base.id:
            raise ManifestError(f"{w}: a mod can't depend on itself")
        if not isinstance(values, dict) or not values:
            raise ManifestError(f"{w}: give the values to use (files, steps, warnings, method, run, createDirs, "
                                "notes) or a 'skip' reason")
        unknown = set(values) - set(_COND_OVERRIDES)
        if unknown:
            raise ManifestError(f"{w}: unknown key(s) {', '.join(sorted(unknown))}")
        if "skip" in values and set(values) - {"skip", "notes"}:
            raise ManifestError(f"{w}: a 'skip' can't also override install values")
        ov = {_COND_OVERRIDES[k]: _parse_override(k, v, w) for k, v in values.items()}
        _check_install(ov.get("method", base.method), ov.get("files", base.files), ov.get("run", base.run), w,
                       ov.get("rpf", base.rpf))
        out.append((other, ov))
    return tuple(out)


def _parse_game_build(raw: Any, base: Mod, index: int) -> GameBuild:
    where = f"Mod {base.id!r} gameBuilds[{index}]"
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: must be an object")
    unknown = set(raw) - _ENTRY_KEYS
    if unknown:
        raise ManifestError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    lo, hi = _check_build(raw.get("min"), where), _check_build(raw.get("max"), where)
    _check_range(lo, hi, where)
    # never used if the top-level version already covers the whole range
    top_lo, top_hi = base.min_game_build, base.max_game_build
    covers_lo = top_lo is None or (lo is not None and build_key(lo) >= build_key(top_lo))
    covers_hi = top_hi is None or (hi is not None and build_key(hi) <= build_key(top_hi))
    if covers_lo and covers_hi:
        raise ManifestError(
            f"{where}: range {_range_text(lo, hi)} lies inside the top-level range "
            f"({_range_text(top_lo, top_hi)}), so it would never be used. Set minGameBuild/maxGameBuild."
        )
    if "unsupported" in raw:
        text = raw["unsupported"]
        if not isinstance(text, str) or not text.strip():
            raise ManifestError(f"{where}: 'unsupported' must be a non-empty reason")
        if set(raw) - {"min", "max", "unsupported", "notes"}:
            raise ManifestError(f"{where}: an 'unsupported' entry can't also override mod values")
        return GameBuild(lo, hi, unsupported=text.strip())
    ov = {attr: _parse_override(key, raw[key], where) for key, attr in _OVERRIDES.items() if key in raw}
    if not ov:
        raise ManifestError(f"{where}: give the values that differ for this build (version, page, archive, ...) "
                            "or an 'unsupported' reason")
    _check_install(ov.get("method", base.method), ov.get("files", base.files), ov.get("run", base.run), where,
                   ov.get("rpf", base.rpf))
    return GameBuild(lo, hi, overrides=ov)


def _mod_from(raw: dict[str, Any]) -> Mod:
    for key in ("id", "order", "tier", "layer", "name", "page", "archive", "install"):
        if key not in raw:
            raise ManifestError(f"Mod entry {raw.get('id', '?')!r} is missing {key!r}")
    where = f"Mod {raw['id']!r}"
    inst = raw["install"]
    method = inst.get("method")
    if raw["tier"] not in TIERS:
        raise ManifestError(f"{where}: unknown tier {raw['tier']!r}")
    files = _parse_files(inst.get("files", []), where)
    rpf = _parse_rpf(inst["rpf"], where) if "rpf" in inst else ()
    _check_install(method, files, inst.get("run"), where, rpf)
    lo = _check_build(raw.get("minGameBuild"), where)
    hi = _check_build(raw.get("maxGameBuild"), where)
    _check_range(lo, hi, where)
    mod = Mod(
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
        rpf=rpf,
        conflicts=tuple(raw.get("conflicts", [])),
        slot=raw.get("slot"),
        replaces=raw.get("replaces"),
        warnings=tuple(raw.get("warnings", [])),
        requires=dict(raw.get("requires", {})),
        notes=raw.get("notes", ""),
        image=_check_https(raw.get("image"), "image", where),
        download=_check_download(raw.get("download"), where),
        redistribution=_check_redistribution(raw.get("redistribution"), where),
        free_route=_check_free_route(raw.get("freeRoute"), raw["id"]),
        require_members=_parse_override("requireMembers", raw["requireMembers"], where) if "requireMembers" in raw else (),
        reject_members=_parse_override("rejectMembers", raw["rejectMembers"], where) if "rejectMembers" in raw else (),
        pick=_check_pick(raw["pick"], where) if "pick" in raw else None,
        settings=_check_settings(raw["settings"], where) if "settings" in raw else (),
        min_game_build=lo,
        max_game_build=hi,
    )
    ws = _parse_conditions(raw.get("whenSelected"), mod, "whenSelected")
    wm = _parse_conditions(raw.get("whenMissing"), mod, "whenMissing")
    if ws or wm:
        mod = replace(mod, when_selected=ws, when_missing=wm)
    entries = raw.get("gameBuilds", [])
    if not isinstance(entries, list):
        raise ManifestError(f"{where}: 'gameBuilds' must be a list")
    if entries:
        mod = replace(mod, game_builds=tuple(_parse_game_build(e, mod, i) for i, e in enumerate(entries)))
    return mod


EDITIONS = ("enhanced", "legacy")
EDITION_EXES = {"enhanced": ("GTA5_Enhanced.exe",), "legacy": ("GTA5.exe",)}


def manifest_files(edition: str = "enhanced") -> tuple[str, str, str]:
    """(mods, profiles, hotkeys) file names of an edition's manifest set."""
    if edition not in EDITIONS:
        raise ManifestError(f"Unknown edition {edition!r}: use one of {', '.join(EDITIONS)}")
    suffix = "" if edition == "enhanced" else f"-{edition}"
    return f"mods{suffix}.json", f"profiles{suffix}.json", f"hotkeys{suffix}.json"


def load_manifest(directory: str | Path | None = None, edition: str = "enhanced") -> Manifest:
    """Load the bundled manifest set of ``edition``, or the one in ``directory`` (for development/overrides)."""
    d = Path(directory) if directory else None
    mods_file, prof_file, keys_file = manifest_files(edition)
    mods_raw = _read_json(d, mods_file)
    prof_raw = _read_json(d, prof_file)
    keys_raw = _read_json(d, keys_file)
    declared = mods_raw.get("edition", edition)
    if declared != edition:
        raise ManifestError(f"{mods_file} says it is for edition {declared!r}, but it is the {edition} file set")

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
        for spec in mod.settings:
            for k, rule in spec["keys"].items():
                for other in (rule.get("whenSelected", {}) if isinstance(rule, dict) else {}):
                    if other not in mods:
                        raise ManifestError(f"Mod {mod.id!r} settings {spec['file']!r} {k!r}: whenSelected refers to "
                                            f"unknown mod {other!r}")
        fr = mod.free_route or {}
        if fr.get("type") == "alternative":
            alt = mods.get(fr["mod"])
            if alt is None:
                raise ManifestError(f"Mod {mod.id!r} freeRoute: unknown alternative mod {fr['mod']!r}")
            if alt.tier == "paid":
                raise ManifestError(f"Mod {mod.id!r} freeRoute: the alternative {alt.id!r} is paid too")
        for name, conds in (("whenSelected", mod.when_selected), ("whenMissing", mod.when_missing)):
            for other, ov in conds:
                if other not in mods:
                    raise ManifestError(f"Mod {mod.id!r} {name} refers to unknown mod {other!r}")
                for w in ov.get("warnings", ()):
                    if w.get("with") not in mods:
                        raise ManifestError(f"Mod {mod.id!r} {name}[{other!r}] has a warning about unknown mod "
                                            f"{w.get('with')!r}")

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

    source_profiles = dict(profiles)
    packs, addons, categories, default_pack = _load_packs(d, edition, mods, profiles, default)

    for k in keys_raw.get("keys", []):
        if k.get("mod") not in mods:
            raise ManifestError(f"hotkeys.json refers to unknown mod {k.get('mod')!r}")

    tested_raw = mods_raw.get("testedGameBuilds", [])
    if not isinstance(tested_raw, list):
        raise ManifestError("testedGameBuilds must be a list of game builds")
    tested = [_check_build(t, "testedGameBuilds") for t in tested_raw]
    legacy = _check_build(mods_raw.get("testedGameBuild"), "testedGameBuild")
    if legacy and all(build_key(legacy) != build_key(t) for t in tested):
        tested.append(legacy)
    tested.sort(key=build_key)

    manifest = Manifest(
        pack=mods_raw.get("pack", "Leonida V"),
        version=mods_raw.get("version", "0"),
        tested_build=tested[-1] if tested else "",
        exe_names=tuple(mods_raw.get("gameExeNames", list(EDITION_EXES[edition]))),
        online_safe_items=tuple(mods_raw.get("onlineSafeItems", [])),
        prerequisites=tuple(mods_raw.get("prerequisites", [])),
        mods=mods,
        profiles=profiles,
        default_profile=default,
        hotkeys=tuple(keys_raw.get("keys", [])),
        tested_builds=tuple(tested),
        edition=edition,
        packs=packs,
        addons=addons,
        categories=categories,
        default_pack=default_pack,
        source_profiles=source_profiles,
    )
    for pk in packs.values():  # every pack is a profile too: its mods with the default add-ons
        ids = manifest.pack_mod_ids(pk.id)
        manifest.profiles[pk.id] = Profile(pk.id, pk.name, pk.description,
                                           tuple(m.id for m in manifest.ordered(ids)), dict(pk.requires))
    if default_pack in manifest.profiles:
        manifest.default_profile = default_pack
    # Resolve every profile and pack (with every variant) once so bad includes fail at load time.
    for pid in profiles:
        manifest.resolve(pid)
    for pk in packs.values():
        for v in (None, *[v.id for v in pk.variants]):
            manifest.resolve_pack(pk.id, variant=v)
    return manifest


def packs_file(edition: str = "enhanced") -> str:
    manifest_files(edition)
    return "modpacks.json" if edition == "enhanced" else f"modpacks-{edition}.json"


def _strict(obj: Any, allowed: set[str], required: set[str], where: str) -> dict:
    if not isinstance(obj, dict):
        raise ManifestError(f"{where}: must be an object")
    unknown = set(obj) - allowed
    if unknown:
        raise ManifestError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    missing = required - set(obj)
    if missing:
        raise ManifestError(f"{where}: missing {', '.join(sorted(missing))}")
    for k in required:
        if isinstance(obj[k], str) and not obj[k].strip():
            raise ManifestError(f"{where}: {k!r} can't be empty")
    return obj


def _id_list(value: Any, where: str, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ManifestError(f"{where}: {key!r} must be a list of ids")
    return tuple(value)


def _load_packs(d: Path | None, edition: str, mods: dict[str, Mod], profiles: dict[str, Profile], default: str):
    """(packs, addons, categories, default pack) from the edition's modpacks file, or one pack per profile."""
    name = packs_file(edition)
    try:
        raw = _read_json(d, name)
    except ManifestError as exc:
        if "not found" not in str(exc):
            raise
        packs = {p.id: Pack(p.id, p.name, p.description, p.include, requires=dict(p.requires))
                 for p in profiles.values()}
        return packs, {}, {}, default
    _strict(raw, {"default", "categories", "addons", "packs"}, {"packs"}, name)
    categories: dict[str, Category] = {}
    for c in raw.get("categories", []):
        c = _strict(c, {"id", "name", "description"}, {"id", "name"}, f"{name} category")
        if c["id"] in categories:
            raise ManifestError(f"{name}: duplicate category {c['id']!r}")
        categories[c["id"]] = Category(c["id"], c["name"], c.get("description", ""))
    addons: dict[str, Addon] = {}
    for a in raw.get("addons", []):
        where = f"{name} add-on {a.get('id', '?') if isinstance(a, dict) else '?'!r}"
        a = _strict(a, {"id", "name", "category", "mods", "description", "picture"}, {"id", "name", "category", "mods"},
                    where)
        if a["id"] in addons:
            raise ManifestError(f"{name}: duplicate add-on {a['id']!r}")
        if a["category"] not in categories:
            raise ManifestError(f"{where}: unknown category {a['category']!r}")
        amods = _id_list(a["mods"], where, "mods")
        if not amods:
            raise ManifestError(f"{where}: 'mods' can't be empty")
        for m in amods:
            if m not in mods:
                raise ManifestError(f"{where}: unknown mod {m!r}")
        addons[a["id"]] = Addon(a["id"], a["name"], a["category"], amods, a.get("description", ""),
                                _check_https(a.get("picture"), "picture", where))
    packs: dict[str, Pack] = {}
    for pk in raw["packs"]:
        where = f"{name} pack {pk.get('id', '?') if isinstance(pk, dict) else '?'!r}"
        pk = _strict(pk, {"id", "name", "description", "picture", "base", "defaultAddons", "categories", "requires",
                          "variants", "defaultVariant"}, {"id", "name", "base"}, where)
        if pk["id"] in packs:
            raise ManifestError(f"{name}: duplicate pack {pk['id']!r}")
        cats = _id_list(pk.get("categories"), where, "categories")
        for c in cats:
            if c not in categories:
                raise ManifestError(f"{where}: unknown category {c!r}")

        def check_addons(ids: tuple[str, ...], w: str, cats=cats) -> tuple[str, ...]:
            for aid in ids:
                if aid not in addons:
                    raise ManifestError(f"{w}: unknown add-on {aid!r}")
                if cats and addons[aid].category not in cats:
                    raise ManifestError(f"{w}: add-on {aid!r} is in category {addons[aid].category!r}, which this "
                                        "pack doesn't offer")
            return ids

        variants = []
        for v in pk.get("variants", []):
            vw = f"{where} variant {v.get('id', '?') if isinstance(v, dict) else '?'!r}"
            v = _strict(v, {"id", "name", "description", "addons", "settings", "requires"}, {"id", "name"}, vw)
            if not isinstance(v.get("requires", {}), dict):
                raise ManifestError(f"{vw}: 'requires' must be an object")
            vset = v.get("settings", {})
            if not isinstance(vset, dict):
                raise ManifestError(f"{vw}: 'settings' must be an object")
            for mid, files in vset.items():  # {"<mod id>": {"<file>": {"<key>": value}}}
                if mid not in mods:
                    raise ManifestError(f"{vw}: settings for unknown mod {mid!r}")
                if not isinstance(files, dict) or not all(
                        isinstance(keys, dict) and all(isinstance(x, _SCALAR) for x in keys.values())
                        for keys in files.values()):
                    raise ManifestError(f"{vw}: settings must be {{\"<mod>\": {{\"<file>\": {{\"<key>\": value}}}}}}")
            variants.append(Variant(v["id"], v["name"], v.get("description", ""),
                                    check_addons(_id_list(v.get("addons"), vw, "addons"), vw), dict(v.get("settings", {})),
                                    dict(v.get("requires", {}))))
        if len({v.id for v in variants}) != len(variants):
            raise ManifestError(f"{where}: duplicate variant ids")
        dv = pk.get("defaultVariant")
        if dv is not None and dv not in {v.id for v in variants}:
            raise ManifestError(f"{where}: defaultVariant {dv!r} isn't one of its variants")
        base = _id_list(pk["base"], where, "base")
        if not isinstance(pk.get("requires", {}), dict):
            raise ManifestError(f"{where}: 'requires' must be an object")
        packs[pk["id"]] = Pack(pk["id"], pk["name"], pk.get("description", ""), base,
                               check_addons(_id_list(pk.get("defaultAddons"), where, "defaultAddons"), where),
                               cats, _check_https(pk.get("picture"), "picture", where), dict(pk.get("requires", {})),
                               tuple(variants), dv)
    if not packs:
        raise ManifestError(f"{name}: no packs")
    default_pack = raw.get("default", next(iter(packs)))
    if default_pack not in packs:
        raise ManifestError(f"{name}: default pack {default_pack!r} is not defined")
    for pk in packs.values():  # base tokens: mod ids, @tier:, @profile: (a profile or another pack)
        for token in pk.base:
            if token.startswith("@profile:"):
                ref = token.split(":", 1)[1]
                if ref not in profiles and ref not in packs:
                    raise ManifestError(f"{name} pack {pk.id!r}: unknown profile {ref!r}")
            elif not token.startswith("@tier:") and token not in mods:
                raise ManifestError(f"{name} pack {pk.id!r}: unknown mod {token!r}")
    return packs, addons, categories, default_pack
