"""Ready-made setups (plan F8): one click = pack + variant + add-ons, tested together; GTA's own settings follow from
the variant and the PC (gamesettings.py). Data: ``leonida/manifest/setups.json``.

* ``load`` / ``problems``: the setups of an edition and their data errors (tested against the manifest);
* ``fits`` / ``best_for``: whether a PC meets a setup's needs (RAM, video memory, RTX, RTX 50), and the best one;
* ``choose``: apply a setup to a session (its pack choice; the chosen id is remembered in ``<state>/setup.json``);
* ``export`` / ``import_setup``: the user's own setup as a small JSON file to share;
* ``build_lock``: the release lockfile (``modpack.json`` format) of a setup, from the matched downloads on this PC.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

STATE_FILE = "setup.json"
EXPORT_KIND = "leonida-setup"


@dataclass(frozen=True)
class Setup:
    id: str
    name: str
    edition: str
    pack: str
    variant: str | None
    addons: tuple[str, ...]
    pc: dict = field(default_factory=dict)
    rank: int = 0
    description: str = ""
    tested_on: tuple[str, ...] = ()


def _from(raw: dict) -> Setup:
    return Setup(raw["id"], raw["name"], raw.get("edition", "enhanced"), raw["pack"], raw.get("variant"),
                 tuple(raw.get("addons", ())), dict(raw.get("pc", {})), int(raw.get("rank", 0)),
                 raw.get("description", ""), tuple(raw.get("testedOn", ())))


def load(edition: str | None = None, path: Path | None = None) -> list[Setup]:
    text = Path(path).read_text(encoding="utf-8") if path else \
        resources.files("leonida.manifest").joinpath("setups.json").read_text(encoding="utf-8")
    out = [_from(s) for s in json.loads(text)["setups"]]
    return [s for s in out if edition is None or s.edition == edition]


def get(setup_id: str, edition: str | None = None) -> Setup:
    for s in load(edition):
        if s.id == setup_id:
            return s
    raise KeyError(f"No setup {setup_id!r}. `leonida setup list` shows them.")


def problems(manifest, setups: list[Setup] | None = None) -> list[str]:
    """A setup's pack, variant and add-ons must exist in the manifest of its edition."""
    out = []
    ids = set()
    for s in setups if setups is not None else load(manifest.edition):
        if s.id in ids:
            out.append(f"{s.id}: duplicate id")
        ids.add(s.id)
        if s.pack not in manifest.packs:
            out.append(f"{s.id}: unknown pack {s.pack!r}")
            continue
        pack = manifest.get_pack(s.pack)
        if (s.variant is None) != (not pack.variants) or (s.variant and not pack.variant(s.variant)):
            out.append(f"{s.id}: variant {s.variant!r} doesn't fit pack {s.pack!r}")
        offered = {a.id for lst in manifest.addons_for(s.pack).values() for a in lst}
        out += [f"{s.id}: add-on {a!r} isn't offered by {s.pack!r}" for a in s.addons if a not in offered]
        if set(s.pc) - {"ramMinGB", "vramMinGB", "rtx", "gpu"}:
            out.append(f"{s.id}: unknown pc needs {sorted(set(s.pc) - {'ramMinGB', 'vramMinGB', 'rtx', 'gpu'})}")
    return out


def fits(setup: Setup, pc) -> tuple[bool, list[str]]:
    """Whether the PC (gamesettings.PC) meets the setup's needs; unknown facts don't block, they're named."""
    why = []
    need = setup.pc
    if "ramMinGB" in need and pc.ram_gb is not None and pc.ram_gb + 0.5 < need["ramMinGB"]:
        why.append(f"needs {need['ramMinGB']} GB of RAM (this PC: {pc.ram_gb:.0f} GB)")
    if "vramMinGB" in need and pc.vram_gb is not None and pc.vram_gb + 0.25 < need["vramMinGB"]:
        why.append(f"needs {need['vramMinGB']} GB of video memory (this PC: {pc.vram_gb:.0f} GB)")
    if need.get("rtx") and pc.rtx is False:
        why.append("needs an NVIDIA RTX card")
    if need.get("gpu") == "rtx50" and not any("rtx 50" in g.lower().replace("rtx50", "rtx 50") for g in pc.gpus):
        why.append("needs an NVIDIA RTX 50-series card")
    return not why, why


def best_for(pc, edition: str = "enhanced") -> Setup | None:
    """The highest-ranked setup this PC meets (first-run preselection)."""
    ok = [s for s in load(edition) if fits(s, pc)[0]]
    return max(ok, key=lambda s: s.rank) if ok else None


def choose(session, setup_id: str) -> Setup:
    s = get(setup_id, session.manifest.edition)
    session.choose_pack(s.pack, list(s.addons), s.variant)
    path = Path(session.state) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"setup": s.id}, indent=1), encoding="utf-8")
    return s


def chosen(session) -> str | None:
    """The setup last chosen, if the pack choice still matches it (a changed add-on makes it the user's own)."""
    try:
        sid = json.loads((Path(session.state) / STATE_FILE).read_text(encoding="utf-8"))["setup"]
        s = get(sid, session.manifest.edition)
    except (OSError, ValueError, KeyError):
        return None
    c = session.pack_choice()
    if c is None or (c.pack, c.variant, tuple(sorted(c.addons or ()))) != (s.pack, s.variant, tuple(sorted(s.addons))):
        return None
    return s.id


def export(session, name: str = "My setup") -> dict:
    """The current choice as a shareable setup file (no paths, no personal data)."""
    c = session.pack_choice()
    if c is None:
        raise ValueError("Choose a pack first.")
    return {"kind": EXPORT_KIND, "schema": 1, "edition": session.manifest.edition, "name": name, "pack": c.pack,
            "variant": c.variant, "addons": sorted(c.addons or ())}


def import_setup(session, data: dict) -> Setup:
    """Apply a shared setup file after checking it against this manifest."""
    if data.get("kind") != EXPORT_KIND:
        raise ValueError("Not a Leonida setup file.")
    if data.get("edition", "enhanced") != session.manifest.edition:
        raise ValueError(f"This setup is for GTA V {data.get('edition')}, but your mod list is "
                         f"{session.manifest.edition}.")
    s = Setup("imported", data.get("name", "Imported setup"), session.manifest.edition, data["pack"],
              data.get("variant"), tuple(data.get("addons", ())))
    bad = problems(session.manifest, [s])
    if bad:
        raise ValueError("This setup doesn't fit your mod list: " + "; ".join(bad))
    session.choose_pack(s.pack, list(s.addons), s.variant)
    return s


def build_lock(session, setup_id: str) -> dict:
    """The setup's release lockfile: choose it, then record the matched downloads (``modpack.build_modpack``)."""
    from . import modpack

    s = choose(session, setup_id)
    data = modpack.build_modpack(session)
    data["setup"] = {"id": s.id, "name": s.name, "pack": s.pack, "variant": s.variant, "addons": list(s.addons)}
    return data
