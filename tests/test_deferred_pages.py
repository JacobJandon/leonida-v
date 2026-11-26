"""MainWindow(defer=True), as LeonidaV.exe starts: the frame and the start page now, every other page when it's first
needed or one per idle moment after the first paint. Timers and caches only peek: they never build a page."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402
from test_gui_pages import dialogs, qapp, wait_idle, wait_until  # noqa: E402,F401  (fixtures)

import leonida.gui.app as A  # noqa: E402
from leonida.session import Session  # noqa: E402


def _session(tmp_path, game, downloads, pack: bool) -> Session:
    s = Session(state=tmp_path / "st", download_dir=str(downloads), game_dir=str(game), game_build="1.0.1013.20")
    if pack:
        s.choose_pack(s.base_manifest.default_pack)
    return s


def _built(win) -> set:
    out = {i for i in range(len(win.pages)) if win.pages.peek(i) is not None}
    return out | {k for k in win.LIBRARY if win.peek_page(k) is not None}


def test_only_the_start_page_is_built_then_the_rest_after_the_first_paint(qapp, tmp_path, game, downloads):  # noqa: F811
    win = A.MainWindow(_session(tmp_path, game, downloads, pack=True), defer=True)
    try:
        assert _built(win) == {"pack_page"}                       # a returning user: My modpack, nothing else
        assert win.stack.currentWidget() is win.pack_page
        win.bottom.refresh_work()                                  # the bottom bar's timer only peeks
        assert _built(win) == {"pack_page"}
        win.go(3)                                                  # a page is built the first time it's opened
        assert isinstance(win.pages[3], A.GetPage) and win.stack.currentWidget() is win.pages[3]
        assert 3 in _built(win) and 2 not in _built(win)
        win.show_home("about")
        assert win.peek_page("about_page") is not None and win.peek_page("settings_page") is None
        win.resize(1200, 800)
        win.show()
        wait_until(lambda: len(_built(win)) == len(win.pages) + len(win.LIBRARY))   # idle time after the paint
        assert all(type(p).__name__ != "_Placeholder" for p in win.pages)
        assert win.stack.count() == len(win.pages) + len(win.LIBRARY)
    finally:
        QApplication.processEvents()
        wait_idle(win, *win.pages)
        win.close()
        win.deleteLater()


def test_a_first_start_builds_welcome(qapp, tmp_path, game, downloads):  # noqa: F811
    win = A.MainWindow(_session(tmp_path, game, downloads, pack=False), defer=True)
    try:
        assert _built(win) == {0} and win.stack.currentWidget() is win.pages[0]
        assert [type(p).__name__ for p in win.pages][:2] == ["WelcomePage", "GamePage"]   # iterating builds them
    finally:
        wait_idle(win, *win.pages)
        win.close()
        win.deleteLater()
