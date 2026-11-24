"""Pre-install checks: game build compatibility, leftovers, exclusive slots, warnings, hotkeys, prerequisites."""

from __future__ import annotations

import fnmatch
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .detect import file_description, is_rtx50
from .manifest import Manifest, Mod, build_key

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


def _build_findings(manifest: Manifest, mods: list[Mod], build: str | None) -> list[Finding]:
    """Game-build compatibility of the selected (already resolved) mods."""
    tested = ", ".join(manifest.tested_builds) or "none listed"
    if build_key(build) is None:
        return [Finding(INFO, "version-unknown",
                        f"Could not read the game version, so every mod uses its latest version. "
                        f"Tested game builds: {tested}.")]
    out: list[Finding] = []
    for m in mods:
        if not m.unsupported:
            continue
        alts = [a.name for a in manifest.mods.values()
                if m.slot and a.slot == m.slot and a.id != m.id and not a.for_build(build).unsupported]
        what = (f"Swap it for {' or '.join(alts)} (`leonida swap {m.id} <alternative>`)" if alts
                else "Pick another profile, or leave it out (untick it in the app)")
        out.append(Finding(ERROR, "build-unsupported",
                           f"{m.name} can't be used on game build {build}: {m.unsupported} {what}.", m.id))
    older = [m for m in mods if m.variant is not None and not m.unsupported]
    if older:
        names = ", ".join(f"{m.name} {m.version}".strip() for m in older)
        out.append(Finding(INFO, "build-variant", f"On game build {build} these mods use an older version: {names}."))
    if manifest.newer_than_tested(build):
        out.append(Finding(WARNING, "version-newer",
                           f"Game build {build} is newer than every tested build ({tested}). Script Hook V, "
                           "SHVDNE and Resource Extensions may need an update for it first."))
    elif not manifest.is_tested(build):
        out.append(Finding(INFO, "version-untested",
                           f"Game build {build} isn't one of the tested builds ({tested}); "
                           "the mods' own build ranges are used."))
    return out


NVE_GAMECONFIG = "onigiri/common/data/gameconfig.xml"
# Proxy DLL names that ASI loaders and other injectors use. GTA V Enhanced ships none of them in its folder
# (checked against a real 1.0.1013.20 install), so any of these in the game root came from something else.
LOADER_DLLS = ("version.dll", "dinput8.dll", "xinput1_4.dll", "winmm.dll", "dsound.dll", "d3d11.dll", "d3d12.dll",
               "dxgi.dll", "winhttp.dll")
STOCK_ROOT_DLLS: frozenset[str] = frozenset()  # none of LOADER_DLLS is part of the stock game


def _gameconfig_findings(game: Path, root_files: list[str], selected: set[str]) -> list[Finding]:
    out: list[Finding] = []
    re_on, nve_on = "resourceextensions" in selected, "nve" in selected
    if re_on:
        if any(n.lower() == "gameconfig.xml" for n in root_files):
            out.append(Finding(ERROR, "gameconfig", "Remove the loose gameconfig.xml from the game folder: "
                               "Resource Extensions replaces it.", "resourceextensions"))
        if nve_on:
            out.append(Finding(INFO, "gameconfig-nve",
                               "Leave NVE's onigiri\\common\\data\\gameconfig.xml as it is: Resource Extensions works "
                               "with it. Don't add another gameconfig.xml anywhere in onigiri.", "resourceextensions"))
        else:
            out.append(Finding(INFO, "gameconfig-rpf",
                               "Make sure mods\\update\\update.rpf holds no custom gameconfig.xml "
                               "(Resource Extensions replaces it).", "resourceextensions"))
    onigiri = game / "onigiri"
    if onigiri.is_dir():
        for root, _dirs, files in os.walk(onigiri):
            for name in files:
                if name.lower() != "gameconfig.xml":
                    continue
                rel = (Path(root) / name).relative_to(game).as_posix()
                if rel.lower() == NVE_GAMECONFIG:
                    continue
                why = "It conflicts with Resource Extensions" if re_on else "Only NVE's own one belongs there"
                shown, nve_file = rel.replace("/", "\\"), NVE_GAMECONFIG.replace("/", "\\")
                out.append(Finding(WARNING, "gameconfig-onigiri",
                                   f"{shown} isn't NVE's gameconfig.xml ({nve_file}). {why}; "
                                   "remove it unless that mod's own instructions need it.", "nve"))
    return out


def _installs_root_file(mod: Mod, name: str) -> bool:
    low = name.lower()
    return any(spec.type == "file" and spec.match.lower() == low and spec.to.replace("\\", "/").strip("./") == ""
               for spec in mod.files)


def _loader_dll_findings(game: Path, root_files: list[str], mods: list[Mod], installed: set[str]) -> list[Finding]:
    out: list[Finding] = []
    present = {n.lower(): n for n in root_files}
    for dll in LOADER_DLLS:
        name = present.get(dll)
        if not name or dll in STOCK_ROOT_DLLS or dll in installed:
            continue
        desc = file_description(game / name)
        what = f" ({desc})" if desc else ""
        users = [m.name for m in mods if _installs_root_file(m, dll)]
        if users:
            out.append(Finding(WARNING, "loader-overwrite",
                               f"{name}{what} is already in the game folder and wasn't put there by Leonida. "
                               f"{', '.join(users)} install{'s' if len(users) == 1 else ''} its own {name}, which "
                               "replaces it. Leonida backs up the original first, so rolling back or uninstalling "
                               "puts it back exactly (the baseline snapshot checks it).", None))
        else:
            out.append(Finding(INFO, "loader-dll",
                               f"{name}{what} is in the game folder but wasn't installed by Leonida. Leonida leaves it "
                               "alone; if it's an ASI loader, .asi plugins may load twice.", None))
    return out


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
    installed_paths: set[str] | None = None,
) -> list[Finding]:
    """``installed_paths``: lower-case game-relative paths Leonida's install log placed (for the loader-DLL check)."""
    f: list[Finding] = []
    # Each mod as it applies to this game build and selection (a no-op for mods the Session already resolved).
    chosen = {m.id for m in mods}
    mods = [m.for_build(game_version) for m in mods]
    mods = [m if m.selection is not None else m.for_selection(chosen) for m in mods]
    mods = [m for m in mods if not m.not_needed]
    selected = {m.id for m in mods}

    # Game folder and version
    if not game_dir or not Path(game_dir).is_dir():
        f.append(Finding(ERROR, "no-game", "GTA V Enhanced folder not set. Run `leonida detect`."))
    else:
        f.extend(_build_findings(manifest, mods, game_version))

        # Leftover conflicting files in the game folder
        root_files = [p.name for p in Path(game_dir).iterdir() if p.is_file()]
        for mod in mods:
            for pattern in mod.conflicts:
                for name in fnmatch.filter([n.lower() for n in root_files], pattern.lower()):
                    f.append(Finding(ERROR, "conflict-file",
                                     f"Remove {name} from the game folder: it must not run alongside {mod.name}.",
                                     mod.id))
        f.extend(_gameconfig_findings(Path(game_dir), root_files, selected))
        f.extend(_loader_dll_findings(Path(game_dir), root_files, mods, installed_paths or set()))

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
        if m.is_paid:
            route = manifest.free_route_text(m.id) if m.id in manifest.mods else "no free route recorded yet"
            f.append(Finding(INFO, "paid", f"{m.name} is paid; free route: {route}.", m.id))

    return f


def has_errors(findings: list[Finding]) -> bool:
    return any(x.level == ERROR for x in findings)
