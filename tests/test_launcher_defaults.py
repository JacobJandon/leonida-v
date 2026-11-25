"""Launcher defaults: Verify files (installed files and archive entries against the install log, then the locked
settings written again), the folder buttons, What's new after an update, and the mod update badges."""

from __future__ import annotations

import json

import pytest
from test_settings import install_all, kit  # noqa: F401  (fixture)

from leonida import filecheck as FC
from leonida import log as L
from leonida.installer import InstallError


# ------------------------------------------------------------------------------------------------ the engine
def test_verify_files_finds_missing_changed_and_returned_files(kit, game):  # noqa: F811
    install_all(kit)
    res = kit.verify_files()
    assert res.ok and res.checked > 0 and res.summary()[0].startswith(f"All {res.checked} installed file(s)")
    (game / "Menyoo.asi").write_text("someone else's file")
    (game / "ScriptHookVDotNetCore.dll").unlink()
    res = kit.verify_files()
    assert {(p.path, p.problem) for p in res.problems} == {("Menyoo.asi", FC.CHANGED),
                                                          ("ScriptHookVDotNetCore.dll", FC.MISSING)}
    assert set(res.mods()) == {"menyoo", "shvdne"}
    text = "\n".join(res.summary({"menyoo": "Menyoo"}))
    assert "2 of" in text and "Menyoo:" in text and "Menyoo.asi: changed" in text


def test_the_last_action_on_a_path_decides(tmp_path):
    game, state = tmp_path / "g", tmp_path / "s"
    game.mkdir()
    log = L.InstallLog(state / "install-log.json")
    (game / "a.txt").write_text("v2")
    st = log.new_step("one", "copy")
    st.actions.append(L.Action(L.ADD, "a.txt", "old-hash"))
    st.status = "done"
    st2 = log.new_step("settings:one", "settings")
    from leonida.matcher import sha256_file

    st2.actions.append(L.Action(L.REPLACE, "a.txt", sha256_file(game / "a.txt"), "backups/x"))
    st2.actions.append(L.Action(L.MKDIR, "made/"))
    st2.actions.append(L.Action(L.EXT_REMOVE, "gone.txt", None, None))
    st2.status = "done"
    progress = []
    res = FC.check_files(log, game, state, progress=lambda i, n, p: progress.append((i, n)))
    assert [p.path for p in res.problems] == ["made/"] and progress[-1] == (3, 3)
    (game / "made").mkdir()
    (game / "gone.txt").write_text("back")
    res = FC.check_files(log, game, state)
    assert [(p.path, p.problem) for p in res.problems] == [("gone.txt", FC.CAME_BACK)]
    assert res.mods() == ["one"]                                  # a settings step counts for its mod


def test_archive_entries_are_checked_with_the_helper(tmp_path, monkeypatch):
    from leonida import rpf as R

    game, state = tmp_path / "g", tmp_path / "s"
    (game / "mods" / "update").mkdir(parents=True)
    (game / "mods" / "update" / "update.rpf").write_bytes(b"RPF7")
    folder = state / "backups" / "step-1" / "rpf-entries"
    folder.mkdir(parents=True)
    (folder / R.ENTRY_MANIFEST).write_text(json.dumps({"entries": [
        {"entry": "x64/a.ytd", "after": "h1"}, {"entry": "x64/b.ytd", "after": "h2"}, {"entry": "c", "after": None}]}))
    log = L.InstallLog(state / "install-log.json")
    st = log.new_step("maps", "rpf")
    st.actions.append(L.Action(L.RPF_EDIT, "mods/update/update.rpf", None, "backups/step-1/rpf-entries"))
    st.status = "done"
    res = FC.check_files(log, game, state, helper=None)
    assert res.ok and "RPF helper isn't installed" in res.skipped[0]
    monkeypatch.setattr(R, "run_helper", lambda cmd, g, ops: [{"hashes": {"x64/a.ytd": "h1", "x64/b.ytd": "zz"}}])
    res = FC.check_files(log, game, state, helper=["helper"])
    assert [(p.problem, p.detail) for p in res.problems] == [(FC.ENTRIES, "x64/b.ytd")]

    def boom(*a):
        raise R.RpfError("no helper today")

    monkeypatch.setattr(R, "run_helper", boom)
    res = FC.check_files(log, game, state, helper=["helper"])
    assert res.ok and "no helper today" in res.skipped[0]


def test_verify_refuses_without_a_game_or_while_online_safe(kit, game, monkeypatch):  # noqa: F811
    install_all(kit)
    monkeypatch.setattr(type(kit), "online_status", lambda self: "online-safe")
    with pytest.raises(InstallError, match="Online-safe"):
        kit.verify_files()
    kit.config.game_dir = None
    with pytest.raises(InstallError, match="Find your game"):
        kit.verify_files()


# ------------------------------------------------------------------------------------------------ the GUI
pytest.importorskip("PySide6")

from test_gui_pages import dialogs, make_win, qapp, wait_idle, wait_until  # noqa: E402,F401  (fixtures)


def test_verify_files_in_the_launcher(kit, game, qt_app, monkeypatch):  # noqa: F811
    import leonida.gui.app as A
    from leonida.gui import launcher as Lg

    monkeypatch.setenv("LEONIDA_NO_OPEN", "1")
    install_all(kit)
    win = A.MainWindow(kit)
    try:
        Lg.verify_files(win)
        wait_until(lambda: getattr(win.bottom, "verifying", None) is None and win.notifications.items)
        assert win.notifications.items[0].text.startswith("Verify files: all ")
        (game / "Menyoo.asi").write_text("changed")
        drifted = game / "ScriptHookVDotNet.ini"
        drifted.write_text(drifted.read_text().replace("F4", "F9"))   # a locked value changed by hand
        assert kit.settings_drift()
        Lg.verify_files(win)
        wait_until(lambda: getattr(win.bottom, "verifying", None) is None and len(win.notifications.items) > 1)
        note = win.notifications.items[0]
        assert "1 file(s) differ" in note.text and "Locked settings written again" in note.text
        assert note.action == "Show" and kit.settings_drift() == []
        assert "Menyoo.asi: changed" in win.pages[6].view.toPlainText()
        note.on_action()
        assert win.stack.currentIndex() == 6 and win.pages[6].tabs.currentIndex() == 2
    finally:
        wait_idle(win, *win.pages)
        win.close()
        win.deleteLater()


def test_verify_with_nothing_installed_and_the_folder_buttons(make_win, game, monkeypatch):  # noqa: F811
    from leonida.gui import launcher as Lg

    win = make_win()
    Lg.verify_files(win)
    assert "Nothing is installed" in win.notifications.items[0].text
    opened = []
    monkeypatch.setattr("leonida.gui.app._open", lambda p: opened.append(p))
    assert Lg.open_folder(win, "game").startswith("Opened") and opened == [str(game)]
    assert "No mods folder yet" in Lg.open_folder(win, "mods")
    (game / "mods").mkdir()
    Lg.open_folder(win, "mods")
    assert opened[-1] == str(game / "mods")
    win.session.config.game_dir = None
    assert "Find your game" in Lg.open_folder(win, "game")
    menu = win.pack_page.more_menu()
    assert [a.text() for a in menu.actions()] == ["Verify files", "Open game folder", "Open mods folder",
                                                  "Open downloads folder"]


def test_update_badges(make_win):  # noqa: F811
    from types import SimpleNamespace as NS

    from leonida.gui import launcher as Lg

    win = make_win()
    s = win.session
    mid = s.mods()[0].id
    plan = NS(pending=[NS(mod_id=mid, change=NS(new_version="2.0"))])
    Lg.set_mod_updates(win, plan)
    assert win.mod_updates == {mid: "2.0"}
    win.show_home("browse")
    win.browse.tabs.setCurrentIndex(1)
    row = next(r for r in win.browse.rows if r.mod.id == mid)
    assert row.update_badge.text() == "Update 2.0"
    tile = next(t for t in win.browse.tiles if any(m.id == mid for m in t.info.mods))
    assert any(b.text() == "1 update" for b in tile.findChildren(Lg.W.Badge))
    Lg.set_mod_updates(win, None)
    win.browse.refresh_mods()
    assert not hasattr(next(r for r in win.browse.rows if r.mod.id == mid), "update_badge")


def test_whats_new(make_win, tmp_path):  # noqa: F811
    from leonida import __version__
    from leonida.gui import extras as E

    doc = tmp_path / "CHANGELOG.md"
    doc.write_text(f"# Changelog\n\n## Unreleased\n\n- next\n\n## {__version__} (today)\n\n- this one\n\n"
                   "## 0.9\n\n- old\n", encoding="utf-8")
    text = E.whats_new(doc=doc)
    assert "- this one" in text and "- next" in text and "- old" not in text
    assert E.whats_new("9.9", doc=tmp_path / "nope.md") == ""
    win = make_win()
    s = win.session
    assert E.maybe_whats_new(win) is False and s.config.seen_version == __version__   # a first start
    s.config.seen_version = "0.9"
    assert E.maybe_whats_new(win) is True
    note = win.notifications.items[0]
    assert "updated to" in note.text and "(from 0.9)" in note.text and note.action == "What's new"
    note.on_action()
    assert win.whats_new_dialog.windowTitle().startswith("What's new")
    assert E.maybe_whats_new(win) is False                                            # once
