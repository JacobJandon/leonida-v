"""Built-in browser: opens a mod author's page; whatever the user downloads there is saved to the downloads folder.

Leonida never scrapes around download buttons or ads: the user clicks Download on the author's own page, exactly as in a
normal browser, and the file lands where the matcher looks. Cookies/logins persist in the state folder.
Import this module only after the QApplication exists (main() sets AA_ShareOpenGLContexts for QtWebEngine).
"""

from __future__ import annotations

import re
from pathlib import Path

import shiboken6
from PySide6.QtCore import QCoreApplication, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..manifest import Mod

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    name = _UNSAFE.sub("_", Path(name).name).strip(" .")
    return name or "download"


def unique_path(folder: Path, name: str) -> Path:
    p = folder / name
    stem, suffix, i = p.stem, p.suffix, 2
    while p.exists():
        p = folder / f"{stem} ({i}){suffix}"
        i += 1
    return p


class _Page(QWebEnginePage):
    def createWindow(self, _type):  # noqa: N802 - Qt naming. Links that open a new tab/popup load here instead.
        return self


class BrowserWindow(QDialog):
    file_saved = Signal(str)  # full path of a finished download
    download_started = Signal(str)  # file name of a download that just started
    file_failed = Signal(str, str)  # file name, reason (cancelled / interrupted)

    def __init__(self, state_dir: Path, download_dir: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.download_dir = Path(download_dir)
        self.queue: list[Mod] = []
        self.current: Mod | None = None
        self.setWindowTitle("Leonida V - get mods")
        self.resize(1200, 820)

        root = Path(state_dir) / "browser"
        # The profile must outlive every page that uses it. Qt deletes children in creation order, so the view (which
        # owns the page) is created before the profile: whichever way this window is destroyed, page goes first.
        self.view = QWebEngineView(self)
        self.profile = QWebEngineProfile("leonida", self)
        self.profile.setPersistentStoragePath(str(root / "storage"))
        self.profile.setCachePath(str(root / "cache"))
        # Force: keep session cookies too, so sign-ins (e.g. Nexus) survive closing Leonida
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.profile.downloadRequested.connect(self._download)
        self.page = _Page(self.profile, self.view)
        self.view.setPage(self.page)
        app = QCoreApplication.instance()
        if app is not None:  # app exit: release the page, then the profile, while QtWebEngine is still running
            app.aboutToQuit.connect(self.release_web)
        self.view.urlChanged.connect(lambda u: self.url.setText(u.toString()))

        lay = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        bar = QHBoxLayout()
        for text, fn in (("<", self.view.back), (">", self.view.forward), ("Reload", self.view.reload)):
            b = QPushButton(text)
            b.setMaximumWidth(70)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.url = QLineEdit()
        self.url.returnPressed.connect(self._go_typed)
        bar.addWidget(self.url)
        self.next_btn = QPushButton("Next missing mod >")
        self.next_btn.clicked.connect(self.next_mod)
        bar.addWidget(self.next_btn)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        self.status = QLabel("")
        self.bar = QProgressBar()
        self.bar.setMaximumWidth(260)
        self.bar.hide()
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(self.bar)
        lay.addLayout(row)
        self._update_next()

    def release_web(self) -> None:
        """Delete the page, then the profile (in that order, now). Called at app exit; the window is unusable after."""
        for obj in (self.page, self.profile):
            if obj is not None and shiboken6.isValid(obj):
                shiboken6.delete(obj)
        self.page = self.profile = None

    # ---- navigation -----------------------------------------------------------
    def _go_typed(self) -> None:
        text = self.url.text().strip()
        if text and "://" not in text:
            text = "https://" + text
        self.view.load(QUrl(text))

    def open_mod(self, mod: Mod, url: str | None = None, title: str | None = None) -> None:
        """Show ``mod``'s page (or ``url``, e.g. its files tab) with ``title`` (HTML) above it."""
        self.current = mod
        self.title.setText(title or (
            f"<b>{mod.name}</b> by {mod.author or 'unknown'}. Click the author's <b>Download</b> button on this page. "
            f"Leonida saves the file to <b>{self.download_dir}</b> and recognises it automatically."))
        self.view.load(QUrl(url or mod.page))
        self.show()
        self.raise_()
        self.activateWindow()

    def set_queue(self, mods: list[Mod]) -> None:
        self.queue = list(mods)
        self._update_next()

    def next_mod(self) -> None:
        if self.queue:
            self.open_mod(self.queue.pop(0))
        self._update_next()

    def _update_next(self) -> None:
        self.next_btn.setEnabled(bool(self.queue))
        self.next_btn.setText(f"Next missing mod ({len(self.queue)}) >" if self.queue else "No more mods")

    # ---- downloads ------------------------------------------------------------
    def _download(self, req: QWebEngineDownloadRequest) -> None:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        target = unique_path(self.download_dir, safe_name(req.downloadFileName() or req.suggestedFileName()))
        req.setDownloadDirectory(str(self.download_dir))
        req.setDownloadFileName(target.name)
        req.receivedBytesChanged.connect(lambda: self._progress(req))
        req.stateChanged.connect(lambda state: self._state(req, state, target))
        req.accept()
        self.status.setText(f"Downloading {target.name} ...")
        self.download_started.emit(target.name)
        self.bar.setValue(0)
        self.bar.show()

    def _progress(self, req: QWebEngineDownloadRequest) -> None:
        total = req.totalBytes()
        if total > 0:
            self.bar.setMaximum(100)
            self.bar.setValue(int(req.receivedBytes() * 100 / total))
        else:
            self.bar.setMaximum(0)  # busy indicator

    def _state(self, req: QWebEngineDownloadRequest, state, target: Path) -> None:
        S = QWebEngineDownloadRequest.DownloadState
        if state == S.DownloadCompleted:
            self.bar.hide()
            self.status.setText(f"Saved {target.name}.")
            self.file_saved.emit(str(target))
        elif state in (S.DownloadCancelled, S.DownloadInterrupted):
            self.bar.hide()
            reason = req.interruptReasonString() if state == S.DownloadInterrupted else "cancelled"
            self.status.setText(f"Download of {target.name} failed: {reason}")
            self.file_failed.emit(target.name, reason)
