"""The user's modpack choice (pack, add-ons, variant) and switching packs.

The choice is saved per edition in ``<state>/pack.json``::

    {"enhanced": {"pack": "plus", "addons": ["interiors", "street-food"], "variant": "balanced"},
     "legacy":   {"pack": "core", "addons": null, "variant": null}}

``addons`` null = the pack's default add-ons. Without an entry the old profile choice (config.json ``profile``)
carries over: the pack with that id (profiles become packs with the same id), else the default pack.
Switching packs can roll back what isn't in the new pack (``rollback_mods``), mod by mod, newest first, and only
where no kept mod shares files with it (the same rule as mod updates).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FILE_NAME = "pack.json"


@dataclass(frozen=True)
class PackChoice:
    pack: str
    addons: tuple[str, ...] | None = None   # None = the pack's default add-ons
    variant: str | None = None


def _read(state: Path) -> dict:
    try:
        data = json.loads((Path(state) / FILE_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_choice(state: Path, edition: str) -> PackChoice | None:
    raw = _read(state).get(edition)
    if not isinstance(raw, dict) or not isinstance(raw.get("pack"), str):
        return None
    addons = raw.get("addons")
    addons = tuple(a for a in addons if isinstance(a, str)) if isinstance(addons, list) else None
    variant = raw.get("variant") if isinstance(raw.get("variant"), str) else None
    return PackChoice(raw["pack"], addons, variant)


def save_choice(state: Path, edition: str, choice: PackChoice) -> Path:
    data = _read(state)
    data[edition] = {"pack": choice.pack, "addons": list(choice.addons) if choice.addons is not None else None,
                     "variant": choice.variant}
    p = Path(state) / FILE_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def rollback_mods(session, ui, mod_ids: set[str]) -> list[str]:
    """Roll back the installed steps of ``mod_ids`` (mods not in the newly chosen pack), newest first. A step that a
    kept mod's later step shares files with is left installed, with the reason. Returns a report."""
    from .modupdate import _rollback_one, dependents

    installer = session.installer(ui)
    report: list[str] = []
    steps = sorted((s for s in session.log.active_steps() if s.mod in mod_ids and s.status == "done"),
                   key=lambda s: s.id, reverse=True)
    for step in steps:
        blocking = [d for d in dependents(session.log, step) if d.mod not in mod_ids]
        if blocking:
            report.append(f"{step.mod}: kept, because {', '.join(sorted({d.mod for d in blocking}))} (still in the "
                          "pack) was installed later and shares files with it")
            continue
        try:
            warnings = _rollback_one(installer, step)
        except Exception as exc:  # report and go on with the others
            report.append(f"{step.mod}: couldn't roll back ({exc})")
            continue
        report.append(f"{step.mod}: rolled back")
        report += [f"  ! {w}" for w in warnings]
    return report
