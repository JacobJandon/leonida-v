"""Pre-install checks: game version, leftovers, exclusive slots, warnings, hotkeys, prerequisites."""

from __future__ import annotations

import fnmatch
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .detect import compare_versions, is_rtx50
from .manifest import Manifest, Mod

ERROR, WARNING, INFO = "error", "warning", "info"


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str
    mod: str | None = None


def hotkey_map(manifest: Manifest, mods: list[Mod], overrides: dict[str, str] | None = None) -> dict[str, list[tuple[str, str]]]:
    """key -> [(mod id, action)] for the selected mods, after the user's overrides."""
    overrides = overrides or {}
    selected = {m.id for m in mods}
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for k in manifest.hotkeys:
        if k["mod"] not in selected:
            continue
        key = overrides.get(f"{k['mod']}/{k['action']}", k["key"])
        out[key.upper()].append((k["mod"], k["action"]))
    return dict(out)


def run_checks(
    manifest: Manifest,
    mods: list[Mod],
    game_dir: Path | None,
    *,
    game_version: str | None = None,
    gpu_names: list[str] | None = None,
    key_overrides: dict[str, str] | None = None,
    prerequisites: dict[str, bool | None] | None = None,
    profile_requires: dict | None = None,
) -> list[Finding]:
    f: list[Finding] = []
    selected = {m.id for m in mods}

    # Game folder and version
    if not game_dir or not Path(game_dir).is_dir():
        f.append(Finding(ERROR, "no-game", "GTA V Enhanced folder not set. Run `leonida detect`."))
    else:
        cmp = compare_versions(game_version, manifest.tested_build)
        if cmp is None:
            f.append(Finding(INFO, "version-unknown",
                             f"Could not read the game version. Tested build: {manifest.tested_build}."))
        elif cmp > 0:
            f.append(Finding(WARNING, "version-newer",
                             f"Game {game_version} is newer than the tested build {manifest.tested_build}. "
                             "Script Hook V / SHVDNE / Resource Extensions may need updates first."))
        elif cmp < 0:
            f.append(Finding(INFO, "version-older",
                             f"Game {game_version} is older than the tested build {manifest.tested_build}. "
                             "Update the game before modding."))

        # Leftover conflicting files in the game folder
        root_files = [p.name for p in Path(game_dir).iterdir() if p.is_file()]
        for mod in mods:
            for pattern in mod.conflicts:
                for name in fnmatch.filter([n.lower() for n in root_files], pattern.lower()):
                    f.append(Finding(ERROR, "conflict-file",
                                     f"Remove {name} from the game folder: it must not run alongside {mod.name}.",
                                     mod.id))
        if "resourceextensions" in selected:
            if any(n.lower() == "gameconfig.xml" for n in root_files):
                f.append(Finding(ERROR, "gameconfig", "Remove the loose gameconfig.xml: Resource Extensions replaces it.",
                                 "resourceextensions"))
            f.append(Finding(INFO, "gameconfig-rpf",
                             "Make sure mods\\update\\update.rpf holds no custom gameconfig.xml "
                             "(Resource Extensions replaces it).", "resourceextensions"))

    # Exclusive slots
    slots: dict[str, list[str]] = defaultdict(list)
    for m in mods:
        if m.slot:
            slots[m.slot].append(m.id)
    for slot, ids in slots.items():
        if len(ids) > 1:
            f.append(Finding(ERROR, "slot-clash", f"Only one mod may use the '{slot}' slot: {', '.join(ids)}."))

    # Pairwise warnings
    for m in mods:
        for w in m.warnings:
            if w["with"] in selected:
                f.append(Finding(WARNING, "pair-warning", w["message"], m.id))

    # GPU requirement
    gpus = gpu_names or []
    needs_rtx50 = [m for m in mods if m.requires.get("gpu") == "rtx50"]
    if ((profile_requires or {}).get("gpu") == "rtx50" or needs_rtx50) and not is_rtx50(gpus):
        names = ", ".join(m.name for m in needs_rtx50) or "this profile"
        seen = ", ".join(gpus) if gpus else "no GPU detected"
        f.append(Finding(WARNING, "gpu", f"{names} needs an NVIDIA RTX 50-series GPU ({seen})."))

    # Hotkeys
    for key, users in hotkey_map(manifest, mods, key_overrides).items():
        if len({u[0] for u in users}) > 1:
            who = "; ".join(f"{manifest.mod(mid).name}: {act}" for mid, act in users)
            f.append(Finding(WARNING, "hotkey", f"{key} is used by more than one mod ({who}). "
                             "Rebind in the mod's settings, then `leonida keys set`."))

    # Prerequisites
    for pid, ok in (prerequisites or {}).items():
        name = next((p["name"] for p in manifest.prerequisites if p["id"] == pid), pid)
        if ok is False:
            f.append(Finding(ERROR, "prereq", f"Install {name} first."))
        elif ok is None:
            f.append(Finding(INFO, "prereq-unknown", f"Could not check {name}; make sure it is installed."))

    # Downloads that need an account or a manual source
    for m in mods:
        if m.source in ("discord", "patreon", "shop"):
            f.append(Finding(INFO, "manual-source", f"{m.name} comes from {m.source}; get it there manually.", m.id))
        if m.tier == "paid":
            f.append(Finding(INFO, "paid", f"{m.name} is paid.", m.id))

    return f


def has_errors(findings: list[Finding]) -> bool:
    return any(x.level == ERROR for x in findings)
