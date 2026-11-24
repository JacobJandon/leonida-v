"""Leonida's built-in browser (leonida/gui/browser.py) on the real QtWebEngine, offscreen.

Pages are ``data:`` URLs only; the download test clicks a ``data:`` link, so nothing leaves the machine.
"""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LEONIDA_NO_NET", "1")

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal  # noqa: E402

if QCoreApplication.instance() is None:  # must happen before the QApplication exists
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
pytest.importorskip("PySide6.QtWebEngineWidgets")  # imported before the app exists, as QtWebEngine requires

from conftest import flush_deletes  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEnginePage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

pytestmark = pytest.mark.webengine

DS = QWebEngineDownloadRequest.DownloadState


@pytest.fixture(scope="module")
def qapp(qt_app):
    return qt_app


def wait_until(cond, timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.005)
    QApplication.processEvents()
    assert cond(), "timed out waiting for QtWebEngine"


@pytest.fixture(scope="module")
def bw_module(qapp, tmp_path_factory):
    """One BrowserWindow (one QWebEngineProfile named 'leonida') for the whole module."""
    from leonida.gui.browser import BrowserWindow

    root = tmp_path_factory.mktemp("browser")
    win = BrowserWindow(root / "state", root / "downloads")
    yield win
    win.close()
    win.deleteLater()
    flush_deletes()  # really delete it now (page before profile); a pending delete at exit crashes QtWebEngine


@pytest.fixture
def bw(bw_module, tmp_path):
    """The shared window, reset: empty queue, a fresh download folder, no status."""
    bw_module.download_dir = tmp_path / "dl"  # not created yet: the download handler creates it
    bw_module.set_queue([])
    bw_module.current = None
    bw_module.status.setText("")
    bw_module.bar.hide()
    return bw_module


def data_mod(manifest, mod_id: str, body: str):
    return dataclasses.replace(manifest.mod(mod_id), page=f"data:text/html,<title>{mod_id}</title>{body}")


def load(bw, fn) -> bool:
    res = []
    bw.view.loadFinished.connect(res.append)
    try:
        fn()
        wait_until(lambda: res)
    finally:
        bw.view.loadFinished.disconnect(res.append)
    return res[0]


# ---------------------------------------------------------------------------------------------- helpers
def test_safe_name():
    from leonida.gui.browser import safe_name

    assert safe_name("my:mod?.zip") == "my_mod_.zip"
    assert safe_name("folder/sub/file.zip") == "file.zip"
    assert safe_name("bad\x01name|x*.7z") == "bad_name_x_.7z"
    assert safe_name('a"b<c>.rar') == "a_b_c_.rar"
    assert safe_name("  file.zip. ") == "file.zip"
    assert safe_name("") == "download"
    assert safe_name(" .. ") == "download"


def test_unique_path(tmp_path):
    from leonida.gui.browser import unique_path

    assert unique_path(tmp_path, "mod.zip") == tmp_path / "mod.zip"
    (tmp_path / "mod.zip").write_bytes(b"1")
    assert unique_path(tmp_path, "mod.zip") == tmp_path / "mod (2).zip"
    (tmp_path / "mod (2).zip").write_bytes(b"2")
    assert unique_path(tmp_path, "mod.zip") == tmp_path / "mod (3).zip"
    (tmp_path / "README").write_bytes(b"x")
    assert unique_path(tmp_path, "README") == tmp_path / "README (2)"


# ---------------------------------------------------------------------------------------------- window
def test_window_layout_and_profile_paths(bw):
    assert bw.windowTitle() == "Leonida V - get mods"
    assert bw.profile.storageName() == "leonida"
    assert Path(bw.profile.persistentStoragePath()).parts[-2:] == ("browser", "storage")
    assert Path(bw.profile.cachePath()).parts[-2:] == ("browser", "cache")
    # session cookies are kept too, so a Nexus sign-in survives closing Leonida
    assert bw.profile.persistentCookiesPolicy() == bw.profile.PersistentCookiesPolicy.ForcePersistentCookies
    assert not bw.next_btn.isEnabled() and bw.next_btn.text() == "No more mods"
    assert bw.bar.isHidden()


def test_open_mod_loads_the_page_and_explains_what_to_do(bw, manifest):
    mod = data_mod(manifest, "mapfixes", "<h1>Map Fixes</h1>")
    assert load(bw, lambda: bw.open_mod(mod)) is True
    assert bw.current is mod and bw.isVisible()
    title = bw.title.text()
    assert f"<b>{mod.name}</b> by {mod.author}" in title and str(bw.download_dir) in title
    wait_until(lambda: bw.url.text().startswith("data:text/html"))
    wait_until(lambda: bw.view.title() == "mapfixes")
    # unknown author
    anon = dataclasses.replace(mod, author="")
    assert load(bw, lambda: bw.open_mod(anon)) is True
    assert "by unknown." in bw.title.text()


def test_queue_and_next_missing_mod(bw, manifest):
    a = data_mod(manifest, "mapfixes", "a")
    b = data_mod(manifest, "bugstarfixes", "b")
    bw.set_queue([a, b])
    assert bw.next_btn.isEnabled() and bw.next_btn.text() == "Next missing mod (2) >"
    assert load(bw, bw.next_mod) is True
    assert bw.current is a and bw.next_btn.text() == "Next missing mod (1) >"
    assert load(bw, bw.next_btn.click) is True
    assert bw.current is b and not bw.next_btn.isEnabled() and bw.next_btn.text() == "No more mods"
    bw.next_mod()  # nothing left: stays on the last page
    assert bw.current is b and bw.queue == []


def test_set_queue_copies_the_list(bw, manifest):
    mods = [manifest.mod("mapfixes")]
    bw.set_queue(mods)
    mods.append(manifest.mod("lwe"))
    assert len(bw.queue) == 1


def test_typed_address_gets_https(bw, monkeypatch):
    loaded = []
    monkeypatch.setattr(bw.view, "load", lambda url: loaded.append(url.toString()))
    for text in ("example.com/mods", "  http://127.0.0.1:9/x  ", ""):
        bw.url.setText(text)
        QTest.keyClick(bw.url, Qt.Key.Key_Return)
    assert loaded == ["https://example.com/mods", "http://127.0.0.1:9/x", ""]


def test_links_that_open_a_new_window_stay_in_the_same_page(bw):
    page = bw.view.page()
    assert page.createWindow(QWebEnginePage.WebWindowType.WebBrowserTab) is page
    assert page.createWindow(QWebEnginePage.WebWindowType.WebDialog) is page


# ------------------------------------------------------------------------------------------- downloads
def test_real_download_lands_in_the_download_folder(bw, manifest):
    page = data_mod(manifest, "mapfixes", "<p>download page</p>")
    assert load(bw, lambda: bw.open_mod(page)) is True
    saved = []
    bw.file_saved.connect(saved.append)
    click = ("var a=document.createElement('a');a.href='data:application/zip;base64,aGVsbG8=';"
             "a.download='Map:Fixes?.zip';document.body.appendChild(a);a.click();")
    try:
        bw.view.page().runJavaScript(click)
        wait_until(lambda: len(saved) == 1)
        first = Path(saved[0])
        assert first == bw.download_dir / "Map_Fixes_.zip"
        wait_until(lambda: first.is_file() and first.read_bytes() == b"hello")
        assert bw.status.text() == "Saved Map_Fixes_.zip." and bw.bar.isHidden()
        bw.view.page().runJavaScript(click)  # same name again: kept side by side
        wait_until(lambda: len(saved) == 2)
        assert Path(saved[1]) == bw.download_dir / "Map_Fixes_ (2).zip"
    finally:
        bw.file_saved.disconnect(saved.append)
    assert sorted(p.name for p in bw.download_dir.iterdir()) == ["Map_Fixes_ (2).zip", "Map_Fixes_.zip"]


class FakeRequest(QObject):
    """The parts of QWebEngineDownloadRequest that BrowserWindow uses."""

    receivedBytesChanged = Signal()  # noqa: N815 - Qt naming
    stateChanged = Signal(object)  # noqa: N815

    def __init__(self, file_name="", suggested="mod.zip", total=0, received=0, reason="Network error"):
        super().__init__()
        self.file_name, self.suggested = file_name, suggested
        self.total, self.received, self.reason = total, received, reason
        self.directory = None
        self.accepted = False

    def downloadFileName(self):  # noqa: N802
        return self.file_name

    def suggestedFileName(self):  # noqa: N802
        return self.suggested

    def setDownloadDirectory(self, d):  # noqa: N802
        self.directory = d

    def setDownloadFileName(self, name):  # noqa: N802
        self.file_name = name

    def accept(self):
        self.accepted = True

    def totalBytes(self):  # noqa: N802
        return self.total

    def receivedBytes(self):  # noqa: N802
        return self.received

    def interruptReasonString(self):  # noqa: N802
        return self.reason


def test_download_handler_wiring_with_a_fake_request(bw):
    saved = []
    bw.file_saved.connect(saved.append)
    try:
        bw.download_dir.mkdir(parents=True, exist_ok=True)
        (bw.download_dir / "Menyoo.zip").write_bytes(b"old")
        req = FakeRequest(file_name="", suggested="sub/Menyoo.zip", total=200)
        bw._download(req)
        assert req.accepted and req.directory == str(bw.download_dir)
        assert req.file_name == "Menyoo (2).zip"
        assert bw.status.text() == "Downloading Menyoo (2).zip ..." and not bw.bar.isHidden()
        req.received = 50
        req.receivedBytesChanged.emit()
        assert bw.bar.maximum() == 100 and bw.bar.value() == 25
        req.total = 0
        req.receivedBytesChanged.emit()
        assert bw.bar.maximum() == 0  # unknown size: busy indicator
        req.stateChanged.emit(DS.DownloadInProgress)
        assert saved == [] and not bw.bar.isHidden()
        req.stateChanged.emit(DS.DownloadCompleted)
        assert saved == [str(bw.download_dir / "Menyoo (2).zip")]
        assert bw.status.text() == "Saved Menyoo (2).zip." and bw.bar.isHidden()
    finally:
        bw.file_saved.disconnect(saved.append)


@pytest.mark.parametrize("state, text", [
    (DS.DownloadCancelled, "Download of x.zip failed: cancelled"),
    (DS.DownloadInterrupted, "Download of x.zip failed: Network error"),
])
def test_download_cancelled_or_interrupted(bw, state, text):
    saved = []
    bw.file_saved.connect(saved.append)
    try:
        req = FakeRequest(file_name="x.zip")
        bw._download(req)
        req.stateChanged.emit(state)
    finally:
        bw.file_saved.disconnect(saved.append)
    assert bw.status.text() == text and bw.bar.isHidden() and saved == []


def test_main_window_opens_the_real_browser_and_hears_saved_files(qapp, bw_module, tmp_path, game, downloads,
                                                                 monkeypatch):
    """MainWindow.open_page with the real BrowserWindow class (its own profile instance is avoided by reusing
    the module's window), then a saved file updates the Get mods page."""
    import leonida.gui.app as A
    from leonida.session import Session

    monkeypatch.delenv("LEONIDA_NO_OPEN", raising=False)
    monkeypatch.setenv("LEONIDA_NO_UPDATE_CHECK", "1")
    s = Session(state=tmp_path / "gui-state", download_dir=str(downloads), game_dir=str(game),
                game_build="1.0.1013.20")
    win = A.MainWindow(s)
    try:
        bw_module.file_saved.connect(win._file_saved)
        win.browser = bw_module
        mod = data_mod(s.manifest, "mapfixes", "<p>map fixes</p>")
        queue = [data_mod(s.manifest, "bugstarfixes", "b")]
        assert load(bw_module, lambda: win.open_page(mod, queue=queue)) is True
        assert bw_module.download_dir == downloads and bw_module.current is mod
        assert [m.id for m in bw_module.queue] == ["bugstarfixes"]
        f = downloads / "ScriptHookV_1.0.zip"
        f.write_bytes(b"PK")
        bw_module.file_saved.emit(str(f))
        assert bw_module.status.text() == "Saved ScriptHookV_1.0.zip: recognised as Script Hook V."
        assert win.statusBar().currentMessage() == bw_module.status.text()
    finally:
        bw_module.file_saved.disconnect(win._file_saved)
        win.browser = None
        win.close()
        win.deleteLater()
        flush_deletes()


def test_main_window_creates_its_browser_once(qapp, tmp_path, game, downloads, monkeypatch):
    """With no browser yet, MainWindow builds a real BrowserWindow (state/browser in the session's state)."""
    import leonida.gui.app as A
    from leonida.session import Session

    monkeypatch.delenv("LEONIDA_NO_OPEN", raising=False)
    monkeypatch.setenv("LEONIDA_NO_UPDATE_CHECK", "1")
    s = Session(state=tmp_path / "gui-state", download_dir=str(downloads), game_dir=str(game),
                game_build="1.0.1013.20")
    win = A.MainWindow(s)
    made = []
    from leonida.gui import browser as B

    real = B.BrowserWindow

    def spy(*a, **k):
        made.append(a)
        return real(*a, **k)

    monkeypatch.setattr(B, "BrowserWindow", spy)
    try:
        mod = data_mod(s.manifest, "mapfixes", "m")
        win.open_page(mod)
        win.open_page(dataclasses.replace(mod, page="data:text/html,again"))
        assert len(made) == 1 and made[0] == (s.state, downloads, win)
        assert isinstance(win.browser, real) and win.browser.parent() is win
        assert Path(win.browser.profile.persistentStoragePath()).is_relative_to(s.state)
    finally:
        if win.browser is not None:
            win.browser.close()
            win.browser.view.setPage(None)
        win.close()
        win.deleteLater()
        flush_deletes()


def test_fake_request_mirrors_the_real_api():
    # the fake request mirrors the real class's method names (guards against API drift in PySide6)
    for name in ("downloadFileName", "suggestedFileName", "setDownloadDirectory", "setDownloadFileName", "accept",
                 "totalBytes", "receivedBytes", "interruptReasonString", "receivedBytesChanged", "stateChanged"):
        assert hasattr(QWebEngineDownloadRequest, name), name
