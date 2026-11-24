"""Offscreen smoke test of the wizard (skipped when PySide6 isn't installed)."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import make_zip  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from leonida.gui.app import PAGES, MainWindow  # noqa: E402
from leonida.session import Session  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_wizard_walks_every_page(app, tmp_path, game, downloads, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1158.13")
    make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "s", "bin/dinput8.dll": "d"})
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
    assert get_page.table.item(0, 2).text() == "ready"
    assert get_page.table.item(1, 2).text() == "missing"
    check_page = win.pages[4]
    check_page.refresh()
    assert check_page.list.count() > 0
    win.close()


def test_hud_choice_sets_swap(app, tmp_path, game, downloads):
    s = Session(state=tmp_path / "gui-state2", download_dir=str(downloads), game_dir=str(game))
    win = MainWindow(s)
    page = win.pages[2]
    page.hud.setCurrentIndex(1)
    assert s.config.swaps == {"hud": "hud-fbicat"}
    page.hud.setCurrentIndex(0)
    assert s.config.swaps == {}
    win.close()
