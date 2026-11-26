"""The window starts the in-game menu's bridge (leonida/gui/menuhook.py) and it writes the menu's data into the
window's own State. The installed 1.0.1 once ran on another State, so the menu said "Open Leonida" while it was
open; build/selftest.py checks the same in the frozen app."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from test_gui_pages import dialogs, make_win, qapp, wait_until  # noqa: E402,F401  (fixtures)

from leonida import menubridge as B  # noqa: E402
from leonida.gui import menuhook  # noqa: E402


def test_window_starts_the_bridge_and_it_writes_into_the_windows_state(make_win, monkeypatch):  # noqa: F811
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))   # as on the user's PC
    monkeypatch.delenv("LEONIDA_NO_MENU_BRIDGE", raising=False)
    monkeypatch.setattr(B, "game_running", lambda: True)
    win = make_win()
    s = win.session
    step = s.log.new_step(B.MENU_ID, "copy")                   # the menu is installed
    step.status, step.finished = "done", step.started
    s.log.save()
    win._startup_notes()
    hook = win.menu_hook
    assert isinstance(hook, menuhook.MenuHook) and hook.timer.isActive()
    try:
        hook.tick()
        model = B.bridge_dir(s.state) / B.MODEL
        wait_until(model.is_file, 10000)
        data = json.loads(model.read_text(encoding="utf-8"))
        assert data["heartbeat"] > 0 and data["leonida"]
        win._startup_notes()                                    # never a second hook
        assert win.menu_hook is hook
    finally:
        hook.timer.stop()


def test_a_failing_start_up_note_never_stops_the_bridge(make_win, monkeypatch):  # noqa: F811
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.delenv("LEONIDA_NO_MENU_BRIDGE", raising=False)
    win = make_win()

    def boom():
        raise RuntimeError("drift check broke")

    monkeypatch.setattr(win.session, "settings_drift", boom)
    import leonida.gui.extras as X

    monkeypatch.setattr(X, "maybe_whats_new", lambda w: (_ for _ in ()).throw(RuntimeError("what's new broke")))
    with pytest.raises(RuntimeError, match="what's new broke"):
        win._startup_notes()
    assert isinstance(win.menu_hook, menuhook.MenuHook)
    win.menu_hook.timer.stop()


def test_offscreen_and_opt_out_have_no_bridge(make_win, monkeypatch):  # noqa: F811
    win = make_win()
    win._startup_notes()
    assert win.menu_hook is None                                # tests and screenshots (offscreen)
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setenv("LEONIDA_NO_MENU_BRIDGE", "1")
    assert menuhook.install(win) is None
