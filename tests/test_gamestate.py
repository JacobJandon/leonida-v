"""The launcher's game state: Playing / Stop, play time per pack, and the notice when GTA V closes before story mode
(leonida/gamestate.py and the bottom bar). The real game is never started or looked for."""
from __future__ import annotations

import os
import time

import pytest

from leonida import gamestate as GS


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


# ------------------------------------------------------------------------------------------- the engine
def test_watch_play_starting_playing_ended():
    c = Clock()
    w = GS.GameWatch(c)
    assert w.poll([]) is None and w.state == "idle"
    w.starting()
    assert w.state == "starting"
    c.t += 20
    assert w.poll([], launcher_running=True) is None and w.state == "starting"
    assert w.poll(["GTA5_Enhanced.exe"]) == ("started", None) and w.state == "playing"
    c.t += 65
    assert w.poll(["GTA5_Enhanced.exe"]) is None and round(w.elapsed()) == 65
    assert w.poll([]) == ("ended", (1020.0, 1085.0)) and w.state == "idle"


def test_watch_sees_a_game_started_elsewhere_and_gives_up_on_a_play_that_never_came():
    c = Clock()
    w = GS.GameWatch(c)
    assert w.poll(["GTA5.exe"]) == ("started", None)          # started from Steam / the Rockstar launcher
    assert w.names == ["GTA5.exe"]
    assert w.poll([])[0] == "ended"
    w.starting()
    c.t += GS.START_TIMEOUT + 1
    assert w.poll([], launcher_running=True) is None          # the launcher still works on it
    assert w.poll([]) == ("gave-up", None) and w.state == "idle"


def test_running_reads_a_listing():
    procs = {"explorer.exe", "gta5_enhanced.exe", "playgtav.exe"}
    assert GS.running(listing=procs) == ["GTA5_Enhanced.exe"]
    assert GS.running(GS.LAUNCHER_EXES, procs) == ["PlayGTAV.exe"]
    assert GS.running(listing=set()) == []


def test_process_names_is_stubbed_in_tests():
    assert GS.process_names() == set()                        # conftest: no real process list


def test_story_mode_from_the_script_hook_v_net_log(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    started = time.time()
    assert GS.story_reached(game, started) is None            # no log: can't tell
    log = game / GS.SHVDN_LOG
    log.write_text("[12:00:01] [INFO] Initializing\n", encoding="utf-8")
    assert GS.story_reached(game, started) is False           # written this session, no scripts loaded yet
    assert GS.ended_how(game, started, started + 400) == GS.BEFORE_STORY
    log.write_text("[12:00:01] [INFO] Loading scripts from C:\\game\\scripts\n", encoding="utf-8")
    assert GS.story_reached(game, started) is True
    assert GS.ended_how(game, started, started + 30) == GS.STORY
    old = started - 3600
    os.utime(log, (old, old))
    assert GS.story_reached(game, started) is None            # an old log says nothing about this session
    assert GS.ended_how(game, started, started + 30) == GS.BEFORE_STORY     # short: closed early
    assert GS.ended_how(game, started, started + 600) == GS.UNKNOWN
    assert GS.ended_how(None, started, started + 600) == GS.UNKNOWN


def test_play_time_per_pack(tmp_path):
    assert GS.stats_for(tmp_path, "core").sessions == 0
    GS.record_session(tmp_path, "core", 0, 1800, GS.STORY)
    st = GS.record_session(tmp_path, "core", 5000, 5600, GS.BEFORE_STORY)
    assert st.sessions == 2 and st.total_seconds == 2400 and st.last_seconds == 600 and st.last_end == GS.BEFORE_STORY
    assert GS.stats_for(tmp_path, "core").total_seconds == 2400
    assert GS.stats_for(tmp_path, "plus").sessions == 0
    (tmp_path / GS.STATS_NAME).write_text("not json", encoding="utf-8")
    assert GS.load_stats(tmp_path) == {}


def test_durations_and_when():
    assert GS.duration(12) == "12 s" and GS.duration(420) == "7 min" and GS.duration(3900) == "1 h 05 min"
    assert GS.clock(42) == "0:42" and GS.clock(725) == "12:05" and GS.clock(3723) == "1:02:03"
    now = time.mktime((2026, 11, 25, 20, 0, 0, 0, 0, -1))
    from datetime import datetime, timezone

    def iso(t):
        return datetime.fromtimestamp(t, timezone.utc).isoformat()

    assert GS.when(iso(now - 60), now).startswith("today ")
    assert GS.when(iso(now - 86400), now) == "yesterday"
    assert GS.when(iso(now - 3 * 86400), now) == "3 days ago"
    assert GS.when(iso(now - 30 * 86400), now).startswith("2026-10-")
    assert GS.when(None) == "never" and GS.when("garbage") == "never"


# ------------------------------------------------------------------------------------------- the bar
pytest.importorskip("PySide6")


from test_gui_pages import dialogs, make_win, qapp  # noqa: E402,F401  (fixtures)


@pytest.fixture
def win(make_win):  # noqa: F811
    return make_win()


def test_bar_playing_stop_and_the_crash_notice(win, monkeypatch, dialogs):  # noqa: F811
    from leonida.gui import launcher as L

    bar = win.bottom
    c = Clock(time.time())
    bar.watch = GS.GameWatch(c)
    bar.polled(set())
    assert bar.play_btn.text() == "Play"
    bar.watch.starting()
    bar.show_play()
    assert bar.play_btn.text() == "Starting…" and not bar.play_btn.isEnabled()
    assert "Starting GTA V" in bar.work.text()
    bar.polled({"gta5_enhanced.exe"})
    assert bar.play_btn.text() == "Stop" and bar.play_btn.isEnabled()
    c.t += 42
    bar.refresh_work()
    assert bar.work.text() == "Playing · 0:42"
    stopped = []
    monkeypatch.setattr(L, "stop_game", lambda w: stopped.append(1) or "closing")
    win.play()                                               # the button stops the game while it runs
    assert stopped == [1]
    bar.polled(set())                                        # gone after 42 s, no proof of story mode
    assert bar.play_btn.text() == "Play"
    note = win.notifications.items[0]
    assert "before story mode" in note.text and note.action == "Check the game's logs"
    checked = []
    monkeypatch.setattr(win.pages[6], "check_logs", lambda: checked.append(1))
    win.toast.action_clicked.emit()
    assert checked == [1] and win.stack.currentIndex() == 6
    st = GS.stats_for(win.session.state, win.session.pack_choice().pack)
    assert st.sessions == 1 and round(st.total_seconds) == 42 and st.last_end == GS.BEFORE_STORY
    win.update_sidebar()
    assert "played 42 s" in bar.pack.text()


def test_a_long_session_notes_the_play_time_and_minimises(win, monkeypatch):
    from leonida.gui import launcher as L

    win.session.config.on_game_start = "minimise"
    mins = []
    monkeypatch.setattr(win, "showMinimized", lambda: mins.append(1))
    L.game_event(win, "started")
    assert mins == [1]
    now = time.time()
    L.game_event(win, "ended", (now - 3600, now))
    assert "played 1 h 00 min" in win.notifications.items[0].text
    L.game_event(win, "gave-up")
    assert "didn't open" in win.notifications.items[0].text


def test_stop_asks_first(win, dialogs):  # noqa: F811
    from PySide6.QtWidgets import QMessageBox

    from leonida.gui import launcher as L

    dialogs.answer = QMessageBox.StandardButton.No
    assert L.stop_game(win) == "GTA V keeps running."
    dialogs.answer = QMessageBox.StandardButton.Yes
    assert L.stop_game(win).startswith("Would close")       # LEONIDA_NO_OPEN in tests: nothing is killed


def test_settings_when_the_game_starts(win):
    page = win.settings_page
    page.refresh()
    assert page.on_start.currentData() == "stay"
    page.on_start.setCurrentIndex(page.on_start.findData("close"))
    assert win.session.config.on_game_start == "close"
