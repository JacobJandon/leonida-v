"""Load and validate the Leonida V manifest (mods.json, profiles.json, hotkeys.json).

mods.json schema (top level)
----------------------------
  "pack", "version", "gameExeNames": [...], "prerequisites": [...], "onlineSafeItems": [...]
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

TIERS = ("core", "optional", "alternative", "paid")
METHODS = ("copy", "generic", "run", "guided", "rpf")
_BUILD_RE = re.compile(r"^\d+(\.\d+){1,3}$")
# gameBuilds entry key -> Mod field it overrides
_OVERRIDES = {
    "version": "version", "page": "page", "image": "image", "source": "source", "archive": "archive",
    "download": "download", "files": "files", "steps": "steps", "run": "run", "createDirs": "create_dirs",
    "method": "method", "notes": "notes", "requireMembers": "require_members", "rejectMembers": "reject_members",
    "pick": "pick", "rpf": "rpf",
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
    else:
        raise ManifestError(f"{where}: download type must be 'github' or 'direct'")
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
        exe_names=tuple(mods_raw.get("gameExeNames", ["GTA5_Enhanced.exe"])),
        online_safe_items=tuple(mods_raw.get("onlineSafeItems", [])),
        prerequisites=tuple(mods_raw.get("prerequisites", [])),
        mods=mods,
        profiles=profiles,
        default_profile=default,
        hotkeys=tuple(keys_raw.get("keys", [])),
        tested_builds=tuple(tested),
    )
    # Resolve every profile once so bad includes fail at load time.
    for pid in profiles:
        manifest.resolve(pid)
    return manifest
