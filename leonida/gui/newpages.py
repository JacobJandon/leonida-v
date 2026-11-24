"""New pages for the redesign, self-contained and driven by a Session, ready to drop into app.py's wizard.

    ModpackPage(session)      "Choose your modpack": a big picture card per profile/pack, "Your own mods"
    editions_from(installs)   detected game folders -> the Enhanced / Legacy choices for widgets.EditionPicker
    PlaytestView(session)     "Play test": runs leonida.playtest on a worker thread with the live PlaytestPanel

They use only leonida/gui/widgets.py and the theme; nothing in app.py imports them yet.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from .. import PACK_NAME
from . import widgets as W
from .workers import start_worker

EXE_EDITION = {"gta5_enhanced.exe": "Enhanced", "gta5.exe": "Legacy"}


# ------------------------------------------------------------------------------------------- modpacks
class ModpackPage(QWidget):
    """One card per pack (today: the manifest's profiles). Clicking a card selects it; ``choose`` saves it."""

    pack_chosen = Signal(str)
    add_own_mod = Signal()
    next_requested = Signal()

    def __init__(self, session, gpus: list[str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.cards: dict[str, W.PackCard] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        lay.addWidget(W.PageHeader(None, 7, "Choose your modpack",
                                   "Pick a starting point. Add or remove add-ons on the next page; switching packs "
                                   "later rolls back what isn't in the new one."))
        holder, self.flow = W.flow_box(16)
        scroll = QScrollArea()
        scroll.setWidget(holder)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(scroll, 1)
        manifest = session.manifest
        rtx50 = _is_rtx50(gpus)
        for pid, prof in manifest.profiles.items():
            mods = manifest.resolve(pid, [], [], {})
            paid = any(getattr(m, "is_paid", False) for m in mods)
            needs = (prof.requires or {}).get("gpu")
            locked = needs == "rtx50" and not rtx50
            badges = [("Paid add-ons", "warning") if paid else ("Free", "success")]
            if needs == "rtx50":
                badges.append(("RTX 50 only", "warning" if locked else "success"))
            card = W.PackCard(pid, prof.name, prof.description, mods=len(mods), badges=badges,
                              recommended=pid == manifest.default_profile)
            if locked:
                card.setEnabled(False)
                card.setProperty("disabled", True)
                card.setToolTip("Needs an NVIDIA RTX 50-series GPU")
            card.clicked.connect(self.select)
            self.cards[pid] = card
            self.flow.addWidget(card)
        own, ol = _card()
        row = QHBoxLayout()
        row.addWidget(W._icon_label("mods", W.C["coral"], 20))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(W._label("Your own mods", "subtitle"))
        col.addWidget(W._label("Add any mod from a file or a page link: it gets the same logged install, rollback "
                               "and online-safe handling.", "caption", wrap=True))
        row.addLayout(col, 1)
        self.add_btn = W.button("Add a mod", "secondary", self.add_own_mod.emit, "download")
        row.addWidget(self.add_btn)
        ol.addLayout(row)
        lay.addWidget(own)
        self.next_btn = W.button("Next: add-ons  →", "primary", self.next_requested.emit, glow=True)
        lay.addWidget(W.ActionBar(right=[self.next_btn]))
        self.selected = session.profile_id if session.profile_id in self.cards else next(iter(self.cards), None)
        if self.selected:
            self.select(self.selected)

    def select(self, pack_id: str) -> None:
        card = self.cards.get(pack_id)
        if card is None or not card.isEnabled():
            return
        self.selected = pack_id
        for pid, c in self.cards.items():
            c.set_selected(pid == pack_id)
        self.pack_chosen.emit(pack_id)

    def choose(self) -> str | None:
        """Save the selected pack as the session's profile."""
        if self.selected:
            self.session.config.profile = self.selected
            self.session.save()
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

    The first install of each edition wins (detect_games lists the best guess first)."""
    found: dict[str, tuple[str, str | None]] = {}
    for g in installs:
        edition = EXE_EDITION.get(Path(g.exe).name.lower())
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
