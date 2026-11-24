"""Leonida V wizard: Welcome -> Game -> Choose mods -> Get mods -> Check -> Install -> Manage."""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import PACK_NAME, __version__
from ..checks import ERROR, INFO, WARNING, has_errors
from ..detect import detect_games, find_exe
from ..installer import InstallError, windows_launch_command
from ..manifest import Mod
from ..matcher import build_lock, write_lock
from ..onlinesafe import OnlineSafeError, go_online_safe, restore_mods
from ..onlinesafe import status as online_status
from ..paths import LOCK_NAME
from ..session import Session
from .chooser import ChoosePage, how_text
from .images import ImageLoader, network_allowed
from .workers import MainThreadCaller, start_worker

PAGES = ("Welcome", "Game", "Choose mods", "Get mods", "Check", "Install", "Manage")
SYSTEM_BROWSER_SOURCES = ("discord",)  # Discord invites open the Discord app, not a page


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


def _verify_results(session) -> list:
    """What the game's own logs say about the installed mods ([] if the verifier is unavailable)."""
    try:
        from ..verify import verify_session

        return verify_session(session)
    except Exception:  # noqa: BLE001 - a log check must never break the wizard
        return []


def _open(path_or_url: str) -> None:
    if os.environ.get("LEONIDA_NO_OPEN"):
        return
    if path_or_url.startswith("http"):
        webbrowser.open_new_tab(path_or_url)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path_or_url))


# ----------------------------------------------------------------------- UI bridge
class GuiUI:
    """Implements the installer's UI protocol with dialogs.

    Safe to use from a worker thread: every call is run on the UI thread (the worker waits for dialogs).
    """

    def __init__(self, parent: QWidget, log_view: QPlainTextEdit, caller: MainThreadCaller | None = None):
        self.parent = parent
        self.view = log_view
        self.caller = caller or MainThreadCaller(parent)

    def info(self, msg: str) -> None:
        self.caller.call(lambda: self.view.appendPlainText(msg))

    def warn(self, msg: str) -> None:
        self.caller.call(lambda: self.view.appendPlainText("! " + msg))

    def confirm(self, msg: str, default: bool = True) -> bool:
        return self.caller.call(
            lambda: QMessageBox.question(self.parent, PACK_NAME, msg) == QMessageBox.StandardButton.Yes)

    def wait_done(self, title: str, steps: list[str], folder: Path | None) -> bool:
        return self.caller.call(lambda: self._wait_done(title, steps, folder))

    def _wait_done(self, title: str, steps: list[str], folder: Path | None) -> bool:
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
        if sys.platform == "win32" and not os.environ.get("LEONIDA_NO_OPEN"):
            subprocess.Popen(windows_launch_command(path), cwd=str(path.parent))
        self.info(f"Started {path.name}. Finish its installer, then click Done in the next window.")


# ---------------------------------------------------------------------------- pages
class WelcomePage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        logo = QLabel()
        pix = QPixmap(str(logo_path()))
        if not pix.isNull():
            logo.setPixmap(pix.scaled(112, 112, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
        head.addWidget(logo)
        head.addWidget(_title(f"{PACK_NAME} {__version__}"))
        head.addStretch()
        lay.addLayout(head)
        lay.addWidget(_wrap(
            "Turns GTA V Enhanced into a GTA VI-style experience with a curated, conflict-checked mod list.<br><br>"
            "<b>Story mode only.</b> Mods in GTA Online can get your account banned. Use the "
            "<i>Online-safe</i> switch on the last page before going online.<br><br>"
            "Before you start: back up your saves, turn off automatic game updates, and turn off "
            "BattlEye in the Rockstar Games Launcher (story mode).<br><br>"
            "Leonida V never re-hosts mods. It downloads each mod from its author: automatically where the author "
            "publishes a direct release, otherwise by opening the author's page inside Leonida, where you click "
            "Download and Leonida picks the file up. Then it installs them in order and logs every file so it can "
            "undo everything."))
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


class GetPage(QWidget):
    COLS = ("#", "Mod", "How", "Status", "File / page")
    STATUS = 3

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        self.busy: dict[str, str] = {}  # mod id -> live status text while downloading
        self.notes: dict[str, str] = {}  # mod id -> last result of "Download everything" (e.g. why it failed)
        self.cancel_requested = False
        self.everything = False          # "Download everything": the browser part follows the automatic one
        self.autodl = None               # the AutoDownloader while it runs
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Get the mods"))
        self.hint = _wrap("")
        lay.addWidget(self.hint)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(self.open_row)
        lay.addWidget(self.table)
        self.progress = QProgressBar()
        self.progress.hide()
        lay.addWidget(self.progress)
        self.auto_status = _wrap("")
        self.auto_status.hide()
        lay.addWidget(self.auto_status)
        row = QHBoxLayout()
        self.auto_btn = QPushButton("Download all automatic")
        self.auto_btn.clicked.connect(self.download_auto)
        self.browse_btn = QPushButton("Download everything")
        self.browse_btn.setToolTip("Automatic downloads first, then Leonida's browser goes through the rest: it finds "
                                   "the right file on each page and points at it; you sign in where a site asks and "
                                   "click Download; each file is checked as it arrives.")
        self.browse_btn.clicked.connect(self.download_everything)
        self.cancel_btn = QPushButton("Cancel download")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.hide()
        for b in (self.auto_btn, self.browse_btn, self.cancel_btn):
            row.addWidget(b)
        for text, fn in (("Open download folder", self.open_folder), ("Assign a file...", self.assign),
                         ("Rescan", self.refresh)):
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
            status = "ready" if f else self.busy.get(m.id) or self.notes.get(m.id, "missing")
            if getattr(m, "unsupported", None) and not f:
                status = "not for this game build"
            vals = (str(m.order), m.name, how_text(m), status, f.name if f else m.page)
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 1 and m.version:
                    item.setToolTip(f"Version for your game build: {m.version}")
                if c == self.STATUS and getattr(m, "unsupported", None):
                    item.setToolTip(m.unsupported)
                self.table.setItem(r, c, item)
        missing = res.missing(mods)
        n_auto = sum(1 for m in missing if m.download)
        self.auto_btn.setEnabled(bool(n_auto) and not self.busy and self.autodl is None)
        self.auto_btn.setText(f"Download all automatic ({n_auto})")
        self.browse_btn.setEnabled(bool(missing) and not self.busy and self.autodl is None)
        extra = ""
        if res.ambiguous or res.unmatched:
            extra = f"<br>{len(res.ambiguous) + len(res.unmatched)} file(s) not recognised: use <i>Assign a file</i>."
        self.hint.setText(
            f"Downloads go to <b>{folder}</b>. <i>Download all automatic</i> fetches every mod whose author publishes "
            "a direct release; the rest open one by one in Leonida's browser, where you click the author's Download "
            "button. Double-click a row to open its page. "
            f"<b>{len(mods) - len(missing)}/{len(mods)}</b> ready.{extra}")
        if not missing:
            write_lock(s.state / LOCK_NAME, build_lock(s.manifest.pack, s.manifest.version, res.matched))

    def open_row(self, row: int, _col: int) -> None:
        self.win.open_page(self.mods[row])

    # ---- automatic downloads (author-published GitHub releases / direct links) ------------------------------
    def download_auto(self) -> None:
        if not network_allowed():
            return
        todo = [m for m in self.result.missing(self.mods) if m.download]
        if not todo:
            return
        folder = self.win.session.config.downloads()
        self.cancel_requested = False
        self.busy = {m.id: "queued" for m in todo}
        self.cancel_btn.show()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.refresh()

        def work(emit):
            from .. import downloader as D

            out = []
            for m in todo:
                if self.cancel_requested:
                    out.append((m.id, None, "cancelled"))
                    continue
                last = [-1]

                def prog(done, total, mid=m.id, last=last):
                    # report each new percent, or each new MB when the server doesn't send a size
                    step = int(done * 100 / total) if total else done // 1_000_000
                    if step != last[0]:
                        last[0] = step
                        emit((mid, done, total))

                try:
                    plan = D.plan_for(m)
                    if not plan.url:
                        plan = D.resolve(plan)
                    emit((m.id, 0, plan.size))
                    path = D.download(plan, folder, progress=prog, cancel=lambda: self.cancel_requested)
                    out.append((m.id, path.name, None))
                except Exception as exc:  # noqa: BLE001 - shown per mod
                    out.append((m.id, None, str(exc) or type(exc).__name__))
            return out

        start_worker(self, work, pass_progress=True, on_progress=self._dl_progress,
                     on_done=self._dl_done, on_fail=lambda msg: self._dl_done([("?", None, msg)]))

    def _dl_progress(self, payload) -> None:
        mid, done, total = payload
        if total:
            pct = int(done * 100 / total)
            self.busy[mid] = f"downloading {pct}%"
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)
        else:
            self.busy[mid] = f"downloading {done // 1_000_000} MB"
            self.progress.setRange(0, 0)
        name = self.win.session.manifest.mods.get(mid)
        self.progress.setFormat(f"{name.name if name else mid}: %p%")
        for r, m in enumerate(self.mods):
            if m.id == mid:
                self.table.setItem(r, self.STATUS, QTableWidgetItem(self.busy[mid]))

    def _dl_done(self, results) -> None:
        self.busy = {}
        self.cancel_btn.hide()
        self.progress.hide()
        failed = [(mid, err) for mid, _name, err in results if err]
        if self.everything:  # go on in the browser; failed automatic ones are retried there
            self.everything = False
            self.notes.update({mid: f"automatic download failed: {err}" for mid, err in failed})
            if not self.cancel_requested:
                self._browser_part()
                return
        self.refresh()
        if failed:
            mods = self.win.session.manifest.mods
            lines = "\n".join(f"- {mods[mid].name if mid in mods else mid}: {err}" for mid, err in failed)
            QMessageBox.warning(self, PACK_NAME, f"Some downloads did not finish:\n{lines}\n\n"
                                "You can get those in Leonida's browser instead.")

    def cancel(self) -> None:
        self.cancel_requested = True
        self.everything = False
        if self.autodl is not None:
            self.autodl.stop()

    # ---- "Download everything": automatic downloads, then the browser through the rest ------------------------
    def download_everything(self) -> None:
        missing = self.result.missing(self.mods)
        if not missing:
            return
        self.notes = {}
        self.cancel_requested = False
        if network_allowed() and any(m.download for m in missing):
            self.everything = True
            self.download_auto()
        else:
            self._browser_part()

    def _browser_part(self) -> None:
        self.refresh()
        rest = self.result.missing(self.mods)
        if not rest:
            return
        browser = self.win.browser_window()
        if browser is None:  # no QtWebEngine (or opening is off): the pages one by one, as before
            self.get_in_browser()
            return
        from .autodl import AutoDownloader

        dl = self.autodl = AutoDownloader(browser, self.win.session, rest, parent=self)
        dl.mod_status.connect(self._auto_mod_status)
        dl.status.connect(self._auto_line)
        dl.need_login.connect(self._auto_login)
        dl.mod_done.connect(lambda _mid, _path: self.refresh())
        dl.mod_failed.connect(lambda mid, reason: self.notes.__setitem__(mid, f"needs you: {reason}"))
        dl.finished.connect(self._auto_finished)
        self.cancel_btn.setText("Stop")
        self.cancel_btn.show()
        self.auto_status.show()
        self.refresh()
        dl.start()

    def _auto_mod_status(self, mod_id: str, text: str) -> None:
        if text == "ready" or text.startswith("failed"):
            self.busy.pop(mod_id, None)
        else:
            self.busy[mod_id] = text
        for r, m in enumerate(self.mods):
            if m.id == mod_id:
                self.table.setItem(r, self.STATUS, QTableWidgetItem(self.busy.get(mod_id) or self.notes.get(mod_id, text)))

    def _auto_line(self, text: str) -> None:
        self.auto_status.setText(text)

    def _auto_login(self, site: str) -> None:
        self.auto_status.setText(f"<b>Sign in to {site} in Leonida's browser window.</b> Leonida goes on by itself "
                                 "once you're signed in (it never types your password).")
        browser = self.win.browser
        if browser is not None:
            browser.raise_()
            browser.activateWindow()

    def _auto_finished(self) -> None:
        dl, self.autodl = self.autodl, None
        self.busy = {}
        self.cancel_btn.hide()
        self.cancel_btn.setText("Cancel download")
        self.refresh()
        need = [m for m in self.result.missing(self.mods) if m.id in self.notes]
        done = sum(1 for kind, _ in (dl.results.values() if dl else []) if kind == "done")
        msg = f"Download everything: {done} file(s) arrived and were checked."
        if need:
            msg += " Still needed: " + "; ".join(f"{m.name} ({self.notes[m.id]})" for m in need)
        self.auto_status.setText(msg)

    # ---- everything else: the author's page inside Leonida -------------------------------------------------
    def get_in_browser(self) -> None:
        rest = [m for m in self.result.missing(self.mods) if not m.download]
        if not rest:
            return
        self.win.open_page(rest[0], queue=rest[1:])

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
        running = bool(getattr(self, "_running", False))
        self.next_btn.setEnabled(bool(self.todo()) and bool(s.game_dir()) and not running)
        self.dry_btn.setEnabled(bool(s.game_dir()) and not running)

    def _set_running(self, on: bool) -> None:
        self._running = on
        self.win.setCursor(Qt.CursorShape.BusyCursor if on else Qt.CursorShape.ArrowCursor)
        self.refresh()

    def dry_run(self) -> None:
        s = self.win.session
        ui = GuiUI(self, self.view, self.win.caller)
        inst = s.installer(ui, dry_run=True)
        res = s.matches()
        todo = self.todo()

        def work():
            for m in todo:
                inst.install(m, res.matched.get(m.id))

        self._set_running(True)
        start_worker(self, work, on_done=lambda _r: self._set_running(False),
                     on_fail=lambda msg: (self._set_running(False), self.view.appendPlainText("! " + msg)))

    def install_next(self) -> None:
        """Runs Installer.install on a worker thread so big archives don't freeze the window."""
        s = self.win.session
        todo = self.todo()
        if not todo:
            return
        m = todo[0]
        res = s.matches()
        if m.id not in res.matched:
            QMessageBox.warning(self, PACK_NAME, f"{m.name} is not downloaded yet (see Get mods).")
            return
        ui = GuiUI(self, self.view, self.win.caller)
        inst = s.installer(ui)
        path = res.matched[m.id]

        def failed(msg: str) -> None:
            self._set_running(False)
            QMessageBox.critical(self, PACK_NAME, msg)

        self._set_running(True)
        start_worker(self, lambda: inst.install(m, path), on_done=lambda step: self._installed(inst, ui, m, step),
                     on_fail=failed)

    def _installed(self, inst, ui: GuiUI, m: Mod, step) -> None:
        self._set_running(False)
        self.view.appendPlainText(f"Step {step.id} done: {m.name} ({len(step.actions)} change(s) logged).")
        box = QMessageBox(self)
        box.setWindowTitle("Test now")
        box.setText(f"{m.name} is installed. Launch story mode, drive for a minute, then come back.")
        keep = box.addButton("Works - continue", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Undo this step", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        undo = box.clickedButton() is not keep
        if not undo:
            failed = [r for r in _verify_results(self.win.session) if r.mod == m.id and r.level == ERROR]
            if failed:
                lines = "\n".join(f"- {r.message}" + (f"\n    {r.log}: {r.line}" if r.line else "") for r in failed)
                undo = QMessageBox.question(
                    self, PACK_NAME, f"The game's logs say {m.name} did not load:\n{lines}\n\nUndo this step?") \
                    == QMessageBox.StandardButton.Yes
        if undo:
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
        for text, fn in (("Check the game's logs (after playing)", self.check_logs),
                         ("Check for mod updates", self.check_mod_updates),
                         ("Online-safe ON (move mods out)", self.safe_on),
                         ("Online-safe OFF (bring mods back)", self.safe_off),
                         ("Undo last step", self.undo_last),
                         ("Uninstall everything", self.uninstall)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            lay.addWidget(b)
        self.mod_update_btn = QPushButton("Install mod updates")
        self.mod_update_btn.clicked.connect(self.apply_mod_updates)
        self.mod_update_btn.hide()
        lay.addWidget(self.mod_update_btn)
        self.mod_plan = None
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        lay.addWidget(self.view)
        lay.addWidget(_title("Leonida updates"))
        self.update_label = QLabel(f"You have {PACK_NAME} {__version__}.")
        self.update_label.setWordWrap(True)
        lay.addWidget(self.update_label)
        urow = QHBoxLayout()
        self.check_btn = QPushButton("Check for updates")
        self.check_btn.clicked.connect(self.check_updates)
        self.update_btn = QPushButton("Update Leonida")
        self.update_btn.clicked.connect(self.apply_update)
        self.update_btn.hide()
        self.force_btn = QPushButton("Force update")
        self.force_btn.setToolTip("Download and reinstall the latest Leonida V release even if you already have it "
                                  "(repairs a broken install). Settings, downloads and installed mods are kept.")
        self.force_btn.clicked.connect(self.force_update)
        urow.addWidget(self.check_btn)
        urow.addWidget(self.update_btn)
        urow.addWidget(self.force_btn)
        urow.addStretch()
        lay.addLayout(urow)
        self.update_info = None

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)

    def refresh(self) -> None:
        s = self.win.session
        g = s.game_dir()
        st = online_status(g, s.manifest.online_safe_items) if g and g.is_dir() else "no game folder"
        self.state.setText(f"Mods: {st}   |   steps installed: {len(s.log.installed_mods())}")

    # ---- did the mods load? (the game's own logs) -------------------------------------------------------------
    def check_logs(self) -> None:
        results = _verify_results(self.win.session)
        self.view.appendPlainText("Game logs:" if results else "Game logs: nothing installed yet, or no game folder.")
        mark = {ERROR: "FAILED", WARNING: "check", INFO: "ok"}
        for r in results:
            text = f"  [{mark.get(r.level, r.level)}] {r.message}"
            if r.level != INFO and r.line:
                text += f"\n      {r.log}: {r.line}"
            self.view.appendPlainText(text)

    # ---- mod updates from the Leonida modpack -----------------------------------------------------------------
    def check_mod_updates(self) -> None:
        if not network_allowed():
            return
        s = self.win.session
        self.mod_update_btn.hide()
        self.view.appendPlainText("Checking the Leonida modpack for tested mod updates ...")

        def work():
            from .. import modpack, modupdate

            pack = modpack.fetch_latest()
            return None if pack is None else modupdate.plan_updates(s, pack)

        def done(plan) -> None:
            self.mod_plan = plan
            if plan is None:
                self.view.appendPlainText("No modpack has been published yet.")
                return
            for line in plan.summary():
                self.view.appendPlainText("  " + line)
            self.mod_update_btn.setVisible(bool(plan.pending))

        start_worker(self, work, on_done=done, on_fail=lambda msg: self.view.appendPlainText("! " + msg))

    def apply_mod_updates(self) -> None:
        plan = self.mod_plan
        if not plan or not plan.pending:
            return
        names = ", ".join(i.name for i in plan.pending)
        if QMessageBox.question(self, PACK_NAME, f"Update {names}?\nEach update is logged and can be undone.") \
                != QMessageBox.StandardButton.Yes:
            return
        from .. import modupdate

        s = self.win.session
        ui = GuiUI(self, self.view, self.win.caller)
        self.mod_update_btn.setEnabled(False)

        def done(report) -> None:
            self.mod_update_btn.setEnabled(True)
            self.mod_update_btn.hide()
            for line in report:
                self.view.appendPlainText("  " + line)
            self.refresh()

        def failed(msg: str) -> None:
            self.mod_update_btn.setEnabled(True)
            self.view.appendPlainText("! " + msg)

        start_worker(self, lambda: modupdate.run_updates(s, plan, ui), on_done=done, on_fail=failed)

    # ---- Leonida self-update ------------------------------------------------------------------------------
    def check_updates(self, quiet: bool = False) -> None:
        if not network_allowed():
            return
        try:
            from .. import updater
        except ImportError:
            return
        self.check_btn.setEnabled(False)
        self.update_label.setText("Checking GitHub for a newer Leonida V ...")

        def done(info) -> None:
            self.check_btn.setEnabled(True)
            self.update_info = info
            if info.newer:
                self.update_label.setText(f"<b>{PACK_NAME} {info.latest}</b> is available (you have {info.current}). "
                                          f"<a href='{info.page}'>What's new</a>")
                self.update_label.setTextFormat(Qt.TextFormat.RichText)
                self.update_label.setOpenExternalLinks(True)
                self.update_btn.show()
                self.win.statusBar().showMessage(f"{PACK_NAME} {info.latest} is available: see Manage.", 15000)
            else:
                self.update_label.setText(f"You have {PACK_NAME} {info.current}"
                                          + (f"; the latest release is {info.latest}." if info.latest
                                             else ". No release has been published yet."))
                self.update_btn.hide()

        def failed(msg: str) -> None:
            self.check_btn.setEnabled(True)
            self.update_label.setText(f"You have {PACK_NAME} {__version__}." + ("" if quiet else
                                      f" Could not check for updates: {msg}"))

        start_worker(self, updater.check, on_done=done, on_fail=failed)

    def force_update(self) -> None:
        if not network_allowed():
            return
        if QMessageBox.question(self, PACK_NAME, f"Reinstall the latest {PACK_NAME} release from GitHub, even if you "
                                "already have it?\nYour settings, downloads and installed mods are kept.") \
                != QMessageBox.StandardButton.Yes:
            return
        from .. import updater

        self.force_btn.setEnabled(False)
        self.update_label.setText("Looking up the latest release ...")

        def got(info) -> None:
            self.force_btn.setEnabled(True)
            self.update_info = info
            if not info.latest:
                self.update_label.setText("No Leonida V release has been published on GitHub yet.")
                return
            self._run_apply(info, force=True)

        def failed(msg: str) -> None:
            self.force_btn.setEnabled(True)
            self.update_label.setText(f"Could not reach GitHub: {msg}")

        start_worker(self, updater.check, on_done=got, on_fail=failed)

    def apply_update(self) -> None:
        info = self.update_info
        if not info or not info.newer:
            return
        if QMessageBox.question(self, PACK_NAME, f"Download and install {PACK_NAME} {info.latest}?\n"
                                "Your settings, downloads and installed mods are kept.") \
                != QMessageBox.StandardButton.Yes:
            return
        self._run_apply(info)

    def _run_apply(self, info, force: bool = False) -> None:
        from .. import updater

        frozen = getattr(sys, "frozen", False)
        project = Path(sys.executable).parent if frozen else Path(__file__).resolve().parents[2]
        s = self.win.session
        self.update_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.update_label.setText("Updating ...")

        def done(msg: str) -> None:
            self.update_label.setText(msg)
            self.check_btn.setEnabled(True)
            QMessageBox.information(self, PACK_NAME, msg)
            if updater.install_kind(project) == "exe":
                self.win.close()  # the helper swaps the exe in once this process has exited

        def failed(msg: str) -> None:
            self.update_btn.setEnabled(True)
            self.check_btn.setEnabled(True)
            self.update_label.setText(f"Update failed: {msg}")

        def work():
            if force:
                return updater.apply(info, project, s.state, force=True)
            return updater.apply(info, project, s.state)

        start_worker(self, work, on_done=done, on_fail=failed)

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
        self.caller = MainThreadCaller(self)
        self.images = ImageLoader(self.session.state / "images", self)
        self.browser = None
        self.setWindowTitle(f"{PACK_NAME} {__version__}")
        self.setWindowIcon(QIcon(str(logo_path())))
        self.resize(1180, 760)
        central = QWidget()
        outer = QHBoxLayout(central)
        self.nav = QListWidget()
        self.nav.setFixedWidth(160)
        self.nav.addItems(PAGES)
        outer.addWidget(self.nav)
        right = QVBoxLayout()
        self.stack = QStackedWidget()
        self.pages = [cls(self) for cls in (WelcomePage, GamePage, ChoosePage, GetPage,
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
        QTimer.singleShot(4000, self._daily_update_check)

    def _daily_update_check(self) -> None:
        """Quietly look for a newer Leonida at most once a day (LEONIDA_NO_UPDATE_CHECK=1 turns it off)."""
        if os.environ.get("LEONIDA_NO_UPDATE_CHECK") or not network_allowed():
            return
        import time

        stamp = self.session.state / "last-update-check.txt"
        try:
            if time.time() - stamp.stat().st_mtime < 24 * 3600:
                return
        except OSError:
            pass
        try:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
        except OSError:
            return
        self.pages[-1].check_updates(quiet=True)

    def go(self, i: int) -> None:
        i = max(0, min(i, len(self.pages) - 1))
        self.stack.setCurrentIndex(i)
        if self.nav.currentRow() != i:
            self.nav.setCurrentRow(i)
        self.back.setEnabled(i > 0)
        self.fwd.setEnabled(i < len(self.pages) - 1)

    def browser_window(self):
        """Leonida's browser window (created once), or None without QtWebEngine or when opening is off."""
        if os.environ.get("LEONIDA_NO_OPEN"):
            return None
        try:
            from .browser import BrowserWindow
        except ImportError:
            return None
        if self.browser is None:
            self.browser = BrowserWindow(self.session.state, self.session.config.downloads(), self)
            self.browser.file_saved.connect(self._file_saved)
        self.browser.download_dir = self.session.config.downloads()
        return self.browser

    def open_page(self, mod: Mod, queue: list[Mod] | None = None) -> None:
        """Open a mod's page in Leonida's browser (downloads land in the downloads folder)."""
        if os.environ.get("LEONIDA_NO_OPEN"):
            return
        if mod.source in SYSTEM_BROWSER_SOURCES:
            _open(mod.page)
            mod = None
        queue = [m for m in (queue or []) if m.source not in SYSTEM_BROWSER_SOURCES]
        if mod is None and not queue:
            return
        try:
            from .browser import BrowserWindow
        except ImportError as exc:  # QtWebEngine missing: fall back to the system browser
            self.statusBar().showMessage(f"Built-in browser unavailable ({exc}); using your browser.", 8000)
            for m in [mod, *queue]:
                if m:
                    _open(m.page)
            return
        if self.browser is None:
            self.browser = BrowserWindow(self.session.state, self.session.config.downloads(), self)
            self.browser.file_saved.connect(self._file_saved)
        self.browser.download_dir = self.session.config.downloads()
        self.browser.set_queue(queue)
        if mod is not None:
            self.browser.open_mod(mod)
        else:
            self.browser.next_mod()

    def _file_saved(self, path: str) -> None:
        get_page = self.pages[3]
        get_page.refresh()
        name = Path(path).name
        hit = next((m for m, f in get_page.result.matched.items() if f.name == name), None)
        if hit:
            msg = f"Saved {name}: recognised as {self.session.manifest.mod(hit).name}."
        else:
            msg = f"Saved {name}, but it isn't recognised yet. Use 'Assign a file...' on Get mods."
        if self.browser:
            self.browser.status.setText(msg)
        self.statusBar().showMessage(msg, 10000)


def logo_path(name: str = "leonida.png") -> Path:
    """The app logo (02 / Sunset Emblem), bundled next to this module (and in the frozen build)."""
    base = Path(getattr(sys, "_MEIPASS", "")) / "leonida" / "gui" / "assets" if getattr(sys, "frozen", False) else None
    if base is not None and (base / name).exists():
        return base / name
    return Path(__file__).resolve().parent / "assets" / name


def main() -> int:
    # QtWebEngine (the built-in browser) needs this before the QApplication exists.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    if sys.platform == "win32":  # own taskbar entry + icon instead of python's
        import contextlib
        import ctypes

        with contextlib.suppress(Exception):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JacobJandon.LeonidaV")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(PACK_NAME)
    app.setWindowIcon(QIcon(str(logo_path())))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
