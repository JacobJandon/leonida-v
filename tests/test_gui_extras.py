"""The launcher's other systems (leonida/gui/extras.py): Settings, About & help, notifications."""

from __future__ import annotations

import sys
import types
import zipfile

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402
from test_gui_pages import dialogs, make_win, qapp, wait_until  # noqa: E402,F401  (fixtures)

from leonida import __version__  # noqa: E402
from leonida.gui import extras as X  # noqa: E402
from leonida.paths import Config  # noqa: E402


# ------------------------------------------------------------------------------------------------ settings
def test_settings_save_to_config(make_win, dialogs):  # noqa: F811
    win = make_win()
    s = win.session
    win.show_home("settings")
    page = win.settings_page
    assert win.stack.currentWidget() is page and win.home_nav.state(2) == "current"
    assert page.folder_labels["game"].full == str(s.game_dir())
    page.debug.setChecked(True)
    page.updates.setChecked(False)
    page.site_boxes["nexusmods.com"].setChecked(True)
    cfg = Config.load(s.state)
    assert cfg.debug is True and cfg.update_check is False and cfg.autodl_sites == {"nexusmods.com": True}
    assert page.site_boxes["gta5-mods.com"].isChecked()          # on by default
    assert page.last_check.text() == "Last checked: never"


def test_nexus_is_off_by_default_with_the_reason(make_win, dialogs):  # noqa: F811
    win = make_win()
    page = win.settings_page
    assert not page.site_boxes["nexusmods.com"].isChecked()
    assert any("terms restrict automated downloading" in lab.text() for lab in page.findChildren(type(page.last_check)))


def test_update_check_switch_is_honoured(make_win, dialogs, monkeypatch):  # noqa: F811
    win = make_win()
    calls = []
    monkeypatch.delenv("LEONIDA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("LEONIDA_NO_NET", raising=False)
    monkeypatch.setattr(win.pages[6], "check_updates", lambda quiet=False: calls.append(quiet))
    win.session.config.update_check = False
    win._daily_update_check()
    assert calls == []
    win.session.config.update_check = True
    win._daily_update_check()
    assert calls == [True]


def test_folders_are_validated(make_win, dialogs, tmp_path, monkeypatch):  # noqa: F811
    win = make_win()
    page = win.settings_page
    empty = tmp_path / "NotTheGame"
    empty.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(empty)))
    page.change_folder("game")
    assert dialogs.texts("warning")[-1].startswith("No GTA V in")
    assert win.session.config.game_dir != str(empty)
    other = tmp_path / "Game2"
    other.mkdir()
    (other / "GTA5_Enhanced.exe").write_bytes(b"MZ")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(other)))
    page.change_folder("game")
    assert Config.load(win.session.state).game_dir == str(other)
    dl = tmp_path / "NewDownloads"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(dl)))
    page.change_folder("downloads")
    assert Config.load(win.session.state).download_dir == str(dl) and dl.is_dir()
    assert win.notifications.items[0].text.startswith("Downloads folder")


def test_default_variant(make_win, dialogs):  # noqa: F811
    win = make_win()
    s = win.session
    pid = next(p.id for p in s.base_manifest.packs.values() if p.variants)
    s.choose_pack(pid)
    page = win.settings_page
    page.refresh()
    picked = []
    win.pages[2].pick_variant = lambda vid: picked.append(vid)
    last = s.base_manifest.packs[pid].variants[-1]
    page.variant.setCurrentIndex(page.variant.findData(last.id))
    assert picked == [last.id]


def test_reset_keeps_what_undoes_the_mods(tmp_path):
    st = tmp_path / "State"
    (st / "backups").mkdir(parents=True)
    (st / "images").mkdir()
    for name in ("install-log.json", "baseline-snapshot.json", "pack.json", "scan-results.json",
                 "archive-listings.json", "custom-mods.json"):
        (st / name).write_text("{}")
    (st / "backups" / "b1").write_text("x")
    (st / "browser").mkdir()
    Config(game_dir="G:/game", download_dir="D:/dl", profile="core", swaps={"a": "b"}, debug=True).save(st)
    gone = X.reset_state(st)
    assert {"pack.json", "scan-results.json", "archive-listings.json", "custom-mods.json", "images/"} <= set(gone)
    for kept in ("install-log.json", "baseline-snapshot.json", "backups/b1", "browser"):
        assert (st / kept).exists(), kept
    cfg = Config.load(st)
    assert (cfg.game_dir, cfg.download_dir, cfg.profile, cfg.swaps, cfg.debug) == ("G:/game", "D:/dl", None, {}, False)


def test_reset_from_the_page_asks_first(make_win, dialogs):  # noqa: F811
    from PySide6.QtWidgets import QMessageBox

    win = make_win()
    s = win.session
    s.choose_pack("core")
    dialogs.answer = QMessageBox.StandardButton.No
    win.settings_page.reset()
    assert (s.state / "pack.json").exists()
    dialogs.answer = QMessageBox.StandardButton.Yes
    win.settings_page.reset()
    assert not (s.state / "pack.json").exists() and win.notifications.items[0].text.startswith("Reset:")


@pytest.mark.skipif(sys.platform != "win32", reason="shortcuts are Windows only")
def test_shortcuts_make_and_remove(make_win, dialogs, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LEONIDA_STARTMENU_DIR", str(tmp_path / "start"))
    monkeypatch.setenv("LEONIDA_DESKTOP_DIR", str(tmp_path / "desk"))
    monkeypatch.delenv("LEONIDA_NO_SHORTCUTS", raising=False)
    target = tmp_path / "Start-Leonida.bat"
    target.write_text("@echo off")
    win = make_win()
    page = win.settings_page
    monkeypatch.setattr(page, "_shortcut_target", lambda: (target, "", True))
    page.make_shortcuts()
    assert (tmp_path / "start" / "Leonida V.lnk").is_file() and (tmp_path / "desk" / "Leonida V.lnk").is_file()
    page.remove_shortcuts()
    assert not (tmp_path / "start" / "Leonida V.lnk").exists() and page.shortcut_note.text().startswith("Removed")
    page.remove_shortcuts()
    assert page.shortcut_note.text() == "There were no Leonida shortcuts."


# ---------------------------------------------------------------------------------------------- about/help
def test_about_credits_licence_and_links(make_win, dialogs):  # noqa: F811
    win = make_win()
    win.show_home("about")
    page = win.about_page
    items = X.credits()
    names = {(c.name, c.author) for c in items}
    assert ("Script Hook V", "Alexander Blade") in names
    assert any(c.kind == "Tools" and "CodeWalker" in c.name and c.author == "dexyfex" for c in items)
    assert page.credit_count == len(items) > 20
    assert page._licence().startswith("MIT License")


def test_help_without_diagnostics_says_so(make_win, dialogs, monkeypatch):  # noqa: F811
    monkeypatch.setattr(X, "optional", lambda name: None)
    win = make_win()
    page = X.AboutPage(win)
    assert not page.report_btn.isEnabled() and "next Leonida build" in page.help_note.text()
    assert page.report() is False
    text = page.copy_info()
    assert QApplication.clipboard().text() == text and f"Leonida V {__version__}" in text
    assert page.logs_dir() == win.session.state
    page.deleteLater()


def test_report_a_problem(make_win, dialogs, tmp_path, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMessageBox

    def build(session, out_dir):
        path = out_dir / "Leonida-report.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("logs/leonida.log", "x")
            z.writestr("state/config.json", "{}")
        return path

    fake = types.SimpleNamespace(build=build, preview=lambda session: ["logs/leonida.log", "state/config.json"])
    monkeypatch.setitem(sys.modules, "leonida.diagnostics", fake)
    monkeypatch.setenv("LEONIDA_DESKTOP_DIR", str(tmp_path))
    opened = []
    monkeypatch.setattr(X, "_open", lambda url: opened.append(url))
    win = make_win()
    page = X.AboutPage(win)
    assert page.report_btn.isEnabled()
    dialogs.answer = QMessageBox.StandardButton.Yes
    assert page.report() is True                       # built on a worker thread
    wait_until(lambda: getattr(page, "last_report", None) is not None and opened)
    path = page.last_report
    assert path == tmp_path / "Leonida-report.zip" and path.is_file()
    first, ask = dialogs.texts("question")[-2:]
    assert first.startswith("A problem report will hold:") and "state/config.json" in first  # shown before saving
    assert "logs/leonida.log" in ask and "Nothing is sent by Leonida" in ask
    (url,) = opened
    assert url.startswith(X.REPO_URL + "/issues/new?") and "Leonida-report.zip" in url and "title=" in url
    page.deleteLater()


def test_system_info_has_no_personal_paths(make_win, dialogs, monkeypatch):  # noqa: F811
    import os

    win = make_win()
    import platform
    import subprocess

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a process")))
    monkeypatch.setattr(platform, "_uname_cache", None, raising=False)
    info = X.system_info(win.session)       # starts no process (platform.platform() does on some systems)
    assert "Game: GTA V Enhanced" in info and os.path.expanduser("~") not in info


# --------------------------------------------------------------------------------------------- notifications
def test_notifications_toast_and_bell(make_win, dialogs):  # noqa: F811
    win = make_win(show=True)
    win.notify("Script Hook V installed (step 1).", "success")
    win.notify("Leonida V 9.9 is available", "info")
    assert win.toast.isVisible() and win.toast.text.text() == "Leonida V 9.9 is available"
    assert win.bell.text() == "2 new"
    menu = win.bell.show_menu()
    texts = [a.text() for a in menu.actions()]
    assert texts[0].endswith("Leonida V 9.9 is available") and texts[1].endswith("installed (step 1).")
    assert win.bell.text() == ""                                    # seen
    for i in range(60):
        win.notifications.notify(f"n{i}")
    assert len(win.notifications.items) == 50


def test_saved_downloads_notify(make_win, dialogs, downloads):  # noqa: F811
    from conftest import make_zip

    win = make_win()
    path = make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "shv"})
    win._file_saved(str(path))
    assert "recognised as Script Hook V" in win.notifications.items[0].text
