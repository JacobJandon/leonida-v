"""Offscreen smoke test of the wizard (skipped when PySide6 isn't installed)."""

import os
import threading

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LEONIDA_NO_NET", "1")  # no preview-image fetching in tests

from conftest import make_zip  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QCheckBox  # noqa: E402

from leonida.gui.app import PAGES, MainWindow  # noqa: E402
from leonida.gui.chooser import ChoosePage, how_text  # noqa: E402
from leonida.gui.workers import MainThreadCaller, start_worker  # noqa: E402
from leonida.session import Session  # noqa: E402


@pytest.fixture(scope="module")
def app(qt_app):
    return qt_app


def _wait(app, cond, timeout=10.0):
    import time

    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def test_wizard_walks_every_page(app, tmp_path, game, downloads, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1158.13")
    make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "s", "bin/xinput1_4.dll": "x"})
    s = Session(state=tmp_path / "gui-state", download_dir=str(downloads), game_dir=str(game))
    win = MainWindow(s)
    win.show()
    for i in range(len(PAGES)):
        win.go(i)
        app.processEvents()
        assert win.stack.currentIndex() == i
    get_page = win.pages[3]
    get_page.refresh()
    assert get_page.table.rowCount() == 14
    assert get_page.table.item(0, get_page.STATUS).text() == "ready"
    assert get_page.table.item(1, get_page.STATUS).text() == "missing"
    check_page = win.pages[4]
    check_page.refresh()
    assert check_page.list.count() > 0
    win.close()


def test_chooser_has_a_card_per_mod_and_hud_choice_sets_swap(app, tmp_path, game, downloads):
    s = Session(state=tmp_path / "gui-state2", download_dir=str(downloads), game_dir=str(game))
    win = MainWindow(s)
    page = win.pages[2]
    assert isinstance(page, ChoosePage)
    assert set(page.cards) == set(s.manifest.mods)
    page.cards["hud-fbicat"].control.setChecked(True)
    assert s.config.swaps == {"hud-geckomacabre": "hud-fbicat"}
    assert "hud-fbicat" in {m.id for m in s.mods()}
    page.cards["hud-geckomacabre"].control.setChecked(True)
    assert s.config.swaps == {}
    win.close()


def test_chooser_include_toggles_add_and_remove(app, tmp_path, game, downloads):
    s = Session(state=tmp_path / "gui-state3", download_dir=str(downloads), game_dir=str(game))
    win = MainWindow(s)
    page = win.pages[2]
    extra = page.cards["immersivecombat"].control
    assert isinstance(extra, QCheckBox) and not extra.isChecked()
    extra.setChecked(True)
    assert s.config.add == ["immersivecombat"]
    extra.setChecked(False)
    assert s.config.add == []
    page.cards["menyoo"].control.setChecked(False)
    assert s.config.remove == ["menyoo"]
    assert "menyoo" not in {m.id for m in s.mods()}
    assert not page.cards["scripthookv"].control.isEnabled()  # framework mods are required
    win.close()


def test_how_text_describes_the_download_route(manifest):
    assert how_text(manifest.mod("lwe")).startswith("manual")
    assert how_text(manifest.mod("menyoo")).startswith(("in-app", "automatic"))


def test_worker_runs_off_the_ui_thread_and_caller_marshals_back(app):
    main = threading.get_ident()
    seen = {}
    caller = MainThreadCaller()

    def work(emit):
        seen["worker"] = threading.get_ident()
        emit(5)
        seen["ui"] = caller.call(threading.get_ident)
        return 42

    holder = QCoreApplication.instance()
    start_worker(holder, work, pass_progress=True,
                 on_progress=lambda p: seen.setdefault("progress", (p, threading.get_ident())),
                 on_done=lambda r: seen.setdefault("done", (r, threading.get_ident())))
    _wait(app, lambda: "done" in seen)
    assert seen["worker"] != main
    assert seen["ui"] == main
    assert seen["progress"] == (5, main)
    assert seen["done"] == (42, main)


def test_manage_page_log_check_and_update_buttons(app, tmp_path, game, downloads):
    s = Session(state=tmp_path / "gui-state5", download_dir=str(downloads), game_dir=str(game))
    win = MainWindow(s)
    manage = win.pages[-1]
    manage.check_logs()  # nothing installed: says so, never raises
    assert "Game logs" in manage.view.toPlainText()
    assert manage.mod_update_btn.isHidden()
    manage.check_mod_updates()  # LEONIDA_NO_NET: does nothing
    win.close()
