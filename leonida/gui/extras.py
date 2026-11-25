"""The launcher's other default systems: Settings, About & help (credits, report a problem, logs, system info) and
notifications (a toast plus the bell in the bottom bar).

Report a problem uses ``leonida.diagnostics.build(session, out_dir)`` and Debug mode ``leonida.logs.setup(state,
debug)`` when those modules are there (they come from the exe build); without them the buttons say so. Nothing is
ever sent anywhere: the report is a zip on the Desktop, and the GitHub "new issue" page only opens when you say so.
"""

from __future__ import annotations

import importlib
import os
import platform
import re
import shutil
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import PACK_NAME, __version__
from . import widgets as W

REPO_URL = "https://github.com/JacobJandon/leonida-v"
GUIDE_URL = f"{REPO_URL}/blob/main/docs/GUIDE.md"
ROOT = Path(__file__).resolve().parents[2]


def optional(module: str):
    """``leonida.<module>`` if this build has it, else None (diagnostics / logs come with the exe build)."""
    try:
        return importlib.import_module(f"leonida.{module}")
    except ImportError:
        return None


def _open(target: str) -> None:
    if os.environ.get("LEONIDA_NO_OPEN"):
        return
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl(target) if "://" in target else QUrl.fromLocalFile(target))


def _card(title: str, text: str = "") -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("card", True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 14, 18, 16)
    lay.setSpacing(8)
    lay.addWidget(W._label(title.upper(), "eyebrow"))
    if text:
        lay.addWidget(W._label(text, "caption", wrap=True))
    return f, lay


def _page(title: str, eyebrow: str) -> tuple[QWidget, QVBoxLayout, QVBoxLayout]:
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(12)
    outer.addWidget(W._label(eyebrow, "eyebrow"))
    outer.addWidget(W._label(title, "title"))
    body = QWidget()
    lay = QVBoxLayout(W.clear_background(body))
    lay.setContentsMargins(0, 0, 8, 0)
    lay.setSpacing(14)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(body)
    outer.addWidget(area, 1)
    return page, outer, lay


# ------------------------------------------------------------------------------------------- state reset
# What "Reset Leonida's state" removes: choices and caches only. Never the install log, its backups and snapshot
# (they undo the mods), the play-test records, the browser's sign-ins, the game or the downloads.
RESET_FILES = ("pack.json", "custom-mods.json", "settings-unlocked.json", "archive-listings.json",
               "scan-results.json", "update-check.json", "last-update-check.txt", "paid-status.json")
RESET_DIRS = ("images",)
KEEP = ("install-log.json", "baseline-snapshot.json", "backups", "orphans", "playtest", "browser")


def reset_state(state: Path) -> list[str]:
    """Reset Leonida's choices and caches in ``state``; the game and downloads folders stay set. Returns what went."""
    from ..paths import Config

    state = Path(state)
    gone: list[str] = []
    for name in RESET_FILES:
        p = state / name
        if p.is_file():
            p.unlink()
            gone.append(name)
    for name in RESET_DIRS:
        p = state / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            gone.append(name + "/")
    old = Config.load(state)
    if (state / "config.json").is_file():
        Config(game_dir=old.game_dir, download_dir=old.download_dir).save(state)
        gone.append("config.json (choices; game and downloads folders kept)")
    return gone


# --------------------------------------------------------------------------------------------- credits
@dataclass(frozen=True)
class Credit:
    name: str
    author: str
    licence: str
    page: str
    kind: str   # "Mods" / "Tools"


def credits(doc: Path | None = None) -> list[Credit]:
    """Every mod and tool from docs/CREDITS.md's tables ([] when the file isn't there)."""
    doc = doc or next((p for p in (ROOT / "docs" / "CREDITS.md",
                                   Path(getattr(sys, "_MEIPASS", "")) / "docs" / "CREDITS.md") if p.is_file()), None)
    if doc is None or not Path(doc).is_file():
        return []
    out, section = [], ""
    for line in Path(doc).read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = "Mods" if "Mods" in line else ("Tools" if "Tools" in line else "")
            continue
        if not section or not line.startswith("|") or set(line) <= set("|- :"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] in ("Mod", "Tool"):
            continue
        page = re.search(r"<(https?://[^>]+)>", line)
        licence = cells[4] if section == "Mods" and len(cells) > 4 else (cells[2] if len(cells) > 2 else "")
        out.append(Credit(cells[0], cells[1] if len(cells) > 1 else "", licence, page.group(1) if page else "",
                          section))
    return out


def system_info(session) -> str:
    """What a bug report needs (no personal data: no user name, no paths outside the game/kit)."""
    from ..detect import EDITION_NAMES

    s = session
    c = s.pack_choice()
    lines = [f"{PACK_NAME} {__version__} ({'exe' if getattr(sys, 'frozen', False) else 'source'})",
             f"System: {_os_name()}, {64 if sys.maxsize > 2**32 else 32}-bit",  # no platform.platform(): it
             # starts `cmd /c ver` (Windows, Python 3.11) or `uname -p` (Linux) to find out
             f"Python {platform.python_version()}",
             f"Game: {EDITION_NAMES.get(s.game_edition or s.edition, 'GTA V')} {s.game_version() or 'not found'}",
             f"GPU: {', '.join(s.gpus()) or 'unknown'}",
             f"Pack: {c.pack or 'none'} (variant {c.variant or 'default'})",
             f"Installed mods: {len(s.log.installed_mods())}"]
    try:
        from PySide6 import __version__ as pyside

        lines.insert(3, f"PySide6 {pyside}")
    except ImportError:
        pass
    return "\n".join(lines)


def issue_url(session, zip_name: str = "") -> str:
    """A pre-filled GitHub "new issue" page (opened only when the user says so; nothing is sent by Leonida)."""
    body = ("**What happened?**\n\n\n**What did you expect?**\n\n\n**System**\n```\n" + system_info(session)
            + "\n```\n" + (f"\nPlease attach `{zip_name}` (on your Desktop) to this issue.\n" if zip_name else ""))
    q = urllib.parse.urlencode({"title": f"Problem report: {PACK_NAME} {__version__}", "body": body})
    return f"{REPO_URL}/issues/new?{q}"


# ------------------------------------------------------------------------------------------- what's new
def changelog_path() -> Path | None:
    for p in (ROOT / "docs" / "CHANGELOG.md", Path(getattr(sys, "_MEIPASS", "")) / "docs" / "CHANGELOG.md",
              Path(sys.executable).parent / "CHANGELOG.md"):
        if p.is_file():
            return p
    return None


def whats_new(version: str = __version__, doc: Path | None = None) -> str:
    """The changelog's section for ``version`` (Markdown), with "Unreleased" on top for a source checkout. "" when
    there is no changelog or no such section."""
    doc = doc or changelog_path()
    if doc is None or not Path(doc).is_file():
        return ""
    text = Path(doc).read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)[1:]
    out = []
    for sec in sections:
        head = sec.splitlines()[0] if sec else ""
        if head.split(" ")[0] == version or (head.startswith("Unreleased") and not getattr(sys, "frozen", False)):
            out.append("## " + sec.strip())
    return "\n\n".join(out)


def show_whats_new(win) -> QDialog | None:
    """A window with what changed in this version (non-modal; the release page when there is no changelog)."""
    text = whats_new() or (f"## {__version__}\n\nThe release notes are on the "
                           f"[release page]({REPO_URL}/releases).")
    dlg = QDialog(win)
    dlg.setWindowTitle(f"What's new in {PACK_NAME} {__version__}")
    dlg.resize(760, 620)
    lay = QVBoxLayout(dlg)
    view = QTextBrowser()
    view.setOpenExternalLinks(True)
    view.setMarkdown(text)
    lay.addWidget(view, 1)
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(W.button("Close", "primary", dlg.accept))
    lay.addLayout(row)
    win.whats_new_dialog = dlg
    dlg.show()                      # not modal: Leonida stays usable
    return dlg


def maybe_whats_new(win) -> bool:
    """After Leonida was updated (the version differs from the one last seen), offer "What's new" once. A first
    start just remembers the version. True when it was offered."""
    s = win.session
    seen = s.config.seen_version
    if seen == __version__:
        return False
    used_before = seen is not None or bool(s.log.steps) or (s.state / "pack.json").is_file()
    s.config.seen_version = __version__
    s.save()
    if not used_before:
        return False
    win.notify(f"{PACK_NAME} was updated to {__version__}" + (f" (from {seen})" if seen else "") + ".", "info",
               "What's new", lambda: show_whats_new(win))
    return True


# ------------------------------------------------------------------------------------------ notifications
@dataclass
class Note:
    text: str
    tone: str
    when: str
    action: str = ""
    on_action: object = None


class Notifications(QObject):
    """``notify(text, tone)``: a toast over the window and an entry under the bell in the bottom bar."""

    changed = Signal()

    def __init__(self, toast: W.Toast, parent: QObject | None = None):
        super().__init__(parent)
        self.toast = toast
        self.items: list[Note] = []
        self.unread = 0
        self._on_action = None
        toast.action_clicked.connect(self._action)

    def notify(self, text: str, tone: str = "info", action: str = "", on_action=None) -> None:
        """``action``/``on_action``: a button on the toast (and the bell's entry) that does the obvious next thing."""
        self.items.insert(0, Note(text, tone, time.strftime("%H:%M"), action, on_action))
        del self.items[50:]
        self.unread += 1
        self._on_action = on_action if action else None
        self.toast.show_message(text, tone, action if on_action else "", timeout_ms=0 if action else 6000)
        self.changed.emit()

    def _action(self) -> None:
        fn, self._on_action = self._on_action, None
        self.toast.hide()
        if fn is not None:
            fn()

    def seen(self) -> None:
        self.unread = 0
        self.changed.emit()


class Bell(QPushButton):
    """The bottom bar's notification button: the unread count, and the recent ones in a menu."""

    def __init__(self, center: Notifications, parent: QWidget | None = None):
        super().__init__(parent)
        self.center = center
        self.setProperty("variant", "ghost")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(W.icon("info"))
        self.clicked.connect(self.show_menu)
        center.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        n = self.center.unread
        self.setText(f"{n} new" if n else "")
        self.setToolTip("Notifications" + (f": {n} new" if n else ""))

    def show_menu(self) -> QMenu:
        menu = QMenu(self)
        if not self.center.items:
            menu.addAction("No notifications yet").setEnabled(False)
        for note in self.center.items[:15]:
            act = menu.addAction(f"{note.when}  {note.text}" + (f"  ({note.action})" if note.on_action else ""))
            if note.on_action is not None:
                act.triggered.connect(lambda _=False, fn=note.on_action: fn())
        self.center.seen()
        if not os.environ.get("LEONIDA_NO_OPEN"):
            menu.popup(self.mapToGlobal(self.rect().topLeft()))
        self.menu = menu
        return menu


# ------------------------------------------------------------------------------------------------ settings
class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        page, outer, lay = _page("Settings", "LEONIDA")
        QVBoxLayout(self).addWidget(page)
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.body = lay
        self.build()

    def build(self) -> None:
        lay = self.body
        s = self.win.session
        # -- folders
        card, cl = _card("Folders", "Where your game is, where downloads go, and where Leonida keeps its own files.")
        self.folder_labels: dict[str, QLabel] = {}
        for key, name in (("game", "Game folder"), ("downloads", "Downloads"), ("state", "Leonida's files")):
            row = QHBoxLayout()
            title = W._label(name, "subtitle")
            title.setFixedWidth(150)  # the paths line up
            row.addWidget(title, 0)
            lab = W.ElidedLabel("", None)
            self.folder_labels[key] = lab
            row.addWidget(lab, 1)
            if key == "game":
                row.addWidget(W.button("Change…", "secondary", lambda _=False, k=key: self.change_folder(k)))
            else:  # downloads and Leonida's own files: their contents go along
                row.addWidget(W.button("Move…", "secondary", lambda _=False, k=key: self.move_folder(k)))
            row.addWidget(W.button("Open", "ghost", lambda _=False, k=key: self.open_folder(k), "external"))
            cl.addLayout(row)
        self.folder_note = W._label("", "caption", wrap=True)
        cl.addWidget(self.folder_note)
        lay.addWidget(card)
        # -- launcher
        card, cl = _card("Launcher")
        self.debug = QCheckBox("Debug mode: write detailed logs (for a problem report)")
        self.debug.toggled.connect(self.set_debug)
        cl.addWidget(self.debug)
        self.debug_note = W._label("", "caption", wrap=True)
        cl.addWidget(self.debug_note)
        row = QHBoxLayout()
        row.addWidget(W._label("When GTA V starts", "subtitle"))
        self.on_start = QComboBox()
        for value, text in (("stay", "Keep Leonida open"), ("minimise", "Minimise Leonida"),
                            ("close", "Close Leonida (no play time or crash notice)")):
            self.on_start.addItem(text, value)
        self.on_start.currentIndexChanged.connect(self.set_on_start)
        row.addWidget(self.on_start)
        row.addStretch()
        cl.addLayout(row)
        row = QHBoxLayout()
        self.setup_btn = W.button("Run setup again", "secondary", self.run_setup)
        self.setup_btn.setToolTip("The first-run setup: your game, what Windows needs, your modpack, downloads, "
                                  "install and a play test")
        row.addWidget(self.setup_btn)
        row.addWidget(W.button("Make a debug report", "secondary", self.debug_report))
        row.addStretch()
        cl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(W.button("Make Start menu + desktop shortcuts", "secondary", self.make_shortcuts))
        row.addWidget(W.button("Remove them", "ghost", self.remove_shortcuts))
        row.addStretch()
        cl.addLayout(row)
        self.shortcut_note = W._label("", "caption", wrap=True)
        cl.addWidget(self.shortcut_note)
        lay.addWidget(card)
        # -- updates
        card, cl = _card("Leonida updates")
        self.updates = QCheckBox("Look for a newer Leonida once a day")
        self.updates.toggled.connect(self.set_updates)
        cl.addWidget(self.updates)
        row = QHBoxLayout()
        row.addWidget(W._label("Channel", "subtitle"))
        self.channel = QComboBox()
        self.channel.addItem("Stable releases", "stable")
        self.channel.addItem("Beta: pre-releases too (for testers)", "beta")
        self.channel.currentIndexChanged.connect(self.set_channel)
        row.addWidget(self.channel)
        row.addStretch()
        cl.addLayout(row)
        self.last_check = W._label("", "caption")
        cl.addWidget(self.last_check)
        row = QHBoxLayout()
        row.addWidget(W.button("Check now", "secondary", self.check_now))
        row.addWidget(W.button("Force update…", "ghost", lambda: self.win.pages[6].force_update()))
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(card)
        # -- downloads
        card, cl = _card("Downloads: Leonida's clicks on the sites",
                         "Where Leonida may press a site's own Download button for you in its browser (it waits "
                         "through the countdowns and never skips ads). Switched off, it points at the button and "
                         "you click.")
        from .autodl import AUTO_SITES, auto_sites

        current = auto_sites(s.config.autodl_sites)
        self.site_boxes: dict[str, QCheckBox] = {}
        for site in AUTO_SITES:
            box = QCheckBox(site)
            box.setChecked(current[site])
            box.toggled.connect(lambda on, st=site: self.set_site(st, on))
            self.site_boxes[site] = box
            cl.addWidget(box)
            if site == "nexusmods.com":
                cl.addWidget(W._label("Off by default: Nexus Mods' terms restrict automated downloading, so it's "
                                      "your choice. Sign in yourself in Leonida's browser either way.", "caption",
                                      "warning", wrap=True))
        lay.addWidget(card)
        # -- pack
        card, cl = _card("Modpack", "The variant your pack uses (also on the Modpack page).")
        row = QHBoxLayout()
        self.variant = QComboBox()
        self.variant.currentIndexChanged.connect(self.set_variant)
        row.addWidget(W._label("Variant", "subtitle"))
        row.addWidget(self.variant)
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(card)
        # -- reset
        card, cl = _card("Reset", "Forget your choices and caches: the pack, your own mods list, unlocked settings, "
                                  "picture and scan caches. Your game, your installed mods (and their undo "
                                  "information), the downloads and your browser sign-ins are not touched.")
        row = QHBoxLayout()
        row.addWidget(W.button("Reset Leonida's state…", "danger", self.reset))
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(card)
        lay.addStretch()

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)

    def refresh(self) -> None:
        s = self.win.session
        g = s.game_dir()
        self.folder_labels["game"].full = str(g) if g else "not set"
        self.folder_labels["downloads"].full = str(s.config.downloads())
        self.folder_labels["state"].full = str(s.state)
        for lab in self.folder_labels.values():
            lab.setToolTip(lab.full)
            lab._fit()
        problems = []
        if not g or not g.is_dir():
            problems.append("The game folder isn't set or doesn't exist: use Change… or the Game page.")
        self.folder_note.setText(" ".join(problems))
        self.folder_note.setVisible(bool(problems))
        for box, value in ((self.debug, s.config.debug), (self.updates, s.config.update_check)):
            box.blockSignals(True)
            box.setChecked(bool(value))
            box.blockSignals(False)
        for combo, value in ((self.on_start, s.config.on_game_start), (self.channel, s.config.update_channel)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        from .. import firstrun as FR

        data = FR.load(s.state)
        self.setup_btn.setText("Continue setup" if data and not data.get("finished") else "Run setup again")
        logs = optional("logs")
        self.debug_note.setText("" if logs else "Detailed logs come with the next Leonida build; the setting is kept.")
        self.debug_note.setVisible(not logs)
        stamp = s.state / "last-update-check.txt"
        self.last_check.setText("Last checked: " + (stamp.read_text(encoding="utf-8").strip() if stamp.is_file()
                                                   else "never"))
        c = s.pack_choice()
        pack = s.base_manifest.packs.get(c.pack) if c.pack else None
        self.variant.blockSignals(True)
        self.variant.clear()
        if pack and pack.variants:
            current = pack.variant(c.variant)
            for v in pack.variants:
                self.variant.addItem(v.name, v.id)
            self.variant.setCurrentIndex(max(0, self.variant.findData(current.id if current else None)))
            self.variant.setEnabled(True)
        else:
            self.variant.addItem("This pack has no variants" if pack else "Choose a pack first")
            self.variant.setEnabled(False)
        self.variant.blockSignals(False)

    # ---- actions
    def change_folder(self, key: str) -> None:
        from ..detect import ALL_EXES

        s = self.win.session
        start = str(s.game_dir() or "") if key == "game" else str(s.config.downloads())
        chosen = QFileDialog.getExistingDirectory(self, "Choose the game folder" if key == "game" else
                                                  "Choose the downloads folder", start)
        if not chosen:
            return
        path = Path(chosen)
        if key == "game":
            if not any((path / exe).is_file() for exe in ALL_EXES):
                QMessageBox.warning(self, PACK_NAME, f"No GTA V in {path}: it needs GTA5_Enhanced.exe or GTA5.exe.")
                return
            s.config.game_dir = str(path)
            s.refresh_game_version()
        else:
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".leonida-write-test"
                probe.write_text("x")
                probe.unlink()
            except OSError as exc:
                QMessageBox.warning(self, PACK_NAME, f"Leonida can't write to {path}: {exc}")
                return
            s.config.download_dir = str(path)
        s.save()
        self.refresh()
        self.win.update_sidebar()
        self.win.notify(f"{'Game' if key == 'game' else 'Downloads'} folder: {path}", "success")

    def open_folder(self, key: str) -> None:
        s = self.win.session
        target = {"game": s.game_dir(), "downloads": s.config.downloads(), "state": s.state}[key]
        if target:
            _open(str(target))

    def set_debug(self, on: bool) -> None:
        s = self.win.session
        s.config.debug = bool(on)
        s.save()
        logs = optional("logs")
        if logs is not None and hasattr(logs, "setup"):
            logs.setup(s.state, bool(on))

    def set_on_start(self, _i: int = 0) -> None:
        s = self.win.session
        s.config.on_game_start = self.on_start.currentData() or "stay"
        s.save()

    def set_channel(self, _i: int = 0) -> None:
        s = self.win.session
        s.config.update_channel = self.channel.currentData() or "stable"
        s.save()

    def run_setup(self) -> None:
        from .. import firstrun as FR

        data = FR.load(self.win.session.state)
        if data and not data.get("finished"):
            self.win.setup_flow.begin(int(data.get("step", 0) or 0))   # where it was left
        else:
            self.win.setup_flow.begin(0, fresh=True)

    def debug_report(self) -> bool:
        """The problem report (About & help), with debug logging switched on first so the next one has more."""
        if not self.win.session.config.debug:
            self.debug.setChecked(True)
        return self.win.about_page.report()

    def _busy(self) -> str:
        pages = self.win.pages
        if getattr(pages[5], "_running", False) or getattr(self.win.setup_flow, "installing", False):
            return "an install is running"
        if getattr(pages[3], "busy", None) or getattr(pages[3], "autodl", None) is not None:
            return "downloads are running"
        if getattr(self.win.bottom.watch, "state", "idle") != "idle":
            return "GTA V is running"
        return ""

    def move_folder(self, key: str) -> None:
        """Move… the downloads or Leonida's own files: everything is copied, checked, then removed from the old place
        (leonida/relocate.py), on a worker thread."""
        from .. import relocate as R
        from ..paths import home_state_dir
        from .workers import start_worker

        s = self.win.session
        busy = self._busy()
        if busy:
            QMessageBox.information(self, PACK_NAME, f"Not now: {busy}. Try again when it's done.")
            return
        if key == "state" and os.environ.get("LEONIDA_STATE_DIR"):
            QMessageBox.information(self, PACK_NAME, "Leonida's files are set by LEONIDA_STATE_DIR: change that "
                                                     "instead.")
            return
        current = s.state if key == "state" else s.config.downloads()
        chosen = QFileDialog.getExistingDirectory(self, "Move Leonida's files to…" if key == "state" else
                                                  "Move the downloads to…", str(current.parent))
        if not chosen:
            return
        target = Path(chosen)
        if key == "state":
            ask = (f"Move Leonida's files (install log, undo backups, settings) to {target}?\n\nLeonida copies "
                   "everything, checks it, then removes the old copy, and restarts.")
            if QMessageBox.question(self, PACK_NAME, ask) != QMessageBox.StandardButton.Yes:
                return

        def work():
            if key == "state":
                return R.move_state(current, target, home_state_dir())
            return R.move_downloads(current, target)

        def done(report) -> None:
            for line in report.lines():
                self.win.pages[6].view.appendPlainText(line)
            if key == "downloads":
                s.config.download_dir = str(target)
                s.save()
                self.refresh()
                self.win.pages[3].refresh(force=True)
                self.win.notify(f"Downloads moved to {target} ({report.copied} file(s)).", "success")
                return
            self.win.notify(f"Leonida's files moved to {target}. Leonida restarts now.", "success")
            self.restart()

        def failed(msg: str) -> None:
            QMessageBox.warning(self, PACK_NAME, msg)

        self.win.notify("Moving… (Leonida keeps working meanwhile)", "info")
        start_worker(self, work, on_done=done, on_fail=failed)

    def restart(self) -> bool:
        """Start a new Leonida and close this one (after Leonida's files moved)."""
        if os.environ.get("LEONIDA_NO_OPEN"):
            return False
        from PySide6.QtCore import QProcess

        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv   # LeonidaV.exe, or python + the script
        QProcess.startDetached(sys.executable, args)
        QApplication.instance().quit()
        return True

    def set_updates(self, on: bool) -> None:
        s = self.win.session
        s.config.update_check = bool(on)
        s.save()

    def check_now(self) -> None:
        self.win.pages[6].check_updates()
        self.win.go(6)
        self.win.pages[6].tabs.setCurrentIndex(2)

    def set_site(self, site: str, on: bool) -> None:
        s = self.win.session
        s.config.autodl_sites = {**(s.config.autodl_sites or {}), site: bool(on)}
        s.save()

    def set_variant(self, _i: int) -> None:
        vid = self.variant.currentData()
        if vid and vid != self.win.session.pack_choice().variant:
            self.win.pages[2].pick_variant(vid)
            self.win.update_sidebar()

    def _shortcut_target(self):
        from ..cli import shortcut_target

        return shortcut_target()

    def make_shortcuts(self) -> None:
        from .. import shortcuts as SC

        target, icon, minimized = self._shortcut_target()
        try:
            made = SC.create(target, icon=icon, workdir=target.parent, minimized=minimized)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.shortcut_note.setText(f"Couldn't make the shortcuts: {exc}")
            return
        self.shortcut_note.setText("Made: " + ", ".join(str(p) for p in made) if made else
                                   "No shortcuts made (only on Windows).")

    def remove_shortcuts(self) -> None:
        from .. import shortcuts as SC

        gone = []
        for folder in (SC.start_menu_dir(), SC.desktop_dir()):
            lnk = Path(folder) / f"{SC.NAME}.lnk"
            if lnk.is_file():
                lnk.unlink()
                gone.append(str(lnk))
        self.shortcut_note.setText("Removed: " + ", ".join(gone) if gone else "There were no Leonida shortcuts.")

    def reset(self) -> None:
        if QMessageBox.question(self, PACK_NAME, "Reset Leonida's choices and caches?\n\nYour game, installed mods "
                                "(and their undo information), downloads and browser sign-ins stay as they are.") \
                != QMessageBox.StandardButton.Yes:
            return
        s = self.win.session
        gone = reset_state(s.state)
        from ..paths import Config

        s.config = Config.load(s.state)
        self.win.edition_changed()
        self.refresh()
        self.win.notify(f"Reset: {len(gone)} item(s) cleared.", "success")


# ----------------------------------------------------------------------------------------------- about
class AboutPage(QWidget):
    """Version, build, licence, links, credits, and help: report a problem, logs, system info."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        page, outer, lay = _page("About & help", "LEONIDA")
        QVBoxLayout(self).addWidget(page)
        self.layout().setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        from .app import logo_path

        logo = QLabel()
        from PySide6.QtGui import QPixmap

        pm = QPixmap(str(logo_path()))
        if not pm.isNull():
            logo.setPixmap(pm.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        top.addWidget(logo)
        col = QVBoxLayout()
        col.addWidget(W._label(f"{PACK_NAME} {__version__}", "title"))
        frozen = getattr(sys, "frozen", False)
        col.addWidget(W._label(f"{'LeonidaV.exe build' if frozen else 'Source checkout'} · Python "
                               f"{platform.python_version()} · {_os_name()}", "caption"))
        col.addWidget(W._label(self._licence(), "caption", wrap=True))
        links = QHBoxLayout()
        links.addWidget(W.button("GitHub", "secondary", lambda: _open(REPO_URL), "external"))
        links.addWidget(W.button("Guide", "secondary", lambda: _open(GUIDE_URL), "external"))
        links.addWidget(W.button("What's new", "secondary", lambda: show_whats_new(self.win)))
        links.addStretch()
        col.addLayout(links)
        top.addLayout(col, 1)
        lay.addLayout(top)
        # -- help
        card, cl = _card("Help", "Something went wrong? Make a problem report: a zip on your Desktop with Leonida's "
                                 "logs and state (no game files). Nothing is sent: you attach it yourself.")
        row = QHBoxLayout()
        self.report_btn = W.button("Report a problem…", "primary", self.report)
        row.addWidget(self.report_btn)
        row.addWidget(W.button("Open logs folder", "secondary", self.open_logs))
        row.addWidget(W.button("Copy system info", "secondary", self.copy_info))
        row.addStretch()
        cl.addLayout(row)
        self.help_note = W._label("", "caption", wrap=True)
        cl.addWidget(self.help_note)
        if optional("diagnostics") is None:
            self.report_btn.setEnabled(False)
            self.report_btn.setToolTip("Comes with the next Leonida build")
            self.help_note.setText("Problem reports come with the next Leonida build; until then use Copy system "
                                   "info and Open logs folder.")
        lay.addWidget(card)
        # -- keys (the same list as the modpack's Overview)
        from .launcher import keys_card

        try:
            self.keys = keys_card(win, win.session.mods())
        except Exception:  # noqa: BLE001 - the About page must open without a mod list
            self.keys = None
        if self.keys is not None:
            lay.addWidget(self.keys)
        # -- credits
        items = credits()
        card, cl = _card("Credits", "Every mod comes from its author's own page; all rights stay with them. Thank "
                                    "you to everyone below.")
        for kind in ("Mods", "Tools"):
            group = [c for c in items if c.kind == kind]
            if not group:
                continue
            cl.addWidget(W._label(kind, "subtitle"))
            for c in group:
                line = QHBoxLayout()
                name = W._label(c.name, None)
                name.setMinimumWidth(320)
                line.addWidget(name)
                line.addWidget(W.ElidedLabel(c.author, None), 1)
                if c.page:
                    line.addWidget(W.button("Page", "ghost", lambda _=False, u=c.page: _open(u), "external"))
                cl.addLayout(line)
        if not items:
            cl.addWidget(W._label("docs/CREDITS.md isn't part of this build.", "caption"))
        self.credit_count = len(items)
        lay.addWidget(card)
        lay.addStretch()

    @staticmethod
    def _licence() -> str:
        lic = next((p for p in (ROOT / "LICENSE", Path(getattr(sys, "_MEIPASS", "")) / "LICENSE") if p.is_file()),
                   None)
        if lic is None:
            return "MIT licence."
        lines = [ln.strip() for ln in lic.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return " · ".join(lines[:2]) + ". The mods keep their authors' own licences."

    def logs_dir(self) -> Path:
        s = self.win.session
        logs = optional("logs")
        if logs is not None and hasattr(logs, "log_dir"):
            return Path(logs.log_dir(s.state))
        return s.state / "logs" if (s.state / "logs").is_dir() else s.state

    def open_logs(self) -> None:
        _open(str(self.logs_dir()))

    def copy_info(self) -> str:
        text = system_info(self.win.session)
        QApplication.clipboard().setText(text)
        self.help_note.setText("System info copied: paste it into your message.")
        return text

    def report(self) -> bool:
        """Make the problem report (on a worker: it reads and zips the logs); ``last_report`` is its path when done.
        False when there is no report module or the person said no."""
        diagnostics = optional("diagnostics")
        if diagnostics is None:
            return False
        from .. import shortcuts as SC

        names: list[str] = []
        if hasattr(diagnostics, "preview"):  # what it will hold, shown before anything is saved
            try:
                names = [str(n) for n in diagnostics.preview(self.win.session)]
            except Exception:  # noqa: BLE001 - the list is a courtesy; the build still works
                names = []
        if names and QMessageBox.question(self, PACK_NAME, "A problem report will hold:\n" + _listing(names)
                                          + "\n\nSave it on your Desktop?") != QMessageBox.StandardButton.Yes:
            return False
        from .workers import start_worker

        out = Path(SC.desktop_dir())
        session = self.win.session
        self.report_btn.setEnabled(False)
        self.help_note.setText("Making the report…")

        def failed(msg: str) -> None:
            self.report_btn.setEnabled(True)
            self.help_note.setText("")
            QMessageBox.warning(self, PACK_NAME, f"Couldn't make the report: {msg}")

        start_worker(self, lambda: Path(diagnostics.build(session, out)), on_done=self._report_done, on_fail=failed)
        return True

    def _report_done(self, path: Path) -> None:
        self.report_btn.setEnabled(True)
        self.last_report = path
        names: list[str] = []
        try:
            import zipfile

            with zipfile.ZipFile(path) as z:
                names = z.namelist()
        except (OSError, ValueError):
            pass
        ask = (f"Saved {path.name} on your Desktop. It holds:\n{_listing(names)}\n\nOpen GitHub's \"new issue\" page now "
               "(filled in with your Leonida version, game build and GPU) to attach it? Nothing is sent by Leonida.")
        if QMessageBox.question(self, PACK_NAME, ask) == QMessageBox.StandardButton.Yes:
            _open(issue_url(self.win.session, path.name))
        self.help_note.setText(f"Report saved: {path}")
        self.win.notify(f"Problem report saved: {path.name}", "success")


def _os_name() -> str:
    """"Windows 11" without platform.system(), which on Windows starts `cmd /c ver` (a process at window start)."""
    winver = getattr(sys, "getwindowsversion", None)  # only on Windows (tests may fake sys.platform elsewhere)
    if sys.platform == "win32" and winver is not None:
        build = winver().build
        return f"Windows {'11' if build >= 22000 else '10'} (build {build})"
    return sys.platform


def _listing(names: list[str], most: int = 25) -> str:
    return "\n".join(f"  {n}" for n in names[:most]) + (f"\n  … and {len(names) - most} more" if len(names) > most
                                                       else "")


__all__ = ["AboutPage", "Bell", "Notifications", "SettingsPage", "credits", "issue_url", "reset_state",
           "system_info"]
