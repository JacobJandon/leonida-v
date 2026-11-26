"""Settings > Storage (sizes per kind, Clean up now / more, the extra yes for paid files) and the clean-up at each
start, on fake folders with a fake Recycle Bin."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from conftest import make_zip  # noqa: E402
from test_gui_pages import SB, dialogs, make_win, qapp, wait_idle, wait_until  # noqa: E402,F401  (fixtures)

from leonida import cleanup as C  # noqa: E402


@pytest.fixture
def bin_(tmp_path, monkeypatch):
    folder = tmp_path / "bin"
    monkeypatch.setattr(C, "recycle", C.move_to(folder))
    return folder


@pytest.fixture
def win(make_win):  # noqa: F811
    w = make_win()
    yield w
    page = w.peek_page("settings_page")
    if page is not None:
        wait_idle(page)                 # its scan runs on a thread the page owns: done before the window goes


def _files(downloads):
    shv = make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "shv"})
    dup = downloads / "ScriptHookV_1.0 (1).zip"
    dup.write_bytes(shv.read_bytes())
    nve = make_zip(downloads / "NaturalVision Enhanced 1.0.zip", {"Main Package/x.dll": "x"})   # paid, not in pack
    return shv, dup, nve


def _storage(win):
    page = win.settings_page
    page.scan_storage(force=True)
    wait_until(lambda: page._storage is not None and not page._storage_busy)
    return page


def test_storage_shows_the_kinds_and_cleans_the_safe_ones(dialogs, win, downloads, bin_):  # noqa: F811
    shv, dup, nve = _files(downloads)
    page = _storage(win)
    assert "Duplicate downloads: 1" in page.storage_auto.text()
    assert "Downloads of mods not in your pack" in page.storage_ask.text() and "paid" in page.storage_ask.text()
    assert page.clean_btn.isEnabled() and page.clean_more_btn.isEnabled()
    assert page.clean_now() is True
    wait_until(lambda: not (shv.exists() and dup.exists()))
    wait_until(lambda: not page._storage_busy and "Nothing safe" in page.storage_auto.text())
    assert shv.exists() != dup.exists() and nve.exists()                  # one copy stays; the paid file stays
    assert "Cleaned up: 1 item(s)" in win.notifications.items[0].text


def test_clean_more_asks_and_asks_again_for_paid_files(dialogs, win, downloads, bin_,  # noqa: F811
                                                       monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shv, dup, nve = _files(downloads)
    page = _storage(win)
    dialogs.answer = SB.No
    assert page.clean_more() is False and nve.exists()                    # no to the first question: nothing
    asked = [t for k, t in dialogs.calls if k == "question"]
    assert "Move these to the Recycle Bin" in asked[-1] and "Downloads of mods not in your pack" in asked[-1]
    answers = iter([SB.Yes, SB.No])                                       # yes, but not the paid files

    def ask(parent, title, text, *a, **k):
        dialogs.calls.append(("question", text))
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", staticmethod(ask))
    assert page.clean_more() is True
    wait_until(lambda: win.notifications.items and "Cleaned up" in win.notifications.items[0].text)
    assert "paid mods' files you bought" in dialogs.calls[-1][1] and nve.name in dialogs.calls[-1][1]
    assert nve.exists() and "1 stayed" in win.notifications.items[0].text
    answers = iter([SB.Yes, SB.Yes])                                      # and now yes to the paid file too
    wait_until(lambda: not page._storage_busy)
    assert page.clean_more() is True
    wait_until(lambda: not nve.exists())
    wait_idle(win.settings_page)


def test_clean_waits_while_an_install_runs(dialogs, win, downloads, bin_):  # noqa: F811
    shv, dup, nve = _files(downloads)
    page = _storage(win)
    win.pages[5]._running = True
    try:
        assert page.clean_now() is False and shv.exists() and dup.exists()
        assert any("Not now" in t for k, t in dialogs.calls if k == "information")
    finally:
        win.pages[5]._running = False


def test_the_auto_clean_toggle_is_saved(dialogs, win):  # noqa: F811

    page = win.settings_page
    page.refresh()
    assert page.auto_clean.isChecked()
    page.auto_clean.setChecked(False)
    assert win.session.config.auto_cleanup is False
    from leonida.paths import Config

    assert Config.load(win.session.state).auto_cleanup is False


def test_the_clean_up_at_each_start(dialogs, win, downloads, bin_, monkeypatch):  # noqa: F811
    shv, dup, nve = _files(downloads)
    assert win.auto_clean() is False                   # the tests' LEONIDA_NO_CLEANUP
    monkeypatch.delenv("LEONIDA_NO_CLEANUP")
    win.session.config.auto_cleanup = False
    assert win.auto_clean() is False                   # switched off in Settings
    win.session.config.auto_cleanup = True
    assert win.auto_clean() is True
    wait_until(lambda: not (shv.exists() and dup.exists()))
    assert nve.exists()                                # only the safe kinds
    assert "duplicates" in (win.session.state / "logs" / C.LOG_NAME).read_text(encoding="utf-8")
    assert "auto_clean" in [getattr(t, "__name__", "") for t in win._warm_tasks()]
