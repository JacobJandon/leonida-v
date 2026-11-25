"""The GUI's Install page writes a mod's locked settings inside the mod's own step (real-PC bug: the CLI's
`install --only` didn't; the GUI must keep doing it)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import acceptance_flow as AF  # noqa: E402
from test_gui_pages import dialogs, make_win, qapp, wait_idle  # noqa: E402,F401  (fixtures)

from leonida import settings as S  # noqa: E402


def test_install_page_writes_the_locked_settings_with_the_mod(make_win, dialogs, monkeypatch, game, downloads):  # noqa: F811
    monkeypatch.setattr("leonida.verify.verify_session", lambda s: [])
    win = make_win()
    s = win.session
    s.choose_pack("video-setup", None, "balanced")
    mod = s.manifest.mods["actionsv"]
    AF.write_fixture(downloads, mod)
    page = win.pages[5]
    monkeypatch.setattr(page, "todo", lambda: [mod])
    dialogs.button = "Works - continue"
    page.install_next()
    wait_idle(page)
    assert s.log.installed_mods() == {"actionsv"}
    wanted = {w.key: w.value for w in s.settings_for(mod) if w.file == "ActionsV.ini"}
    assert wanted.get("Input/MenuKey") == "F7"
    ini = (game / "ActionsV.ini").read_text(encoding="utf-8-sig")
    assert S.ini_get(ini, "Input/MenuKey") == "F7"
    assert s.settings_drift() == [] and [st.mod for st in s.log.steps] == ["actionsv"]
