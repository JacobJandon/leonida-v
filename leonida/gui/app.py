"""Leonida V wizard: Welcome -> Game -> Choose mods -> Get mods -> Check -> Install -> Manage.

The look is the "Sunset Emblem" theme (leonida/gui/theme.py) with the components in leonida/gui/widgets.py:
a GTA VI-style launcher on near-black with sunset accents. Each page keeps its data widgets (table, list, steps,
log view, ...) under the same names, so the behaviour and the tests don't depend on how a page is drawn.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
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
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import PACK_NAME, __version__
from .. import settings as settings_mod
from ..checks import ERROR, INFO, WARNING, has_errors
from ..detect import ALL_EXES, EDITION_NAMES, GameInstall, check_prerequisites, detect_games, edition_of_exe, find_7zip, find_exe
from ..installer import InstallError, windows_launch_command
from ..manifest import Mod
from ..matcher import build_lock, write_lock
from ..onlinesafe import OnlineSafeError, go_online_safe, restore_mods
from ..onlinesafe import status as online_status
from ..paths import LOCK_NAME
from ..session import Session
from . import theme
from . import widgets as W
from .chooser import ChoosePage, how_text
from .images import ImageLoader, network_allowed
from .newpages import EDITION_LABEL, PlaytestView, editions_from
from .workers import MainThreadCaller, start_worker

PAGES = ("Welcome", "Game", "Choose mods", "Get mods", "Check", "Install", "Manage")
HOME_VIEWS = ("browse", "pack", "settings", "about")  # the LIBRARY list in the sidebar, in its order
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


def _header(step: int, title: str, text: str = "", right: QWidget | None = None) -> W.PageHeader:
    return W.PageHeader(step, len(PAGES), title, text, right)


def _card(margins=(16, 14, 16, 14), spacing: int = 8, tone: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("card", True)
    if tone:
        f.setProperty("tone", tone)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


def _scroll(widget: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidget(widget)
    sc.setWidgetResizable(True)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return sc


def _clear(lay) -> None:
    """Remove (and really detach) every widget in a layout."""
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def _verify_results(session) -> list:
    """What the game's own logs say about the installed mods ([] if the verifier is unavailable)."""
    try:
        from ..verify import verify_session

        return verify_session(session)
    except Exception:  # noqa: BLE001 - a log check must never break the wizard
        return []


def _verify_by_mod(results) -> dict[str, str]:
    """mod id -> one play-test result for the Install stepper: failed > ok > not-seen."""
    out: dict[str, str] = {}
    for r in results:
        if not r.mod:
            continue
        kind = {"failed": "failed", "ok": "ok", "warning": "not-seen", "not-seen": "not-seen"}.get(r.status)
        if kind is None:
            continue
        old = out.get(r.mod)
        if old == "failed" or (old == "ok" and kind == "not-seen"):
            continue
        out[r.mod] = kind
    return out


def _open(path_or_url: str) -> None:
    if os.environ.get("LEONIDA_NO_OPEN"):
        return
    if path_or_url.startswith("http"):
        webbrowser.open_new_tab(path_or_url)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path_or_url))


def _drift_widget(page: QWidget, on_change) -> W.DriftWarning | None:
    """F5: the locked settings of installed mods that no longer have their value, with Restore all / Keep mine."""
    s = page.win.session
    try:
        drift = s.settings_drift()
    except Exception:  # noqa: BLE001 - a settings file that can't be read is a finding of its own, not a crash
        return None
    if not drift:
        return None
    items = [(d.wanted.file, d.wanted.key, settings_mod._text(d.wanted.value),
              "missing" if d.have is None else str(d.have), d.wanted.why) for d in drift]
    w = W.DriftWarning(items)
    w.restore.connect(lambda: _restore_settings(page, on_change))
    w.unlock.connect(lambda f, k: _keep_mine(page, drift, f, k, on_change))
    return w


def _restore_settings(page: QWidget, on_change) -> list[str]:
    """Restore all: write every locked value again (a logged "settings:<mod>" step, undoable)."""
    try:
        report = page.win.session.apply_settings(page.win.log_ui(page))
    except Exception as exc:  # noqa: BLE001
        QMessageBox.warning(page, PACK_NAME, f"Couldn't restore the settings: {exc}")
        return []
    QMessageBox.information(page, PACK_NAME, "Restored:\n" + "\n".join(report) if report
                            else "The settings already had their locked values.")
    on_change()
    return report


def _keep_mine(page: QWidget, drift, file: str, key: str, on_change) -> list[str]:
    """Keep mine: unlock that key, so Leonida stops putting its value back (Manage/CLI can lock it again)."""
    s = page.win.session
    mods = sorted({d.wanted.mod for d in drift if d.wanted.file == file and d.wanted.key == key})
    for mod in mods:
        settings_mod.set_unlocked(s.state, mod, file, key, True)
    on_change()
    return mods


def guide_path() -> Path:
    """GUIDE.md: next to LeonidaV.exe in the frozen build, docs/GUIDE.md in a source copy."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("GUIDE.md")
    return Path(__file__).resolve().parents[2] / "docs" / "GUIDE.md"


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
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        lay.addWidget(W._label("HAND-MADE STEP", "eyebrow"))
        lay.addWidget(_title(title))
        text = "".join(f"<li>{s}</li>" for s in steps) or "<li>Follow the mod's readme.</li>"
        lay.addWidget(_wrap(f"<ol>{text}</ol>"))
        if folder:
            btn = W.button(f"Open files: {folder}", "secondary", icon_name="external")
            btn.clicked.connect(lambda: _open(str(folder)))
            lay.addWidget(btn)
            _open(str(folder))
        box = QDialogButtonBox()
        done = box.addButton("Done", QDialogButtonBox.ButtonRole.AcceptRole)
        done.setProperty("variant", "primary")
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
    """The launcher's front page: the sunset emblem, the pitch, and what to do before starting."""

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 0)
        lay.setSpacing(18)
        logo = logo_path()
        self.start_btn = W.button("Start: find my game", "primary", lambda: win.go(1), "play", glow=True)
        guide = W.button("Read the guide", "ghost", self.open_guide)
        lay.addWidget(W.HeroHeader(
            logo if logo.is_file() else None, eyebrow="THE GTA VI EXPERIENCE · GTA V ENHANCED",
            pitch="A curated, conflict-checked modpack that turns GTA V Enhanced into a GTA VI-style Leonida: "
                  "the new HUD, smarter traffic, fixed maps and that Vice City light. One safe step at a time.",
            actions=[self.start_btn, guide]))
        row = QHBoxLayout()
        row.setSpacing(14)
        for eyebrow, title, text in (
                ("PICK", "Curated and conflict-checked",
                 "Modpacks that fit your GPU and game build. Key clashes, slots and wrong editions are caught before "
                 "anything is installed."),
                ("UNDO", "Every file logged", "A snapshot before the first step. Undo one step or everything, and the "
                                              "game folder is exactly as it was."),
                ("SAFE", "Online-safe switch", "Story mode only. One click moves every mod out before you go online, "
                                               "and back afterwards.")):
            f, cl = _card()
            cl.addWidget(W._label(eyebrow, "eyebrow"))
            cl.addWidget(W._label(title, "subtitle"))
            cl.addWidget(W._label(text, "muted", wrap=True))
            cl.addStretch()
            row.addWidget(f)
        lay.addLayout(row)
        f, cl = _card((18, 14, 18, 16))
        cl.addWidget(W._label("Before you start", "subtitle"))
        cl.addWidget(_wrap(
            "<b>Story mode only.</b> Mods in GTA Online can get your account banned. Use the "
            "<i>Online-safe</i> switch on the last page before going online.<br><br>"
            "Back up your saves, turn off automatic game updates, and turn off "
            "BattlEye in the Rockstar Games Launcher (story mode).<br><br>"
            "Leonida V never re-hosts mods. It downloads each mod from its author: automatically where the author "
            "publishes a direct release, otherwise by opening the author's page inside Leonida, where you click "
            "Download and Leonida picks the file up. Then it installs them in order and logs every file so it can "
            "undo everything."))
        lay.addWidget(f)
        lay.addStretch()
        foot = QHBoxLayout()
        foot.addWidget(W._label(f"{PACK_NAME} {__version__}", "caption"))
        foot.addStretch()
        foot.addWidget(W._label("Every mod comes from its author's own page.", "caption"))
        lay.addLayout(foot)

    def open_guide(self) -> None:
        g = guide_path()
        if g.is_file():
            _open(str(g))


class GamePage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(_header(2, "Find your GTA V",
                              "Pick the game Leonida should mod: GTA V Enhanced (GTA5_Enhanced.exe) or GTA V Legacy "
                              "(GTA5.exe). Each edition has its own mod list. Detect looks in Steam, Epic, the "
                              "Rockstar launcher and the usual folders."))
        self.editions_box = QVBoxLayout()
        lay.addLayout(self.editions_box)
        self.editions: W.EditionPicker | None = None
        self.edition_note = W._label("", "caption", wrap=True)
        lay.addWidget(self.edition_note)
        f, cl = _card((16, 12, 16, 12))
        cl.addWidget(W._label("DETECTED FOLDERS", "eyebrow"))
        self.list = QListWidget()
        self.list.setMinimumHeight(90)
        self.list.setMaximumHeight(160)
        cl.addWidget(self.list)
        lay.addWidget(f)
        row = QHBoxLayout()
        for text, fn, icon_name in (("Detect", self.detect, "game"), ("Browse...", self.browse, None)):
            row.addWidget(W.button(text, "secondary", fn, icon_name))
        row.addStretch()
        lay.addLayout(row)
        self.current = W._label("", "muted", wrap=True)
        lay.addWidget(self.current)
        pc, pl = _card((16, 12, 16, 14), 6)
        pl.addWidget(W._label("THIS PC", "eyebrow"))
        holder, self.pc_flow = W.flow_box(8)
        pl.addWidget(holder)
        lay.addWidget(pc)
        lay.addStretch()
        self.list.itemClicked.connect(lambda it: self.set_dir(it.data(Qt.ItemDataRole.UserRole)))
        self.refresh()

    def showEvent(self, e) -> None:  # noqa: N802 - Qt naming
        self._pc_pills()  # registry and 7-Zip lookups: only when the page is actually seen
        super().showEvent(e)

    def refresh(self) -> None:
        s = self.win.session
        self.current.setText(f"Selected: {s.config.game_dir or '(none)'}   version: {s.game_version() or 'unknown'}")
        self._set_editions(self._installs())

    def _set_editions(self, installs) -> None:
        _clear(self.editions_box)
        s = self.win.session
        current = EDITION_LABEL.get(s.game_edition or "")
        self.editions = W.EditionPicker(editions_from(installs), current)
        self.editions.chosen.connect(self._edition_chosen)
        self.editions_box.addWidget(self.editions)
        base = s.base_manifest
        text = (f"Mod list in use: <b>{EDITION_NAMES.get(s.edition, s.edition)}</b> · {len(base.packs)} modpacks, "
                f"{sum(1 for m in base.mods.values() if m.tier != 'custom')} mods.")
        mismatch = s.edition_mismatch()
        if mismatch:
            text += f"<br><span style='color:{theme.COLORS['error']}'>{mismatch}</span>"
        self.edition_note.setText(text)

    def _edition_chosen(self, name: str) -> None:
        """Switching edition = using that edition's game folder: the session then loads that edition's mod list."""
        folder = next((f for n, f, _b in editions_from(self._installs()) if n == name), None)
        if folder and folder != self.win.session.config.game_dir:
            self.set_dir(folder)

    def _installs(self) -> list:
        """The listed folders and the saved one, each with its edition (from the exe)."""
        items = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        s = self.win.session
        out, seen = [], set()
        saved = [s.config.game_dir] if s.config.game_dir else []
        for d in saved + [x for x in items if x]:  # the saved folder first: it wins its edition's card
            if d in seen:
                continue
            seen.add(d)
            exe = find_exe(Path(d), ALL_EXES)
            if exe:
                version = s.game_version() if d == s.config.game_dir else None
                out.append(GameInstall(Path(d), "listed", exe, version, edition_of_exe(exe)))
        return out

    def _pc_pills(self) -> None:
        while self.pc_flow.count():
            w = self.pc_flow.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        prereq = check_prerequisites()
        names = {"dotnet48": ".NET Framework 4.8", "vcredist": "VC++ 2015-2022 x64"}
        for key, ok in prereq.items():
            pill = W.StatusPill("ready" if ok else ("failed" if ok is False else "not-seen"))
            pill.text.setText(names.get(key, key) + ("" if ok else (" missing" if ok is False else " unknown")))
            self.pc_flow.addWidget(pill)
        seven = find_7zip()
        pill = W.StatusPill("ready" if seven else "not-seen")
        pill.text.setText("7-Zip" if seven else "7-Zip not found (only for .7z/.rar)")
        self.pc_flow.addWidget(pill)

    def detect(self) -> None:
        self.list.clear()
        games = detect_games(ALL_EXES)
        for g in games:
            it = QListWidgetItem(f"{g.path}   [{g.source}]   {g.version or ''}"
                                 + (f"   {EDITION_NAMES[g.edition]}" if getattr(g, "edition", None) in EDITION_NAMES
                                    else ""))
            it.setData(Qt.ItemDataRole.UserRole, str(g.path))
            self.list.addItem(it)
        if games and not self.win.session.config.game_dir:
            self.set_dir(str(games[0].path))
        if not games:
            self.list.addItem("Not found automatically. Use Browse...")
        self._set_editions(self._installs())

    def browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "GTA V folder (Enhanced or Legacy)")
        if d:
            self.set_dir(d)

    def set_dir(self, d: str | None) -> None:
        if not d:
            return
        s = self.win.session
        if not find_exe(Path(d), ALL_EXES):
            QMessageBox.warning(self, PACK_NAME, f"No {' or '.join(ALL_EXES)} in that folder.")
            return
        before = s.edition
        s.config.game_dir = d
        s.save()
        self.refresh()
        if s.edition != before:
            self.win.edition_changed()
        self.win.update_sidebar()


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
        self.rows: dict[str, W.QueueRow] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        overall = QWidget()
        ol = QVBoxLayout(W.clear_background(overall))
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(4)
        self.ready_label = W._label("", "caption")
        ol.addWidget(self.ready_label, 0, Qt.AlignmentFlag.AlignRight)
        self.ready_bar = QProgressBar()
        self.ready_bar.setTextVisible(False)
        self.ready_bar.setFixedWidth(260)
        ol.addWidget(self.ready_bar)
        lay.addWidget(_header(4, "Get the mods", "Leonida downloads what it can from the authors' own releases; the "
                                                 "rest open in its browser, where you click Download.", overall))
        self.hint = _wrap("")
        self.hint.setProperty("role", "muted")
        lay.addWidget(self.hint)
        self.queue = QWidget()
        self.queue_box = QVBoxLayout(W.clear_background(self.queue))
        self.queue_box.setContentsMargins(0, 0, 6, 0)
        self.queue_box.setSpacing(8)
        self.queue_scroll = _scroll(self.queue)
        lay.addWidget(self.queue_scroll, 1)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(self.open_row)
        self.table.hide()
        lay.addWidget(self.table, 1)
        self.progress = QProgressBar()
        self.progress.setProperty("thick", True)
        self.progress.hide()
        lay.addWidget(self.progress)
        self.auto_status = _wrap("")
        self.auto_status.hide()
        lay.addWidget(self.auto_status)
        self.auto_btn = W.button("Download all automatic", "secondary", self.download_auto, "download")
        self.browse_btn = W.button("Download everything", "primary", self.download_everything, "download", glow=True)
        self.browse_btn.setToolTip("Automatic downloads first, then Leonida's browser goes through the rest: it finds "
                                   "the right file on each page and points at it; you sign in where a site asks and "
                                   "click Download; each file is checked as it arrives.")
        self.cancel_btn = W.button("Cancel download", "danger", self.cancel)
        self.cancel_btn.hide()
        self.view_btn = W.button("Show as table", "ghost", self.toggle_view)
        left = [W.button("Open download folder", "ghost", self.open_folder, "external"),
                W.button("Assign a file...", "ghost", self.assign), W.button("Rescan", "ghost", self.refresh),
                self.view_btn]
        lay.addWidget(W.ActionBar(left, [self.cancel_btn, self.auto_btn, self.browse_btn]))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, e) -> None:  # noqa: N802 - Qt naming
        self.refresh()
        self.timer.start(3000)
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self.timer.stop()
        super().hideEvent(e)

    def toggle_view(self) -> None:
        table = self.table.isHidden()
        self.table.setVisible(table)
        self.queue_scroll.setVisible(not table)
        self.view_btn.setText("Show as cards" if table else "Show as table")

    def refresh(self) -> None:
        s = self.win.session
        folder = s.config.downloads()
        folder.mkdir(parents=True, exist_ok=True)
        mods = s.mods()
        res = s.matches(mods)
        self.mods, self.result = mods, res
        self._test_place = s.test_place()
        self.table.setRowCount(len(mods))
        for r, m in enumerate(mods):
            f = res.matched.get(m.id)
            status = "ready" if f else self.busy.get(m.id) or self.notes.get(m.id, "missing")
            if getattr(m, "unsupported", None) and not f:
                status = "not for this game build"
            vals = (str(r + 1), m.name, how_text(m), status,  # its place in the pack; the file with its scan status
                    f"{f.name} · {self._scan_label(f)}" if f else m.page)
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 1 and m.version:
                    item.setToolTip(f"Version for your game build: {m.version}")
                if c == self.STATUS and getattr(m, "unsupported", None):
                    item.setToolTip(m.unsupported)
                self.table.setItem(r, c, item)
        self._refresh_queue(mods, res)
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
        ready = len(mods) - len(missing)
        self.ready_label.setText(f"{ready} of {len(mods)} ready")
        self.ready_bar.setRange(0, max(1, len(mods)))
        self.ready_bar.setValue(ready)
        if not missing:
            write_lock(s.state / LOCK_NAME, build_lock(s.manifest.pack, s.manifest.version, res.matched))

    def _scan_label(self, f) -> str:
        """What Leonida's test place says about a download (quarantine.py): scanned OK / flagged / ..."""
        tp = getattr(self, "_test_place", None)
        r = tp.cached(f) if tp is not None else None
        return r.label if r is not None else "not scanned yet"

    # ---- the queue (one card per mod) -----------------------------------------------------------------
    def _queue_state(self, m: Mod, f, status: str) -> tuple[str, int | None, str]:
        if f:
            return "ready", None, f"{f.name} · {self._scan_label(f)}"
        if status == "not for this game build":
            return "unsupported", None, getattr(m, "unsupported", "") or status
        if status.startswith("downloading"):
            pct = re.search(r"(\d+)%", status)
            return "downloading", int(pct.group(1)) if pct else None, status
        if status == "queued":
            return "queued", None, "waiting for its turn"
        if status.startswith(("needs you", "automatic download failed", "failed")):
            return "failed", None, status
        if status.startswith("sign in"):
            return "manual", None, status
        if getattr(m, "is_paid", False):
            return "paid", None, how_text(m)
        if getattr(m, "manual_download", False):
            return "manual", None, how_text(m)
        return "missing", None, how_text(m)

    def _refresh_queue(self, mods, res) -> None:
        ids = [m.id for m in mods]
        if ids != list(self.rows):
            _clear(self.queue_box)
            self.rows = {}
            for i, m in enumerate(mods, 1):
                acts = []
                if not res.matched.get(m.id):
                    acts.append(W.button("Open page", "secondary", lambda _=False, mod=m: self.win.open_page(mod),
                                         "external"))
                row = W.QueueRow(f"{i}. {m.name}", "queued", None, "", acts, thumb=True)  # numbered like Install
                self.win.pictures.bind_mod(row.art, m)
                self.rows[m.id] = row
                self.queue_box.addWidget(row)
            self.queue_box.addStretch()
        for m in mods:
            self._update_row(m.id)

    def _update_row(self, mod_id: str) -> None:
        row = self.rows.get(mod_id)
        m = next((x for x in getattr(self, "mods", []) if x.id == mod_id), None)
        if row is None or m is None:
            return
        f = self.result.matched.get(mod_id)
        status = "ready" if f else self.busy.get(mod_id) or self.notes.get(mod_id, "missing")
        if getattr(m, "unsupported", None) and not f:
            status = "not for this game build"
        kind, pct, detail = self._queue_state(m, f, status)
        row.set_progress(kind, pct, detail)
        for b in row.findChildren(QPushButton):
            b.setVisible(kind != "ready")

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
        self._update_row(mid)

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
        from .autodl import AutoDownloader, auto_sites

        dl = self.autodl = AutoDownloader(browser, self.win.session, rest, parent=self,
                                          sites=auto_sites(self.win.session.config.autodl_sites))
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
        self._update_row(mod_id)

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
        self.win.notify(msg, "warning" if need else "success")

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
    TITLES = {ERROR: "Fix this first", WARNING: "Worth a look", INFO: "Good to know"}

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        self.has_errors = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.counts = QWidget()
        self.counts_row = QHBoxLayout(W.clear_background(self.counts))
        self.counts_row.setContentsMargins(0, 0, 0, 0)
        self.counts_row.setSpacing(6)
        lay.addWidget(_header(5, "Check before installing",
                              "Leonida checks your game, your PC and the mods against each other. Fix the red ones; "
                              "the yellow ones are worth a look.", self.counts))
        self.list = QListWidget()  # the plain list of findings (kept for the CLI-like view and tests)
        self.list.hide()
        lay.addWidget(self.list)
        self.cards = QWidget()
        self.cards_box = QVBoxLayout(W.clear_background(self.cards))
        self.cards_box.setContentsMargins(0, 0, 6, 0)
        self.cards_box.setSpacing(10)
        lay.addWidget(_scroll(self.cards), 1)
        again = W.button("Run checks again", "ghost", self.refresh, "shield")
        self.next_btn = W.button("Next: install  →", "primary", lambda: win.go(5), glow=True)
        lay.addWidget(W.ActionBar([again], [self.next_btn]))

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
        self._render(findings)

    def _render(self, findings) -> None:
        _clear(self.counts_row)
        _clear(self.cards_box)
        n = {lvl: sum(1 for f in findings if f.level == lvl) for lvl in (ERROR, WARNING, INFO)}
        for lvl, one, many, tone in ((ERROR, "to fix", "to fix", "error"), (WARNING, "warning", "warnings", "warning"),
                                     (INFO, "note", "notes", "info")):
            if n[lvl]:
                self.counts_row.addWidget(W.Badge(f"{n[lvl]} {one if n[lvl] == 1 else many}", tone))
        drift = _drift_widget(self, self.refresh)
        if drift is not None:
            self.cards_box.addWidget(drift)
            findings = [f for f in findings if f.code != "setting-drift"]
        if not findings and drift is None:
            self.counts_row.addWidget(W.Badge("all passed", "success"))
            self.cards_box.addWidget(W.EmptyState(
                "shield", "Everything checks out", "No problems found with your game, your PC or the mods.",
                W.button("Next: install  →", "primary", lambda: self.win.go(5))))
        mods = self.win.session.manifest.mods
        tone = {ERROR: "error", WARNING: "warning", INFO: "info"}
        icon_name = {ERROR: "cross", WARNING: "warning", INFO: "info"}
        for f in sorted(findings, key=lambda x: (ERROR, WARNING, INFO).index(x.level)):
            card, cl = _card((16, 12, 16, 12), 4, tone[f.level] if f.level != INFO else None)
            top = QHBoxLayout()
            top.setSpacing(10)
            top.addWidget(W._icon_label(icon_name[f.level], W.TONE_COLORS[tone[f.level]], 18))
            title = mods[f.mod].name if f.mod and f.mod in mods else self.TITLES[f.level]
            top.addWidget(W._label(title, "subtitle"), 1)
            cl.addLayout(top)
            msg = W._label(f.message, "caption", wrap=True)
            msg.setContentsMargins(28, 0, 0, 0)
            cl.addWidget(msg)
            self.cards_box.addWidget(card)
        self.cards_box.addStretch()
        self.next_btn.setEnabled(not self.has_errors)
        self.next_btn.setToolTip("Fix the red items first" if self.has_errors else "")


class InstallPage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(_header(6, "Install, one step at a time",
                              "Mods install one at a time, in order. After each step, launch story mode and drive for "
                              "a minute, then continue or undo that step."))
        body = QHBoxLayout()
        body.setSpacing(18)
        left, ll = _card((14, 8, 14, 8), 0)
        left.setFixedWidth(500)  # room for each mod's picture
        self.stepper_holder = QWidget()
        self.stepper_box = QVBoxLayout(W.clear_background(self.stepper_holder))
        self.stepper_box.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(_scroll(self.stepper_holder))
        body.addWidget(left)
        right = QVBoxLayout()
        right.setSpacing(12)
        cur, cl = _card((18, 14, 18, 16), 6)
        cur.setProperty("selected", True)
        cl.addWidget(W._label("NEXT STEP", "eyebrow"))
        self.next_title = W._label("", "title", wrap=True)
        cl.addWidget(self.next_title)
        self.next_detail = W._label("", "caption", wrap=True)
        cl.addWidget(self.next_detail)
        row = QHBoxLayout()
        self.next_btn = W.button("Install next", "primary", self.install_next, "install", glow=True)
        self.dry_btn = W.button("Dry run (show plan)", "secondary", self.dry_run)
        row.addWidget(self.next_btn)
        row.addWidget(self.dry_btn)
        row.addStretch()
        cl.addLayout(row)
        right.addWidget(cur)
        self.tabs = QTabWidget()
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setProperty("log", True)
        self.view.setPlaceholderText("What each step does shows up here.")
        self.tabs.addTab(self.view, "Step log")
        self.playtest = PlaytestView(win.session)
        self.playtest.finished.connect(lambda _r: self.refresh())
        self.playtest.finished.connect(lambda r: win.notify(f"Play test: {getattr(r, 'message', 'done')}",
                                                            "success" if getattr(r, "ok", False) else "warning"))
        self.tabs.addTab(_scroll(self.playtest), "Play test")
        right.addWidget(self.tabs, 1)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)
        self.steps = QListWidget()  # the plain list (kept for tests and screen readers)
        self.steps.hide()
        lay.addWidget(self.steps)

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
        mods = s.mods()
        for m in mods:
            self.steps.addItem(f"{'[done]' if m.id in done else '[    ]'}  {m.order:>2}. {m.name}")
        running = bool(getattr(self, "_running", False))
        todo = self.todo()
        self.next_btn.setEnabled(bool(todo) and bool(s.game_dir()) and not running)
        self.dry_btn.setEnabled(bool(s.game_dir()) and not running)
        tests = _verify_by_mod(_verify_results(s)) if done else {}
        rows, current = [], todo[0].id if todo else None
        for m in mods:
            state = "done" if m.id in done else ("current" if m.id == current else "pending")
            rows.append((m.name, how_text(m), state, tests.get(m.id) if m.id in done else None))
        _clear(self.stepper_box)
        stepper = W.Stepper(rows, thumbs=True)
        for m, r in zip(mods, stepper.rows, strict=True):
            self.win.pictures.bind_mod(r.art, m)
        self.stepper_box.addWidget(stepper)
        self.stepper_box.addStretch()
        if todo:
            nxt = todo[0]
            self.next_title.setText(f"{mods.index(nxt) + 1}. {nxt.name}")  # the number its row has on the left
            ready = nxt.id in s.matches().matched
            self.next_detail.setText(f"{how_text(nxt)} · {'downloaded, ready to install' if ready else 'not downloaded yet: see Get mods'}")
            self.next_btn.setText(f"Install {nxt.name}" if len(nxt.name) < 28 else "Install next")
        else:
            self.next_title.setText("Everything is installed")
            self.next_detail.setText("Start story mode with the play test below, or go to Manage.")
            self.next_btn.setText("Install next")

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
        self.win.notify(f"{m.name} installed (step {step.id}).", "success")
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
        self.win.update_sidebar()


class ManagePage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(_header(7, "Manage", "Everything Leonida installed, what the game's logs say about it, updates, "
                                           "the play test and the Online-safe switch."))
        cards = QHBoxLayout()
        cards.setSpacing(14)
        a, al = _card()
        al.addWidget(W._label("STATUS", "eyebrow"))
        self.state = W._label("", "subtitle", wrap=True)
        al.addWidget(self.state)
        self.state_pill = W.StatusPill("mods-off")
        al.addWidget(self.state_pill)
        al.addStretch()
        al.addWidget(W.button("Check the game's logs (after playing)", "secondary", self.check_logs, "shield"))
        b, bl = _card()
        bl.addWidget(W._label("ONLINE-SAFE", "eyebrow"))
        bl.addWidget(W._label("Before GTA Online, move every mod out; bring them back for story mode.", "caption",
                              wrap=True))
        bl.addStretch()
        self.safe_on_btn = W.button("Online-safe ON (move mods out)", "secondary", self.safe_on, "shield")
        self.safe_off_btn = W.button("Online-safe OFF (bring mods back)", "ghost", self.safe_off)
        bl.addWidget(self.safe_on_btn)
        bl.addWidget(self.safe_off_btn)
        c, clay = _card()
        clay.addWidget(W._label("LEONIDA", "eyebrow"))
        self.update_label = QLabel(f"You have {PACK_NAME} {__version__}.")
        self.update_label.setWordWrap(True)
        clay.addWidget(self.update_label)
        clay.addStretch()
        urow = QHBoxLayout()
        self.check_btn = W.button("Check for updates", "secondary", self.check_updates)
        self.update_btn = W.button("Update Leonida", "primary", self.apply_update, glow=True)
        self.update_btn.hide()
        self.force_btn = W.button("Force update", "ghost", self.force_update)
        self.force_btn.setToolTip("Download and reinstall the latest Leonida V release even if you already have it "
                                  "(repairs a broken install). Settings, downloads and installed mods are kept.")
        urow.addWidget(self.check_btn)
        urow.addWidget(self.update_btn)
        urow.addWidget(self.force_btn)
        urow.addStretch()
        clay.addLayout(urow)
        for x in (a, b, c):
            cards.addWidget(x, 1)
        lay.addLayout(cards)
        self.drift_box = QVBoxLayout()
        lay.addLayout(self.drift_box)
        self.tabs = QTabWidget()
        inst = QWidget()
        il = QVBoxLayout(inst)
        il.setContentsMargins(12, 12, 12, 12)
        self.installed = QWidget()
        self.installed_box = QVBoxLayout(W.clear_background(self.installed))
        self.installed_box.setContentsMargins(0, 0, 6, 0)
        self.installed_box.setSpacing(8)
        il.addWidget(_scroll(self.installed))
        self.tabs.addTab(inst, "Installed")
        self.playtest = PlaytestView(win.session)
        self.playtest.finished.connect(lambda _r: self.refresh())
        pt = QWidget()
        pl = QVBoxLayout(pt)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.addWidget(self.playtest)
        pl.addStretch()
        self.tabs.addTab(pt, "Play test")
        logs = QWidget()
        lg = QVBoxLayout(logs)
        lg.setContentsMargins(12, 12, 12, 12)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setProperty("log", True)
        lg.addWidget(self.view, 1)
        mrow = QHBoxLayout()
        mrow.addWidget(W.button("Check for mod updates", "secondary", self.check_mod_updates, "download"))
        self.mod_update_btn = W.button("Install mod updates", "primary", self.apply_mod_updates)
        self.mod_update_btn.hide()
        mrow.addWidget(self.mod_update_btn)
        mrow.addStretch()
        lg.addLayout(mrow)
        self.tabs.addTab(logs, "Log and updates")
        lay.addWidget(self.tabs, 1)
        self.mod_plan = None
        lay.addWidget(W.ActionBar([W.button("Uninstall everything", "danger", self.uninstall)],
                                  [W.button("Undo last step", "secondary", self.undo_last)]))
        self.update_info = None

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)

    def refresh(self) -> None:
        s = self.win.session
        g = s.game_dir()
        st = online_status(g, s.manifest.online_safe_items) if g and g.is_dir() else "no game folder"
        n = len(s.log.installed_mods())
        steps = sum(1 for x in s.log.active_steps() if x.status == "done")
        where = {"mods-on": "in the game", "online-safe": "moved out (online-safe)", "clean": "none in the game",
                 "mixed": "some moved out, some in the game", "no game folder": "no game folder set"}.get(st, st)
        self.state.setText(f"{n} mod{'s' if n != 1 else ''} installed in {steps} step{'s' if steps != 1 else ''}"
                           f" · {where}" if n else "No mods installed by Leonida yet"
                           + (f" · mods {where}" if st in ("mods-on", "online-safe", "mixed") else ""))
        kind = {"mods-on": "mods-on", "online-safe": "online-safe"}.get(st, "mods-off")
        self.state_pill.set_status(kind, f"{n} mod{'s' if n != 1 else ''}" if n else "")
        self.safe_on_btn.setEnabled(st != "online-safe")    # the switch shows which way it is
        self.safe_off_btn.setEnabled(st in ("online-safe", "mixed"))
        _clear(self.drift_box)
        drift = _drift_widget(self, self.refresh)
        if drift is not None:
            self.drift_box.addWidget(drift)
        self._installed_rows()

    def _installed_rows(self) -> None:
        _clear(self.installed_box)
        s = self.win.session
        steps = [st for st in s.log.steps if st.status == "done"]
        if not steps:
            self.installed_box.addWidget(W.EmptyState("install", "Nothing installed yet",
                                                      "Pick your mods and install them step by step.",
                                                      W.button("Go to Install  →", "primary",
                                                               lambda: self.win.go(5))))
            return
        tests = _verify_by_mod(_verify_results(s))
        mods = s.manifest.mods
        for st in steps:
            f, fl = _card((14, 8, 10, 8), 0)
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(W._label(f"{st.id:>2}", "caption"))
            settings_of = st.mod.split(":", 1)[1] if st.mod.startswith("settings:") else None
            pic_mod = mods.get(settings_of or st.mod)
            art = W.Art(st.mod, "", 40)
            art.setFixedWidth(64)
            if pic_mod is not None:
                self.win.pictures.bind_mod(art, pic_mod)
            row.addWidget(art)
            col = QVBoxLayout()
            col.setSpacing(0)
            settings_of = st.mod.split(":", 1)[1] if st.mod.startswith("settings:") else None
            m = mods.get(settings_of or st.mod)
            name = (m.name if m else st.mod) if settings_of is None else f"Locked settings: {m.name if m else settings_of}"
            col.addWidget(W._label(name, "subtitle"))
            col.addWidget(W._label(f"{st.method} · {len(st.actions)} change(s) logged"
                                   + (f" · {m.version}" if m and m.version and not settings_of else ""), "caption"))
            row.addLayout(col, 1)
            row.addWidget(W.StatusPill("installed") if settings_of else W.StatusPill(tests.get(st.mod, "installed")))
            fl.addLayout(row)
            self.installed_box.addWidget(f)
        self.installed_box.addStretch()

    # ---- did the mods load? (the game's own logs) -------------------------------------------------------------
    def check_logs(self) -> None:
        results = _verify_results(self.win.session)
        self.view.appendPlainText("Game logs:" if results else "Game logs: nothing installed yet, or no game folder.")
        mark = {"ok": "ok", "failed": "FAILED", "warning": "check", "not-seen": "not yet", "no-log": "no log"}
        for r in results:
            text = f"  [{mark.get(r.status, r.status)}] {r.message}"
            if r.level != INFO and r.line:
                text += f"\n      {r.log}: {r.line}"
            self.view.appendPlainText(text)
        self.tabs.setCurrentIndex(2)
        self._installed_rows()

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
                self.win.notify(f"{PACK_NAME} {info.latest} is available: see Manage or Settings.", "info")
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
        self.win.update_sidebar()

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
        from .launcher import Pictures

        self.pictures = Pictures(self.images, self)  # every mod's picture, wherever mods are listed
        self.browser = None
        self.setWindowTitle(f"{PACK_NAME} {__version__}")
        self.setWindowIcon(QIcon(str(logo_path())))
        self.resize(1320, 860)
        self.setMinimumSize(1120, 600)  # fits a 1280x720 screen with the taskbar and title bar (pages scroll)
        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        outer = QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        column.addLayout(outer, 1)
        logo = logo_path()
        self.sidebar = W.Sidebar(logo if logo.is_file() else None, __version__)
        self.nav = self.sidebar.nav
        for name in PAGES:
            self.nav.add_step(name)
        # the library (Browse, My modpack) above the setup steps, like a launcher's home
        self.home_nav = W.NavList()
        self.home_nav.add_step("Browse", "mods")
        self.home_nav.add_step("My modpack", "play")
        self.home_nav.add_step("Settings", "manage")
        self.home_nav.add_step("About & help", "info")
        self.home_nav.setFixedHeight(4 * 46 + 2 * 8 + 4)  # the rows plus the list's own padding: never scrolled
        self.sidebar.game.hide()  # the bottom bar shows the game, its build and the mods' state
        side = self.sidebar.layout()
        at = side.indexOf(self.nav)
        side.insertWidget(at, W._label("LIBRARY", "eyebrow"))
        side.insertWidget(at + 1, self.home_nav)
        side.insertSpacing(at + 2, 10)
        side.insertWidget(at + 3, W._label("SET UP", "eyebrow"))
        outer.addWidget(self.sidebar)
        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(32, 22, 32, 14)
        right.setSpacing(10)
        self.stack = QStackedWidget()
        self.pages = [cls(self) for cls in (WelcomePage, GamePage, ChoosePage, GetPage,
                                            CheckPage, InstallPage, ManagePage)]
        for p in self.pages:
            self.stack.addWidget(p)
        from .extras import AboutPage, Notifications, SettingsPage
        from .launcher import BottomBar, BrowsePage, PackPage

        self.toast = W.Toast()
        self.notifications = Notifications(self.toast, self)
        self.browse = BrowsePage(self)
        self.pack_page = PackPage(self)
        self.settings_page = SettingsPage(self)
        self.about_page = AboutPage(self)
        for page in (self.browse, self.pack_page, self.settings_page, self.about_page):
            self.stack.addWidget(page)
        right.addWidget(self.stack, 1)
        right.addWidget(self.toast)
        row = QHBoxLayout()
        self.back = W.button("Back", "ghost")
        self.fwd = W.button("Next", "secondary")
        self.back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        self.fwd.clicked.connect(lambda: self.go(self.stack.currentIndex() + 1))
        row.addStretch()
        row.addWidget(self.back)
        row.addWidget(self.fwd)
        right.addLayout(row)
        outer.addWidget(right_w, 1)
        self.bottom = BottomBar(self)
        from .extras import Bell

        self.bell = Bell(self.notifications)
        self.bottom.layout().insertWidget(self.bottom.layout().count() - 1, self.bell)
        column.addWidget(self.bottom)
        self.setCentralWidget(central)
        self.nav.currentRowChanged.connect(lambda r: self.go(r) if r >= 0 else None)
        self.home_nav.currentRowChanged.connect(
            lambda r: self.show_home(HOME_VIEWS[r]) if r >= 0 else None)
        self.go(0)
        if self.returning():  # after the first run the launcher opens on your modpack
            self.show_home("pack")
        QTimer.singleShot(2500, self, self._startup_notes)

    def notify(self, text: str, tone: str = "info") -> None:
        """A toast now and an entry under the bell (finished downloads and installs, updates, drift, play tests)."""
        self.notifications.notify(text, tone)

    def _startup_notes(self) -> None:
        try:
            drift = self.session.settings_drift() if self.session.game_dir() else []
        except Exception:  # noqa: BLE001 - a note must never break the window
            drift = []
        if drift:
            self.notify(f"{len(drift)} locked setting(s) changed since install: see Manage.", "warning")
        QTimer.singleShot(4000, self, self._daily_update_check)  # cancelled if the window is gone by then

    def _daily_update_check(self) -> None:
        """Quietly look for a newer Leonida at most once a day (Settings, or LEONIDA_NO_UPDATE_CHECK=1, turn it off)."""
        if os.environ.get("LEONIDA_NO_UPDATE_CHECK") or not network_allowed() or not self.session.config.update_check:
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

    def returning(self) -> bool:
        """True once a modpack is chosen and the game is found: the launcher's home is then the modpack page."""
        g = self.session.game_dir()
        return (self.session.state / "pack.json").is_file() and bool(g and g.is_dir())

    def show_home(self, which: str = "browse") -> None:
        """The library (Browse, the modpack page) and Settings / About, outside the setup steps."""
        page = {"browse": self.browse, "pack": self.pack_page, "settings": self.settings_page,
                "about": self.about_page}[which]
        self.stack.setCurrentWidget(page)
        if hasattr(page, "refresh") and not page.isVisible():  # a hidden window gets no show event
            page.refresh()
        for r in range(self.nav.count()):
            self.nav.set_state(r, "todo")
        self.nav.blockSignals(True)
        self.nav.clearSelection()
        self.nav.setCurrentRow(-1)
        self.nav.blockSignals(False)
        row = HOME_VIEWS.index(which)
        for r in range(self.home_nav.count()):
            self.home_nav.set_state(r, "current" if r == row else "todo")
        self.back.hide()
        self.fwd.hide()
        self.update_sidebar()

    def open_pack(self, pack_id: str, edition: str | None = None) -> None:
        self.pack_page.set_pack(pack_id, edition)
        self.show_home("pack")

    def play(self) -> None:
        from .launcher import play_game

        self.statusBar().showMessage(play_game(self), 10000)
        self.update_sidebar()

    def go(self, i: int) -> None:
        i = max(0, min(i, len(self.pages) - 1))
        self.back.show()
        self.fwd.show()
        if self.home_nav.currentRow() >= 0:
            self.home_nav.blockSignals(True)
            self.home_nav.clearSelection()
            self.home_nav.setCurrentRow(-1)
            self.home_nav.blockSignals(False)
            for r in range(self.home_nav.count()):
                self.home_nav.set_state(r, "todo")
        self.stack.setCurrentIndex(i)
        if self.nav.currentRow() != i:
            self.nav.setCurrentRow(i)
        for r in range(self.nav.count()):
            self.nav.set_state(r, "current" if r == i else "todo")
        self.back.setEnabled(i > 0)
        self.fwd.setEnabled(i < len(self.pages) - 1)
        self.update_sidebar()

    def log_ui(self, parent: QWidget) -> GuiUI:
        """An installer UI whose lines go to the Manage page's log (rollbacks and settings run from other pages)."""
        return GuiUI(parent, self.pages[-1].view, self.caller)

    def edition_changed(self) -> None:
        """The game folder now holds the other edition: rebuild what shows that edition's mod list."""
        self.pages[2].edition_changed()
        self.pages[3].refresh()

    def update_sidebar(self) -> None:
        """The game card at the bottom of the sidebar: edition, build and whether mods are on."""
        s = self.session
        g = s.game_dir()
        edition = EDITION_NAMES.get(s.game_edition or s.edition)
        if not g or not g.is_dir():
            self.sidebar.set_game(None, "mods-off", "", edition)
            return
        try:
            st = online_status(g, s.manifest.online_safe_items)
        except Exception:  # noqa: BLE001 - the sidebar must never break the window
            st = ""
        n = len(s.log.installed_mods())
        kind = "online-safe" if st == "online-safe" else ("mods-on" if n else "mods-off")
        self.sidebar.set_game(s.game_version(), kind, f"{n} mods" if n and kind == "mods-on" else "", edition)
        if getattr(self, "bottom", None) is not None:
            self.bottom.refresh()

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
        self.notify(msg, "success" if hit else "warning")


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
    from ..paths import state_dir
    from .single import SingleInstance, bring_to_front

    guard = SingleInstance(state_dir(), app)
    if not guard.acquire():  # Leonida already runs on this State: it comes to the front, this start ends
        return 0
    app.aboutToQuit.connect(guard.release)
    from . import crashdialog

    crashdialog.install(app, state_dir())  # Leonida's log (gui session file), Qt messages, the crash dialog
    theme.apply_theme(app)
    win = MainWindow()
    guard.activated.connect(lambda: bring_to_front(win))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
