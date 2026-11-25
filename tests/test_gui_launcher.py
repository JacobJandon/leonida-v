"""The launcher views (leonida/gui/launcher.py): Browse (modpack tiles, every mod, the details drawer), the Modpack page
(banner, main action, tabs), the bottom bar with Play, pictures everywhere mods are listed."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from conftest import make_zip  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from test_gui_pages import dialogs, make_win, qapp, wait_until  # noqa: E402,F401  (fixtures)

from leonida.gui import launcher as L  # noqa: E402


def labels(w) -> list[str]:
    return [" ".join(x.text().split()) for x in w.findChildren(QLabel) if x.text().strip()]


def _pump():
    for _ in range(3):
        QApplication.processEvents()


# ------------------------------------------------------------------------------------------------- browse
def test_browse_shows_every_pack_and_filters(make_win, dialogs):  # noqa: F811
    win = make_win()
    win.show_home("browse")
    b = win.browse
    b.refresh()
    packs = list(win.session.base_manifest.packs)
    assert [t.info.pack.id for t in b.tiles] == packs
    assert b.pack_count.text() == f"{len(packs)} of {len(packs)} modpacks"
    tile = b.tiles[0]
    assert tile.info.pack.name in labels(tile) and any(t.endswith(" mods") for t in labels(tile))
    b.gpu_only.setChecked(True)                    # the test PC has no RTX 50: Max is filtered out
    assert "max-rtx50" not in [t.info.pack.id for t in b.tiles]
    b.gpu_only.setChecked(False)
    b.free_only.setChecked(True)
    assert all(not t.info.paid for t in b.tiles)
    b.free_only.setChecked(False)
    b.edition.setCurrentIndex(b.edition.findData("legacy"))   # the other edition's packs, marked as not your game
    assert b.tiles and all(t.info.edition == "legacy" for t in b.tiles)
    b.tiles[0].clicked.emit()
    assert win.stack.currentWidget() is win.pack_page and win.pack_page.action_kind == "none"
    assert win.pack_page.main_btn.text() == "Not for your game"


def test_mods_browser_search_categories_and_drawer(make_win, dialogs):  # noqa: F811
    win = make_win()
    b = win.browse
    win.show_home("browse")
    b.tabs.setCurrentIndex(1)
    b.refresh()
    total = b.mod_count
    assert total == len([m for m in win.session.manifest.mods.values() if m.tier != "custom"])
    b.search.setText("chiheb")                         # an author: both of their mods
    assert {r.mod.id for r in b.rows} == {"shvdne", "straighttostory"}
    b.search.setText("script hook v .net")             # names: the mod and LemonUI "(for Script Hook V .NET)"
    assert {r.mod.id for r in b.rows} == {"shvdne", "lemonui"}
    b.search.clear()
    framework = next(btn for btn in b.cats.buttons() if btn.text() == "Framework")
    framework.click()
    assert b.rows and all(r.mod.layer == "Framework" for r in b.rows)
    b.mine_only.setChecked(True)
    mine = {m.id for m in win.session.mods()}
    assert all(r.mod.id in mine for r in b.rows)
    b.rows[0].clicked.emit()
    assert b.drawer.isVisibleTo(win) and b.drawer.mod is b.rows[0].mod
    assert b.rows[0].mod.name in labels(b.drawer)
    b.search.setText("no such mod at all")
    assert b.rows == [] and "No mods match" in labels(b)


# ----------------------------------------------------------------------------------------------- pack page
def test_pack_page_actions_follow_the_state(make_win, dialogs, downloads, monkeypatch):  # noqa: F811
    win = make_win()
    s = win.session
    page = win.pack_page
    other = next(p for p in s.base_manifest.packs if p != (s.pack_choice().pack or s.base_manifest.default_pack))
    win.open_pack(other)
    assert win.stack.currentWidget() is page and page.action_kind == "use"
    switched = []
    monkeypatch.setattr(win.pages[2], "switch", lambda pid, *a, **k: switched.append(pid) or True)
    page.main_btn.click()
    assert switched == [other]
    s.choose_pack("core")
    win.open_pack("core")
    assert page.action_kind == "get" and page.main_btn.text().startswith("Get the files (")
    page.main_btn.click()
    assert win.stack.currentIndex() == 3                            # the Get mods step
    monkeypatch.setattr(L, "pack_info", _fake_info(L.pack_info, ready=True))
    page.set_pack("core")
    assert page.action_kind == "install" and page.main_btn.text().startswith("Install (")
    page.main_btn.click()
    assert win.stack.currentIndex() == 5
    monkeypatch.setattr(L, "pack_info", _fake_info(L.pack_info, ready=True, installed=True))
    page.set_pack("core")
    played = []
    monkeypatch.setattr(win, "play", lambda: played.append(1))
    assert page.action_kind == "play" and page.main_btn.text() == "Play"
    page.main_btn.click()
    assert played == [1]


def _fake_info(real, ready=False, installed=False):
    def info(win, pid, edition=None):
        i = real(win, pid, edition)
        if ready:
            i.ready = len(i.mods)
        if installed:
            i.installed = len([m for m in i.mods if not getattr(m, "unsupported", None)])
        return i
    return info


def test_pack_page_tabs(make_win, dialogs):  # noqa: F811
    win = make_win()
    s = win.session
    pid = next(p.id for p in s.base_manifest.packs.values() if p.variants)
    s.choose_pack(pid)
    win.open_pack(pid)
    page = win.pack_page
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Overview", "Mods", "Variants && settings", "Screenshots", "Files && logs"]
    mods = s.mods()
    assert page.mod_rows == [] and page._tab_keys == {0: page._key}  # a tab is built when it is opened
    page.tabs.setCurrentIndex(1)
    assert [r.mod.id for r in page.mod_rows] == [m.id for m in mods]
    pack = s.base_manifest.packs[pid]
    page.tabs.setCurrentIndex(2)
    assert set(page.variant_buttons) == {v.id for v in pack.variants}
    assert page.variant_buttons[pack.variant(None).id].isChecked()
    last = pack.variants[-1].id
    picked = []
    win.pages[2].pick_variant = lambda vid: picked.append(vid)
    page.variant_buttons[last].setChecked(True)
    assert picked == [last]
    page.tabs.setCurrentIndex(3)
    assert len(page.shots) == len([m for m in mods if m.image or m.page])
    page.tabs.setCurrentIndex(4)
    assert "INSTALL LOG" in labels(page.files_tab) and "DOWNLOADS" in labels(page.files_tab)
    page.tabs.setCurrentIndex(1)
    if page.toggles:                                                  # an add-on mod can be switched off here
        mid, box = next(iter(page.toggles.items()))
        calls = []
        win.pages[2].toggle_addon = lambda a, on: calls.append((a, on))
        box.setChecked(not box.isChecked())
        assert calls and calls[0][1] == box.isChecked()


def test_overview_reads_what_you_will_notice():
    items = L.notice_for("Leonida Showcase (GTA VI)")
    assert items, "docs/GTA6-EXPERIENCE.md section 3"
    assert any("HUD" in i for i in items)                      # from Core, through Plus
    assert any("Burger Shot" in i for i in items)              # Showcase's own
    assert len(L.notice_for("Leonida Core")) < len(items)
    assert L.notice_for("No such pack") == []
    assert all("**" not in i for i in items)


def test_summary_and_sizes():
    assert L.summary_of("One. Two.") == "One."
    assert L.summary_of("x" * 300, 20).endswith("…") and len(L.summary_of("x" * 300, 20)) == 20
    assert L.size_text(0) == "not downloaded" and L.size_text(500) == "1 KB" and L.size_text(5 << 20) == "5 MB"
    assert L.size_text(3 << 30) == "3.0 GB"


# ------------------------------------------------------------------------------------- home, bar and Play
def test_home_after_the_first_run_is_the_pack_page(make_win, dialogs):  # noqa: F811
    first = make_win()
    assert first.stack.currentWidget() is first.pages[0]            # no pack chosen yet: the wizard
    first.session.choose_pack("core")
    again = make_win()
    again.session.choose_pack("core")
    win = type(again)(again.session)
    try:
        assert win.stack.currentWidget() is win.pack_page
        assert win.home_nav.state(1) == "current" and win.nav.currentRow() == -1
        win.go(3)                                                    # a setup step again
        assert win.home_nav.currentRow() == -1 and win.nav.state(3) == "current"
        win.home_nav.setCurrentRow(0)
        assert win.stack.currentWidget() is win.browse
    finally:
        win.close()
        win.deleteLater()


def test_bottom_bar_and_play(make_win, dialogs, game, monkeypatch):  # noqa: F811
    win = make_win()
    bar = win.bottom
    bar.refresh()
    assert bar.game.text().startswith("GTA V Enhanced") and bar.play_btn.isEnabled()
    win.play()                                         # no PlayGTAV.exe: the game's own exe starts it too
    assert win.statusBar().currentMessage().startswith("Would start GTA5_Enhanced.exe")
    (game / "PlayGTAV.exe").write_bytes(b"MZ")
    win.play()
    assert win.statusBar().currentMessage().startswith("Would start PlayGTAV.exe")   # opening is off in tests
    monkeypatch.delenv("LEONIDA_NO_OPEN")
    started = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: started.append(a))
    win.play()
    assert started and win.statusBar().currentMessage().startswith("Starting PlayGTAV.exe")
    win.pages[3].busy = {"x": "downloading 10%"}
    bar.refresh_work()
    assert bar.work.text() == "Downloading 1 mod…" and bar.bar.isVisibleTo(win)
    win.pages[3].busy = {}
    bar.refresh_work()
    assert bar.work.text() == "Starting GTA V…" and bar.play_btn.text() == "Starting…"   # until the game shows up
    bar.watch.state = "idle"
    bar.show_play()
    assert not bar.work.isVisibleTo(win) and bar.play_btn.text() == "Play"


def test_play_offers_to_bring_mods_back_after_online_safe(make_win, dialogs, game, monkeypatch):  # noqa: F811
    from leonida.onlinesafe import go_online_safe

    (game / "PlayGTAV.exe").write_bytes(b"MZ")
    (game / "ScriptHookV.dll").write_text("shv")
    win = make_win()
    go_online_safe(game, win.session.manifest.online_safe_items)
    assert not (game / "ScriptHookV.dll").exists()
    win.play()
    assert any("Bring them back" in t for t in dialogs.texts("question"))
    assert (game / "ScriptHookV.dll").exists()


# ------------------------------------------------------------------------------------------------ pictures
def test_cached_pictures_show_without_network(make_win, dialogs, tmp_path):  # noqa: F811
    win = make_win()
    s = win.session
    mod = next(m for m in s.mods() if m.image)
    import hashlib

    cache = s.state / "images"
    cache.mkdir(parents=True, exist_ok=True)
    pm = QPixmap(64, 36)
    pm.fill(QColor("red"))
    path = cache / (hashlib.sha1(mod.image.encode()).hexdigest() + ".png")
    pm.save(str(path))
    assert win.images.cached(mod.image, None) == str(path)
    page_only = cache / (hashlib.sha1(b"https://img.example/p.png").hexdigest() + ".png")
    pm.save(str(page_only))
    win.images.index["https://page.example/"] = "https://img.example/p.png"
    assert win.images.cached(None, "https://page.example/") == str(page_only)
    art = L.thumb(64, 36, mod.id)
    win.pictures.bind_mod(art, mod)                       # LEONIDA_NO_NET is set: it comes from the cache
    wait_until(lambda: art.pixmap is not None)            # decoded on a pool thread, shown on the UI thread
    assert not art.pixmap.isNull()


def test_every_mod_list_shows_pictures(make_win, dialogs, downloads):  # noqa: F811
    win = make_win()
    s = win.session
    make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "shv"})
    win.pages[5].refresh()
    stepper = win.pages[5].stepper_box.itemAt(0).widget()
    assert stepper.rows and all(r.art is not None for r in stepper.rows)
    win.pages[3].refresh()
    assert all(row.art is not None for row in win.pages[3].rows.values())
    s.log.new_step("scripthookv", "copy").status = "done"
    win.pages[6].refresh()
    from leonida.gui.widgets import Art

    assert win.pages[6].findChildren(Art)
    pid = next(p.id for p in s.base_manifest.packs.values() if p.variants)
    s.choose_pack(pid)
    win.pages[2].edition_changed()
    card = next(iter(win.pages[2].addon_cards.values()))
    assert card.findChildren(Art)                         # the add-on's mods as pictures
