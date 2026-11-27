"""Zero-touch (plan F8): no hand steps, every mod proven on, in game too.

Three top-level keys per mod in mods.json / mods-legacy.json (the manifest loader keeps them out of ``Mod``; this
module reads them from the JSON itself, like features.py):

``verify``: how to prove the mod is on. ``in``: ``files`` = Leonida checks it from disk after a game start; ``game``
= the Leonida in-game menu checks it with public natives during the deep play test (exe-build)::

    {"kind": "asi", "in": "files", "name": "ActionsV.asi"}           the .asi is in the game folder (and loaded)
    {"kind": "script", "in": "files", "file": "scripts/X.dll"}       a Script Hook V .NET script is in place
    {"kind": "log", "in": "files", "file": "X.log", "contains": "..."} a fresh log has the line ("" = the log exists)
    {"kind": "file", "in": "files", "path": "mods/x64/audio/sfx/X.rpf"}
    {"kind": "rpf-entry", "in": "files", "archive": "mods/update/update.rpf", "entry": "common/data/handling.meta"}
    {"kind": "dlc", "in": "game", "name": "vihud"}                    IS_DLC_PRESENT(GET_HASH_KEY(name))
    {"kind": "ipl", "in": "game", "name": "vw_casino_main"}           IS_IPL_ACTIVE(name)
    {"kind": "native", "in": "game", "name": "GET_CURRENT_LANGUAGE", "equals": 0}
    {"kind": "files-logged", "in": "files"}                           Leonida's own file check of the install step
    {"kind": "setting", "in": "files", "file": "scripts/X.ini", "key": "Keys/Decline", "equals": "Delete"}
        a value in a mod's config file, read with Leonida's settings reader (ini / xml / json by extension):
        ``equals`` one value, or ``contains`` a string or a list of comma-separated items that must all be there.
        A key the player unlocked (`leonida settings unlock`) proves nothing either way.
    {"kind": "interior", "in": "game", "name": "Up-n-Atom", "x": 80.76, "y": 273.01, "zMin": 109.2, "zMax": 123.5}
        an add-on interior (MLO) is there: the deep play test's probe takes the player to (x, y), samples z between
        zMin and zMax (the interior ymap's own bounding box) and asks GET_INTERIOR_AT_COORDS + IS_INTERIOR_READY.
        The probe has to move the player, so only the probe runs it (not yet built: exe-build); the menu skips it.

``inGameSetup``: what the Leonida menu does once at the first story-mode load, with public natives or the mod's own
documented hooks only (never another script's memory)::

    {"action": "reload-scripts" | "check", "when": "first-load" | "verify-fails", "verify": {...}, "why": "...",
     "onFail": "what to tell the player"}

``manual``: ``{"why": "..."}``, for a mod that still needs the player, and why it can't be automated yet.

``covered``: ``[{"step": "<prefix>", "by": "..."}]``, steps kept as "before you play" lines for the launcher that Leonida
itself writes or checks (not hand steps).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

VERIFY_KINDS = {
    "asi": {"name"}, "script": {"file"}, "log": {"file", "contains"}, "file": {"path"},
    "rpf-entry": {"archive", "entry"}, "dlc": {"name"}, "ipl": {"name"}, "native": {"name"},
    "files-logged": set(), "setting": {"file", "key"}, "interior": {"name", "x", "y", "zMin", "zMax"},
}
ACTIONS = {"reload-scripts", "check"}
NATIVE_RE = re.compile(r"^(GET|IS|HAS)_[A-Z0-9_]+$")   # read-only, no-argument natives (the menu calls them as is)
WHENS = {"first-load", "verify-fails"}
# a hand step Leonida still prints for a non-guided install must start like this (the player really has to act)
HAND_PREFIXES = ("In the game: Settings", "After the first game start", "Optional", "Have an older ScriptHookVDotNet",
                 "Its page recommends raising StaticBounds")


@lru_cache(maxsize=4)
def _raw(edition: str) -> dict[str, dict]:
    name = "mods.json" if edition == "enhanced" else f"mods-{edition}.json"
    data = json.loads(resources.files("leonida.manifest").joinpath(name).read_text(encoding="utf-8"))
    return {m["id"]: m for m in data["mods"]}


def verify_for(mod_id: str, edition: str = "enhanced") -> list[dict]:
    return list(_raw(edition).get(mod_id, {}).get("verify", []))


def in_game_setup(mod_id: str, edition: str = "enhanced") -> list[dict]:
    return list(_raw(edition).get(mod_id, {}).get("inGameSetup", []))


def manual_why(mod_id: str, edition: str = "enhanced") -> str | None:
    return (_raw(edition).get(mod_id, {}).get("manual") or {}).get("why")


def problems(edition: str = "enhanced") -> list[str]:
    """Data errors (tested): unknown kinds, missing fields, a mod without any proof, setups without a reason."""
    out = []
    for mid, m in _raw(edition).items():
        checks = m.get("verify")
        if not checks:
            out.append(f"{mid}: no verify")
        for c in checks or ():
            kind = c.get("kind")
            if kind not in VERIFY_KINDS:
                out.append(f"{mid}: unknown verify kind {kind!r}")
            elif c.get("in") not in ("files", "game"):
                out.append(f"{mid}: verify {kind} needs in: files|game")
            elif kind not in ("log", "files-logged") and VERIFY_KINDS[kind] - set(c):
                out.append(f"{mid}: verify {kind} needs {sorted(VERIFY_KINDS[kind] - set(c))}")
            elif kind == "native" and not NATIVE_RE.match(str(c.get("name", ""))):
                out.append(f"{mid}: native {c.get('name')!r}: only no-argument GET_ / IS_ / HAS_ natives")
            elif "withinSeconds" in c and not (isinstance(c["withinSeconds"], int) and c["withinSeconds"] > 0):
                out.append(f"{mid}: withinSeconds must be a positive whole number (optional)")
            elif kind == "setting" and (c.get("in") != "files" or ("equals" in c) == ("contains" in c)):
                out.append(f"{mid}: setting {c.get('key')!r}: in: files and exactly one of equals / contains")
            elif kind == "interior" and (c.get("in") != "game" or not all(
                    isinstance(c[k], (int, float)) for k in ("x", "y", "zMin", "zMax")) or c["zMin"] > c["zMax"]):
                out.append(f"{mid}: interior {c.get('name')!r}: in: game, numbers x, y, zMin <= zMax")
        for s in m.get("inGameSetup", ()):
            if s.get("action") not in ACTIONS or s.get("when") not in WHENS or not s.get("why") or not s.get("verify"):
                out.append(f"{mid}: inGameSetup needs action, when, verify, why")
                continue
            sv = s["verify"]
            if sv.get("kind") == "native" and not NATIVE_RE.match(str(sv.get("name", ""))):
                out.append(f"{mid}: inGameSetup native {sv.get('name')!r}: only no-argument GET_ / IS_ / HAS_ natives")
        if m.get("manual") is not None and not (m["manual"] or {}).get("why"):
            out.append(f"{mid}: manual needs a why")
    return out


NVE_WHY = ("with NaturalVision Enhanced (paid) this mod goes into NVE's onigiri folder by hand: Leonida's archive engine "
           "writes the mods folder, and NVE's loader doesn't read it")


@dataclass(frozen=True)
class HandStep:
    mod: str
    name: str
    steps: tuple[str, ...]
    why: str | None


def hand_steps(mods, edition: str = "enhanced") -> list[HandStep]:
    """What the player still does by hand for these (resolved, selected) mods: guided installs and the steps a
    non-guided install prints, with the manifest's reason. An empty list = zero-touch."""
    out = []
    for m in mods:
        if getattr(m, "not_needed", None):
            continue
        covered = tuple(c["step"] for c in _raw(edition).get(m.id, {}).get("covered", ()))
        steps = tuple(s for s in (m.steps or ()) if not s.startswith(covered)) if covered else tuple(m.steps or ())
        if m.method == "guided" or steps:
            why = manual_why(m.id, edition)
            if why is None and "+nve" in (getattr(m, "conditions", ()) or ()):
                why = NVE_WHY
            out.append(HandStep(m.id, m.name, steps, why))
    return out


# ------------------------------------------------------------------------------------------------- files half
@dataclass(frozen=True)
class Proof:
    mod: str
    check: dict
    ok: bool | None          # None = can't be told from files (in game, or needs the archive helper)
    detail: str = ""


def _log_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _setting_proof(game: Path, mod_id: str, c: dict, unlocked: set[str]) -> Proof:
    from . import settings as S

    file, key = c["file"], c["key"]
    if any(u.split("|", 1)[-1] == f"{file}|{key}" for u in unlocked):
        return Proof(mod_id, c, None, f"{file}: {key} is unlocked (your own value)")
    p = S.resolve(game, file)
    try:
        text = S._decode(p.read_bytes())[0]
    except OSError:
        return Proof(mod_id, c, False, f"{file} isn't there")
    try:
        have = S.get_value(text, S.format_of(file, c.get("format")), key)
    except Exception as exc:             # a file the mod wrote in another shape: say so, don't crash the check
        return Proof(mod_id, c, False, f"{file} can't be read ({exc})")
    if "equals" in c:
        ok = S.same(have, c["equals"])
        return Proof(mod_id, c, ok, "" if ok else f"{file}: {key} is {have!r}, not {c['equals']!r}")
    want = c["contains"] if isinstance(c["contains"], list) else [c["contains"]]
    text_have = (have or "").lower()
    items = {i.strip() for i in text_have.split(",")}
    # a comma list: whole items only ("50" isn't "500"); a single value: a part of it
    missing = [w for w in want if (str(w).strip().lower() not in items if "," in text_have
                                   else str(w).strip().lower() not in text_have)]
    return Proof(mod_id, c, not missing, "" if not missing else f"{file}: {key} has no {', '.join(map(str, missing))}")


def check_files(game: Path | str, mods, edition: str = "enhanced", since: float | None = None,
                unlocked: set[str] | None = None) -> list[Proof]:
    """The ``in: files`` proofs from disk (read-only). ``since``: a log must be written after this time (the game
    start), or it proves nothing about this start. ``unlocked``: settings.unlocked(state), so a setting the player
    unlocked isn't counted as off."""
    game = Path(game)
    out = []
    for m in mods:
        for c in verify_for(m.id, edition):
            kind = c["kind"]
            if c.get("in") != "files" or kind in ("rpf-entry", "files-logged"):
                out.append(Proof(m.id, c, None, "checked in game" if c.get("in") == "game"
                                 else "Leonida's file check (needs the archive helper)"))
                continue
            if kind == "setting":
                out.append(_setting_proof(game, m.id, c, unlocked or set()))
            elif kind == "asi":
                p = game / c["name"]
                out.append(Proof(m.id, c, p.is_file(), "" if p.is_file() else f"{c['name']} is missing"))
            elif kind in ("script", "file"):
                p = game / c.get("file", c.get("path", ""))
                out.append(Proof(m.id, c, p.exists(), "" if p.exists() else f"{p.relative_to(game)} is missing"))
            elif kind == "log":
                if not c.get("file"):
                    out.append(Proof(m.id, c, None, c.get("note", "")))
                    continue
                p = game / c["file"]
                text = _log_text(p)
                if text is None:
                    out.append(Proof(m.id, c, False, f"{c['file']} isn't there (start the game first)"))
                elif since is not None and p.stat().st_mtime < since:
                    out.append(Proof(m.id, c, None, f"{c['file']} is from an earlier start"))
                else:
                    ok = (c.get("contains") or "") in text
                    out.append(Proof(m.id, c, ok, "" if ok else f"{c['file']} has no '{c['contains']}'"))
    return out


def summary(proofs: list[Proof]) -> dict[str, str]:
    """mod id -> "on" (every files proof ok), "off" (one failed), "not checked" (nothing told from files)."""
    by: dict[str, list[Proof]] = {}
    for p in proofs:
        by.setdefault(p.mod, []).append(p)
    out = {}
    for mid, ps in by.items():
        told = [p for p in ps if p.ok is not None]
        out[mid] = "not checked" if not told else ("on" if all(p.ok for p in told) else "off")
    return out


def describe(check: dict) -> str:
    """A check in words (docs, the launcher)."""
    k = check["kind"]
    return {
        "asi": lambda c: f"{c['name']} loaded",
        "script": lambda c: f"{Path(c['file']).name} in scripts",
        "log": lambda c: (f"{c['file']}: '{c['contains']}'" if c.get("contains") else f"{c.get('file') or 'log'}"),
        "file": lambda c: f"{c['path']} present",
        "rpf-entry": lambda c: f"{re.sub(r'^mods/', '', c['archive'])} > {c['entry']}",
        "dlc": lambda c: f"DLC pack {c['name']} present (in game)",
        "ipl": lambda c: f"IPL {c['name']} active (in game)",
        "native": lambda c: f"{c['name']} = {c.get('equals')} (in game)",
        "files-logged": lambda c: "its logged files are in place",
        "setting": lambda c: (f"{c['file']}: {c['key']} = {c['equals']}" if "equals" in c
                              else f"{c['file']}: {c['key']} has {c['contains']}"),
        "interior": lambda c: f"the {c['name']} interior is there (in game, probe)",
    }[k](check)
