"""The must items of docs/UX-REVIEW.md (M1-M10) that live in the launcher, and the engine pieces behind them."""
from __future__ import annotations

import pytest

from leonida import playinfo as P
from leonida import settings as S
from leonida.log import Action

pytest.importorskip("PySide6")

from test_gui_launcher import labels  # noqa: E402
from test_gui_pages import dialogs, make_win, qapp  # noqa: E402,F401  (fixtures)


# ------------------------------------------------------------------------------------- M7: key aliases
def test_dotnet_key_aliases_are_the_same_key():
    assert S.same("Next", "PageDown") and S.same("prior", "PageUp") and S.same("Return", "Enter")
    assert S.same("Capital", "CapsLock") and S.same("Snapshot", "PrintScreen") and S.same("Back", "Backspace")
    assert not S.same("Next", "PageUp") and S.same("1.50", 1.5) and not S.same("F8", "F9")


# ------------------------------------------------------------------------------------- M3 / M4: from the data
def test_keys_come_from_the_data_with_the_values_leonida_locks(make_win):  # noqa: F811
    s = make_win().session
    rows = P.keys(s)
    by_action = {(r.mod, r.action): r for r in rows}
    assert rows and all(r.key for r in rows)
    assert all(not r.key.isdigit() for r in rows)                # Windows key codes are shown as names
    text = P.keys_text(rows)
    assert text.count("\n") == len(rows) - 1 and rows[0].action in text
    assert len(by_action) == len(rows)
    assert P.key_label("119") == "F8" and P.key_label("LControlKey") == "Left Ctrl" and P.key_label("NumPad7") == "Num 7"
    assert P.key_label("Next") == "Page Down" and P.key_label("65") == "A" and P.key_label("v") == "V"


def test_before_play_lists_the_in_game_steps(make_win):  # noqa: F811
    s = make_win().session
    mods = list(s.manifest.mods.values())
    items = P.before_play(s, mods)
    assert items and all(P.IN_GAME.match(step) for _m, step in items)
    assert any("Borderless" in step for _m, step in items)
    assert len({step for _m, step in items}) == len(items)    # no repeats


def test_screen_type_from_settings_xml(tmp_path):
    folder = tmp_path / "Documents" / "Rockstar Games" / "GTAV Enhanced"
    folder.mkdir(parents=True)
    assert P.settings_xml(tmp_path) is None and P.screen_type(tmp_path / "nope.xml") is None
    (folder / "settings.xml").write_text('<Settings><video><Windowed value="2" /></video></Settings>')
    assert P.screen_type(P.settings_xml(tmp_path)) == "borderless"
    (folder / "settings.xml").write_text('<Windowed value="0" />')
    assert P.screen_type(P.settings_xml(tmp_path)) == "fullscreen"
    (folder / "settings.xml").write_text("<Settings />")
    assert P.screen_type(P.settings_xml(tmp_path)) is None


def test_overview_shows_before_you_play_and_the_keys(make_win, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QApplication

    from leonida.gui import launcher as L

    win = make_win()
    s = win.session
    hud = next(p for p in s.base_manifest.packs if any("Borderless" in st for _m, st in
                                                       P.before_play(s, s.base_manifest.resolve_pack(p))))
    s.choose_pack(hud)
    monkeypatch.setattr(P, "screen_type", lambda path=None: "fullscreen")
    win.open_pack(hud)
    texts = labels(win.pack_page.overview)
    assert "BEFORE YOU PLAY" in texts and "KEYS IN THE GAME" in texts
    assert any(t.startswith("⚠ Your Screen Type is Fullscreen") for t in texts)
    card = L.keys_card(win, s.mods())
    next(b for b in card.findChildren(L.QPushButton) if b.text() == "Copy as text").click()
    assert QApplication.clipboard().text() == P.keys_text(card.rows)
    monkeypatch.setattr(P, "screen_type", lambda path=None: "borderless")
    assert any(t.startswith("✓") for t in labels(L.before_play_card(win, s.mods())))
    assert win.about_page.keys is None or win.about_page.keys.rows   # About & help shows the same list


# ------------------------------------------------------------------------------------- M1 / M2: navigation
def test_returning_users_get_the_modpack_and_a_folded_wizard(make_win):  # noqa: F811
    win = make_win()
    assert not win.returning() and win.nav.isVisibleTo(win) and win.setup_toggle.text().endswith("SET UP")
    win.go(0)
    assert not win.back.isVisibleTo(win)                       # nothing to go back to from Welcome
    assert "Vice City" not in " ".join(labels(win.pages[0]))
    win.session.choose_pack(win.session.pack_choice().pack or win.session.base_manifest.default_pack)
    again = make_win()
    again.session.choose_pack(win.session.pack_choice().pack)
    w2 = type(win)(again.session)
    try:
        assert w2.returning() and w2.stack.currentWidget() is w2.pack_page
        assert not w2.nav.isVisibleTo(w2) and "WIZARD" in w2.setup_toggle.text()
        w2.setup_toggle.click()
        assert w2.nav.isVisibleTo(w2)
        w2.setup_toggle.click()
        w2.go(3)                                               # a setup step opens the wizard again
        assert w2.nav.isVisibleTo(w2)
        w2.foot_nav.setCurrentRow(0)                           # Settings sits at the bottom
        assert w2.stack.currentWidget() is w2.settings_page and w2.home_nav.state(2) == "current"
        w2.home_nav.setCurrentRow(1)
        assert w2.stack.currentWidget() is w2.pack_page and w2.foot_nav.currentRow() == -1
    finally:
        w2.close()
        w2.deleteLater()


# ------------------------------------------------------------------------------------- M5 / M6: missing, counts
def test_the_one_missing_mod_is_named_everywhere(make_win, dialogs):  # noqa: F811
    win = make_win()
    s = win.session
    for pid in s.base_manifest.packs:                        # a pack with an optional mod (it can be removed)
        s.choose_pack(pid)
        if any(m.tier != "core" for m in s.mods()):
            break
    mods = s.mods()
    last = next(m for m in reversed(mods) if m.tier != "core")
    for m in mods:
        if m.id != last.id:
            st = s.log.new_step(m.id, "copy")
            st.status = "done"
    s.log.save()
    install = win.pages[5]
    install.refresh()
    assert install.next_title.text() == "All downloaded mods are installed"
    assert last.name in install.next_detail.text() and install.remove_btn.isVisibleTo(install)
    install.next_btn.click()
    assert win.stack.currentIndex() == 3
    get = win.pages[3]
    get.refresh()
    assert " · missing: " in get.ready_label.text()                     # the files it still needs, by name
    win.update_sidebar()
    n = len(mods) - 1
    assert win.bottom.state.text.text().endswith(f"{n} of {len(mods)} mods")
    page = win.pages[6]
    page.refresh()
    assert page.state.text().startswith(f"{n} of {len(mods)} mods installed")
    install._remove_missing()                                # dialogs answer Yes
    assert last.id not in {m.id for m in s.mods()} and last.id in s.config.remove


def test_the_pack_button_names_a_single_missing_file(make_win, monkeypatch):  # noqa: F811
    from leonida.gui import launcher as L

    win = make_win()
    s = win.session
    pid = s.pack_choice().pack or s.base_manifest.default_pack
    s.choose_pack(pid)
    mods = s.mods()
    real = s.matches

    def matches(m=None):
        r = real(m)
        r.matched = {x.id: s.config.downloads() / "x.zip" for x in mods[1:]}
        return r

    monkeypatch.setattr(s, "matches", matches)
    monkeypatch.setattr(L, "pack_info", lambda w, p, e=None: L._pack_info(w, p, e or s.edition))
    win.open_pack(pid)
    if len(mods[0].name) < 24:
        assert win.pack_page.main_btn.text() == f"Get {mods[0].name}"


# ------------------------------------------------------------------------------------- M8 / M9: words
def test_words_not_jargon():
    from types import SimpleNamespace as NS

    import leonida.gui.app as A

    step = NS(mod="x", actions=[Action("add", "a.dll"), Action("add", "b.dll"), Action("replace", "c.ini"),
                                Action("mkdir", "d/")])
    assert A.changes_text(step) == "2 files added, 1 changed · can be undone"
    assert A.changes_text(NS(mod="settings:x", actions=[Action("replace", "c.ini")])) == \
        "1 mod setting file written · can be undone"
    assert A.changes_text(NS(mod="x", actions=[])) == "no files · can be undone"
    assert A.scan_words(None) == "not checked yet" and A.scan_words(NS(status="ok", label="")) == "✓ checked"
    from leonida.gui.launcher import first_sentence

    assert first_sentence("Short. Then the details (its page, 2026).") == ("Short.", "Then the details (its page, 2026).")


def test_drift_is_said_in_words(qapp):  # noqa: F811
    from PySide6.QtWidgets import QLabel

    from leonida.gui.widgets import DriftWarning

    w = DriftWarning([("scripts/RideShare.ini", "Keys/CancelJob", "PageDown", "F9", "Clashes with Menyoo.", "Ryde")])
    texts = [lab.text() for lab in w.findChildren(QLabel)]
    assert "Ryde: CancelJob was changed to F9; Leonida sets PageDown" in texts
    assert w.restore_btn.text() == "Put it back"


# ------------------------------------------------------------------------------------- M10: the graphics card
def test_gpu_requirements():
    assert P.gpu_meets("rtx", ["NVIDIA GeForce RTX 4070"]) and not P.gpu_meets("rtx", ["NVIDIA GeForce GTX 1070"])
    assert P.gpu_meets("rtx50", ["NVIDIA GeForce RTX 5080"]) and not P.gpu_meets("rtx50", ["NVIDIA GeForce RTX 4070"])
    assert P.gpu_meets("rtx", []) is None and P.gpu_meets(None, []) is True and P.gpu_meets("odd", ["x"]) is None
    assert P.gpu_note("rtx", ["NVIDIA GeForce GTX 1070"]) == "Needs an NVIDIA RTX card; you have a GTX 1070"
    assert P.gpu_note("rtx", ["NVIDIA GeForce RTX 3060"]) == ""


def test_an_addon_this_card_cant_run_is_greyed_out(make_win, monkeypatch):  # noqa: F811
    import dataclasses

    from leonida.gui.chooser import AddonCard

    win = make_win()
    s = win.session
    mod = next(iter(s.manifest.mods.values()))
    needy = dataclasses.replace(mod, requires={"gpu": "rtx"})
    addon = type("A", (), {"id": "x", "name": "X", "description": "", "mods": (needy.id,)})()
    card = AddonCard(addon, [needy], False, lambda *a: None, blocked=P.gpu_note("rtx", ["NVIDIA GeForce GTX 1070"]))
    assert not card.control.isEnabled() and "GTX 1070" in card.control.toolTip()
    ticked = AddonCard(addon, [needy], True, lambda *a: None, blocked="Needs an NVIDIA RTX card; you have a GTX 1070")
    assert ticked.control.isEnabled()                        # already chosen: it can be unticked


def test_variant_requires_is_read_from_the_manifest(tmp_path):
    import json
    import shutil
    from pathlib import Path

    from leonida.manifest import load_manifest

    src = Path(__file__).resolve().parents[1] / "leonida" / "manifest"
    dst = tmp_path / "m"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    packs = json.loads((dst / "modpacks.json").read_text(encoding="utf-8"))
    pack = next(p for p in packs["packs"] if p.get("variants"))
    pack["variants"][-1]["requires"] = {"gpu": "rtx"}
    (dst / "modpacks.json").write_text(json.dumps(packs), encoding="utf-8")
    m = load_manifest(dst)
    assert m.packs[pack["id"]].variants[-1].requires == {"gpu": "rtx"}
