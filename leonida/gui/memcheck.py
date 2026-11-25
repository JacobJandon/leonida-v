"""The low-memory step before the game starts (Play, Play test).

    if not memcheck.confirm(win):        # True: go ahead (memory fine, apps closed, or "Play anyway")
        return "Cancelled."

When free memory is low (under 6 GB of RAM or 12 GB of commit; leonida/memwatch.check_memory), a dialog says
"GTA may crash while loading: free memory is low", lists the biggest memory users by name and offers:
  - "Close them and play": closes only the apps the user ticked (none are ticked to begin with), each asked to
    close like clicking its X (never forced, so they can save); Windows, security, the game and Leonida are
    never offered;
  - "Play anyway";
  - "Cancel".
Nothing is ever closed without that click. With the offscreen platform (tests, screenshots) nobody can answer a
dialog, so the check is skipped unless a memory source is passed in.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .. import PACK_NAME
from .. import memwatch as M

log = logging.getLogger("leonida.gui")

CLOSE, ANYWAY, CANCEL = "close", "anyway", "cancel"


class MemoryDialog(QDialog):
    def __init__(self, chk: M.MemoryCheck, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(PACK_NAME)
        self.choice = CANCEL
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{M.LOW_HEADLINE}</b>")
        lay.addWidget(head)
        reasons = "; ".join(chk.reasons)
        body = QLabel(f"{reasons[:1].upper()}{reasons[1:]}. With the full pack the game needs about "
                      f"{M.gb(M.LOW_FREE_MB)} of free RAM and {M.gb(M.LOW_COMMIT_MB)} of free commit (RAM + page "
                      "file) while it loads. Closing other apps helps; so does the Performance variant.")
        body.setWordWrap(True)
        lay.addWidget(body)
        self.boxes: list[QCheckBox] = []
        if chk.closeable:
            lay.addWidget(QLabel("Using the most memory now. Tick the apps to close (save your work in them first):"))
            for a in chk.closeable:
                box = QCheckBox(f"{a.name}  ({M.gb(a.mb)})")
                box.setProperty("app", a.name)
                box.toggled.connect(self._update)
                self.boxes.append(box)
                lay.addWidget(box)
        others = [a for a in chk.apps if not a.closeable]
        if others:
            note = QLabel("Also using memory (Windows, Leonida or the game; not offered): "
                          + ", ".join(f"{a.name} ({M.gb(a.mb)})" for a in others))
            note.setWordWrap(True)
            lay.addWidget(note)
        buttons = QDialogButtonBox()
        self.close_btn = QPushButton("Close them and play")
        self.anyway_btn = QPushButton("Play anyway")
        cancel = QPushButton("Cancel")
        buttons.addButton(self.close_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.anyway_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
        self.close_btn.clicked.connect(lambda: self._pick(CLOSE))
        self.anyway_btn.clicked.connect(lambda: self._pick(ANYWAY))
        cancel.clicked.connect(lambda: self._pick(CANCEL))
        self.close_btn.setVisible(bool(self.boxes))
        lay.addWidget(buttons)
        self._update()

    def picked(self) -> list[str]:
        return [b.property("app") for b in self.boxes if b.isChecked()]

    def _update(self) -> None:
        self.close_btn.setEnabled(bool(self.picked()))

    def _pick(self, choice: str) -> None:
        self.choice = choice
        (self.reject if choice == CANCEL else self.accept)()


def confirm(win: QWidget | None, mem: M.NullMemory | None = None, run_dialog=None, close_apps=M.close_apps) -> bool:
    """The low-memory step. True: start the game; False: the user cancelled. ``run_dialog(dialog)`` shows the
    dialog (default: exec, modal); tests pass their own."""
    if mem is None:
        if QGuiApplication.platformName() == "offscreen":
            return True
        mem = M.default_ops()
    chk = M.check_memory(mem)
    if not chk.low:
        return True
    log.info("low memory before playing: %s", "; ".join(chk.reasons))
    dlg = MemoryDialog(chk, win)
    (run_dialog or (lambda d: d.exec()))(dlg)
    log.info("low-memory dialog: %s %s", dlg.choice, dlg.picked() if dlg.choice == CLOSE else "")
    if dlg.choice == CANCEL:
        return False
    if dlg.choice == CLOSE and dlg.picked():
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            closed, left = close_apps(dlg.picked())
        finally:
            QGuiApplication.restoreOverrideCursor()
        if left and run_dialog is None:
            QMessageBox.information(win, PACK_NAME, f"Still running: {', '.join(left)}. Some apps only hide in the "
                                                    "tray when closed: close them from there if you like. The game "
                                                    "starts now.")
        log.info("closed %s; still running %s", closed, left)
    return True
