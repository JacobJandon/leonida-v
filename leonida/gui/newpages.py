"""Pages for the redesign, self-contained and driven by a Session.

    ModpackPage(session)      "Choose your modpack": a big picture card per modpack (Manifest.packs), "Your own mods"
    editions_from(installs)   detected game folders -> the Enhanced / Legacy choices for widgets.EditionPicker
    PlaytestView(session)     "Play test": runs leonida.playtest on a worker thread with the live PlaytestPanel
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from .. import PACK_NAME
from . import widgets as W
from .workers import start_worker

EXE_EDITION = {"gta5_enhanced.exe": "Enhanced", "gta5.exe": "Legacy"}
EDITION_LABEL = {"enhanced": "Enhanced", "legacy": "Legacy"}
LABEL_EDITION = {v: k for k, v in EDITION_LABEL.items()}
EDITION_TEXT = {"enhanced": "GTA V Enhanced", "legacy": "GTA V Legacy"}


# ------------------------------------------------------------------------------------------- modpacks
class ModpackPage(QWidget):
    """One big picture card per modpack of the edition in use (``Manifest.packs``: modpacks.json, or one per profile
    without it). Clicking a card selects it; ``choose`` saves it (ChoosePage switches with the rollback question)."""

    pack_chosen = Signal(str)
    add_own_mod = Signal()
    next_requested = Signal()

    def __init__(self, session, gpus: list[str] | None = None, images=None, parent: QWidget | None = None,
                 pictures=None):
        super().__init__(parent)
        self.session = session
        self.gpus = gpus
        self.images = images
        self.pictures = pictures   # the window's picture decoder (off the UI thread), when there is one
        self.cards: dict[str, W.PackCard] = {}
        self.selected: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        self.edition_badge = W.Badge("", "info")
        lay.addWidget(W.PageHeader(None, 7, "Choose your modpack",
                                   "Pick a starting point. Add or remove add-ons on the next page; switching packs "
                                   "later rolls back what isn't in the new one.", self.edition_badge))
        self.holder, self.flow = W.flow_box(16)
        self.scroll = scroll = QScrollArea()
        scroll.setWidget(self.holder)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(scroll, 1)
        own, ol = _card()
        row = QHBoxLayout()
        row.addWidget(W._icon_label("mods", W.C["coral"], 20))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(W._label("Your own mods", "subtitle"))
        self.own_caption = W._label("", "caption", wrap=True)
        col.addWidget(self.own_caption)
        row.addLayout(col, 1)
        self.add_btn = W.button("Add a mod", "secondary", self.add_own_mod.emit, "download")
        row.addWidget(self.add_btn)
        ol.addLayout(row)
        lay.addWidget(own)
        self.next_btn = W.button("Next: add-ons  →", "primary", self.next_requested.emit, glow=True)
        lay.addWidget(W.ActionBar(right=[self.next_btn]))
        if images is not None:
            images.loaded.connect(self._image_loaded)
        self.rebuild()

    def rebuild(self) -> None:
        """(Re)build the cards for the session's edition (after a game folder of the other edition is picked)."""
        while self.flow.count():
            w = self.flow.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.cards = {}
        s = self.session
        base = s.base_manifest
        rtx50 = _is_rtx50(self.gpus)
        self.edition_badge.setText(f"Mods for {EDITION_TEXT.get(base.edition, base.edition)}")
        default = base.default_pack or base.default_profile
        for pid, pack in base.packs.items():
            try:
                ids = base.pack_mod_ids(pid)
            except Exception:  # noqa: BLE001 - a broken pack still gets a card, with 0 mods
                ids = set()
            mods = [base.mods[i] for i in ids if i in base.mods]
            paid = any(getattr(m, "is_paid", False) for m in mods)
            needs = (pack.requires or {}).get("gpu")
            locked = needs == "rtx50" and not rtx50
            badges = [("Paid add-ons by creators", "warning") if paid else ("Free", "success")]
            if needs == "rtx50":
                badges.append(("RTX 50 only", "warning" if locked else "success"))
            if pack.variants:
                badges.append((f"{len(pack.variants)} variants", None))
            addons = sum(len(lst) for lst in base.addons_for(pid).values())
            card = W.PackCard(pid, pack.name, pack.description, mods=len(mods), addons=addons, badges=badges,
                              recommended=pid == default)
            if locked:
                card.setEnabled(False)
                card.setProperty("disabled", True)
                card.setToolTip("Needs an NVIDIA RTX 50-series GPU")
            card.clicked.connect(self.select)
            self.cards[pid] = card
            self.flow.addWidget(card)
            if self.images is not None and pack.picture:
                self.images.request(f"pack:{pid}", pack.picture, None)
        try:
            n = len(s.custom_entries())
        except Exception:  # noqa: BLE001 - a broken custom-mods.json is reported on the add-ons page
            n = 0
        self.own_caption.setText(
            (f"You have {n} of your own. " if n else "") + "Add any mod from a file or a page link: it gets the same "
            "logged install, rollback and online-safe handling.")
        self._fit_cards()
        current = s.pack_choice().pack
        enabled = [pid for pid, c in self.cards.items() if c.isEnabled()]
        self.selected = None
        pick = current if current in enabled else (enabled[0] if enabled else None)
        if pick:
            self.select(pick)

    def _image_loaded(self, key: str, path: str) -> None:
        card = self.cards.get(key[len("pack:"):]) if key.startswith("pack:") else None
        if card is not None and path:
            pictures = self.pictures
            if pictures is not None:
                pictures.show(card.art, path)          # decoded off the UI thread
            else:
                card.art.set_pixmap(QPixmap(path))

    def select(self, pack_id: str) -> None:
        card = self.cards.get(pack_id)
        if card is None or not card.isEnabled():
            return
        self.selected = pack_id
        for pid, c in self.cards.items():
            c.set_selected(pid == pack_id)
        QTimer.singleShot(0, self._show_selected)  # once the cards are laid out
        self.pack_chosen.emit(pack_id)

    CARD_MIN, CARD_MAX, GAP = 220, 300, 16

    def _fit_cards(self) -> None:
        """As many pack cards per row as fit (up to 300 px each), so four packs sit side by side on a normal window."""
        width = self.scroll.viewport().width() - 2
        if width <= 0 or not self.cards:
            return
        cols = max(1, min(len(self.cards), (width + self.GAP) // (self.CARD_MIN + self.GAP)))
        w = min(self.CARD_MAX, (width - self.GAP * (cols - 1)) // cols)
        for card in self.cards.values():
            card.setFixedWidth(w)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_cards)  # the scroll area gets its new width after this event

    def _show_selected(self) -> None:
        card = self.cards.get(self.selected or "")
        if card is not None and self.scroll.widget() is not None:
            self.scroll.ensureVisible(card.x(), card.y(), 0, 16)  # its top (picture) in view; no jump if it is

    def choose(self) -> str | None:
        """Save the selected pack (with its default add-ons and variant) unless it's already the chosen one."""
        if self.selected:
            s = self.session
            if s.pack_choice().pack != self.selected or s.config.profile != self.selected:
                s.choose_pack(self.selected)
        return self.selected


def _is_rtx50(gpus: list[str] | None) -> bool:
    from ..detect import is_rtx50

    return bool(gpus) and is_rtx50(gpus)


def _card():
    from PySide6.QtWidgets import QFrame

    f = QFrame()
    f.setProperty("card", True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(6)
    return f, lay


# ------------------------------------------------------------------------------------------- editions
def editions_from(installs) -> list[tuple[str, str | None, str | None]]:
    """detect.GameInstall list -> [("Enhanced", folder, build), ("Legacy", folder, build)] for EditionPicker.

    The edition comes from ``GameInstall.edition`` (detect_games reads it from the exe), else from the exe's name.
    The first install of each edition wins (detect_games lists the best guess first)."""
    found: dict[str, tuple[str, str | None]] = {}
    for g in installs:
        edition = EDITION_LABEL.get(getattr(g, "edition", None) or "") or EXE_EDITION.get(Path(g.exe).name.lower())
        if edition and edition not in found:
            found[edition] = (str(g.path), g.version)
    return [(name, *found.get(name, (None, None))) for name in ("Enhanced", "Legacy")]


# ------------------------------------------------------------------------------------------- play test
class PlaytestView(QWidget):
    """Start button + PlaytestPanel. The play test closes GTA if it's open, so it asks first."""

    finished = Signal(object)  # the PlaytestReport
    failed = Signal(str)

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.thread = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.panel = W.PlaytestPanel()
        lay.addWidget(self.panel)
        row = QHBoxLayout()
        self.keep = QCheckBox("Leave the game running afterwards")
        row.addWidget(self.keep)
        row.addStretch()
        self.start_btn = W.button("Play test", "primary", self.start, "play", glow=True)
        row.addWidget(self.start_btn)
        lay.addLayout(row)
        self.toast = W.Toast()
        lay.addWidget(self.toast)

    def start(self) -> bool:
        if self.thread is not None:
            return False
        answer = QMessageBox.question(
            self, PACK_NAME, "The play test closes GTA V if it's running, starts it again from PlayGTAV.exe and waits "
            "for story mode (up to 5 minutes). Save your game first. Start it now?")
        if answer != QMessageBox.StandardButton.Yes:
            return False
        from . import memcheck

        if not memcheck.confirm(self):  # low free memory: close apps (the user's pick) / play anyway / cancel
            return False
        from .. import playtest

        keep = self.keep.isChecked()
        self.panel.start()
        self.start_btn.setEnabled(False)
        self.thread = start_worker(self, lambda progress: playtest.playtest(self.session, keep_running=keep,
                                                                           progress=progress),
                                   on_done=self._done, on_fail=self._fail, on_progress=self.panel.on_progress,
                                   pass_progress=True)
        return True

    def _done(self, report) -> None:
        self.thread = None
        self.start_btn.setEnabled(True)
        self.panel.show_report(report)
        tone = "success" if getattr(report, "ok", False) else "error"
        self.toast.show_message(report.message, tone, timeout_ms=0 if tone == "error" else 8000)
        self.finished.emit(report)

    def _fail(self, msg: str) -> None:
        self.thread = None
        self.start_btn.setEnabled(True)
        self.panel.timer.stop()
        self.panel.pill.set_status("failed", "couldn't run")
        self.toast.show_message(f"The play test couldn't run: {msg}", "error")
        self.failed.emit(msg)
