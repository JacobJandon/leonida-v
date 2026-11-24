"""Leonida V wizard: Welcome -> Game -> Profile -> Get mods -> Check -> Install -> Manage."""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import PACK_NAME, __version__
from ..checks import ERROR, INFO, WARNING, has_errors
from ..detect import detect_games, find_exe, is_rtx50
from ..installer import InstallError
from ..matcher import build_lock, write_lock
from ..onlinesafe import OnlineSafeError, go_online_safe, restore_mods
from ..onlinesafe import status as online_status
from ..paths import LOCK_NAME
from ..session import Session

PAGES = ("Welcome", "Game", "Profile", "Get mods", "Check", "Install", "Manage")
HUD_CHOICES = (("hud", "GTA VI Inspired HUD & Radar (recommended)"),
               ("hud-fbicat", "GTA VI HUD by fbicat (Discord)"),
               ("hud-geckomacabre", "GTA VI Inspired HUD for Enhanced (geckomacabre)"))


def _title(text: str) -> QLabel:
    lab = QLabel(text)
    f = QFont()
    f.setPointSize(16)
    f.setBold(True)
    lab.setFont(f)
    return lab


def _wrap(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setOpenExternalLinks(True)
    return lab


def _open(path_or_url: str) -> None:
    if os.environ.get("LEONIDA_NO_OPEN"):
        return
    if path_or_url.startswith("http"):
        webbrowser.open_new_tab(path_or_url)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path_or_url))


# ----------------------------------------------------------------------- UI bridge
class GuiUI:
    """Implements the installer's UI protocol with dialogs."""

    def __init__(self, parent: QWidget, log_view: QPlainTextEdit):
        self.parent = parent
        self.view = log_view

    def info(self, msg: str) -> None:
        self.view.appendPlainText(msg)
        QApplication.processEvents()

    def warn(self, msg: str) -> None:
        self.view.appendPlainText("! " + msg)

    def confirm(self, msg: str, default: bool = True) -> bool:
        return QMessageBox.question(self.parent, PACK_NAME, msg) == QMessageBox.StandardButton.Yes

    def wait_done(self, title: str, steps: list[str], folder: Path | None) -> bool:
        dlg = QDialog(self.parent)
        dlg.setWindowTitle(f"Manual step: {title}")
        lay = QVBoxLayout(dlg)
        lay.addWidget(_title(title))
        text = "".join(f"<li>{s}</li>" for s in steps) or "<li>Follow the mod's readme.</li>"
        lay.addWidget(_wrap(f"<ol>{text}</ol>"))
        if folder:
            btn = QPushButton(f"Open files: {folder}")
            btn.clicked.connect(lambda: _open(str(folder)))
            lay.addWidget(btn)
            _open(str(folder))
        box = QDialogButtonBox()
        box.addButton("Done", QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        return dlg.exec() == QDialog.DialogCode.Accepted

    def launch(self, path: Path) -> None:
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", str(path)], cwd=str(path.parent))
        self.info(f"Started {path.name}. Finish its installer, then click Done in the next window.")


# ---------------------------------------------------------------------------- pages
class WelcomePage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(_title(f"{PACK_NAME} {__version__}"))
        lay.addWidget(_wrap(
            "Turns GTA V Enhanced into a GTA VI-style experience with a curated, conflict-checked mod list.<br><br>"
            "<b>Story mode only.</b> Mods in GTA Online can get your account banned. Use the "
            "<i>Online-safe</i> switch on the last page before going online.<br><br>"
            "Before you start: back up your saves, turn off automatic game updates, and turn off "
            "BattlEye in the Rockstar Games Launcher (story mode).<br><br>"
            "Leonida V never re-hosts mods: it opens each author's page, finds your downloads, "
            "installs them in order, and logs every file so it can undo everything."))
        lay.addStretch()


class GamePage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Find GTA V Enhanced"))
        self.list = QListWidget()
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for text, fn in (("Detect", self.detect), ("Browse...", self.browse)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.current = QLabel()
        lay.addWidget(self.current)
        self.list.itemClicked.connect(lambda it: self.set_dir(it.data(Qt.ItemDataRole.UserRole)))
        self.refresh()

    def refresh(self) -> None:
        s = self.win.session
        self.current.setText(f"Selected: {s.config.game_dir or '(none)'}   version: {s.game_version() or 'unknown'}")

    def detect(self) -> None:
        self.list.clear()
        games = detect_games(self.win.session.manifest.exe_names)
        for g in games:
            it = QListWidgetItem(f"{g.path}   [{g.source}]   {g.version or ''}")
            it.setData(Qt.ItemDataRole.UserRole, str(g.path))
            self.list.addItem(it)
        if games and not self.win.session.config.game_dir:
            self.set_dir(str(games[0].path))
        if not games:
            self.list.addItem("Not found automatically. Use Browse...")

    def browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "GTA V Enhanced folder")
        if d:
            self.set_dir(d)

    def set_dir(self, d: str | None) -> None:
        if not d:
            return
        s = self.win.session
        if not find_exe(Path(d), s.manifest.exe_names):
            QMessageBox.warning(self, PACK_NAME, f"No {', '.join(s.manifest.exe_names)} in that folder.")
            return
        s.config.game_dir = d
        s.save()
        self.refresh()


class ProfilePage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        s = win.session
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Choose a profile"))
        gpus = s.gpus()
        lay.addWidget(QLabel(f"GPU: {', '.join(gpus) or 'unknown'}"))
        self.group = QButtonGroup(self)
        for p in s.manifest.profiles.values():
            rb = QRadioButton(f"{p.name}: {p.description}")
            rb.setProperty("pid", p.id)
            if p.requires.get("gpu") == "rtx50" and not is_rtx50(gpus):
                rb.setEnabled(False)
                rb.setText(rb.text() + "  (needs an RTX 50-series GPU)")
            rb.setChecked(p.id == s.profile_id)
            self.group.addButton(rb)
            lay.addWidget(rb)
        self.group.buttonClicked.connect(self.pick)
        lay.addWidget(QLabel("HUD:"))
        self.hud = QComboBox()
        current = next((new for old, new in s.config.swaps.items() if old == "hud"), "hud")
        for mid, label in HUD_CHOICES:
            self.hud.addItem(label, mid)
        self.hud.setCurrentIndex(max(0, [m for m, _ in HUD_CHOICES].index(current)))
        self.hud.currentIndexChanged.connect(self.pick_hud)
        lay.addWidget(self.hud)
        lay.addStretch()

    def pick(self, rb: QRadioButton) -> None:
        self.win.session.config.profile = rb.property("pid")
        self.win.session.save()

    def pick_hud(self) -> None:
        s = self.win.session
        mid = self.hud.currentData()
        if mid == "hud":
            s.config.swaps.pop("hud", None)
        else:
            s.config.swaps["hud"] = mid
        s.save()


class GetPage(QWidget):
    COLS = ("#", "Mod", "Status", "File / page")

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Get the mods"))
        self.hint = _wrap("")
        lay.addWidget(self.hint)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.open_row)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, fn in (("Open all missing pages", self.open_missing), ("Open download folder", self.open_folder),
                         ("Assign a file...", self.assign), ("Rescan", self.refresh)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, e) -> None:  # noqa: N802 - Qt naming
        self.refresh()
        self.timer.start(3000)
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self.timer.stop()
        super().hideEvent(e)

    def refresh(self) -> None:
        s = self.win.session
        folder = s.config.downloads()
        folder.mkdir(parents=True, exist_ok=True)
        mods = s.mods()
        res = s.matches(mods)
        self.mods, self.result = mods, res
        self.table.setRowCount(len(mods))
        for r, m in enumerate(mods):
            f = res.matched.get(m.id)
            vals = (str(m.order), m.name, "ready" if f else "missing", f.name if f else m.page)
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        missing = len(res.missing(mods))
        extra = ""
        if res.ambiguous or res.unmatched:
            extra = f"<br>{len(res.ambiguous) + len(res.unmatched)} file(s) not recognised: use <i>Assign a file</i>."
        self.hint.setText(f"Save every download into <b>{folder}</b>. Double-click a row to open its page. "
                          f"<b>{len(mods) - missing}/{len(mods)}</b> ready.{extra}")
        if not missing:
            write_lock(s.state / LOCK_NAME, build_lock(s.manifest.pack, s.manifest.version, res.matched))

    def open_row(self, row: int, _col: int) -> None:
        _open(self.mods[row].page)

    def open_missing(self) -> None:
        for m in self.result.missing(self.mods):
            _open(m.page)

    def open_folder(self) -> None:
        _open(str(self.win.session.config.downloads()))

    def assign(self) -> None:
        s = self.win.session
        files = [p.name for p in list(self.result.ambiguous) + self.result.unmatched]
        if not files:
            QMessageBox.information(self, PACK_NAME, "Every file in the folder is already recognised.")
            return
        f, ok = QInputDialog.getItem(self, PACK_NAME, "File:", files, 0, False)
        if not ok:
            return
        names = [f"{m.id}  ({m.name})" for m in self.mods]
        m, ok = QInputDialog.getItem(self, PACK_NAME, f"{f} is:", names, 0, False)
        if ok:
            s.config.assignments[f] = m.split()[0]
            s.save()
            self.refresh()


class CheckPage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Checks"))
        self.list = QListWidget()
        lay.addWidget(self.list)
        b = QPushButton("Run checks again")
        b.clicked.connect(self.refresh)
        lay.addWidget(b)

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)

    def refresh(self) -> None:
        self.list.clear()
        findings = self.win.session.findings()
        tag = {ERROR: "ERROR", WARNING: "WARNING", INFO: "info"}
        for f in findings:
            self.list.addItem(f"{tag[f.level]}: {f.message}")
        if not findings:
            self.list.addItem("All checks passed.")
        self.has_errors = has_errors(findings)


class InstallPage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Install"))
        lay.addWidget(_wrap("Mods install one at a time, in order. After each step, launch story mode and "
                            "drive for a minute, then continue or undo that step."))
        self.steps = QListWidget()
        lay.addWidget(self.steps)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        lay.addWidget(self.view)
        row = QHBoxLayout()
        self.next_btn = QPushButton("Install next")
        self.next_btn.clicked.connect(self.install_next)
        self.dry_btn = QPushButton("Dry run (show plan)")
        self.dry_btn.clicked.connect(self.dry_run)
        row.addWidget(self.next_btn)
        row.addWidget(self.dry_btn)
        lay.addLayout(row)

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)

    def todo(self):
        s = self.win.session
        done = s.log.installed_mods()
        return [m for m in s.mods() if m.id not in done]

    def refresh(self) -> None:
        s = self.win.session
        done = s.log.installed_mods()
        self.steps.clear()
        for m in s.mods():
            self.steps.addItem(f"{'[done]' if m.id in done else '[    ]'}  {m.order:>2}. {m.name}")
        self.next_btn.setEnabled(bool(self.todo()) and bool(s.game_dir()))

    def dry_run(self) -> None:
        s = self.win.session
        ui = GuiUI(self, self.view)
        inst = s.installer(ui, dry_run=True)
        res = s.matches()
        for m in self.todo():
            inst.install(m, res.matched.get(m.id))

    def install_next(self) -> None:
        s = self.win.session
        todo = self.todo()
        if not todo:
            return
        m = todo[0]
        res = s.matches()
        if m.id not in res.matched:
            QMessageBox.warning(self, PACK_NAME, f"{m.name} is not downloaded yet (see Get mods).")
            return
        ui = GuiUI(self, self.view)
        inst = s.installer(ui)
        try:
            step = inst.install(m, res.matched[m.id])
        except InstallError as exc:
            QMessageBox.critical(self, PACK_NAME, str(exc))
            self.refresh()
            return
        self.view.appendPlainText(f"Step {step.id} done: {m.name} ({len(step.actions)} change(s) logged).")
        box = QMessageBox(self)
        box.setWindowTitle("Test now")
        box.setText(f"{m.name} is installed. Launch story mode, drive for a minute, then come back.")
        keep = box.addButton("Works - continue", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Undo this step", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is not keep:
            for w in inst.rollback(step.id):
                ui.warn(w)
            self.view.appendPlainText(f"Step {step.id} undone.")
        self.refresh()


class ManagePage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Manage"))
        self.state = QLabel()
        lay.addWidget(self.state)
        for text, fn in (("Online-safe ON (move mods out)", self.safe_on),
                         ("Online-safe OFF (bring mods back)", self.safe_off),
                         ("Undo last step", self.undo_last),
                         ("Uninstall everything", self.uninstall)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            lay.addWidget(b)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        lay.addWidget(self.view)

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)

    def refresh(self) -> None:
        s = self.win.session
        g = s.game_dir()
        st = online_status(g, s.manifest.online_safe_items) if g and g.is_dir() else "no game folder"
        self.state.setText(f"Mods: {st}   |   steps installed: {len(s.log.installed_mods())}")

    def _guard(self, fn) -> None:
        try:
            fn()
        except (OnlineSafeError, InstallError, RuntimeError) as exc:
            QMessageBox.warning(self, PACK_NAME, str(exc))
        self.refresh()

    def safe_on(self) -> None:
        s = self.win.session
        self._guard(lambda: self.view.appendPlainText(
            f"Moved out: {', '.join(go_online_safe(s.game_dir(), s.manifest.online_safe_items)) or 'nothing'}"))

    def safe_off(self) -> None:
        s = self.win.session
        self._guard(lambda: self.view.appendPlainText(f"Restored: {', '.join(restore_mods(s.game_dir()))}"))

    def undo_last(self) -> None:
        s = self.win.session
        last = s.log.last_active()
        if not last:
            return
        self._guard(lambda: [self.view.appendPlainText("! " + w)
                             for w in s.installer(GuiUI(self, self.view)).rollback(last.id)])

    def uninstall(self) -> None:
        if QMessageBox.question(self, PACK_NAME, "Undo every Leonida V step?") != QMessageBox.StandardButton.Yes:
            return
        s = self.win.session

        def run():
            warnings, residual = s.installer(GuiUI(self, self.view)).uninstall()
            for w in warnings:
                self.view.appendPlainText("! " + w)
            self.view.appendPlainText("Game folder matches the pre-install snapshot."
                                      if residual is not None and residual.empty
                                      else f"Differences left: {residual.summary() if residual else 'no baseline'}")
        self._guard(run)


# ---------------------------------------------------------------------------- window
class MainWindow(QMainWindow):
    def __init__(self, session: Session | None = None):
        super().__init__()
        self.session = session or Session()
        self.setWindowTitle(f"{PACK_NAME} {__version__}")
        self.resize(980, 640)
        central = QWidget()
        outer = QHBoxLayout(central)
        self.nav = QListWidget()
        self.nav.setFixedWidth(160)
        self.nav.addItems(PAGES)
        outer.addWidget(self.nav)
        right = QVBoxLayout()
        self.stack = QStackedWidget()
        self.pages = [cls(self) for cls in (WelcomePage, GamePage, ProfilePage, GetPage,
                                            CheckPage, InstallPage, ManagePage)]
        for p in self.pages:
            self.stack.addWidget(p)
        right.addWidget(self.stack)
        row = QHBoxLayout()
        self.back = QPushButton("Back")
        self.fwd = QPushButton("Next")
        self.back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        self.fwd.clicked.connect(lambda: self.go(self.stack.currentIndex() + 1))
        row.addStretch()
        row.addWidget(self.back)
        row.addWidget(self.fwd)
        right.addLayout(row)
        outer.addLayout(right)
        self.setCentralWidget(central)
        self.nav.currentRowChanged.connect(self.go)
        self.go(0)

    def go(self, i: int) -> None:
        i = max(0, min(i, len(self.pages) - 1))
        self.stack.setCurrentIndex(i)
        if self.nav.currentRow() != i:
            self.nav.setCurrentRow(i)
        self.back.setEnabled(i > 0)
        self.fwd.setEnabled(i < len(self.pages) - 1)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
