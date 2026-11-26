"""Settings > Graphics (values with their source, the measured video memory, Tune for this PC with progress and
Stop, Reset to recommended), Manage > Installed (on and checked in game / not confirmed, Check in game, mods off on
this game build with Turn on anyway) and the Library's health line. No real game: play tests and the tune are fakes;
GTA's settings.xml lives in the tests' own Documents folder (conftest)."""
from __future__ import annotations

import copy
import dataclasses
import json
import threading
import time
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("PySide6")

from test_gui_pages import SB, dialogs, make_win, qapp, wait_idle, wait_until  # noqa: E402,F401  (fixtures)

from leonida import gamesettings as G  # noqa: E402
from leonida import tune as T  # noqa: E402
from leonida.gui import graphics as GR  # noqa: E402
from leonida.gui import health as H  # noqa: E402
from leonida.log import InstallLog  # noqa: E402

GTX1070 = G.PC(15.8, 8.0, ("NVIDIA GeForce GTX 1070",))


def install(s, *mods: str) -> None:
    log = InstallLog(s.state / "install-log.json")
    for mid in mods:
        log.new_step(mid, "copy").status = "done"
    log.save()
    s.log = InstallLog(s.state / "install-log.json")


def checked(s, data: dict) -> None:
    p = s.state / "ingame" / "checked.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def last_report(s, status="passed", peak=None, when="2026-11-26 18:40:00", message="ok") -> None:
    p = s.state / "playtest" / "last-report.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    mem = {"peak": {"gpu_used_mb": peak}} if peak is not None else {}
    p.write_text(json.dumps({"when": when, "status": status, "message": message, "memory": mem}), encoding="utf-8")


def texts(w) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [lab.text() for lab in w.findChildren(QLabel)]


@pytest.fixture
def win(dialogs, make_win, monkeypatch):  # noqa: F811
    w = make_win()
    monkeypatch.setattr(w.session, "pc_specs", lambda: GTX1070)
    yield w
    for key in ("settings_page",):
        page = w.peek_page(key)
        if page is not None:
            wait_idle(page, page.graphics)


# ------------------------------------------------------------------------------------------------- Graphics
def test_graphics_shows_each_value_with_its_source_and_the_vram_peak(win):
    s = win.session
    card = win.settings_page.graphics
    card.refresh(force=True)
    text = card.values.text()
    assert "Texture quality: 2  ·  GPU tier top" in text and "(Leonida sets these after your first install.)" in text
    assert "not measured yet" in card.vram.text() and not card.reset_btn.isEnabled()
    install(s, "scripthookv")
    T.save_tuned(s.state, {"graphics/MaxLodScale/@value": "0.500000"})
    last_report(s, peak=4300)
    card.refresh(force=True)
    text = card.values.text()
    assert "0.500000  ·  tuned on this PC" in text and "after your first install" not in text
    assert card.vram.text() == "Video memory peak: 4.2 GB of 8.0 GB, measured in the play test on 2026-11-26 18:40:00."
    assert card.reset_btn.isEnabled() and "1 value(s) tuned" in card.reset_btn.toolTip()
    assert GR.short_source("your graphics card (high tier, 6 GB)") == "GPU tier high"
    assert GR.short_source("variant ram16") == "variant ram16"


def test_reset_to_recommended_forgets_the_tuned_values_and_writes_the_rest(win, dialogs, monkeypatch):  # noqa: F811
    s = win.session
    install(s, "scripthookv")
    T.save_tuned(s.state, {"graphics/MaxLodScale/@value": "0.500000"})
    writes = []
    monkeypatch.setattr(s, "apply_game_settings", lambda ui, dry_run=False: writes.append(ui) or ["settings.xml"])
    card = win.settings_page.graphics
    card.refresh(force=True)
    dialogs.answer = SB.No
    assert card.reset() is False and T.load_tuned(s.state)
    dialogs.answer = SB.Yes
    assert card.reset() is True
    assert T.load_tuned(s.state) == {} and len(writes) == 1
    assert "tuned on this PC" not in card.values.text() and not card.reset_btn.isEnabled()
    assert "Back to the recommended" in win.notifications.items[0].text
    assert json.loads((s.state / T.TUNED_FILE).read_text())["values"] == {}


def _ready_for_tune(win, monkeypatch):
    s = win.session
    install(s, "scripthookv")
    current = G.wanted("enhanced", "owner-pick", "ram16", {"hud-geckomacabre"}, GTX1070)
    monkeypatch.setattr(s, "game_settings", lambda: current)
    plays = []

    def fake_playtest(sess, **k):
        plays.append(k)
        return NS(ok=True, status="passed", memory={"peak": {"gpu_used_mb": 5100.0}})

    monkeypatch.setattr("leonida.playtest.playtest", fake_playtest)
    return s, plays


def test_tune_runs_in_the_background_with_progress_and_stops_on_request(win, dialogs, monkeypatch):  # noqa: F811
    s, plays = _ready_for_tune(win, monkeypatch)
    card = win.settings_page.graphics
    gate = threading.Event()

    def fake_tune(sess, run_test, progress, stop, **k):
        runs = []
        for key, value in (("graphics/MaxLodScale/@value", "0.250000"), ("graphics/CityDensity/@value", "0.900000")):
            if stop():
                progress("stopped")
                break
            progress(f"{key.split('/')[1]} = {value}: 1 play test(s) ...")
            rep = run_test(sess)
            progress("kept")
            runs.append(T.TuneRun(key, value, rep.status, 5100.0, 8192.0, None, True))
            gate.wait(10)                      # the test presses Stop meanwhile
        return runs

    monkeypatch.setattr(T, "tune", fake_tune)
    dialogs.answer = SB.No
    assert card.tune_or_stop() is False and not card.running
    dialogs.answer = SB.Yes
    assert card.tune_or_stop() is True and card.running
    assert card.tune_btn.text() == "Stop the tune" and not card.reset_btn.isEnabled()
    assert "the settings tune is running" in win.settings_page._busy()
    wait_until(lambda: "Step 1 of" in card.progress.text() and "video memory peak 5.0 GB" in card.progress.text())
    assert "MaxLodScale = 0.250000" in card.progress.text() and "play test 1" in card.progress.text()
    assert card.tune_or_stop() is True                       # Stop
    assert "Stopping after this play test" in card.progress.text() and not card.tune_btn.isEnabled()
    gate.set()
    wait_until(lambda: not card.running)
    assert card.progress.text().startswith("Tune stopped: 1 of 1 step(s) kept.") and len(plays) == 1
    assert card.tune_btn.text() == "Tune for this PC" and card.tune_btn.isEnabled()
    assert "Tune stopped" in win.notifications.items[0].text


def test_the_real_tune_stops_before_the_next_step(tmp_path, monkeypatch):
    """tune.tune(stop=...): asked before each step; what was kept so far stays."""
    from test_tune import _FakeSession, _Report

    s = _FakeSession(tmp_path)
    calls = []

    def run_test(sess):
        calls.append(1)
        return _Report("passed", {"peak": {"gpu_used_mb": 3000}})

    runs = T.tune(s, run_test=run_test, stop=lambda: len(calls) >= 2)
    assert len(runs) == 2 and all(r.kept for r in runs)
    assert len(T.load_tuned(tmp_path)) >= 1


def test_tune_refuses_without_an_install_and_reports_a_failure(win, dialogs, monkeypatch):  # noqa: F811
    card = win.settings_page.graphics
    assert card.start_tune() is False
    assert any("Install your pack first" in t for k, t in dialogs.calls if k == "information")
    _ready_for_tune(win, monkeypatch)

    def broken(*a, **k):
        raise ValueError("Leonida can't read this graphics card's video memory")

    monkeypatch.setattr(T, "tune", broken)
    assert card.start_tune() is True
    wait_until(lambda: not card.running)
    assert "video memory" in card.progress.text()
    assert any("couldn't go on" in t for k, t in dialogs.calls if k == "warning")


# ------------------------------------------------------------------------------------------------- Manage
def test_installed_rows_say_checked_in_game_with_the_reason(win):
    s = win.session
    install(s, "scripthookv", "shvdne", "straighttostory")
    checked(s, {"scripthookv": {"ok": True, "at": time.time(), "checks": ["In game: ScriptHookV.dll loaded."]},
                "shvdne": {"ok": False, "at": time.time(), "checks": [],
                           "failed": ["In game: Script Hook V .NET's scripts folder: no."]}})
    page = win.pages[6]
    page.refresh()
    lines = [lab.text() for lab in page.installed.findChildren(type(page.state)) if lab.objectName() == "ingameChecked"]
    assert "✓ on and checked in game" in lines
    assert "! not confirmed in game: In game: Script Hook V .NET's scripts folder: no." in lines
    assert "not checked in game yet" in lines
    assert page.ingame_summary.text().startswith("In game: 1 on and checked · 1 not confirmed · 1 not checked")
    assert page.check_ingame_btn.isVisible() or not page.isVisible()


def test_check_in_game_runs_the_deep_play_test(win, dialogs, monkeypatch):  # noqa: F811
    s = win.session
    install(s, "scripthookv")
    seen = []

    def fake_playtest(sess, **k):
        seen.append(k)
        return NS(ok=True, status="passed", message="ok", timeline=[], results=[], notes=[], evidence=[],
                  story_mode_after=60.0, verdict=lambda: "PASSED")

    monkeypatch.setattr("leonida.playtest.playtest", fake_playtest)
    monkeypatch.setattr(win.pages[6].playtest.panel, "show_report", lambda r: None)
    page = win.pages[6]
    page.refresh()
    assert page.check_in_game() is True
    wait_until(lambda: page.playtest.thread is None)
    assert seen and seen[0]["deep"] is True and page.tabs.currentIndex() == 1
    assert "Leonida's menu checks each mod" in [t for k, t in dialogs.calls if k == "question"][-1]
    page.playtest.start_btn.click()                          # the plain button stays a normal play test
    wait_until(lambda: page.playtest.thread is None)
    assert "deep" not in seen[-1]


def _off_on_build(win):
    s = win.session
    mine = {m.id for m in s.mods()}
    mid = next(m.id for m in s.manifest.mods.values() if m.tier == "optional" and m.id not in mine)
    s.config.add = [mid]
    base = copy.copy(s.base_manifest)
    base.mods = dict(base.mods)
    base.mods[mid] = dataclasses.replace(base.mods[mid], min_game_build="1.0.9999.0")
    s.base_manifest = base
    return mid


def test_mods_off_on_this_build_are_greyed_and_can_be_turned_on_anyway(win, dialogs, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMessageBox

    s = win.session
    mid = _off_on_build(win)
    page = win.pages[6]
    page.refresh()
    assert mid in page.off_rows and mid not in {m.id for m in s.mods()}
    row = texts(page.off_rows[mid])
    assert any("needs game build 1.0.9999.0" in t for t in row)
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    asked = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: asked.append(a[2]) or next(answers)))
    assert page.set_on_anyway(mid, True) is False and s.config.on_anyway == []
    assert page.set_on_anyway(mid, True) is True and s.config.on_anyway == [mid]
    assert "may crash the game" in asked[-1]
    assert mid in {m.id for m in s.mods()}                   # in the selection now: Get mods / Install see it
    page.refresh()
    assert any("turned on anyway" in t for t in texts(page.off_rows[mid]))
    f = [x for x in s.findings(force=True) if x.mod == mid and x.code == "build-unsupported"]
    assert f and f[0].level == "warning" and "turned on anyway" in f[0].message   # not a blocking error
    from leonida.paths import Config

    assert Config.load(s.state).on_anyway == [mid]
    assert page.set_on_anyway(mid, False) is True and s.config.on_anyway == []
    assert mid not in {m.id for m in s.mods()}


# ------------------------------------------------------------------------------------------------- Library
def test_the_health_line(win, monkeypatch):
    from leonida import gamestate as GS

    s = win.session
    mods = s.mods()
    h = H.health(s, mods, s.profile_id, free_mb=12 * 1024)
    assert h.parts == ["No mods on yet"] and h.tone == "info"
    install(s, "scripthookv", "shvdne")
    checked(s, {"scripthookv": {"ok": True, "at": 1}, "shvdne": {"ok": False, "at": 1, "failed": ["x"]}})
    last_report(s, "passed")
    h = H.health(s, mods, s.profile_id, free_mb=12 * 1024)
    n = len([m for m in mods if not m.unsupported])
    assert h.parts[:3] == [f"2 of {n} mods on, 1 checked in game", "1 not confirmed in game",
                           "last play test passed (11/26 18:40)"]
    assert h.tone == "warning"
    checked(s, {"scripthookv": {"ok": True, "at": 1}})
    GS.record_session(s.state, s.profile_id, 0, 30, GS.BEFORE_STORY)
    h = H.health(s, mods, s.profile_id, free_mb=3 * 1024)
    assert "last game start closed before story mode (a crash?)" in h.parts
    assert "only 3.0 GB of RAM free" in h.parts and h.tone == "warning"
    GS.record_session(s.state, s.profile_id, 0, 900, GS.STORY)
    h = H.health(s, mods, s.profile_id, free_mb=12 * 1024)
    assert h.tone == "success" and h.text.startswith(f"2 of {n} mods on, 1 checked in game")


def test_the_health_card_is_the_librarys_first_card(win, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_FREE_MB", str(2 * 1024))
    s = win.session
    install(s, "scripthookv")
    win.open_pack(s.pack_choice().pack or s.base_manifest.default_pack)
    page = win.pack_page
    page.tabs.setCurrentIndex(0)
    page.refresh(force=True)
    first = page.overview.layout().itemAt(0).widget()
    assert first.objectName() == "healthCard"
    line = first.findChild(type(page.name), "healthLine").text()
    assert line.startswith("⚠ 1 of ") and "only 2.0 GB of RAM free" in line and "no play test yet" in line
    last_report(s, "crashed", message="It crashed")
    page.refresh()                                           # a new play test result rebuilds it
    line = page.overview.layout().itemAt(0).widget().findChild(type(page.name), "healthLine").text()
    assert "last play test crashed" in line
