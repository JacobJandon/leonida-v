"""What each mod does in the game, so two mods never do the same job and break each other.

Every mod in mods.json / mods-legacy.json has ``features``: words from ``VOCAB`` (what it changes in the game).
Two selected mods that share a feature are a clash, unless one of them records how they coexist::

    "sharesFeature": [{"feature": "fuel", "with": "fuelreloaded",
                       "how": "the HUD's BurnFuel is locked to False while Fuel Reloaded is selected",
                       "verified": "locked setting; not yet in game"}]

Mods in the same ``slot`` are left to the slot check (only one may be selected anyway). Either/or pairs never meet:
their whenSelected / whenMissing ``skip`` takes one out before the check. The keys sit at the top level of a mod
entry (the manifest loader keeps them out of ``Mod``), so this module reads them from the JSON files themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

VOCAB = frozenset({
    # frameworks and limits
    "script-runtime", "dotnet-runtime", "menu-library", "archive-loader", "storage-fix", "memory-limits",
    "packfile-limit", "staticbounds-limit", "lod-streaming-limit", "gameconfig-pools", "leonida-menu",
    # look and world
    "graphics-timecycle", "graphics-reshade", "graphics-raytracing", "sky", "road-textures", "vegetation",
    "map-fixes", "map-additions", "interiors-mp", "interiors-open-world", "interiors-fastfood", "interiors-shop",
    "phone-contacts", "phone-icons", "loading-screens", "startup-skip",
    # HUD and play
    "hud", "minimap", "wanted-system", "police-ai", "fuel", "vehicle-tuning", "dealership", "character-switch",
    "crouch", "gym", "binoculars", "radio", "camera-crash", "trainer", "actions-animations", "player-models",
    "street-food", "jobs-delivery", "jobs-rideshare",
    # driving and combat
    "vehicle-handling", "vehicle-damage", "vehicle-models", "traffic-population", "camera-vehicle-firstperson",
    "ragdoll", "melee", "weapon-damage", "weapon-sounds", "camera-aim", "camera-shake-hit",
})


@dataclass(frozen=True)
class Clash:
    a: str
    b: str
    feature: str
    record: dict | None      # the sharesFeature record that settles it (None = a clash)

    @property
    def settled(self) -> bool:
        return self.record is not None


@lru_cache(maxsize=4)
def _raw(edition: str) -> dict[str, dict]:
    name = "mods.json" if edition == "enhanced" else f"mods-{edition}.json"
    data = json.loads(resources.files("leonida.manifest").joinpath(name).read_text(encoding="utf-8"))
    return {m["id"]: m for m in data["mods"]}


def features_of(mod_id: str, edition: str = "enhanced") -> tuple[str, ...]:
    return tuple(_raw(edition).get(mod_id, {}).get("features", ()))


def record_for(a: str, b: str, feature: str, edition: str = "enhanced") -> dict | None:
    raw = _raw(edition)
    for x, y in ((a, b), (b, a)):
        for rec in raw.get(x, {}).get("sharesFeature", ()):
            if rec.get("feature") == feature and rec.get("with") == y:
                return rec
    return None


def clashes(mods, edition: str = "enhanced") -> list[Clash]:
    """Every pair of the given (resolved, selected) mods that shares a feature, settled or not."""
    out: list[Clash] = []
    mods = [m for m in mods if not getattr(m, "not_needed", None)]
    for i, a in enumerate(mods):
        fa = set(features_of(a.id, edition))
        if not fa:
            continue
        for b in mods[i + 1:]:
            if a.slot and a.slot == getattr(b, "slot", None):
                continue                                   # the slot check reports it
            for feat in sorted(fa & set(features_of(b.id, edition))):
                out.append(Clash(a.id, b.id, feat, record_for(a.id, b.id, feat, edition)))
    return out


def problems(edition: str = "enhanced") -> list[str]:
    """Data errors: unknown features, a mod without features, records that point nowhere (tested)."""
    raw = _raw(edition)
    out = []
    for mid, m in raw.items():
        feats = m.get("features")
        if not feats:
            out.append(f"{mid}: no features")
            continue
        out += [f"{mid}: unknown feature {f!r}" for f in feats if f not in VOCAB]
        for rec in m.get("sharesFeature", ()):
            other = rec.get("with")
            if set(rec) != {"feature", "with", "how", "verified"}:
                out.append(f"{mid}: sharesFeature needs exactly feature, with, how, verified")
            elif other not in raw:
                out.append(f"{mid}: sharesFeature with unknown mod {other!r}")
            elif rec["feature"] not in feats or rec["feature"] not in raw[other].get("features", ()):
                out.append(f"{mid}: sharesFeature {rec['feature']!r}, which {other} or {mid} doesn't have")
    return out
