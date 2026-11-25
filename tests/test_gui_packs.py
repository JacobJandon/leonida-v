# ruff: noqa: F811  (the shared fixtures of test_gui_pages are imported, then used as arguments)
"""GUI for the edition, modpack, add-on, variant, 'your own mods' and locked-settings engines (F3/F4/F5).

Uses the fixtures of test_gui_pages (a MainWindow on a temp state and a stub game folder; every dialog faked)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QPushButton  # noqa: E402
from test_gui_pages import BUILD, dialogs, make_win, qapp, trace_qt_threads  # noqa: E402,F401

from leonida import custommods  # noqa: E402
from leonida import settings as settings_mod  # noqa: E402
from leonida.checks import WARNING  # noqa: E402
from leonida.detect import GameInstall  # noqa: E402
from leonida.gui import app as A  # noqa: E402
from leonida.gui import widgets as W  # noqa: E402
from leonida.gui.newpages import editions_from  # noqa: E402
from leonida.gui.ownmods import CustomModDialog, CustomModsPanel, describe  # noqa: E402
from leonida.session import Session  # noqa: E402


def _flush():
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture
def legacy(tmp_path) -> Path:
    g = tmp_path / "Grand Theft Auto V"
    g.mkdir()
    (g / "GTA5.exe").write_bytes(b"MZ legacy")
    return g


# ------------------------------------------------------------------------------------------------- editions
def test_editions_from_uses_the_detected_edition():
    gi = [GameInstall(Path("D:/A"), "steam", Path("D:/A/odd-name.exe"), "1.0.1013.20", "enhanced"),
          GameInstall(Path("D:/L"), "steam", Path("D:/L/GTA5.exe"), "1.0.3586.0", None)]
    assert editions_from(gi) == [("Enhanced", str(Path("D:/A")), "1.0.1013.20"),
                                 ("Legacy", str(Path("D:/L")), "1.0.3586.0")]


def test_game_page_switching_edition_switches_the_mod_list(make_win, monkeypatch, game, legacy):
    win = make_win()
    s = win.session
    page, choose = win.pages[1], win.pages[2]
    assert s.edition == "enhanced"
    assert "Mod list in use: <b>GTA V Enhanced</b>" in page.edition_note.text()
    monkeypatch.setattr(A, "detect_games", lambda names: [
        GameInstall(game, "steam", game / "GTA5_Enhanced.exe", BUILD, "enhanced"),
        GameInstall(legacy, "steam", legacy / "GTA5.exe", None, "legacy")])
    page.detect()
    assert page.list.item(1).text().endswith("GTA V Legacy")
    assert page.editions.buttons["Legacy"].isEnabled() and page.editions.current() == "Enhanced"
    enhanced_packs = {b.text() for b in choose.group.buttons()}
    # picking the Legacy card uses that folder: the session loads the Legacy mod list and the pages follow
    page.editions.buttons["Legacy"].setChecked(True)
    _flush()
    assert s.config.game_dir == str(legacy) and s.edition == "legacy"
    assert s.base_manifest.edition == "legacy"
    assert "Mod list in use: <b>GTA V Legacy</b>" in page.edition_note.text()
    legacy_packs = {b.text() for b in choose.group.buttons()}
    assert legacy_packs == {p.name for p in s.base_manifest.packs.values()} and legacy_packs != enhanced_packs
    assert set(choose.packs.cards) == set(s.base_manifest.packs)
    assert choose.packs.edition_badge.text() == "Mods for GTA V Legacy"
    assert win.sidebar.edition.text() == "GTA V Legacy"
    assert all(m.id in s.base_manifest.mods for m in s.mods())
    # and back
    page.editions.buttons["Enhanced"].setChecked(True)
    _flush()
    assert s.edition == "enhanced" and win.sidebar.edition.text() == "GTA V Enhanced"
    assert {b.text() for b in choose.group.buttons()} == enhanced_packs


def test_game_page_shows_an_edition_mismatch(make_win, legacy):
    win = make_win()
    s = win.session
    s.edition_override = "enhanced"
    win.pages[1].set_dir(str(legacy))
    assert "the mod list in use is for GTA V Enhanced" in win.pages[1].edition_note.text()


# ------------------------------------------------------------------------------------------------- modpacks
def test_modpack_cards_come_from_the_packs(make_win):
    win = make_win()
    s = win.session
    page = win.pages[2]
    cards = page.packs.cards
    assert list(cards) == list(s.base_manifest.packs)
    showcase = s.base_manifest.packs["video-setup"]
    texts = [b.text() for b in cards["video-setup"].findChildren(W.Badge)]
    assert f"{len(showcase.variants)} variants" in texts
    assert f"{len(s.base_manifest.pack_mod_ids('video-setup'))} mods" in texts
    # choosing another pack on the picker saves it (default add-ons and variant) and opens the add-ons view
    page.packs.select("video-setup")
    page.packs.next_btn.click()
    assert page.views.currentIndex() == 1
    c = s.pack_choice()
    assert (c.pack, c.addons, c.variant) == ("video-setup", None, None)
    assert s.config.profile == "video-setup"
    assert set(page.addon_cards) == {a.id for lst in s.base_manifest.addons_for("video-setup").values() for a in lst}
    assert all(page.addon_cards[a].control.isChecked() for a in showcase.default_addons)
    # "Change pack" goes back with the chosen pack selected
    page.show_packs()
    assert page.views.currentIndex() == 0 and page.packs.selected == "video-setup"


def test_addon_toggle_and_rollback_question(make_win, dialogs, monkeypatch):
    win = make_win()
    s = win.session
    page = win.pages[2]
    base = s.base_manifest
    addon = base.addons["street-food"]
    assert not page.addon_cards["street-food"].control.isChecked()
    page.addon_cards["street-food"].control.setChecked(True)
    _flush()
    assert s.chosen_addons() == ("street-food",)
    assert set(addon.mods) <= {m.id for m in s.mods()}
    assert page.addon_cards["street-food"].control.isChecked()  # rebuilt, still ticked
    # its mod is installed: turning the add-on off asks
    rolled = []
    monkeypatch.setattr("leonida.packs.rollback_mods", lambda sess, ui, ids: rolled.append(set(ids)) or
                        [f"{i}: rolled back" for i in sorted(ids)])
    monkeypatch.setattr(s.log, "installed_mods", lambda: set(addon.mods) | {"scripthookv"})
    dialogs.button = "Cancel"
    page.toggle_addon("street-food", False)
    assert s.chosen_addons() == ("street-food",) and rolled == []  # cancelled: the old choice is back
    assert "not in your new choice" in dialogs.boxes[-1]
    dialogs.button = "Keep installed"
    page.toggle_addon("street-food", False)
    assert s.chosen_addons() == () and rolled == []
    page.toggle_addon("street-food", True)
    dialogs.button = "Roll back"
    page.toggle_addon("street-food", False)
    assert rolled == [set(addon.mods)]
    assert any("rolled back" in t for t in dialogs.texts("information"))


def test_pack_switch_from_the_radio_row_rolls_back(make_win, dialogs, monkeypatch):
    win = make_win()
    s = win.session
    page = win.pages[2]
    rolled = []
    monkeypatch.setattr("leonida.packs.rollback_mods", lambda sess, ui, ids: rolled.append(set(ids)) or [])
    rb = next(b for b in page.group.buttons() if b.property("pid") == "core-plus")
    rb.click()
    plus = {m.id for m in s.mods()}
    leaving = plus - set(s.base_manifest.pack_mod_ids("core"))
    assert leaving
    monkeypatch.setattr(s.log, "installed_mods", lambda: set(leaving))
    dialogs.button = "Roll back"
    next(b for b in page.group.buttons() if b.property("pid") == "core").click()
    assert s.pack_choice().pack == "core" and rolled == [leaving]
    assert any("Nothing to roll back" in t for t in dialogs.texts("information"))


def test_variant_switcher_writes_the_variant_settings(make_win, dialogs, monkeypatch):
    win = make_win()
    s = win.session
    page = win.pages[2]
    assert page.variant_box.isHidden()  # Core has no variants
    s.choose_pack("video-setup")
    page.rebuild()
    pack = s.base_manifest.packs["video-setup"]
    assert not page.variant_box.isHidden()
    assert list(page.variant_buttons) == [v.id for v in pack.variants]
    assert page.variant_buttons[pack.default_variant].isChecked()
    applied = []
    monkeypatch.setattr(s.log, "installed_mods", lambda: {"scripthookv"})
    monkeypatch.setattr(s, "installed_settings", lambda: ["something locked"])
    monkeypatch.setattr(s, "apply_settings", lambda ui, dry_run=False: applied.append(1) or ["ScriptHookV: x.ini"])
    page.variant_buttons["ultra"].click()
    assert s.pack_choice().variant == "ultra" and applied == [1]
    assert any("Write the Ultra settings" in t for t in dialogs.texts("question"))
    assert page.variant_buttons["ultra"].isChecked()
    assert page.variant_desc.text() == pack.variant("ultra").description
    dialogs.answer = A.QMessageBox.StandardButton.No
    page.pick_variant("performance")
    assert s.pack_choice().variant == "performance" and applied == [1]
    page.pick_variant("performance")  # same: nothing asked
    assert s.pack_choice().variant == "performance"


# ------------------------------------------------------------------------------------------------- your own mods
def _fill(**values):
    def hook(dlg):
        if isinstance(dlg, CustomModDialog):
            for name, value in values.items():
                widget = getattr(dlg, name)
                if name == "method":
                    widget.setCurrentIndex(widget.findData(value))
                elif name == "target":
                    widget.setCurrentText(value)
                elif name in ("from_file", "from_page"):
                    widget.setChecked(value)
                else:
                    widget.setText(value)
            dlg.save()
    return hook


def test_your_own_mods_add_edit_disable_remove_export(make_win, dialogs, monkeypatch, tmp_path):
    win = make_win()
    s = win.session
    page = win.pages[2]
    mod_file = tmp_path / "MyTrainer.zip"
    mod_file.write_bytes(b"PK")
    # added from the modpack page's "Add a mod" (file, copy two files into scripts)
    dialogs.on_dialog = _fill(name="My Trainer", from_file=True, file=str(mod_file), method="copy",
                              files="trainer.asi, trainer.ini", target="scripts")
    page.packs.add_btn.click()
    entries = custommods.load_entries(s.state)
    assert [e["id"] for e in entries] == ["my-trainer"]
    assert entries[0]["files"] == [{"match": "trainer.asi", "to": "scripts"}, {"match": "trainer.ini", "to": "scripts"}]
    assert page.views.currentIndex() == 1
    assert "my-trainer" in {m.id for m in s.mods()}
    assert s.matches().matched["my-trainer"] == mod_file  # its own file, wherever it is
    assert "my-trainer" not in page.cards  # listed in its panel, not as a mod card
    assert list(page.own.row_widgets) == ["my-trainer"]
    assert describe(entries[0]) == "MyTrainer.zip · trainer.asi, trainer.ini -> scripts"
    assert "You have 1 of your own." in page.packs.own_caption.text()
    # a page-only mod needs its download name
    dialogs.on_dialog = _fill(name="Page Mod", from_page=True, page="https://example.org/mod", archive="")
    assert page.own.add() is None
    dlg = dialogs.dialogs[-1]
    assert dlg.error.isVisibleTo(dlg) and "archive" in dlg.error.text()
    dialogs.on_dialog = _fill(name="Page Mod", from_page=True, page="https://example.org/mod", archive="pagemod*.zip",
                              method="generic")
    assert page.own.add()["id"] == "page-mod"
    assert describe(custommods.load_entries(s.state)[1]) == "example.org · placed by Leonida"
    # copy without files is refused in the dialog
    dialogs.on_dialog = _fill(name="Bad", from_file=True, file=str(mod_file), method="copy", files="")
    assert page.own.add() is None and "which files" in dialogs.dialogs[-1].error.text()
    # edit keeps the id and order
    dialogs.on_dialog = _fill(target="plugins")
    page.own.edit(next(x for x in custommods.load_entries(s.state) if x["id"] == "my-trainer"))
    e = next(x for x in custommods.load_entries(s.state) if x["id"] == "my-trainer")
    assert e["id"] == "my-trainer" and e["order"] == 1 and e["files"][0]["to"] == "plugins"
    # switch one off: not in the mod list any more (and editing keeps it off)
    _flush()
    panel = page.own
    panel.set_enabled("page-mod", False)
    assert "page-mod" not in {m.id for m in s.mods()}
    dialogs.on_dialog = _fill(notes="later")
    panel.edit(next(x for x in custommods.load_entries(s.state) if x["id"] == "page-mod"))
    assert next(x for x in custommods.load_entries(s.state) if x["id"] == "page-mod")["enabled"] is False
    # export
    out = tmp_path / "out" / "mine.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    assert panel.export() == out
    assert sorted(x["id"] for x in json.loads(out.read_text(encoding="utf-8"))["mods"]) == ["my-trainer", "page-mod"]
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    assert panel.export() is None
    # remove (asks; mentions an installed one stays installed)
    monkeypatch.setattr(s.log, "installed_mods", lambda: {"my-trainer"})
    dialogs.answer = A.QMessageBox.StandardButton.No
    assert panel.remove("my-trainer") is False
    dialogs.answer = A.QMessageBox.StandardButton.Yes
    assert panel.remove("my-trainer") is True
    assert "stay until you undo" in dialogs.texts("question")[-1]
    assert [x["id"] for x in custommods.load_entries(s.state)] == ["page-mod"]


def test_your_own_mods_panel_reports_a_broken_file(make_win):
    win = make_win()
    s = win.session
    s.state.mkdir(parents=True, exist_ok=True)
    (s.state / custommods.FILE_NAME).write_text("{broken", encoding="utf-8")
    panel = CustomModsPanel(s)
    assert panel.entries() == [] and panel.row_widgets == {}
    assert panel.rows.count() == 1
    panel.deleteLater()


# ------------------------------------------------------------------------------------------------- locked settings
def _drift(s, monkeypatch):
    wanted = settings_mod.Wanted("menyoo", "menyooStuff/menyooConfig.ini", "ini", "Settings/OpenKey", "F10",
                                 "Clashes with the phone.")
    state = {"drift": [settings_mod.Drift(wanted, "F8")]}
    monkeypatch.setattr(s, "settings_drift", lambda: list(state["drift"]))
    applied = []

    def apply(ui, dry_run=False):
        applied.append(1)
        state["drift"] = []
        return ["Menyoo: menyooStuff/menyooConfig.ini"]

    monkeypatch.setattr(s, "apply_settings", apply)
    return state, applied


def test_check_page_drift_warning_restore_all(make_win, dialogs, monkeypatch):
    win = make_win()
    s = win.session
    state, applied = _drift(s, monkeypatch)
    page = win.pages[4]
    page.refresh()
    drift = page.cards.findChildren(W.DriftWarning)
    assert len(drift) == 1
    assert any(f.code == "setting-drift" and f.level == WARNING for f in s.findings())
    labels = [lab.text() for lab in drift[0].findChildren(QLabel)]
    assert "Menyoo 2.0: OpenKey was changed to F8; Leonida sets F10" in labels           # in words, not file/key
    assert "Clashes with the phone." in labels
    drift[0].restore_btn.click()
    assert applied == [1]
    assert any(t.startswith("Restored:") for t in dialogs.texts("information"))
    assert not [w for w in page.cards.findChildren(W.DriftWarning) if w.isVisibleTo(page)]


def test_manage_page_drift_warning_keep_mine(make_win, dialogs, monkeypatch):
    win = make_win()
    s = win.session
    state, applied = _drift(s, monkeypatch)
    page = win.pages[6]
    page.refresh()
    assert page.drift_box.count() == 1
    w = page.drift_box.itemAt(0).widget()
    keep = next(b for b in w.findChildren(QPushButton) if b.text() == "Keep mine")
    state["drift"] = []
    keep.click()
    key = settings_mod.unlock_key("menyoo", "menyooStuff/menyooConfig.ini", "Settings/OpenKey")
    assert key in settings_mod.unlocked(s.state)
    assert page.drift_box.count() == 0
    assert applied == []


def test_restore_settings_failure_is_reported(make_win, dialogs, monkeypatch):
    win = make_win()
    s = win.session
    _drift(s, monkeypatch)
    monkeypatch.setattr(s, "apply_settings", lambda ui, dry_run=False: (_ for _ in ()).throw(RuntimeError("locked")))
    assert A._restore_settings(win.pages[6], lambda: None) == []
    assert dialogs.texts("warning")[-1] == "Couldn't restore the settings: locked"
    monkeypatch.setattr(s, "settings_drift", lambda: (_ for _ in ()).throw(OSError("unreadable")))
    assert A._drift_widget(win.pages[6], lambda: None) is None
    monkeypatch.setattr(s, "apply_settings", lambda ui, dry_run=False: [])
    A._restore_settings(win.pages[6], lambda: None)
    assert dialogs.texts("information")[-1] == "The settings already had their locked values."


def test_session_still_saves_the_pack_when_reopened(make_win):
    win = make_win()
    s = win.session
    win.pages[2].switch("core-plus", ["interiors"], None)
    again = Session(state=s.state)
    assert again.pack_choice().pack == "core-plus" and again.chosen_addons() == ("interiors",)
