"""Offscreen tests for every wizard page and button handler (leonida/gui: app, chooser, images, workers).

Nothing here blocks, opens a window outside Qt's offscreen platform, touches the network or the real game folder:
message boxes, input/file dialogs, ``QDialog.exec``, ``webbrowser``, ``QDesktopServices`` and ``subprocess`` are
replaced per test, downloads/updates use fakes, and every Session lives in ``tmp_path``.
"""

from __future__ import annotations

import copy
import dataclasses
import os
import re
import sys
import threading
import time
import types
import warnings
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LEONIDA_NO_NET", "1")

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal  # noqa: E402

if QCoreApplication.instance() is None:  # QtWebEngine (browser tests) needs this before the app exists
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from conftest import AutoUI, flush_deletes, make_zip  # noqa: E402
from PySide6.QtGui import QColor, QDesktopServices, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
)

import leonida  # noqa: E402
import leonida.gui.app as A  # noqa: E402
from leonida import PACK_NAME, __version__  # noqa: E402
from leonida.checks import ERROR, INFO, WARNING, Finding  # noqa: E402
from leonida.detect import GameInstall  # noqa: E402
from leonida.downloader import DownloadError, DownloadPlan  # noqa: E402
from leonida.gui import theme  # noqa: E402
from leonida.gui.chooser import SOURCE_TEXT, ChoosePage, how_text  # noqa: E402
from leonida.gui.images import INDEX, ImageLoader, network_allowed  # noqa: E402
from leonida.gui.workers import MainThreadCaller, start_worker  # noqa: E402
from leonida.installer import InstallError  # noqa: E402
from leonida.manifest import Manifest  # noqa: E402
from leonida.onlinesafe import OnlineSafeError  # noqa: E402
from leonida.paths import LOCK_NAME  # noqa: E402
from leonida.session import Session  # noqa: E402
from leonida.verify import VerifyResult  # noqa: E402

BUILD = "1.0.1013.20"            # NVE has a variant for it; nothing unsupported
BUILD_NO_NVE = "1.0.1013.29"     # NVE is unsupported on this build
SB = QMessageBox.StandardButton


# ------------------------------------------------------------------------------------------------ helpers
@pytest.fixture(scope="session")
def qapp(qt_app):
    return qt_app


def wait_until(cond, timeout: float = 20.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.005)
    QApplication.processEvents()
    assert cond(), "timed out waiting for the GUI"


def idle(obj) -> bool:
    """True once every worker started with ``obj`` as parent has finished and been cleaned up."""
    return not getattr(obj, "_leonida_workers", None)


def wait_idle(*objs, timeout: float = 20.0) -> None:
    wait_until(lambda: all(idle(o) for o in objs), timeout)


def make_png(path: Path, color: str = "red") -> Path:
    pix = QPixmap(32, 18)
    pix.fill(QColor(color))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert pix.save(str(path), "PNG")
    return path


def patch_mods(session: Session, **changes: dict) -> None:
    """Give the session a manifest where some mods have changed fields (e.g. a slot or GPU requirement)."""
    base = copy.copy(session.base_manifest)
    base.mods = dict(base.mods)
    for mid, fields in changes.items():
        base.mods[mid] = dataclasses.replace(base.mods[mid], **fields)
    session.manifest = base


class Dialogs:
    """Stands in for every modal dialog / external opener and records what the GUI asked."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []   # (kind, text) for QMessageBox statics
        self.answer = SB.Yes                     # what QMessageBox.question returns
        self.items: list = []                    # QInputDialog.getItem answers: (text, ok) or callable(items)
        self.item_prompts: list[tuple[str, list]] = []
        self.directory = ""                      # QFileDialog.getExistingDirectory
        self.button = None                       # text of the QMessageBox button to click in exec()
        self.boxes: list[str] = []               # QMessageBox.exec texts
        self.accept = True                       # QDialog.exec result
        self.on_dialog = None                    # hook(dialog) run inside the fake QDialog.exec
        self.dialogs: list[QDialog] = []
        self.opened: list[tuple[str, object]] = []

    def texts(self, kind: str) -> list[str]:
        return [t for k, t in self.calls if k == kind]


@pytest.fixture(autouse=True)
def trace_qt_threads(monkeypatch):
    """Let coverage see code that runs on QThread / QThreadPool threads (it only hooks Python-started threads).

    Wraps the two thread entry points so the active trace function is installed in the Qt thread first; the
    original code then runs unchanged. Does nothing when no tracer is active (plain pytest or sys.monitoring)."""
    tracer = threading.gettrace()
    if tracer is None:
        return
    from leonida.gui import images, workers

    def traced(orig):
        def run(self, *a):
            sys.settrace(tracer)
            try:
                return orig(self, *a)
            finally:
                sys.settrace(None)
        return run

    monkeypatch.setattr(workers._Worker, "run", traced(workers._Worker.run))
    monkeypatch.setattr(images._Job, "run", traced(images._Job.run))


@pytest.fixture(autouse=True)
def dialogs(monkeypatch, tmp_path):
    d = Dialogs()
    monkeypatch.setenv("LEONIDA_NO_OPEN", "1")
    monkeypatch.setenv("LEONIDA_NO_NET", "1")
    monkeypatch.setenv("LEONIDA_NO_UPDATE_CHECK", "1")
    monkeypatch.setenv("LEONIDA_FAKE_GPU", "")
    monkeypatch.setenv("LEONIDA_STATE_DIR", str(tmp_path / "env-state"))
    monkeypatch.setenv("LEONIDA_DOWNLOAD_DIR", str(tmp_path / "env-downloads"))

    def box(kind, ret):
        def fake(parent, title, text, *a, **k):
            d.calls.append((kind, text))
            return d.answer if kind == "question" else ret
        return staticmethod(fake)

    monkeypatch.setattr(QMessageBox, "question", box("question", SB.Yes))
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, kind, box(kind, SB.Ok))

    def get_item(parent, title, label, items, *a, **k):
        d.item_prompts.append((label, list(items)))
        ans = d.items.pop(0)
        return ans(list(items)) if callable(ans) else ans

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(get_item))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: d.directory))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))   # never a real one

    def box_exec(self):
        d.boxes.append(self.text())
        for b in self.buttons():
            if b.text() == d.button:
                b.click()
        return 0

    def dlg_exec(self):
        d.dialogs.append(self)
        if d.on_dialog:
            d.on_dialog(self)
        return QDialog.DialogCode.Accepted if d.accept else QDialog.DialogCode.Rejected

    monkeypatch.setattr(QMessageBox, "exec", box_exec)
    monkeypatch.setattr(QDialog, "exec", dlg_exec)

    import webbrowser

    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, lambda url, *a, _n=name, **k: d.opened.append((_n, url)))
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: d.opened.append(("url", url))))
    monkeypatch.setattr(os, "startfile", lambda *a, **k: d.opened.append(("startfile", a)), raising=False)
    monkeypatch.setattr(A, "subprocess", types.SimpleNamespace(
        Popen=lambda *a, **k: d.opened.append(("popen", (a, k)))))

    def no_network(*a, **k):
        raise AssertionError("network access in a GUI test")

    monkeypatch.setattr("leonida.downloader._open", no_network)
    monkeypatch.setattr("leonida.downloader.page_image", lambda *a, **k: None)
    monkeypatch.setattr("leonida.downloader.fetch_image", lambda *a, **k: None)
    return d


@pytest.fixture
def make_win(qapp, tmp_path, game, downloads):
    wins: list[A.MainWindow] = []

    def make(build: str | None = BUILD, game_dir="default", show: bool = False) -> A.MainWindow:
        s = Session(state=tmp_path / f"gui-state{len(wins)}", download_dir=str(downloads),
                    game_dir=str(game) if game_dir == "default" else game_dir, game_build=build)
        w = A.MainWindow(s)
        wins.append(w)
        if show:
            w.show()
            QApplication.processEvents()
        return w

    yield make
    for w in wins:
        wait_idle(w, *w.pages)
        w.close()
        w.deleteLater()
    flush_deletes()


@pytest.fixture
def shv_zip(downloads) -> Path:
    return make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "shv", "bin/xinput1_4.dll": "loader"})


# --------------------------------------------------------------------------------------- module helpers
def test_title_wrap_and_logo(qapp):
    lab = A._title("Hello")
    assert lab.text() == "Hello" and lab.font().bold() and lab.font().pointSize() == 16
    w = A._wrap("<b>x</b>")
    assert w.wordWrap() and w.openExternalLinks() and w.textFormat() == Qt.TextFormat.RichText
    assert A.logo_path().is_file() and A.logo_path().name == "leonida.png"


def test_logo_path_in_a_frozen_build(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert A.logo_path() == Path(A.__file__).resolve().parent / "assets" / "leonida.png"  # not bundled: fallback
    bundled = tmp_path / "leonida" / "gui" / "assets" / "leonida.png"
    make_png(bundled)
    assert A.logo_path() == bundled


def test_verify_results_returns_results_and_swallows_errors(monkeypatch):
    r = VerifyResult("ok", "loaded", "fine", mod="scripthookv")
    monkeypatch.setattr("leonida.verify.verify_session", lambda s: [r])
    assert A._verify_results(object()) == [r]

    def boom(s):
        raise ValueError("broken logs")

    monkeypatch.setattr("leonida.verify.verify_session", boom)
    assert A._verify_results(object()) == []


def test_open_respects_no_open_and_uses_the_right_opener(dialogs, monkeypatch, tmp_path):
    A._open("https://example.com/mod")
    assert dialogs.opened == []
    monkeypatch.delenv("LEONIDA_NO_OPEN")
    A._open("https://example.com/mod")
    A._open(str(tmp_path))
    assert dialogs.opened[0] == ("open_new_tab", "https://example.com/mod")
    kind, url = dialogs.opened[1]
    assert kind == "url" and url.isLocalFile() and Path(url.toLocalFile()) == tmp_path


def test_main_builds_the_window_and_runs_the_event_loop(qapp, monkeypatch, tmp_path):
    import ctypes

    ids = []
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(shell32=types.SimpleNamespace(
        SetCurrentProcessExplicitAppUserModelID=ids.append)), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    made = []

    class Win(A.MainWindow):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)

    monkeypatch.setattr(A, "MainWindow", Win)
    monkeypatch.setattr(QApplication, "exec", lambda *a: 0)
    old_name = qapp.applicationName()
    try:
        assert A.main() == 0
    finally:
        qapp.setApplicationName(old_name)
    assert ids == ["JacobJandon.LeonidaV"]
    assert len(made) == 1 and made[0].isVisible()
    assert made[0].windowTitle() == f"{PACK_NAME} {__version__}"
    assert made[0].session.state == tmp_path / "env-state"  # default Session honours LEONIDA_STATE_DIR
    made[0].close()
    made[0].deleteLater()


def test_running_the_module_as_a_script_calls_main(qapp, monkeypatch):
    import runpy

    monkeypatch.setattr(QApplication, "exec", lambda *a: 0)
    before = set(QApplication.topLevelWidgets())
    old_name = qapp.applicationName()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("leonida.gui.app", run_name="__main__")
    qapp.setApplicationName(old_name)
    assert exc.value.code == 0
    for w in set(QApplication.topLevelWidgets()) - before:
        w.close()
        w.deleteLater()
    QApplication.processEvents()


# ---------------------------------------------------------------------------------------------- GuiUI
def test_gui_ui_info_warn_confirm_on_the_ui_thread(make_win, dialogs):
    win = make_win()
    view = win.pages[5].view
    ui = A.GuiUI(win, view)
    ui.info("hello")
    ui.warn("careful")
    assert view.toPlainText().splitlines()[-2:] == ["hello", "! careful"]
    assert ui.confirm("Proceed?") is True
    dialogs.answer = SB.No
    assert ui.confirm("Proceed?") is False
    assert dialogs.texts("question") == ["Proceed?", "Proceed?"]


def test_gui_ui_dialogs_from_a_worker_thread(make_win, dialogs, tmp_path):
    win = make_win()
    page = win.pages[5]
    ui = A.GuiUI(page, page.view, win.caller)
    seen = {}

    def work():
        seen["thread"] = threading.get_ident()
        ui.info("from worker")
        seen["confirm"] = ui.confirm("Overwrite?")
        seen["done"] = ui.wait_done("Copy files", ["one", "two"], None)
        return "ok"

    start_worker(page, work, on_done=lambda r: seen.setdefault("result", r))
    wait_idle(page)
    wait_until(lambda: "result" in seen)  # on_done arrives through the event queue after the thread ended
    assert seen["thread"] != threading.get_ident()
    assert seen == {**seen, "confirm": True, "done": True, "result": "ok"}
    assert "from worker" in page.view.toPlainText()
    dlg = dialogs.dialogs[-1]
    assert dlg.windowTitle() == "Manual step: Copy files"
    labels = " ".join(lab.text() for lab in dlg.findChildren(QLabel))
    assert "<li>one</li><li>two</li>" in labels
    assert not [b for b in dlg.findChildren(QPushButton) if b.text().startswith("Open files")]


def test_wait_done_opens_the_folder_and_can_be_cancelled(make_win, dialogs, monkeypatch, tmp_path):
    win = make_win()
    ui = A.GuiUI(win, win.pages[5].view, win.caller)
    folder = tmp_path / "extracted"
    folder.mkdir()
    clicked = []

    def press_open(dlg):
        btn = next(b for b in dlg.findChildren(QPushButton) if b.text().startswith("Open files"))
        btn.click()
        clicked.append(btn.text())

    # LEONIDA_NO_OPEN set: the button exists but nothing is opened
    dialogs.on_dialog = press_open
    assert ui.wait_done("Guided", [], folder) is True
    assert dialogs.opened == [] and clicked == [f"Open files: {folder}"]
    labels = " ".join(lab.text() for lab in dialogs.dialogs[-1].findChildren(QLabel))
    assert "Follow the mod's readme." in labels

    monkeypatch.delenv("LEONIDA_NO_OPEN")
    dialogs.accept = False
    assert ui.wait_done("Guided", ["x"], folder) is False
    opened = [Path(u.toLocalFile()) for k, u in dialogs.opened if k == "url"]
    assert opened == [folder, folder]  # once when the dialog opens, once for the button


def test_gui_ui_launch_starts_the_installer_unless_no_open(make_win, dialogs, monkeypatch, tmp_path):
    win = make_win()
    view = win.pages[5].view
    ui = A.GuiUI(win, view)
    exe = tmp_path / "tool" / "Install_GTA6Hud.bat"
    exe.parent.mkdir()
    exe.write_text("@echo off")
    monkeypatch.setattr(sys, "platform", "win32")
    ui.launch(exe)
    assert dialogs.opened == []
    assert "Started Install_GTA6Hud.bat" in view.toPlainText()
    monkeypatch.delenv("LEONIDA_NO_OPEN")
    ui.launch(exe)
    kind, (args, kwargs) = dialogs.opened[0]
    assert kind == "popen" and args[0] == A.windows_launch_command(exe) and kwargs["cwd"] == str(exe.parent)


# ------------------------------------------------------------------------------------------ Welcome / nav
def test_welcome_page_and_navigation(make_win, monkeypatch):
    win = make_win(show=True)
    welcome = win.pages[0]
    texts = [lab.text() for lab in welcome.findChildren(QLabel)]
    assert f"{PACK_NAME} {__version__}" in texts
    assert any("Story mode only" in t for t in texts)
    assert any(lab.pixmap() is not None and not lab.pixmap().isNull() for lab in welcome.findChildren(QLabel))
    assert not win.back.isEnabled() and win.fwd.isEnabled()
    win.fwd.click()
    assert win.stack.currentIndex() == 1 and win.nav.currentRow() == 1
    win.back.click()
    assert win.stack.currentIndex() == 0
    win.go(99)
    assert win.stack.currentIndex() == len(A.PAGES) - 1 and not win.fwd.isEnabled() and win.back.isEnabled()
    win.go(-5)
    assert win.stack.currentIndex() == 0
    win.nav.setCurrentRow(4)
    assert win.stack.currentIndex() == 4

    monkeypatch.setattr(A, "logo_path", lambda name="leonida.png": Path("missing.png"))
    page = A.WelcomePage(win)
    assert all(lab.pixmap() is None or lab.pixmap().isNull() for lab in page.findChildren(QLabel))


# ---------------------------------------------------------------------------------------------- Game page
def test_game_page_shows_selection_and_detects_games(make_win, monkeypatch, game, tmp_path):
    win = make_win(game_dir=None)
    page = win.pages[1]
    assert page.current.text() == f"Selected: (none)   version: {BUILD}"
    other = tmp_path / "Other GTA"
    other.mkdir()
    (other / "GTA5_Enhanced.exe").write_bytes(b"MZ")
    seen = []

    def fake_detect(exe_names):
        seen.append(exe_names)
        return [GameInstall(game, "steam", game / "GTA5_Enhanced.exe", "1.0.1013.20"),
                GameInstall(other, "epic", other / "GTA5_Enhanced.exe", None)]

    monkeypatch.setattr(A, "detect_games", fake_detect)
    page.detect()
    assert seen == [("GTA5_Enhanced.exe", "GTA5.exe")]
    assert page.list.count() == 2
    assert page.list.item(0).text() == f"{game}   [steam]   1.0.1013.20"
    assert page.list.item(1).data(Qt.ItemDataRole.UserRole) == str(other)
    assert win.session.config.game_dir == str(game)  # first hit picked automatically
    assert str(game) in page.current.text()
    # clicking another row selects it
    page.list.itemClicked.emit(page.list.item(1))
    assert win.session.config.game_dir == str(other)
    # detecting again keeps the user's choice
    page.detect()
    assert win.session.config.game_dir == str(other)
    # nothing found
    monkeypatch.setattr(A, "detect_games", lambda names: [])
    page.detect()
    assert page.list.count() == 1 and page.list.item(0).text().startswith("Not found automatically")


def test_game_page_browse_good_bad_and_cancelled(make_win, dialogs, game, tmp_path):
    win = make_win(game_dir=None)
    page = win.pages[1]
    dialogs.directory = ""
    page.browse()
    assert not win.session.config.game_dir
    wrong = tmp_path / "not-gta"
    wrong.mkdir()
    dialogs.directory = str(wrong)
    page.browse()
    assert dialogs.texts("warning") == ["No GTA5_Enhanced.exe or GTA5.exe in that folder."]
    assert not win.session.config.game_dir
    dialogs.directory = str(game)
    page.browse()
    assert win.session.config.game_dir == str(game)
    assert Session(state=win.session.state).config.game_dir == str(game)  # saved
    page.set_dir(None)
    page.set_dir("")
    assert win.session.config.game_dir == str(game)


# -------------------------------------------------------------------------------------------- Choose mods
def test_how_text_for_every_route(manifest):
    assert how_text(manifest.mod("menyoo")) == "automatic download"
    for source, text in SOURCE_TEXT.items():
        mod = next(m for m in manifest.mods.values() if m.source == source and not m.download)
        assert how_text(mod) == text
    assert how_text(manifest.mod("mapfixes")) == "in-app download (author's page)"


def test_choose_profile_switch_rebuilds_cards(make_win):
    win = make_win()
    page = win.pages[2]
    assert isinstance(page, ChoosePage)
    s = win.session
    buttons = {b.property("pid"): b for b in page.group.buttons()}
    assert buttons["core"].isChecked()
    assert not buttons["max-rtx50"].isEnabled()  # no RTX 50 GPU
    assert "RTX 50-series" in buttons["max-rtx50"].toolTip()
    assert not page.cards["immersivecombat"].control.isChecked()
    assert page.summary.text() == "<b>15</b> mods selected."  # Core's 14 mods + Leonida's in-game menu
    assert f"Game build: <b>{BUILD}</b>" in page.build_label.text()
    buttons["core-plus"].click()
    assert s.config.profile == "core-plus"
    assert page.desc.text() == s.manifest.profile("core-plus").description
    assert page.cards["immersivecombat"].control.isChecked()
    assert page.summary.text() == f"<b>{len(s.mods())}</b> mods selected."
    assert Session(state=s.state).config.profile == "core-plus"


def test_choose_rtx50_gpu_enables_the_profile(make_win, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GPU", "NVIDIA GeForce RTX 5090")
    win = make_win()
    page = win.pages[2]
    rb = next(b for b in page.group.buttons() if b.property("pid") == "max-rtx50")
    assert rb.isEnabled()
    labels = [lab.text() for lab in page.findChildren(QLabel)]
    assert any("GPU: NVIDIA GeForce RTX 5090." in t for t in labels)


def test_choose_toggle_include_and_guards(make_win):
    win = make_win()
    page = win.pages[2]
    c = win.session.config
    page._building = True
    page.toggle("menyoo", False)
    page.pick_slot("hud", "hud")
    assert c.remove == [] and c.swaps == {}
    page._building = False
    menyoo = page.cards["menyoo"].control
    menyoo.setChecked(False)
    assert c.remove == ["menyoo"] and page.summary.text() == "<b>14</b> mods selected."
    menyoo.setChecked(True)  # back in: removed from the remove list, not added (the profile brings it)
    assert c.remove == [] and c.add == []
    assert page.summary.text() == "<b>15</b> mods selected."
    extra = page.cards["immersivecombat"].control
    extra.setChecked(True)
    assert c.add == ["immersivecombat"] and page.summary.text() == "<b>16</b> mods selected."
    extra.setChecked(False)
    assert c.add == [] and c.remove == []


def test_choose_slot_swaps_and_clears_other_additions(make_win):
    win = make_win()
    page = win.pages[2]
    c = win.session.config
    assert set(page.slot_buttons) >= {"hud"}
    assert isinstance(page.cards["hud"].control, QRadioButton)
    assert page.cards["hud-geckomacabre"].control.isChecked()
    page.cards["hud"].control.setChecked(True)
    assert c.swaps == {"hud-geckomacabre": "hud"}
    c.add.append("hud-fbicat")  # a stale addition of another member is dropped on the next pick
    page.pick_slot("hud", "hud")
    assert c.add == [] and c.swaps == {"hud-geckomacabre": "hud"}
    page.cards["hud-geckomacabre"].control.setChecked(True)
    assert c.swaps == {}


def test_choose_slot_without_a_profile_default_adds_the_pick(make_win):
    win = make_win()
    s = win.session
    patch_mods(s, immersivecombat={"slot": "test-slot"}, enableallinteriors={"slot": "test-slot"})
    page = win.pages[2]
    page.rebuild()
    assert "test-slot" in page.slot_buttons
    assert not page.cards["immersivecombat"].control.isChecked()
    page.cards["enableallinteriors"].control.setChecked(True)
    assert s.config.add == ["enableallinteriors"]
    page.pick_slot("test-slot", "enableallinteriors")  # picking again doesn't duplicate it
    assert s.config.add == ["enableallinteriors"]
    page.cards["immersivecombat"].control.setChecked(True)
    assert s.config.add == ["immersivecombat"]
    assert s.config.swaps == {}


def test_choose_gpu_requirement_disables_a_mod(make_win):
    win = make_win()
    patch_mods(win.session, immersivecombat={"requires": {"gpu": "rtx50"}})
    page = win.pages[2]
    page.rebuild()
    ctl = page.cards["immersivecombat"].control
    assert not ctl.isEnabled() and ctl.toolTip() == "Needs an NVIDIA RTX 50-series GPU."
    assert not page.cards["scripthookv"].control.isEnabled()
    assert page.cards["scripthookv"].control.toolTip() == "Required: other mods depend on it."


def test_choose_unsupported_mod_card_for_the_game_build(make_win):
    win = make_win(build=BUILD_NO_NVE)
    win.session.config.add = ["nve"]  # NVE is a paid add-on now, not in Core
    page = win.pages[2]
    card = page.cards["nve"]
    reason = win.session.manifest.mod("nve").unsupported
    assert reason and "No NaturalVision Enhanced release" in reason
    assert not card.isEnabled() and not card.control.isEnabled()
    assert card.toolTip() == reason and card.control.toolTip() == reason
    notes = [lab.text() for lab in card.findChildren(QLabel)]
    assert any("Not available for your game build" in t and theme.COLORS["error"] in t for t in notes)
    assert page.cards["menyoo"].isEnabled()
    # the Get page shows the same build problem
    get = win.pages[3]
    get.refresh()
    row = next(r for r, m in enumerate(get.mods) if m.id == "nve")
    assert get.table.item(row, get.STATUS).text() == "not for this game build"
    assert get.table.item(row, get.STATUS).toolTip() == reason


def test_choose_falls_back_when_for_build_fails(make_win, monkeypatch):
    win = make_win()
    page = win.pages[2]
    _ = win.session.manifest  # resolve once, so only the chooser's own call fails below

    def boom(self, build):
        raise RuntimeError("bad build table")

    monkeypatch.setattr(Manifest, "for_build", boom)
    mods = page._resolved_mods()
    assert set(mods) == set(win.session.manifest.mods)


def test_choose_card_images_page_button_and_enlarge(make_win, dialogs, monkeypatch, tmp_path):
    win = make_win()
    page = win.pages[2]
    card = page.cards["menyoo"]
    opened = []
    monkeypatch.setattr(win, "open_page", lambda mod, queue=None: opened.append(mod.id))
    next(b for b in card.findChildren(QPushButton) if b.text() == "Page").click()
    assert opened == ["menyoo"]
    # no picture yet: clicking the thumbnail does nothing
    QTest.mouseClick(card.thumb, Qt.MouseButton.LeftButton)
    assert dialogs.dialogs == [] and card.thumb.text() == "Tools"
    # a broken file is ignored, unknown keys and empty paths too
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    win.images.loaded.emit("menyoo", str(bad))
    win.images.loaded.emit("menyoo", "")
    win.images.loaded.emit("no-such-mod", str(bad))
    assert card.thumb.full is None
    png = make_png(tmp_path / "menyoo.png")
    win.images.loaded.emit("menyoo", str(png))
    wait_until(lambda: card.thumb.full is not None)        # decoded on a pool thread
    assert card.thumb.pixmap().width() == 256
    QTest.mouseClick(card.thumb, Qt.MouseButton.LeftButton)
    assert len(dialogs.dialogs) == 1 and dialogs.dialogs[0].windowTitle() == card.mod.name


def test_choose_requests_preview_images_through_the_loader(make_win, monkeypatch, tmp_path):
    monkeypatch.delenv("LEONIDA_NO_NET")
    png = make_png(tmp_path / "src" / "pic.png", "blue")
    pages, fetched = [], []

    def page_image(url, *a, **k):
        pages.append(url)
        return "https://img.example/" + url.rsplit("/", 1)[-1] + ".png"

    def fetch_image(url, cache_dir, *a, **k):
        fetched.append(url)
        return png

    monkeypatch.setattr("leonida.downloader.page_image", page_image)
    monkeypatch.setattr("leonida.downloader.fetch_image", fetch_image)
    win = make_win()
    page = win.pages[2]
    packs = [p for p in win.session.base_manifest.packs.values() if p.picture]
    wait_until(lambda: all(c.thumb.full is not None for c in page.cards.values())
               and all(page.packs.cards[p.id].art.pixmap is not None for p in packs))
    assert len(fetched) == len(page.cards) + len(packs)  # every mod card and every modpack card
    assert sorted(f"pack:{p.id}" for p in packs) == sorted(k for k in win.images.paths if k.startswith("pack:"))
    no_image = [m for m in win.session.manifest.mods.values() if not m.image]
    assert sorted(pages) == sorted(m.page for m in no_image)


# ----------------------------------------------------------------------------------------------- Get mods
def test_get_page_table_hint_and_buttons(make_win, shv_zip, downloads):
    (downloads / "mystery.zip").write_bytes(b"?")
    win = make_win()
    page = win.pages[3]
    page.refresh()
    n = len(page.mods)  # the core set comes from mods.json, which mod-sources keeps changing
    assert page.table.rowCount() == n
    assert page.table.item(0, 1).text() == "Script Hook V"
    assert page.table.item(0, page.STATUS).text() == "ready"
    assert page.table.item(0, 4).text() == "ScriptHookV_1.0.zip · not checked yet"  # with the test place's status
    assert page.table.item(0, 1).toolTip().startswith("Version for your game build:")
    row = next(r for r, m in enumerate(page.mods) if m.id == "menyoo")
    assert page.table.item(row, page.STATUS).text() == "missing"
    assert page.table.item(row, 2).text() == "automatic download"
    assert page.table.item(row, 4).text() == page.mods[row].page
    n_auto = sum(1 for m in page.result.missing(page.mods) if m.download)
    assert page.auto_btn.text() == f"Download all automatic ({n_auto})" and page.auto_btn.isEnabled()
    assert page.browse_btn.isEnabled()
    hint = page.hint.text()
    assert f"<b>1/{n}</b> ready." in hint and "1 file(s) not recognised" in hint and str(downloads) in hint
    assert not (win.session.state / LOCK_NAME).exists()


def test_get_page_writes_the_lock_when_everything_is_ready(make_win, downloads, dialogs, monkeypatch):
    from leonida.members import member_problem

    def member_for(pattern: str) -> str:  # a path that matches the glob: * and ? -> x, [abc] -> a
        return re.sub(r"\[!?\^?(.)[^\]]*\]", r"\1", pattern).replace("*", "x").replace("?", "x")

    win = make_win()
    s = win.session
    mods = s.mods()
    for i, m in enumerate(mods):
        if m.require_members or m.reject_members:  # a real archive that passes the mod's own content rules
            members = {member_for(p): "x" * (i + 1) for p in m.require_members} or {"readme.txt": "x" * (i + 1)}
            assert member_problem(m, list(members)) is None, (m.id, member_problem(m, list(members)))
            make_zip(downloads / f"file{i}.zip", members)
        else:
            (downloads / f"file{i}.zip").write_bytes(b"x" * (i + 1))
        s.config.assignments[f"file{i}.zip"] = m.id
    page = win.pages[3]
    page.refresh()
    wrong = {p.name: why for p, why in page.result.wrong.items()}
    assert f"<b>{len(mods)}/{len(mods)}</b> ready." in page.hint.text(), wrong  # follows mods.json's core set
    wait_until(lambda: (s.state / LOCK_NAME).is_file())   # written on a worker thread
    assert not page.auto_btn.isEnabled() and not page.browse_btn.isEnabled()
    # nothing left to fetch: both download routes do nothing
    monkeypatch.delenv("LEONIDA_NO_NET")
    calls = []
    monkeypatch.setattr("leonida.downloader.plan_for", lambda m: calls.append(m))
    monkeypatch.setattr(win, "open_page", lambda *a, **k: calls.append(a))
    page.download_auto()
    page.get_in_browser()
    assert calls == [] and page.busy == {} and page.cancel_btn.isHidden()


def test_get_page_timer_runs_only_while_visible(make_win):
    win = make_win(show=True)
    page = win.pages[3]
    win.go(3)
    QApplication.processEvents()
    assert page.timer.isActive() and page.table.rowCount() == 15
    win.go(4)
    QApplication.processEvents()
    assert not page.timer.isActive()


def test_get_page_open_row_and_folder(make_win, dialogs, monkeypatch, downloads):
    win = make_win()
    page = win.pages[3]
    page.refresh()
    opened = []
    monkeypatch.setattr(win, "open_page", lambda mod, queue=None: opened.append((mod.id, queue)))
    page.table.cellDoubleClicked.emit(2, 1)
    assert opened == [(page.mods[2].id, None)]
    page.open_folder()
    assert dialogs.opened == []
    monkeypatch.delenv("LEONIDA_NO_OPEN")
    page.open_folder()
    assert [(k, Path(u.toLocalFile())) for k, u in dialogs.opened] == [("url", downloads)]


def test_get_in_browser_queues_every_page_only_mod(make_win, monkeypatch):
    win = make_win()
    page = win.pages[3]
    page.refresh()
    opened = []
    monkeypatch.setattr(win, "open_page", lambda mod, queue=None: opened.append((mod, queue)))
    page.browse_btn.click()
    expected = [m.id for m in page.mods if not m.download]
    first, queue = opened[0]
    assert [first.id, *(m.id for m in queue)] == expected


def test_get_page_assign_a_file(make_win, dialogs, downloads):
    win = make_win()
    page = win.pages[3]
    page.refresh()
    page.assign()
    assert dialogs.texts("information") == ["Every file in the folder is already recognised."]
    (downloads / "mystery.zip").write_bytes(b"?")
    page.refresh()
    dialogs.items = [("mystery.zip", False)]  # cancelled at the file
    page.assign()
    dialogs.items = [("mystery.zip", True), ("menyoo  (Menyoo)", False)]  # cancelled at the mod
    page.assign()
    assert win.session.config.assignments == {}
    dialogs.items = [lambda items: (items[0], True),
                     lambda items: (next(i for i in items if i.startswith("menyoo ")), True)]
    page.assign()
    assert dialogs.item_prompts[-2] == ("File:", ["mystery.zip"])
    assert dialogs.item_prompts[-1][0] == "mystery.zip is:"
    assert win.session.config.assignments == {"mystery.zip": "menyoo"}
    row = next(r for r, m in enumerate(page.mods) if m.id == "menyoo")
    assert page.table.item(row, page.STATUS).text() == "ready"
    assert page.table.item(row, 4).text() == "mystery.zip · not checked yet"
    assert Session(state=win.session.state).config.assignments == {"mystery.zip": "menyoo"}


def _fake_downloader(monkeypatch, downloads, behaviour):
    """behaviour: mod id -> callable(plan, folder, progress, cancel) returning a Path or raising."""
    calls = {"plan": [], "resolve": [], "download": []}

    def plan_for(mod):
        calls["plan"].append(mod.id)
        url = None if mod.id == "shvdne" else f"https://example.invalid/{mod.id}.zip"
        return DownloadPlan(mod.id, "auto", mod.page, url=url)

    def resolve(plan):
        calls["resolve"].append(plan.mod_id)
        return dataclasses.replace(plan, url=f"https://example.invalid/{plan.mod_id}.zip", size=10)

    def download(plan, folder, progress=None, cancel=None):
        calls["download"].append(plan.mod_id)
        assert Path(folder) == downloads
        return behaviour[plan.mod_id](plan, Path(folder), progress, cancel)

    monkeypatch.setattr("leonida.downloader.plan_for", plan_for)
    monkeypatch.setattr("leonida.downloader.resolve", resolve)
    monkeypatch.setattr("leonida.downloader.download", download)
    return calls


def test_get_page_download_all_automatic(make_win, dialogs, monkeypatch, downloads):
    win = make_win()
    page = win.pages[3]
    page.refresh()
    page.download_auto()  # LEONIDA_NO_NET: nothing happens
    assert page.busy == {} and page.cancel_btn.isHidden()
    monkeypatch.delenv("LEONIDA_NO_NET")

    def shvdne(plan, folder, progress, cancel):
        assert cancel() is False
        for done in (0, 5, 5, 10):  # the repeated 50% is reported once
            progress(done, plan.size)
        p = folder / "ScriptHookVDotNet-Enhanced.zip"
        p.write_bytes(b"shvdn")
        return p

    def hud(plan, folder, progress, cancel):
        progress(3_000_000, None)  # unknown size
        p = folder / "GTA-VI-Inspired-HUD-2.8.2-Enhanced.oiv"
        p.write_bytes(b"oiv")
        return p

    def menyoo(plan, folder, progress, cancel):
        raise DownloadError("HTTP 404 from GitHub")

    def leonidamenu(plan, folder, progress, cancel):  # Leonida's own in-game menu: made locally, the real way
        from leonida.menu import make_zip

        return make_zip(folder)

    calls = _fake_downloader(monkeypatch, downloads, {"shvdne": shvdne, "hud-geckomacabre": hud, "menyoo": menyoo,
                                                      "leonidamenu": leonidamenu})
    statuses = []
    orig = page._dl_progress

    def spy(payload):
        orig(payload)
        mid = payload[0]
        statuses.append((mid, page.busy[mid], page.progress.maximum()))

    page._dl_progress = spy
    page.auto_btn.click()
    assert set(page.busy) == {"shvdne", "hud-geckomacabre", "menyoo", "leonidamenu"}
    assert not page.cancel_btn.isHidden() and not page.progress.isHidden()
    wait_idle(page)
    assert calls["plan"] == ["shvdne", "hud-geckomacabre", "menyoo", "leonidamenu"]
    assert calls["resolve"] == ["shvdne"]  # only the github plan without a URL is resolved
    assert ("shvdne", "downloading 0%", 100) in statuses
    assert ("shvdne", "downloading 50%", 100) in statuses
    assert ("shvdne", "downloading 100%", 100) in statuses
    assert [s for s in statuses if s[1] == "downloading 50%"] == [("shvdne", "downloading 50%", 100)]
    assert ("hud-geckomacabre", "downloading 0 MB", 0) in statuses  # unknown size: busy bar, MB count
    assert page.busy == {} and page.cancel_btn.isHidden() and page.progress.isHidden()
    status = {m.id: page.table.item(r, page.STATUS).text() for r, m in enumerate(page.mods)}
    assert status["shvdne"] == "ready" and status["hud-geckomacabre"] == "ready" and status["menyoo"] == "missing"
    (warning,) = dialogs.texts("warning")
    assert f"- {win.session.manifest.mod('menyoo').name}: HTTP 404 from GitHub" in warning and "Leonida's browser" in warning
    assert page.auto_btn.text() == "Download all automatic (1)"


def test_get_page_download_progress_of_unknown_size(make_win, monkeypatch, downloads):
    monkeypatch.delenv("LEONIDA_NO_NET")
    win = make_win()
    page = win.pages[3]
    page.refresh()

    def hud(plan, folder, progress, cancel):
        progress(1_000_000, None)
        progress(3_000_000, None)
        p = folder / "GTA-VI-Inspired-HUD-2.8.2-Enhanced.oiv"
        p.write_bytes(b"oiv")
        return p

    def ok(name):
        def fn(plan, folder, progress, cancel):
            p = folder / name
            p.write_bytes(b"x")
            return p
        return fn

    _fake_downloader(monkeypatch, downloads, {"shvdne": ok("ScriptHookVDotNet-Enhanced.zip"), "hud-geckomacabre": hud,
                                              "menyoo": ok("Menyoo.zip")})
    statuses = []
    orig = page._dl_progress

    def spy(payload):
        orig(payload)
        statuses.append(page.busy[payload[0]])

    page._dl_progress = spy
    page.download_auto()
    wait_idle(page)
    assert "downloading 3 MB" in statuses


def test_get_page_download_cancel_and_nameless_errors(make_win, dialogs, monkeypatch, downloads):
    monkeypatch.delenv("LEONIDA_NO_NET")
    win = make_win()
    page = win.pages[3]
    page.refresh()

    def shvdne(plan, folder, progress, cancel):
        page.cancel()  # what the Cancel button does, while the worker is busy
        assert cancel() is True
        raise DownloadError()  # no message: the type name is shown

    calls = _fake_downloader(monkeypatch, downloads, {"shvdne": shvdne})
    page.download_auto()
    wait_idle(page)
    assert calls["download"] == ["shvdne"]  # the rest were skipped once cancelled
    (warning,) = dialogs.texts("warning")
    assert f"- {win.session.manifest.mod('shvdne').name}: DownloadError" in warning
    assert warning.count(": cancelled") == 3
    page.cancel_requested = False
    page.cancel_btn.click()
    assert page.cancel_requested is True


def test_get_page_download_worker_failure_is_reported(make_win, dialogs, monkeypatch):
    monkeypatch.delenv("LEONIDA_NO_NET")
    win = make_win()
    page = win.pages[3]
    page.refresh()
    captured = {}

    def fake_start(parent, fn, **kw):
        captured.update(kw)
        kw["on_fail"]("worker crashed")

    monkeypatch.setattr(A, "start_worker", fake_start)
    page.download_auto()
    assert captured["pass_progress"] is True
    assert dialogs.texts("warning") == ["Some downloads did not finish:\n- ?: worker crashed\n\n"
                                        "You can get those in Leonida's browser instead."]
    assert page.busy == {} and page.cancel_btn.isHidden()


# ------------------------------------------------------------------------------------------- Check page
def test_check_page_lists_findings_and_flags_errors(make_win, monkeypatch):
    win = make_win(show=True)
    page = win.pages[4]
    findings = [Finding(ERROR, "x", "Script Hook V is missing", "scripthookv"),
                Finding(WARNING, "y", "Hotkey clash"), Finding(INFO, "z", "FYI")]
    monkeypatch.setattr(win.session, "findings", lambda: findings)
    win.go(4)
    QApplication.processEvents()
    items = [page.list.item(i).text() for i in range(page.list.count())]
    assert items == ["ERROR: Script Hook V is missing", "WARNING: Hotkey clash", "info: FYI"]
    assert page.has_errors is True
    monkeypatch.setattr(win.session, "findings", lambda: [])
    next(b for b in page.findChildren(QPushButton) if b.text() == "Run checks again").click()
    wait_idle(page)                                   # the checks run on a worker thread
    assert [page.list.item(i).text() for i in range(page.list.count())] == ["All checks passed."]
    assert page.has_errors is False


def test_check_page_real_findings(make_win):
    win = make_win(build=BUILD_NO_NVE)
    win.session.config.add = ["nve"]  # NVE is a paid add-on now, not in Core
    page = win.pages[4]
    page.refresh()
    items = [page.list.item(i).text() for i in range(page.list.count())]
    assert any(t.startswith("ERROR:") and "NaturalVision" in t for t in items)
    assert page.has_errors is True


# ----------------------------------------------------------------------------------------- Install page
def _verify(monkeypatch, results):
    monkeypatch.setattr("leonida.verify.verify_session", lambda s: list(results))


def test_install_page_lists_steps_and_needs_a_download(make_win, dialogs):
    win = make_win(show=True)
    page = win.pages[5]
    win.go(5)
    QApplication.processEvents()
    assert page.steps.count() == 15 and page.steps.item(0).text() == "[    ]   1. Script Hook V"
    assert page.next_btn.isEnabled() and page.dry_btn.isEnabled()
    assert page.next_btn.text() == "Get Script Hook V"            # not downloaded: the button says so
    page.next_btn.click()
    assert win.stack.currentIndex() == 3 and dialogs.texts("warning") == []
    page.install_next()                                          # asked directly anyway: it explains
    assert dialogs.texts("warning") == ["Script Hook V is not downloaded yet (see Get mods)."]
    nogame = make_win(game_dir=None).pages[5]
    nogame.refresh()
    assert not nogame.next_btn.isEnabled() and not nogame.dry_btn.isEnabled()


def test_install_next_installs_and_keeps_the_step(make_win, dialogs, monkeypatch, shv_zip, game):
    _verify(monkeypatch, [])
    win = make_win()
    page = win.pages[5]
    page.refresh()
    dialogs.button = "Works - continue"
    page.install_next()
    assert not page.next_btn.isEnabled()  # running
    wait_idle(page)
    assert (game / "ScriptHookV.dll").read_text() == "shv"
    assert dialogs.boxes == ["Script Hook V is installed. Launch story mode, drive for a minute, then come back."]
    text = page.view.toPlainText()
    assert "Step 1 done: Script Hook V (" in text and "undone" not in text
    assert page.steps.item(0).text().startswith("[done]")
    assert win.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert page.next_btn.isEnabled()  # the next mod waits for its download
    page.install_next()
    assert dialogs.texts("warning")[-1].endswith("is not downloaded yet (see Get mods).")


def test_install_next_undo_button_rolls_back(make_win, dialogs, monkeypatch, shv_zip, game):
    _verify(monkeypatch, [])
    win = make_win()
    page = win.pages[5]
    dialogs.button = "Undo this step"
    page.install_next()
    wait_idle(page)
    assert "Step 1 undone." in page.view.toPlainText()
    assert not (game / "ScriptHookV.dll").exists()
    assert page.steps.item(0).text().startswith("[    ]")
    assert not win.session.log.installed_mods()


@pytest.mark.parametrize("answer, undone", [(SB.Yes, True), (SB.No, False)])
def test_install_next_asks_to_undo_when_the_logs_say_it_failed(make_win, dialogs, monkeypatch, shv_zip, game,
                                                               answer, undone):
    _verify(monkeypatch, [
        VerifyResult("failed", "shv-version", "Script Hook V doesn't support this game build", mod="scripthookv",
                     log="ScriptHookV.log", line="FATAL: unknown game version"),
        VerifyResult("failed", "other", "Another mod failed", mod="menyoo"),
        VerifyResult("ok", "loaded", "fine", mod="scripthookv"),
    ])
    win = make_win()
    page = win.pages[5]
    dialogs.button = "Works - continue"
    dialogs.answer = answer
    page.install_next()
    wait_idle(page)
    (q,) = dialogs.texts("question")
    assert q.startswith("The game's logs say Script Hook V did not load:\n- Script Hook V doesn't support")
    assert "    ScriptHookV.log: FATAL: unknown game version" in q and "Another mod" not in q
    assert ("Step 1 undone." in page.view.toPlainText()) is undone
    assert (game / "ScriptHookV.dll").exists() is not undone


class _FakeInstaller:
    def __init__(self, ui, folder=None, fail=None, warnings=()):
        self.ui, self.folder, self.fail, self.warnings = ui, folder, fail, list(warnings)
        self.rolled = []
        self.threads = []

    def install(self, mod, path):
        self.threads.append(threading.get_ident())
        if self.fail:
            raise self.fail
        self.ui.info(f"installing {mod.name} from {Path(path).name}")
        if not self.ui.confirm(f"Replace files for {mod.name}?"):
            raise InstallError("declined")
        if not self.ui.wait_done(f"Set up {mod.name}", ["Open the folder", "Copy the files"], self.folder):
            raise InstallError("Cancelled")
        self.ui.launch(Path(path))
        return types.SimpleNamespace(id=7, actions=[1, 2, 3])

    def rollback(self, step_id):
        self.rolled.append(step_id)
        return self.warnings


def test_install_next_guided_and_run_steps_through_the_worker(make_win, dialogs, monkeypatch, shv_zip, tmp_path):
    _verify(monkeypatch, [])
    win = make_win()
    page = win.pages[5]
    folder = tmp_path / "unpacked"
    folder.mkdir()
    made = []
    monkeypatch.setattr(win.session, "installer",
                        lambda ui, dry_run=False: made.append(_FakeInstaller(ui, folder, warnings=["kept a.ini"]))
                        or made[-1])
    dialogs.button = "Undo this step"
    page.install_next()
    wait_idle(page)
    inst = made[0]
    assert inst.threads and inst.threads[0] != threading.get_ident()
    assert dialogs.texts("question") == ["Replace files for Script Hook V?"]
    assert dialogs.dialogs[-1].windowTitle() == "Manual step: Set up Script Hook V"
    text = page.view.toPlainText()
    assert "installing Script Hook V from ScriptHookV_1.0.zip" in text
    assert "Started ScriptHookV_1.0.zip." in text
    assert "Step 7 done: Script Hook V (3 change(s) logged)." in text
    assert inst.rolled == [7] and "! kept a.ini" in text and "Step 7 undone." in text


def test_install_next_failure_shows_the_error(make_win, dialogs, monkeypatch, shv_zip):
    win = make_win()
    page = win.pages[5]
    monkeypatch.setattr(win.session, "installer",
                        lambda ui, dry_run=False: _FakeInstaller(ui, fail=InstallError("Disk is full")))
    page.install_next()
    wait_idle(page)
    assert dialogs.texts("critical") == ["Disk is full"]
    assert page.next_btn.isEnabled() and not page._running
    assert dialogs.boxes == []


def test_install_next_with_nothing_left_does_nothing(make_win, dialogs, monkeypatch):
    win = make_win()
    page = win.pages[5]
    monkeypatch.setattr(page, "todo", lambda: [])
    page.install_next()
    assert dialogs.calls == [] and idle(page)


def test_dry_run_shows_the_plan_without_touching_the_game(make_win, shv_zip, game):
    win = make_win()
    page = win.pages[5]
    before = sorted(p.name for p in game.rglob("*"))
    page.dry_btn.click()
    assert not page.dry_btn.isEnabled()
    wait_idle(page)
    assert page.view.toPlainText().strip()
    assert sorted(p.name for p in game.rglob("*")) == before
    assert page.dry_btn.isEnabled() and not page._running


def test_dry_run_failure_is_logged(make_win, monkeypatch, shv_zip):
    win = make_win()
    page = win.pages[5]
    monkeypatch.setattr(win.session, "installer",
                        lambda ui, dry_run=False: _FakeInstaller(ui, fail=InstallError("plan broke")))
    page.dry_run()
    wait_idle(page)
    assert page.view.toPlainText().splitlines()[-1] == "! plan broke"
    assert page.dry_btn.isEnabled()


# ------------------------------------------------------------------------------------------ Manage page
def test_manage_state_and_game_log_check(make_win, monkeypatch):
    win = make_win(show=True)
    page = win.pages[6]
    win.go(6)
    QApplication.processEvents()
    assert page.state.text() == "No mods installed by Leonida yet"
    assert page.safe_on_btn.isEnabled() and not page.safe_off_btn.isEnabled()
    assert make_win(game_dir=None).pages[6].state.text() == ""  # not shown yet
    nogame = make_win(game_dir=None).pages[6]
    nogame.refresh()
    assert nogame.state.text() == "No mods installed by Leonida yet"
    _verify(monkeypatch, [
        VerifyResult("failed", "a", "Menyoo did not load", mod="menyoo", log="menyooLog.txt", line="Error 5"),
        VerifyResult("warning", "b", "RE partially active", mod="resourceextensions", log="RE.log", line="partial"),
        VerifyResult("warning", "c", "No line", mod="x"),
        VerifyResult("ok", "d", "Script Hook V loaded", mod="scripthookv", log="ScriptHookV.log", line="ok line"),
        VerifyResult("not-seen", "e", "LemonUI: no log yet", mod="lemonui"),
    ])
    page.check_logs()
    lines = page.view.toPlainText().splitlines()
    assert lines == ["Game logs:", "  [FAILED] Menyoo did not load", "      menyooLog.txt: Error 5",
                     "  [check] RE partially active", "      RE.log: partial", "  [check] No line",
                     "  [ok] Script Hook V loaded", "  [not yet] LemonUI: no log yet"]  # not "[ok]"
    page.view.clear()
    _verify(monkeypatch, [])
    page.check_logs()
    assert page.view.toPlainText() == "Game logs: nothing installed yet, or no game folder."


def test_manage_online_safe_on_off_and_errors(make_win, dialogs, game):
    (game / "ScriptHookV.dll").write_text("shv")
    (game / "dinput8.dll").write_text("loader")
    win = make_win()
    page = win.pages[6]
    page.refresh()
    assert page.state.text() == "No mods installed by Leonida yet · mods in the game"
    page.safe_on()
    wait_idle(page)                                   # game-folder work runs on a worker thread
    text = page.view.toPlainText()
    assert text.startswith("Moved out: ") and "ScriptHookV.dll" in text and "dinput8.dll" in text
    assert not (game / "ScriptHookV.dll").exists()
    assert page.state.text().endswith("mods moved out (online-safe)")
    assert not page.safe_on_btn.isEnabled() and page.safe_off_btn.isEnabled()  # the switch shows which way it is
    page.safe_on()  # already moved out
    wait_idle(page)
    assert dialogs.texts("warning") == ["Mods are already moved out. Use Online-safe OFF (`leonida online-safe off`) to bring them back."]
    page.safe_off()
    wait_idle(page)
    assert "Restored: " in page.view.toPlainText() and (game / "ScriptHookV.dll").read_text() == "shv"
    assert page.state.text().endswith("mods in the game") and page.safe_on_btn.isEnabled()
    page.safe_off()
    wait_idle(page)
    assert dialogs.texts("warning")[-1].startswith("Nothing to restore")


def test_manage_online_safe_with_nothing_to_move(make_win):
    win = make_win()
    page = win.pages[6]
    page.safe_on()
    wait_idle(page)
    assert page.view.toPlainText().splitlines()[-1] == "Moved out: nothing"


def test_manage_undo_last_and_uninstall(make_win, dialogs, shv_zip, game):
    win = make_win()
    page = win.pages[6]
    s = win.session
    page.undo_last()  # nothing installed: it says so
    assert dialogs.texts("information") == ["Nothing to undo: no Leonida step is installed."]
    s.installer(AutoUI()).install(s.manifest.mod("scripthookv"), shv_zip)
    assert (game / "ScriptHookV.dll").exists()
    page.refresh()
    assert page.state.text().startswith("1 of ") and page.state.text().endswith("mods installed · in the game")
    page.undo_last()
    wait_idle(page)
    assert not (game / "ScriptHookV.dll").exists()
    assert page.state.text().startswith("No mods installed by Leonida yet")
    s.installer(AutoUI()).install(s.manifest.mod("scripthookv"), shv_zip)
    dialogs.answer = SB.No
    page.uninstall()
    assert (game / "ScriptHookV.dll").exists()
    dialogs.answer = SB.Yes
    page.uninstall()
    wait_idle(page)
    assert not (game / "ScriptHookV.dll").exists()
    assert page.view.toPlainText().splitlines()[-1] == "Game folder matches the pre-install snapshot."
    assert dialogs.texts("question") == ["Undo every Leonida V step?"] * 2


@pytest.mark.parametrize("residual, expected", [
    (None, "Differences left: no baseline"),
    (types.SimpleNamespace(empty=False, summary=lambda: "1 file changed"), "Differences left: 1 file changed"),
])
def test_manage_uninstall_reports_warnings_and_differences(make_win, monkeypatch, residual, expected):
    win = make_win()
    page = win.pages[6]
    fake = types.SimpleNamespace(uninstall=lambda: (["could not restore x.dll"], residual))
    monkeypatch.setattr(win.session, "installer", lambda ui, dry_run=False: fake)
    page.uninstall()
    wait_idle(page)
    assert page.view.toPlainText().splitlines()[-2:] == ["! could not restore x.dll", expected]


def test_manage_guard_shows_errors(make_win, dialogs, monkeypatch):
    win = make_win(game_dir=None)
    page = win.pages[6]
    page.uninstall()  # no game folder: Session.installer raises RuntimeError
    assert dialogs.texts("warning") == ["Game folder is not set"]

    def busy(*a, **k):
        raise OnlineSafeError("The game is running")

    monkeypatch.setattr(A, "go_online_safe", busy)
    page.safe_on()
    wait_idle(page)
    assert dialogs.texts("warning")[-1] == "The game is running"


def test_manage_undo_last_rollback_warnings(make_win, monkeypatch):
    win = make_win()
    page = win.pages[6]
    monkeypatch.setattr(win.session.log, "last_active", lambda: types.SimpleNamespace(id=3))
    fake = _FakeInstaller(None, warnings=["left over: foo.asi"])
    monkeypatch.setattr(win.session, "installer", lambda ui, dry_run=False: fake)
    page.undo_last()
    wait_idle(page)
    assert fake.rolled == [3] and page.view.toPlainText() == "! left over: foo.asi"


# ---- mod updates
def test_manage_mod_updates_check(make_win, monkeypatch):
    win = make_win()
    page = win.pages[6]
    page.check_mod_updates()  # LEONIDA_NO_NET
    assert page.view.toPlainText() == ""
    monkeypatch.delenv("LEONIDA_NO_NET")
    monkeypatch.setattr("leonida.modpack.fetch_latest", lambda *a, **k: None)
    page.check_mod_updates()
    wait_idle(page)
    assert page.view.toPlainText().splitlines() == [
        "Checking the Leonida modpack for tested mod updates ...", "No modpack has been published yet."]
    assert page.mod_plan is None and page.mod_update_btn.isHidden()

    pack = {"pack": "x"}
    plan = types.SimpleNamespace(summary=lambda: ["[ready] Menyoo -> 2.5"], pending=[types.SimpleNamespace(name="Menyoo")])
    seen = []
    monkeypatch.setattr("leonida.modpack.fetch_latest", lambda *a, **k: pack)
    monkeypatch.setattr("leonida.modupdate.plan_updates", lambda s, p: seen.append((s, p)) or plan)
    page.view.clear()
    page.check_mod_updates()
    wait_idle(page)
    assert seen == [(win.session, pack)]
    assert page.view.toPlainText().splitlines()[-1] == "  [ready] Menyoo -> 2.5"
    assert page.mod_plan is plan and not page.mod_update_btn.isHidden()

    def offline(*a, **k):
        raise DownloadError("GitHub is unreachable")

    monkeypatch.setattr("leonida.modpack.fetch_latest", offline)
    page.check_mod_updates()
    assert page.mod_update_btn.isHidden()
    wait_idle(page)
    assert page.view.toPlainText().splitlines()[-1] == "! GitHub is unreachable"


def test_manage_apply_mod_updates(make_win, dialogs, monkeypatch):
    win = make_win()
    page = win.pages[6]
    runs = []
    monkeypatch.setattr("leonida.modupdate.run_updates",
                        lambda s, plan, ui: runs.append((s, plan, ui)) or ["Menyoo updated to 2.5"])
    page.apply_mod_updates()  # no plan yet
    page.mod_plan = types.SimpleNamespace(pending=[])
    page.apply_mod_updates()  # nothing pending
    assert dialogs.calls == [] and runs == []
    plan = types.SimpleNamespace(pending=[types.SimpleNamespace(name="Menyoo"), types.SimpleNamespace(name="HUD")])
    page.mod_plan = plan
    page.mod_update_btn.show()
    dialogs.answer = SB.No
    page.mod_update_btn.click()
    assert dialogs.texts("question") == ["Update Menyoo, HUD?\nEach update is logged and can be undone."]
    assert runs == []
    dialogs.answer = SB.Yes
    page.apply_mod_updates()
    assert not page.mod_update_btn.isEnabled()
    wait_idle(page)
    (s, p, ui), = runs
    assert s is win.session and p is plan and isinstance(ui, A.GuiUI)
    assert page.view.toPlainText().splitlines()[-1] == "  Menyoo updated to 2.5"
    assert page.mod_update_btn.isEnabled() and page.mod_update_btn.isHidden()

    def broken(s, plan, ui):
        raise RuntimeError("hash mismatch, nothing changed")

    monkeypatch.setattr("leonida.modupdate.run_updates", broken)
    page.mod_update_btn.show()
    page.apply_mod_updates()
    wait_idle(page)
    assert page.view.toPlainText().splitlines()[-1] == "! hash mismatch, nothing changed"
    assert page.mod_update_btn.isEnabled() and not page.mod_update_btn.isHidden()


# ---- Leonida self-update
def _info(latest="9.9.9", newer=True):
    from leonida.updater import UpdateInfo

    return UpdateInfo(current=__version__, latest=latest, newer=newer, notes="notes",
                      page="https://github.com/JacobJandon/leonida-v/releases/latest", zip_url=None, exe_url=None)


def test_manage_check_updates_offline_and_without_updater(make_win, monkeypatch):
    win = make_win()
    page = win.pages[6]
    page.check_updates()
    assert page.update_label.text() == f"You have {PACK_NAME} {__version__}." and page.check_btn.isEnabled()
    monkeypatch.delenv("LEONIDA_NO_NET")
    monkeypatch.delattr(leonida, "updater", raising=False)
    monkeypatch.setitem(sys.modules, "leonida.updater", None)
    page.check_updates()
    assert page.update_label.text() == f"You have {PACK_NAME} {__version__}." and idle(page)


def test_manage_check_updates_newer_current_none_and_failure(make_win, monkeypatch):
    monkeypatch.delenv("LEONIDA_NO_NET")
    win = make_win()
    page = win.pages[6]
    result = {"info": _info()}

    def check(*a, **k):
        if isinstance(result["info"], Exception):
            raise result["info"]
        return result["info"]

    monkeypatch.setattr("leonida.updater.check", check)
    page.check_btn.click()
    assert not page.check_btn.isEnabled() and page.update_label.text().startswith("Checking GitHub")
    wait_idle(page)
    assert page.check_btn.isEnabled() and not page.update_btn.isHidden()
    assert f"<b>{PACK_NAME} 9.9.9</b> is available (you have {__version__})" in page.update_label.text()
    assert "releases/latest" in page.update_label.text()
    assert page.update_label.textFormat() == Qt.TextFormat.RichText
    assert win.statusBar().currentMessage() == f"{PACK_NAME} 9.9.9 is available: see Manage."

    result["info"] = _info(latest=__version__, newer=False)
    page.check_updates()
    wait_idle(page)
    assert page.update_label.text() == f"You have {PACK_NAME} {__version__}; the latest release is {__version__}."
    assert page.update_btn.isHidden()

    result["info"] = _info(latest=None, newer=False)
    page.check_updates()
    wait_idle(page)
    assert page.update_label.text() == f"You have {PACK_NAME} {__version__}. No release has been published yet."

    result["info"] = DownloadError("rate limited")
    page.check_updates()
    wait_idle(page)
    assert page.update_label.text() == f"You have {PACK_NAME} {__version__}. Could not check for updates: rate limited"
    page.check_updates(quiet=True)
    wait_idle(page)
    assert page.update_label.text() == f"You have {PACK_NAME} {__version__}."
    assert page.check_btn.isEnabled()


def _fake_apply(monkeypatch, kind="git", fail=None):
    calls = []

    def apply(info, project, state, **kw):
        calls.append((info, project, state, kw))
        if fail:
            raise fail
        return f"Updated to {info.latest}. Restart Leonida V."

    monkeypatch.setattr("leonida.updater.apply", apply)
    monkeypatch.setattr("leonida.updater.install_kind", lambda project: kind)
    return calls


def test_manage_apply_update(make_win, dialogs, monkeypatch):
    win = make_win()
    page = win.pages[6]
    calls = _fake_apply(monkeypatch)
    page.apply_update()  # no info
    page.update_info = _info(newer=False)
    page.apply_update()  # not newer
    assert dialogs.calls == []
    page.update_info = _info()
    dialogs.answer = SB.No
    page.update_btn.click()
    assert calls == [] and dialogs.texts("question")[0].startswith(f"Download and install {PACK_NAME} 9.9.9?")
    dialogs.answer = SB.Yes
    page.apply_update()
    assert page.update_label.text() == "Updating ..." and not page.check_btn.isEnabled()
    wait_idle(page)
    (info, project, state, kw), = calls
    assert info.latest == "9.9.9" and kw == {} and state == win.session.state
    assert project == Path(A.__file__).resolve().parents[2]
    assert page.update_label.text() == "Updated to 9.9.9. Restart Leonida V."
    assert dialogs.texts("information") == ["Updated to 9.9.9. Restart Leonida V."]
    assert page.check_btn.isEnabled()


def test_manage_apply_update_frozen_exe_closes_the_window(make_win, dialogs, monkeypatch):
    win = make_win()
    page = win.pages[6]
    calls = _fake_apply(monkeypatch, kind="exe")
    closed = []
    monkeypatch.setattr(win, "close", lambda: closed.append(True))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    page.update_info = _info()
    page.apply_update()
    wait_idle(page)
    assert calls[0][1] == Path(sys.executable).parent
    assert closed == [True]


def test_manage_apply_update_failure(make_win, dialogs, monkeypatch):
    win = make_win()
    page = win.pages[6]
    _fake_apply(monkeypatch, fail=DownloadError("checksum mismatch"))
    page.update_info = _info()
    page.update_btn.show()
    page.apply_update()
    wait_idle(page)
    assert page.update_label.text() == "Update failed: checksum mismatch"
    assert page.update_btn.isEnabled() and page.check_btn.isEnabled()
    assert dialogs.texts("information") == []


def test_manage_force_update(make_win, dialogs, monkeypatch):
    win = make_win()
    page = win.pages[6]
    calls = _fake_apply(monkeypatch)
    result = {"info": _info(latest=__version__, newer=False)}

    def check(*a, **k):
        if isinstance(result["info"], Exception):
            raise result["info"]
        return result["info"]

    monkeypatch.setattr("leonida.updater.check", check)
    page.force_update()  # LEONIDA_NO_NET
    assert dialogs.calls == []
    monkeypatch.delenv("LEONIDA_NO_NET")
    dialogs.answer = SB.No
    page.force_btn.click()
    assert len(dialogs.texts("question")) == 1 and idle(page)
    dialogs.answer = SB.Yes
    page.force_update()
    assert not page.force_btn.isEnabled() and page.update_label.text() == "Looking up the latest release ..."
    wait_idle(page)
    (info, project, state, kw), = calls
    assert kw == {"force": True} and info.latest == __version__
    assert page.force_btn.isEnabled()
    assert page.update_label.text() == f"Updated to {__version__}. Restart Leonida V."

    result["info"] = _info(latest=None, newer=False)
    page.force_update()
    wait_idle(page)
    assert page.update_label.text() == "No Leonida V release has been published on GitHub yet." and len(calls) == 1

    result["info"] = DownloadError("offline")
    page.force_update()
    wait_idle(page)
    assert page.update_label.text() == "Could not reach GitHub: offline" and page.force_btn.isEnabled()


# ----------------------------------------------------------------------------------- MainWindow plumbing
def test_daily_update_check_runs_at_most_once_a_day(make_win, monkeypatch):
    win = make_win()
    calls = []
    monkeypatch.setattr(win.pages[-1], "check_updates", lambda quiet=False: calls.append(quiet))
    stamp = win.session.state / "last-update-check.txt"
    win._daily_update_check()  # LEONIDA_NO_UPDATE_CHECK
    monkeypatch.delenv("LEONIDA_NO_UPDATE_CHECK")
    win._daily_update_check()  # LEONIDA_NO_NET
    assert calls == [] and not stamp.exists()
    monkeypatch.delenv("LEONIDA_NO_NET")
    win._daily_update_check()
    assert calls == [True] and stamp.is_file()
    win._daily_update_check()  # checked less than a day ago
    assert calls == [True]
    old = time.time() - 2 * 24 * 3600
    os.utime(stamp, (old, old))
    win._daily_update_check()
    assert calls == [True, True]


def test_daily_update_check_skips_when_the_stamp_cannot_be_written(make_win, monkeypatch):
    monkeypatch.delenv("LEONIDA_NO_UPDATE_CHECK")
    monkeypatch.delenv("LEONIDA_NO_NET")
    win = make_win()
    calls = []
    monkeypatch.setattr(win.pages[-1], "check_updates", lambda quiet=False: calls.append(quiet))
    stamp = win.session.state / "last-update-check.txt"
    stamp.mkdir(parents=True)  # a folder where the stamp file should be
    old = time.time() - 2 * 24 * 3600
    os.utime(stamp, (old, old))
    win._daily_update_check()
    assert calls == []


class _FakeBrowser(QObject):
    file_saved = Signal(str)
    made: list = []

    def __init__(self, state_dir, download_dir, parent=None):
        super().__init__()
        self.args = (Path(state_dir), Path(download_dir), parent)
        self.download_dir = Path(download_dir)
        self.status = QLabel()
        self.queue = []
        self.opened = []
        self.nexts = 0
        _FakeBrowser.made.append(self)

    def set_queue(self, mods):
        self.queue = list(mods)

    def open_mod(self, mod):
        self.opened.append(mod.id)

    def next_mod(self):
        self.nexts += 1
        if self.queue:
            self.opened.append(self.queue.pop(0).id)


@pytest.fixture
def fake_browser(monkeypatch):
    _FakeBrowser.made = []
    monkeypatch.setitem(sys.modules, "leonida.gui.browser",
                        types.SimpleNamespace(BrowserWindow=_FakeBrowser))
    monkeypatch.delenv("LEONIDA_NO_OPEN")
    return _FakeBrowser


def test_open_page_is_off_with_no_open(make_win, monkeypatch):
    monkeypatch.setitem(sys.modules, "leonida.gui.browser", None)  # would fail if it got that far
    win = make_win()
    win.open_page(win.session.manifest.mod("menyoo"))
    assert win.browser is None


def test_open_page_uses_the_built_in_browser_and_reuses_it(make_win, fake_browser, dialogs, downloads):
    win = make_win()
    m = win.session.manifest
    win.open_page(m.mod("mapfixes"), queue=[m.mod("bugstarfixes"), m.mod("hud-fbicat"), m.mod("drivevnve")])
    (b,) = fake_browser.made
    assert b.args == (win.session.state, downloads, win)
    assert b.opened == ["mapfixes"]
    assert [x.id for x in b.queue] == ["bugstarfixes", "drivevnve"]  # Discord invites are not queued
    win.open_page(m.mod("drivevnve"))
    assert len(fake_browser.made) == 1 and b.opened == ["mapfixes", "drivevnve"] and b.queue == []
    assert dialogs.opened == []


def test_open_page_discord_mod_goes_to_the_system_browser(make_win, fake_browser, dialogs):
    win = make_win()
    m = win.session.manifest
    fbicat = m.mod("hud-fbicat")
    win.open_page(fbicat)
    assert dialogs.opened == [("open_new_tab", fbicat.page)]
    assert fake_browser.made == [] and win.browser is None
    win.open_page(fbicat, queue=[m.mod("mapfixes"), m.mod("bugstarfixes")])
    (b,) = fake_browser.made
    assert b.nexts == 1 and b.opened == ["mapfixes"] and [x.id for x in b.queue] == ["bugstarfixes"]


def test_open_page_falls_back_without_qtwebengine(make_win, monkeypatch, dialogs):
    monkeypatch.delenv("LEONIDA_NO_OPEN")
    monkeypatch.setitem(sys.modules, "leonida.gui.browser", None)
    win = make_win()
    m = win.session.manifest
    win.open_page(m.mod("mapfixes"), queue=[m.mod("bugstarfixes")])
    assert dialogs.opened == [("open_new_tab", m.mod("mapfixes").page), ("open_new_tab", m.mod("bugstarfixes").page)]
    assert win.statusBar().currentMessage().startswith("Built-in browser unavailable (")
    assert win.browser is None


def test_get_in_browser_opens_leonidas_browser(make_win, fake_browser):
    win = make_win()
    page = win.pages[3]
    page.refresh()
    page.get_in_browser()
    (b,) = fake_browser.made
    rest = [m.id for m in page.mods if not m.download]
    assert b.opened == [rest[0]] and [x.id for x in b.queue] == rest[1:]


def test_file_saved_reports_recognised_and_unknown_files(make_win, fake_browser, downloads):
    win = make_win()
    win._file_saved(str(downloads / "nothing.zip"))  # no browser yet: status bar only
    assert win.statusBar().currentMessage().startswith("Saved nothing.zip, but it isn't recognised yet.")
    win.open_page(win.session.manifest.mod("mapfixes"))
    b = fake_browser.made[0]
    p = make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "x"})
    b.file_saved.emit(str(p))
    assert b.status.text() == "Saved ScriptHookV_1.0.zip: recognised as Script Hook V."
    assert win.statusBar().currentMessage() == b.status.text()
    assert win.pages[3].table.item(0, win.pages[3].STATUS).text() == "ready"
    (downloads / "random.bin").write_bytes(b"?")
    b.file_saved.emit(str(downloads / "random.bin"))
    assert b.status.text() == "Saved random.bin, but it isn't recognised yet. Use 'Assign a file...' on Get mods."


# ------------------------------------------------------------------------------------------------ images
def test_network_allowed_follows_the_env(monkeypatch):
    assert network_allowed() is False
    monkeypatch.delenv("LEONIDA_NO_NET")
    assert network_allowed() is True


def test_image_loader_offline_does_nothing(qapp, tmp_path):
    loader = ImageLoader(tmp_path / "cache")
    got = []
    loader.loaded.connect(lambda k, p: got.append((k, p)))
    loader.request("m", "https://img.example/a.png", "https://page")
    QApplication.processEvents()
    assert got == [] and loader.pending == set() and not (tmp_path / "cache").exists()


def test_image_loader_fetches_caches_and_indexes(qapp, monkeypatch, tmp_path):
    monkeypatch.delenv("LEONIDA_NO_NET")
    src = make_png(tmp_path / "src.png")
    cache = tmp_path / "cache"
    calls = []

    def page_image(url, *a, **k):
        calls.append(("page", url))
        return "https://img.example/found.png"

    def fetch_image(url, cache_dir, *a, **k):
        calls.append(("fetch", url))
        assert Path(cache_dir) == cache
        return src

    monkeypatch.setattr("leonida.downloader.page_image", page_image)
    monkeypatch.setattr("leonida.downloader.fetch_image", fetch_image)
    loader = ImageLoader(cache)
    got = []
    loader.loaded.connect(lambda k, p: got.append((k, p)))
    loader.request("a", None, "https://author.example/page")
    loader.request("a", None, "https://author.example/page")  # already pending: ignored
    wait_until(lambda: got)
    assert got == [("a", str(src))]
    assert calls == [("page", "https://author.example/page"), ("fetch", "https://img.example/found.png")]
    import json

    assert json.loads((cache / INDEX).read_text(encoding="utf-8")) == {
        "https://author.example/page": "https://img.example/found.png"}
    loader.request("a", None, "https://author.example/page")  # cached: answered at once
    assert got[-1] == ("a", str(src)) and len(got) == 2
    # direct image URL: the page isn't read
    loader.request("b", "https://img.example/direct.png", None)
    wait_until(lambda: len(got) == 3)
    assert calls[-1] == ("fetch", "https://img.example/direct.png") and got[-1] == ("b", str(src))
    # a new loader reuses the index instead of reading the page again
    calls.clear()
    again = ImageLoader(cache)
    got2 = []
    again.loaded.connect(lambda k, p: got2.append((k, p)))
    again.request("c", None, "https://author.example/page")
    wait_until(lambda: got2)
    assert calls == [("fetch", "https://img.example/found.png")]


def test_image_loader_failures_give_an_empty_path(qapp, monkeypatch, tmp_path):
    monkeypatch.delenv("LEONIDA_NO_NET")

    def page_image(url, *a, **k):
        raise OSError("blocked")

    monkeypatch.setattr("leonida.downloader.page_image", page_image)
    cache = tmp_path / "cache"
    loader = ImageLoader(cache)
    got = []
    loader.loaded.connect(lambda k, p: got.append((k, p)))
    loader.request("x", None, "https://author.example/x")
    loader.request("y", None, None)  # nothing to look at
    wait_until(lambda: len(got) == 2)
    assert sorted(got) == [("x", ""), ("y", "")]
    assert loader.paths == {} and loader.pending == set()
    assert not (cache / INDEX).exists()  # failures aren't cached


def test_image_loader_bad_index_and_unwritable_index(qapp, monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / INDEX).write_text("{not json", encoding="utf-8")
    assert ImageLoader(cache).index == {}
    (cache / INDEX).unlink()
    (cache / INDEX).mkdir()  # can't be written: the picture still loads
    monkeypatch.delenv("LEONIDA_NO_NET")
    src = make_png(tmp_path / "s.png")
    monkeypatch.setattr("leonida.downloader.page_image", lambda url, *a, **k: "https://img.example/i.png")
    monkeypatch.setattr("leonida.downloader.fetch_image", lambda url, d, *a, **k: src)
    loader = ImageLoader(cache)
    got = []
    loader.loaded.connect(lambda k, p: got.append((k, p)))
    loader.request("k", None, "https://author.example/k")
    wait_until(lambda: got)
    assert got == [("k", str(src))] and loader.index == {"https://author.example/k": "https://img.example/i.png"}


# ----------------------------------------------------------------------------------------------- workers
def test_start_worker_success_failure_and_no_callbacks(qapp):
    holder = QObject()
    seen = {}
    start_worker(holder, lambda: 41 + 1, on_done=lambda r: seen.setdefault("done", r),
                 on_fail=lambda m: seen.setdefault("unexpected", m))
    start_worker(holder, lambda: 1 / 0, on_fail=lambda m: seen.setdefault("fail", m))

    def nameless():
        raise KeyError()

    start_worker(holder, nameless, on_fail=lambda m: seen.setdefault("nameless", m))
    assert len(holder._leonida_workers) == 3  # all kept alive on the same parent
    start_worker(holder, lambda: None)  # no callbacks at all
    start_worker(holder, lambda: 1 / 0)
    start_worker(holder, lambda emit: emit("tick"), pass_progress=True)
    wait_idle(holder)
    assert seen == {"done": 42, "fail": "division by zero", "nameless": "KeyError"}


def test_start_worker_progress_and_cancel_flag(qapp):
    holder = QObject()
    cancel = threading.Event()
    seen = {"progress": []}

    def work(emit):
        for i in range(1000):
            if cancel.is_set():
                return ("cancelled", i)
            emit(i)
            if i == 3:
                cancel.set()  # the UI's cancel button would set this
        return ("finished", 1000)

    start_worker(holder, work, pass_progress=True, on_progress=seen["progress"].append,
                 on_done=lambda r: seen.setdefault("done", r))
    wait_idle(holder)
    assert seen["done"] == ("cancelled", 4) and seen["progress"] == [0, 1, 2, 3]


def test_main_thread_caller_runs_on_the_ui_thread_and_reraises(qapp):
    holder = QObject()
    caller = MainThreadCaller(holder)
    assert caller.parent() is holder
    main = threading.get_ident()
    assert caller.call(threading.get_ident) == main  # on the UI thread: called directly
    seen = {}

    def work():
        seen["ui"] = caller.call(threading.get_ident)
        seen["none"] = caller.call(lambda: None)
        try:
            caller.call(lambda: {}["missing"])
        except KeyError as exc:
            seen["error"] = repr(exc)
        caller.call(lambda: (_ for _ in ()).throw(ValueError("dialog broke")))

    start_worker(holder, work, on_fail=lambda m: seen.setdefault("fail", m))
    wait_idle(holder)
    assert seen == {"ui": main, "none": None, "error": "KeyError('missing')", "fail": "dialog broke"}
