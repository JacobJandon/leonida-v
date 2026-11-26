"""The game lost its mods: Steam, Epic or Rockstar verified or reinstalled GTA V, so the files Leonida installed are
gone while the install log still lists them. Find that, and Repair: install every lost mod again from the files in
Downloads (never downloading anything), then write the locked settings again.

    found = lost(session)          # LostMods or None (a quick look: do the logged files exist?)
    report = repair(session, ui)   # every lost mod installed again, in its old order; RepairReport

A lost mod's old steps are marked "lost" (they no longer count as installed and are never rolled back: their files
are gone, and the game's own files came back with the verify). Mods whose download isn't in Downloads any more, and
guided mods (they need you), are listed in the report rather than fetched or guessed. Mods moved out on purpose
(Online-safe) are never "lost".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import log as L
from . import settings as S

log = logging.getLogger(__name__)

LOST = "lost"
SHARE = 0.5           # a mod is lost when at least this share of its logged files is gone
FILE_OPS = (L.ADD, L.REPLACE, L.EXT_ADD, L.EXT_CHANGE, L.RPF_EDIT)


@dataclass
class LostMods:
    mods: list[str]                                   # mod ids, in install order
    missing: dict[str, int] = field(default_factory=dict)
    total: dict[str, int] = field(default_factory=dict)

    def text(self, names: dict[str, str] | None = None) -> str:
        names = names or {}
        listed = ", ".join(names.get(m, m) for m in self.mods[:6]) + (" ..." if len(self.mods) > 6 else "")
        return (f"Your game lost {len(self.mods)} mod(s) Leonida installed ({listed}): Steam, Epic or Rockstar "
                "probably repaired or reinstalled it. Repair puts them back from your Downloads (nothing is "
                "downloaded).")


@dataclass
class RepairReport:
    repaired: list[str] = field(default_factory=list)
    no_download: list[str] = field(default_factory=list)
    by_hand: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    settings: list[str] = field(default_factory=list)

    def lines(self, names: dict[str, str] | None = None) -> list[str]:
        n = names or {}
        out = [f"Repaired: {', '.join(n.get(m, m) for m in self.repaired) or 'nothing'}"]
        if self.no_download:
            out.append("Not in Downloads any more (get them again, then Repair): "
                       + ", ".join(n.get(m, m) for m in self.no_download))
        if self.by_hand:
            out.append("Install these again by hand (guided): " + ", ".join(n.get(m, m) for m in self.by_hand))
        out += [f"Failed: {n.get(m, m)}: {why}" for m, why in self.failed.items()]
        if self.settings:
            out.append(f"Locked settings written again: {len(self.settings)} file(s)")
        return out


def _mod_of(step: L.Step) -> str:
    return step.mod.split(":", 1)[1] if step.mod.startswith("settings:") else step.mod


def lost(session, share: float = SHARE) -> LostMods | None:
    """The installed mods whose logged files are (mostly) gone from the game folder; None when none is."""
    game = session.game_dir()
    if not game or not Path(game).is_dir():
        return None
    try:
        if session.online_status() in ("online-safe", "mixed"):
            return None                        # moved out on purpose
    except Exception:  # noqa: BLE001 - no online-safe record: look anyway
        pass
    from .filecheck import expected

    total: dict[str, int] = {}
    missing: dict[str, int] = {}
    order: dict[str, int] = {}
    for _key, (st, a) in expected(session.log).items():
        if st.mod.startswith("settings:") or a.op not in FILE_OPS:
            continue
        target = S.resolve(Path(game), a.path.rstrip("/"))
        if target.is_dir():
            continue                            # a folder a run / guided step made
        total[st.mod] = total.get(st.mod, 0) + 1
        order.setdefault(st.mod, st.id)
        if not target.is_file():
            missing[st.mod] = missing.get(st.mod, 0) + 1
    gone = [m for m in total if missing.get(m, 0) >= max(1, share * total[m])]
    if not gone:
        return None
    gone.sort(key=lambda m: order[m])
    return LostMods(gone, {m: missing[m] for m in gone}, {m: total[m] for m in gone})


def repair(session, ui, found: LostMods | None = None) -> RepairReport:
    """Install every lost mod again from Downloads, in its old order; then the locked settings."""
    from .installer import InstallError

    found = found if found is not None else lost(session)
    rep = RepairReport()
    if not found:
        return rep
    resolved = {m.id: m for m in session.mods()}
    mods = [resolved.get(mid) or session.manifest.mods.get(mid) for mid in found.mods]
    matched = session.matches([m for m in mods if m is not None]).matched
    inst = session.installer(ui)
    for mid, mod in zip(found.mods, mods, strict=True):
        if mod is None:
            rep.failed[mid] = "not in the mod list any more"
            continue
        if mod.method == "guided":
            rep.by_hand.append(mid)
            continue
        archive = matched.get(mid)
        own = (mod.download or {}).get("type") == "leonida"   # Leonida's own files: made locally, never fetched
        if archive is None and not own:
            rep.no_download.append(mid)        # never downloaded again by Repair
            continue
        for st in session.log.steps:           # its old steps: gone with the game's repair, never rolled back
            if _mod_of(st) == mid and st.status == "done":
                st.status = LOST
                st.notes.append("the game lost this mod's files (repaired or reinstalled); installed again by Repair")
        session.log.save()
        try:
            if archive is None and own:
                from . import downloader

                archive = downloader.download(downloader.plan_for(mod), session.config.downloads())
            inst.install(mod, archive)
            rep.repaired.append(mid)
        except (InstallError, OSError) as exc:
            rep.failed[mid] = str(exc)
    try:
        rep.settings = session.apply_settings(ui)
    except (InstallError, OSError) as exc:
        rep.failed["settings"] = str(exc)
    log.info("repair: repaired %s, no download %s, by hand %s, failed %s", rep.repaired, rep.no_download,
             rep.by_hand, list(rep.failed))
    return rep


class QuietUI:
    """Repair without questions: yes to the expected ones, no waiting for a person (guided steps are listed)."""

    def info(self, msg: str) -> None:
        log.info("repair: %s", msg)

    def warn(self, msg: str) -> None:
        log.warning("repair: %s", msg)

    def confirm(self, msg: str, default: bool = True) -> bool:
        return default

    def wait_done(self, title: str, steps: list[str], folder: Path | None) -> bool:
        return False

    def launch(self, path: Path) -> None:
        log.info("repair: not launching %s", path)
