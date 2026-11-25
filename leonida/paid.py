"""Paid mods, the legit way: buy from the author -> your own file in Downloads -> Leonida checks and installs it.

Leonida never opens Patreon tiers or shops for you, never pays, never signs in, and never uses re-uploads. It only:
* shows each paid mod's ``buy`` data from mods.json: the author's own purchase page, the price as that page shows it,
  the tier that gives the file, and when it was checked;
* recognises the file you downloaded yourself. The matcher names it from ``archive``, and ``requireMembers`` /
  ``rejectMembers`` check its contents, so a wrong package is refused. A renamed file works with `leonida assign`;
* says what to do next (`leonida check` / the launcher): tick the pack's add-on, then install. The install runs
  through Leonida's test place first like every download, logged and undoable.

``buy`` sits at the top level of a mod entry (the manifest loader keeps it out of ``Mod``)::

    "buy": {"url": "https://www.patreon.com/...", "price": "from $10 / month (Gold tier)", "tier": "Gold",
            "gets": "what the buyer downloads", "checked": "2026-11-25"}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

BUY_KEYS = {"url", "price", "tier", "gets", "checked"}


@lru_cache(maxsize=4)
def _raw(edition: str) -> dict[str, dict]:
    name = "mods.json" if edition == "enhanced" else f"mods-{edition}.json"
    data = json.loads(resources.files("leonida.manifest").joinpath(name).read_text(encoding="utf-8"))
    return {m["id"]: m for m in data["mods"]}


def buy_info(mod_id: str, edition: str = "enhanced") -> dict:
    return dict(_raw(edition).get(mod_id, {}).get("buy", {}))


@dataclass
class PaidMod:
    id: str
    name: str
    author: str
    buy_url: str
    price: str
    tier: str
    gets: str
    status: str                      # "installed" | "downloaded" | "wrong file" | "not bought"
    file: str = ""                   # the matched (or refused) download's name
    reason: str = ""                 # why a file was refused
    addons: list[str] = field(default_factory=list)      # add-ons of the chosen pack that turn it on
    replaces: list[str] = field(default_factory=list)    # pack mods it takes the place of
    builds: str = ""                 # game builds, in words


def _builds(mod) -> str:
    lo, hi = getattr(mod, "min_game_build", None), getattr(mod, "max_game_build", None)
    parts = []
    if lo or hi:
        parts.append(f"{lo or 'any'} to {hi or 'newest'}")
    for gb in getattr(mod, "game_builds", ()) or ():
        rng = f"{gb.min or 'any'} to {gb.max or 'newest'}"
        parts.append(f"{rng}: not supported" if gb.unsupported else f"{rng}: an older release")
    return "; ".join(p for p in parts if p) or "any (the author names none)"


def _replaces(manifest, mod_id: str) -> list[str]:
    out = []
    for m in manifest.mods.values():
        for other, ov in getattr(m, "when_selected", ()) or ():
            if other == mod_id and "not_needed" in ov:
                out.append(m.name)
    mod = manifest.mods[mod_id]
    if mod.slot:
        out += [m.name for m in manifest.mods.values() if m.slot == mod.slot and m.id != mod_id
                and m.tier != "paid" and m.name not in out]
    return out


def paid_list(session) -> list[PaidMod]:
    """Every paid mod with its buy data and where you are: not bought, downloaded (your file is in Downloads),
    refused (a wrong file) or installed."""
    manifest = session.manifest
    edition = manifest.edition
    paid = [m for m in manifest.mods.values() if m.tier == "paid" and not m.free_since]
    res = session.matches(paid) if paid else None
    installed = session.log.installed_mods()
    pid = session.profile_id
    pack_addons = manifest.addons_for(pid) if pid in manifest.packs else {}
    out = []
    for m in paid:
        b = buy_info(m.id, edition)
        row = PaidMod(m.id, m.name, getattr(m, "author", "") or "", b.get("url", m.page), b.get("price", ""),
                      b.get("tier", ""), b.get("gets", ""), "not bought", builds=_builds(m))
        if m.id in installed:
            row.status = "installed"
        elif res is not None and m.id in res.matched:
            row.status, row.file = "downloaded", res.matched[m.id].name
        elif res is not None:
            for path, (mid, why) in res.wrong.items():
                if mid == m.id:
                    row.status, row.file, row.reason = "wrong file", path.name, why
        row.addons = [a.name for lst in pack_addons.values() for a in lst if m.id in a.mods]
        row.replaces = _replaces(manifest, m.id)
        out.append(row)
    return out


def findings(session) -> list:
    """What `leonida check` and the launcher say about paid mods you downloaded yourself."""
    from .checks import INFO, WARNING, Finding

    out = []
    for p in paid_list(session):
        if p.status == "downloaded":
            how = (f"tick '{p.addons[0]}'" if p.addons else "add it to your pack")
            out.append(Finding(INFO, "paid-downloaded",
                               f"Your {p.name} download ({p.file}) is in Downloads: {how}, then install. Leonida "
                               "checks it in its test place first." + (f" It takes the place of {', '.join(p.replaces)}."
                                                                         if p.replaces else ""), p.id))
        elif p.status == "wrong file":
            out.append(Finding(WARNING, "paid-wrong-file",
                               f"{p.file} looks like {p.name} but isn't the author's package ({p.reason}). Download it "
                               f"again from {p.buy_url}.", p.id))
    return out
