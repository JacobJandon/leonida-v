"""Ready-made setups in the launcher (leonida/setups.py, setups.json): big picture cards with what you get, what the
PC needs, the game build it was play-tested on and the best one for this PC marked. "Use this setup" = choose it
(the pack switch asks about installed mods first), then the setup flow downloads and installs it. Export / Import a
setup file to share a choice. Shown in Browse ("Setups") and in the first-run setup's modpack step."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from .. import PACK_NAME
from .. import setups as SU
from . import widgets as W

CARD_W = 360


def needs_text(s: SU.Setup) -> str:
    need = s.pc or {}
    bits = []
    if "ramMinGB" in need:
        bits.append(f"{need['ramMinGB']} GB RAM")
    if "vramMinGB" in need:
        bits.append(f"{need['vramMinGB']} GB video memory")
    if need.get("gpu") == "rtx50":
        bits.append("an RTX 50-series card")
    elif need.get("rtx"):
        bits.append("an RTX card")
    return "Needs " + ", ".join(bits) if bits else "Runs on most PCs"


def what_you_get(win, s: SU.Setup) -> str:
    base = win.session.base_manifest
    pack = base.packs.get(s.pack)
    try:
        n = len(base.pack_mod_ids(s.pack, s.addons, s.variant))
    except Exception:  # noqa: BLE001 - a setup naming something the manifest lost: say less, never break the page
        n = 0
    variant = pack.variant(s.variant) if pack is not None and s.variant else None
    parts = [f"{n} mods" if n else "", pack.name if pack else s.pack, variant.name if variant else ""]
    if s.addons:
        names = [base.addons[a].name for a in s.addons if a in base.addons]
        parts.append(f"{len(s.addons)} add-on{'s' if len(s.addons) != 1 else ''}"
                     + (f" ({', '.join(names[:3])}{'…' if len(names) > 3 else ''})" if names else ""))
    return " · ".join(p for p in parts if p)


class SetupCard(QFrame):
    """One setup: cover, name, badges (best for this PC / chosen / doesn't fit), what you get, needs, tested on, and
    "Use this setup"."""

    def __init__(self, win, setup: SU.Setup, *, best: bool, chosen: bool, fit: tuple[bool, list[str]],
                 on_use, width: int = CARD_W, cover_h: int = 170):
        super().__init__()
        self.setup = setup
        self.setProperty("card", True)
        self.setProperty("selected", chosen)
        self.setFixedWidth(width)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 14)
        lay.setSpacing(6)
        from .launcher import thumb

        self.cover = thumb(width, cover_h, setup.pack)
        pack = win.session.base_manifest.packs.get(setup.pack)
        if pack is not None and pack.picture:
            win.pictures.bind(self.cover, f"pack:{pack.id}", pack.picture, None)
        elif pack is not None:
            ids = win.session.base_manifest.pack_mod_ids(setup.pack, setup.addons, setup.variant)
            mod = next((m for m in win.session.base_manifest.mods.values() if m.id in ids and getattr(m, "image", None)),
                       None)
            if mod is not None:
                win.pictures.bind_mod(self.cover, mod)
        lay.addWidget(self.cover)
        body = QVBoxLayout()
        body.setContentsMargins(14, 4, 14, 0)
        body.setSpacing(6)
        body.addWidget(W._label(setup.name, "subtitle", wrap=True))
        chips, flow = W.flow_box(6)
        ok, why = fit
        if chosen:
            flow.addWidget(W.Badge("Your setup", "info"))
        if best:
            flow.addWidget(W.Badge("Best for this PC", "success"))
        if not ok:
            flow.addWidget(W.Badge("Too much for this PC", "warning", "; ".join(why)))
        flow.addWidget(W.Badge(f"Tested on {', '.join(setup.tested_on)}" if setup.tested_on else "Not play-tested yet",
                               "success" if setup.tested_on else None))
        body.addWidget(chips)
        from .launcher import summary_of

        desc = W._label(summary_of(setup.description, 110 if width < CARD_W else 170), "caption", wrap=True)
        desc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        desc.setFixedHeight(desc.fontMetrics().lineSpacing() * 3 + 4)   # every card the same height
        desc.setToolTip(setup.description)
        body.addWidget(desc)
        self.get = W._label(what_you_get(win, setup), None, wrap=True)
        self.get.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.get.setFixedHeight(self.get.fontMetrics().lineSpacing() * 3 + 4)    # the buttons line up
        body.addWidget(self.get)
        self.needs = W._label(needs_text(setup), "caption", None if ok else "warning", wrap=True)
        self.needs.setToolTip("" if ok else "This PC: " + "; ".join(why))
        body.addWidget(self.needs)
        row = QHBoxLayout()
        row.addStretch()
        self.use_btn = W.button("Your setup ✓" if chosen else "Use this setup", "secondary" if chosen else "primary",
                                lambda: on_use(setup.id))
        self.use_btn.setEnabled(not chosen)
        row.addWidget(self.use_btn)
        body.addLayout(row)
        lay.addLayout(body)


def fill(win, lay, on_use, *, compact: bool = False) -> list[SetupCard]:
    """The setups of the game's edition into ``lay``: a header (this PC, Export / Import) and the cards."""
    s = win.session
    edition = s.manifest.edition
    try:
        items = SU.load(edition)
    except (OSError, ValueError, KeyError) as exc:
        lay.addWidget(W._label(f"The setups couldn't be read: {exc}", "caption", "warning", wrap=True))
        return []
    pc = s.pc_specs()
    items.sort(key=lambda x: (not SU.fits(x, pc)[0], -x.rank))      # what this PC runs first, best first
    best = SU.best_for(pc, edition)
    mine = SU.chosen(s)
    head = QHBoxLayout()
    head.addWidget(W._label(f"This PC: {pc.describe()}" + (f"  ·  best fit: {best.name}" if best else ""),
                            "caption", wrap=True), 1)
    if not compact:
        head.addWidget(W.button("Import a setup file…", "ghost", lambda: import_file(win, on_use)))
        exp = W.button("Export my setup…", "ghost", lambda: export_file(win))
        exp.setEnabled((s.state / "pack.json").is_file())
        head.addWidget(exp)
    lay.addLayout(head)
    holder, flow = W.flow_box(16)
    cards = []
    for x in items:
        card = SetupCard(win, x, best=bool(best and best.id == x.id), chosen=x.id == mine, fit=SU.fits(x, pc),
                         on_use=on_use, width=300 if compact else CARD_W, cover_h=120 if compact else 170)
        flow.addWidget(card)
        cards.append(card)
    lay.addWidget(holder)
    if not items:
        lay.addWidget(W.EmptyState("pack", "No ready-made setups for this edition yet",
                                   "Pick a modpack instead: Browse > Modpacks."))
    return cards


def choose(win, setup_id: str, data: SU.Setup | None = None) -> bool:
    """Switch to the setup (the pack page's own switch: it asks about installed mods first). True when it's chosen."""
    s = win.session
    x = data or SU.get(setup_id, s.manifest.edition)
    if not win.pages[2].switch(x.pack, list(x.addons), x.variant):
        return False
    if data is None:
        SU.remember(s, x.id)
    return True


def use_setup(win, setup_id: str) -> bool:
    """One click: ask once, choose the setup, then the setup flow downloads everything and installs it."""
    s = win.session
    x = SU.get(setup_id, s.manifest.edition)
    ok, why = SU.fits(x, s.pc_specs())
    ask = (f"Use the setup “{x.name}”?\n\n{what_you_get(win, x)}\n\nLeonida switches your modpack (it asks before "
           "removing installed mods), downloads the mods from their authors' pages and installs them one logged step "
           "at a time." + ("" if ok else f"\n\nThis PC may be too small for it: {'; '.join(why)}."))
    if QMessageBox.question(win, PACK_NAME, ask) != QMessageBox.StandardButton.Yes:
        return False
    if not choose(win, setup_id):
        return False
    win.notify(f"Setup: {x.name}. Downloading, then installing.", "success")
    win.setup_flow.run_setup()
    return True


def export_file(win) -> Path | None:
    s = win.session
    try:
        data = SU.export(s, "My setup")
    except ValueError as exc:
        QMessageBox.information(win, PACK_NAME, str(exc))
        return None
    path, _f = QFileDialog.getSaveFileName(win, "Export my setup", str(Path.home() / "leonida-setup.json"),
                                           "Leonida setup (*.json)")
    if not path:
        return None
    try:
        Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        QMessageBox.warning(win, PACK_NAME, f"Couldn't save it: {exc}")
        return None
    win.notify(f"Setup saved to {path}. Anyone with Leonida can import it (no paths or personal data in it).",
               "success")
    return Path(path)


def import_file(win, on_use=None) -> bool:
    path, _f = QFileDialog.getOpenFileName(win, "Import a setup file", str(Path.home()), "Leonida setup (*.json)")
    if not path:
        return False
    s = win.session
    try:
        x = SU.parse_import(s, json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError) as exc:
        QMessageBox.warning(win, PACK_NAME, f"Not imported: {exc}")
        return False
    ask = f"Use the imported setup “{x.name}”?\n\n{what_you_get(win, x)}"
    if QMessageBox.question(win, PACK_NAME, ask) != QMessageBox.StandardButton.Yes:
        return False
    if not choose(win, x.id, data=x):
        return False
    win.notify(f"Setup imported: {x.name}. Get mods and Install take it from here.", "success")
    return True


class SetupsView(QWidget):
    """Browse > Setups."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.lay = QVBoxLayout(W.clear_background(self))
        self.lay.setContentsMargins(0, 12, 0, 0)
        self.lay.setSpacing(12)
        self.cards: list[SetupCard] = []
        self._key = None

    def refresh(self, force: bool = False) -> None:
        s = self.win.session
        f = Path(s.state) / SU.STATE_FILE
        key = (s.stamp(), f.stat().st_mtime_ns if f.is_file() else None)
        if key == self._key and not force:
            return
        self._key = key
        _clear_all(self.lay)
        self.cards = fill(self.win, self.lay, lambda sid: use_setup(self.win, sid))
        self.lay.addStretch()

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)


def _clear_all(lay) -> None:
    """Widgets and nested layouts out of ``lay``."""
    while lay.count():
        item = lay.takeAt(0)
        if item.widget() is not None:
            w = item.widget()
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _clear_all(item.layout())
