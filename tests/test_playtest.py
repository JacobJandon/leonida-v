"""Play test with a fake game folder, a fake process layer and a fake clock. Never starts the real game."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from leonida import playtest as P
from leonida.cli import main
from leonida.session import Session

SHV_OK = "[00:00:01] INIT: Registering script thread\nSCRIPT HOOK (build Nov 2026, v1.0.3889.0)\nsuccess, game version is 1.0.1013.20"
SHVDN_START = "[00:00:20] [INFO] ScriptHookV .Net Enhanced 3.7.0 (1.2.3)\n[00:00:21] [INFO] Initializing ..."
SHVDN_STORY = "\n[00:01:10] [INFO] Loading scripts from D:\\Game\\scripts ..."


@pytest.fixture(autouse=True)
def never_touch_real_processes(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to start or kill a real process")

    monkeypatch.setattr(P.ProcessOps, "start", refuse)
    monkeypatch.setattr(P.ProcessOps, "kill", refuse)


class FakeGame:
    """PlayGTAV.exe -> GTA5_Enhanced.exe on a fake clock. ``script``: [(seconds after launch, action), ...]."""

    def __init__(self, game: Path, script, running=(), deny_kill=False, start_error=None, events=()):
        self.game, self.script = game, sorted(script, key=lambda x: x[0])
        self.t, self.started_at = 1000.0, None
        self.procs = set(running)
        self.deny_kill, self.start_error, self.event_log = deny_kill, start_error, list(events)
        self.kills, self.starts, self.done = [], [], set()

    # clock
    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s
        self._fire()

    def _fire(self):
        if self.started_at is None:
            return
        for i, (at, action) in enumerate(self.script):
            if i not in self.done and self.t - self.started_at >= at:
                self.done.add(i)
                action(self) if callable(action) else self._act(action)

    def _act(self, action):
        g = self.game
        if action == "game":
            self.procs.add(P.GAME_EXE)
        elif action == "exit":
            self.procs.discard(P.GAME_EXE)
        elif action == "shv":
            (g / "ScriptHookV.log").write_text(SHV_OK)
        elif action == "shvdn":
            (g / "ScriptHookVDotNet.log").write_text(SHVDN_START)
        elif action == "story":
            with open(g / "ScriptHookVDotNet.log", "a") as fh:
                fh.write(SHVDN_STORY)
        elif action == "dump":
            (g / "GTA5_Enhanced_crash.dmp").write_bytes(b"MDMP")

    # ProcessOps
    def running(self, name):
        return [4242] if name in self.procs else []

    def kill(self, name):
        if self.deny_kill:
            return False, f'ERROR: The process "{name}" with PID 4242 could not be terminated. Reason: Access is denied.'
        self.kills.append(name)
        self.procs.discard(name)
        return True, "SUCCESS"

    def start(self, exe, cwd):
        self.starts.append((Path(exe), Path(cwd)))
        if self.start_error:
            raise self.start_error
        self.started_at = self.t
        self.procs.add(P.LAUNCHER)
        self._fire()

    def events(self, seconds):
        return list(self.event_log)


NORMAL = [(3, "game"), (12, "shv"), (25, "shvdn"), (70, "story")]


def make_session(tmp_path, game, installed=("scripthookv", "shvdne", "straighttostory")) -> Session:
    (game / "PlayGTAV.exe").write_bytes(b"MZ launcher")
    s = Session(tmp_path / "st", game_dir=str(game), game_build="1.0.1013.20")
    for mid in installed:
        step = s.log.new_step(mid, "copy")
        step.status, step.finished = "done", step.started
    s.log.save()
    return s


def run(s, fake, **kw):
    kw.setdefault("timeout", 300)
    return P.playtest(s, ops=fake, sleep=fake.sleep, clock=fake.clock, poll=2, settle=10, **kw)


# --------------------------------------------------------------------------------------------------- flows
def test_passed(tmp_path, game):
    s = make_session(tmp_path, game)
    (game / "ScriptHookV.log").write_text("old run")
    (game / "menyooLog.txt").write_text("old menyoo")
    fake = FakeGame(game, NORMAL, running=(P.GAME_EXE, P.LAUNCHER))
    seen = []
    rep = run(s, fake, progress=seen.append)
    assert rep.ok and rep.status == P.PASSED, rep.summary()
    assert fake.starts == [(game / "PlayGTAV.exe", game)]                     # the launcher, never GTA5_Enhanced.exe
    assert fake.kills[:2] == [P.GAME_EXE, P.LAUNCHER]                          # closed before the run
    prev = tmp_path / "st" / "playtest" / "previous"
    assert (prev / "ScriptHookV.log").read_text() == "old run" and (prev / "menyooLog.txt").exists()
    assert sorted(rep.moved_logs) == ["ScriptHookV.log", "menyooLog.txt"]
    assert not (game / "menyooLog.txt").exists() and not list(game.glob("*.prev"))  # nothing new in the game folder
    assert 69 <= rep.story_mode_after <= 73
    assert fake.procs == set()                                                  # closed afterwards
    assert any("Story mode loaded" in m for m in seen) and any("Closed the game" in m for m in seen)
    assert rep.notes == [] and rep.results


def test_keep_running(tmp_path, game):
    s = make_session(tmp_path, game)
    fake = FakeGame(game, NORMAL)
    rep = run(s, fake, keep_running=True)
    assert rep.ok and P.GAME_EXE in fake.procs and fake.kills == []
    assert any("Left the game running" in t for t in rep.timeline)


def test_crash_before_story(tmp_path, game):
    s = make_session(tmp_path, game)
    event = "Log Name: Application | Source: Application Error | Faulting application name: GTA5_Enhanced.exe"
    fake = FakeGame(game, [(3, "game"), (12, "shv"), (40, "dump"), (40, "exit")], events=[event])
    rep = run(s, fake)
    assert rep.status == P.CRASHED and not rep.ok and "before story mode" in rep.message
    ev = "\n".join(rep.evidence)
    assert "GTA5_Enhanced_crash.dmp" in ev and "Faulting application name: GTA5_Enhanced.exe" in ev
    assert "ScriptHookV.log: success, game version is 1.0.1013.20" in ev
    assert rep.results  # the logs were read too


def test_crash_while_settling(tmp_path, game):
    s = make_session(tmp_path, game)
    fake = FakeGame(game, [*NORMAL, (74, "exit")])
    rep = run(s, fake)
    assert rep.status == P.CRASHED and "right after story mode" in rep.message and rep.story_mode_after is not None


def test_hang_without_story_mode(tmp_path, game):
    s = make_session(tmp_path, game)
    fake = FakeGame(game, [(3, "game"), (12, "shv"), (25, "shvdn")])
    rep = run(s, fake, timeout=120)
    assert rep.status == P.HANG and "No story mode within 120 s" in rep.message and "Script Hook V loaded" in rep.message
    assert P.GAME_EXE not in fake.procs  # closed


def test_game_never_starts(tmp_path, game):
    s = make_session(tmp_path, game)
    fake = FakeGame(game, [])
    rep = run(s, fake, launch_timeout=60)
    assert rep.status == P.HANG and "didn't start within 60 s" in rep.message and "Rockstar launcher" in rep.message


def test_admin_game_blocks(tmp_path, game, monkeypatch):
    s = make_session(tmp_path, game)
    monkeypatch.setattr(P, "runasadmin_flag", lambda launcher: "HKCU")
    fake = FakeGame(game, NORMAL, running=(P.GAME_EXE,), deny_kill=True)
    rep = run(s, fake)
    assert rep.status == P.BLOCKED and "Close GTA yourself" in rep.message
    assert 'reg delete "HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion\\AppCompatFlags\\Layers"' in rep.message
    assert str(game / "PlayGTAV.exe") in rep.message and "Access is denied" in rep.evidence[0]
    assert fake.starts == []


def test_kill_that_does_not_stick_blocks(tmp_path, game):
    s = make_session(tmp_path, game)
    fake = FakeGame(game, NORMAL, running=(P.GAME_EXE,))
    fake.kill = lambda name: (True, "SUCCESS")  # says yes, process stays
    rep = run(s, fake, close_timeout=10)
    assert rep.status == P.BLOCKED and "Close GTA yourself" in rep.message and fake.starts == []


def test_start_needs_elevation(tmp_path, game):
    s = make_session(tmp_path, game)
    err = OSError("The requested operation requires elevation")
    err.winerror = 740
    rep = run(s, FakeGame(game, NORMAL, start_error=err))
    assert rep.status == P.BLOCKED and "administrator" in rep.message
    rep = run(s, FakeGame(game, NORMAL, start_error=OSError("bad exe")))
    assert rep.status == P.BLOCKED and "Couldn't start PlayGTAV.exe: bad exe" in rep.message


def test_without_story_mode_helpers(tmp_path, game):
    s = make_session(tmp_path, game, installed=("scripthookv",))
    fake = FakeGame(game, [(3, "game"), (12, "shv")])
    rep = run(s, fake)
    assert rep.ok, rep.summary()
    assert any("click Story Mode" in n for n in rep.notes) and any("Script Hook V .NET isn't installed" in n
                                                                   for n in rep.notes)
    assert 100 <= rep.story_mode_after <= 106  # SHV at 12 s + 90 s


def test_without_any_hook(tmp_path, game):
    s = make_session(tmp_path, game, installed=())
    rep = run(s, FakeGame(game, [(3, "game")]))
    assert rep.ok and 122 <= rep.story_mode_after <= 128


def test_mod_failure_is_failed(tmp_path, game):
    s = make_session(tmp_path, game)

    def bad_shv(fake):
        (fake.game / "ScriptHookV.log").write_text("SCRIPT HOOK (build x, v1.0.3889.0)\nFATAL: Unknown game version")

    fake = FakeGame(game, [(3, "game"), (12, bad_shv), (25, "shvdn"), (70, "story")])
    rep = run(s, fake)
    assert rep.status == P.FAILED and "mod check(s) failed" in rep.message


def test_blocked_without_game_or_launcher(tmp_path, game):
    s = Session(tmp_path / "st", game_build="1.0.1013.20")
    assert P.playtest(s, ops=FakeGame(game, [])).status == P.BLOCKED
    s = Session(tmp_path / "st2", game_dir=str(game), game_build="1.0.1013.20")
    rep = P.playtest(s, ops=FakeGame(game, []))
    assert rep.status == P.BLOCKED and "PlayGTAV.exe isn't in" in rep.message


# ------------------------------------------------------------------------------------------------- helpers
def test_parse_tasklist():
    text = ('"GTA5_Enhanced.exe","21052","Console","1","2,145,332 K"\r\n'
            '"gta5_enhanced.exe","300","Console","1","1 K"\r\n"other.exe","1","Console","1","1 K"\r\n')
    assert P.parse_tasklist(text, "GTA5_Enhanced.exe") == [21052, 300]
    assert P.parse_tasklist("INFO: No tasks are running which match the specified criteria.", "x.exe") == []


def test_parse_events():
    text = ("Event[0]\n  Log Name: Application\n  Source: Application Error\nDescription:\n"
            "Faulting application name: GTA5_Enhanced.exe, version: 1.0.1013.20\nException code: 0xc0000005\n"
            "Event[1]\n  Source: Application Error\nFaulting application name: python.exe\n")
    ev = P.parse_events(text, "GTA5_Enhanced.exe")
    assert len(ev) == 1 and "Exception code: 0xc0000005" in ev[0] and "python.exe" not in ev[0]


def test_crash_files(tmp_path, monkeypatch):
    game = tmp_path / "g"
    (game / "CrashDumps").mkdir(parents=True)
    local = tmp_path / "local" / "CrashDumps"
    local.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    old = game / "old.dmp"
    old.write_bytes(b"x")
    os.utime(old, (1, 1))
    (game / "CrashLog.txt").write_text("x")
    (game / "CrashDumps" / "any.dmp").write_bytes(b"x")
    (local / "GTA5_Enhanced.exe.123.dmp").write_bytes(b"x")
    (local / "notepad.exe.9.dmp").write_bytes(b"x")
    (game / "readme.txt").write_text("x")
    names = {p.name for p in P.crash_files(game, since=100)}
    assert names == {"CrashLog.txt", "any.dmp", "GTA5_Enhanced.exe.123.dmp"}


def test_admin_help_text(tmp_path):
    text = P.admin_help(tmp_path / "PlayGTAV.exe", "HKLM")
    assert text.startswith("GTA runs as administrator") and '"HKLM\\Software\\Microsoft' in text


@pytest.mark.skipif(sys.platform != "win32", reason="tasklist")
def test_real_running_lists_this_python():
    assert os.getpid() in P.ProcessOps().running(Path(sys.executable).name) or P.ProcessOps().running("python.exe")


def test_not_windows_refuses(tmp_path, game, monkeypatch):
    monkeypatch.setattr(P.sys, "platform", "linux")
    rep = P.playtest(make_session(tmp_path, game))
    assert rep.status == P.BLOCKED and "only runs on Windows" in rep.message


# ----------------------------------------------------------------------------------------------------- CLI
def test_cli_playtest(tmp_path, game, monkeypatch, capsys):
    calls = []

    def fake_playtest(session, timeout, keep_running, progress):
        calls.append((timeout, keep_running))
        progress("Started PlayGTAV.exe")
        return P.PlaytestReport(P.CRASHED, "The game closed 30 s after starting", evidence=["crash file: x.dmp"],
                                notes=["Straight To Story Mode isn't installed"])

    monkeypatch.setattr(P, "playtest", fake_playtest)
    rc = main(["--state-dir", str(tmp_path / "st"), "--game-dir", str(game), "playtest", "--timeout", "90",
               "--keep-running"])
    out = capsys.readouterr().out
    assert rc == 1 and calls == [(90.0, True)]
    assert "  Started PlayGTAV.exe" in out and "CRASHED: The game closed 30 s" in out and "evidence: crash file" in out
