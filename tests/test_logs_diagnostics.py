"""Leonida's log (leonida/logs.py), crash hooks, the events modules log, and the debug report
(leonida/diagnostics.py, `leonida report`), including what the report must never contain."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import threading
import zipfile
from pathlib import Path

import pytest
from conftest import AutoUI, make_zip

from leonida import diagnostics as D
from leonida import logs
from leonida.cli import main
from leonida.installer import Installer
from leonida.paths import Config
from leonida.session import Session


def text_of(state: Path) -> str:
    logs.shutdown()  # flushes and closes the files
    p = logs.log_dir(state) / logs.MAIN_LOG
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ------------------------------------------------------------------------------------------- the log
def test_setup_levels_files_and_rotation(tmp_path, monkeypatch):
    monkeypatch.delenv(logs.ENV, raising=False)
    logger = logs.setup(tmp_path)
    assert logger.level == logging.INFO and logs.main_log() == tmp_path / "logs" / "leonida.log"
    rot = next(h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
    assert (rot.maxBytes, rot.backupCount) == (2 * 1024 * 1024, 4)
    logging.getLogger("leonida.test").debug("hidden detail")
    logging.getLogger("leonida.test").info("visible event")
    text = text_of(tmp_path)
    assert "visible event" in text and "hidden detail" not in text and "debug mode off" in text
    logs.setup(tmp_path, debug=True)
    logging.getLogger("leonida.test").debug("now shown")
    assert "now shown" in text_of(tmp_path)


def test_debug_mode_sources(tmp_path, monkeypatch):
    monkeypatch.delenv(logs.ENV, raising=False)
    assert not logs.debug_wanted(tmp_path)
    monkeypatch.setenv(logs.ENV, "1")
    assert logs.debug_wanted(tmp_path)
    monkeypatch.delenv(logs.ENV)
    Config(debug=True).save(tmp_path)
    assert logs.debug_wanted(tmp_path) and logs.setup(tmp_path).level == logging.DEBUG
    (tmp_path / "config.json").write_text("{broken")
    assert not logs.debug_wanted(tmp_path)
    assert logs.debug_wanted(None, True) and not logs.debug_wanted(None)


def test_session_files_are_pruned(tmp_path):
    folder = logs.log_dir(tmp_path)
    folder.mkdir(parents=True)
    for i in range(12):
        (folder / f"session-2026010{i:02d}-000000-gui.log").write_text("old")
    logs.setup(tmp_path, session="gui window")
    logging.getLogger("leonida.gui").info("a click")
    logs.shutdown()
    sessions = sorted(folder.glob("session-*.log"))
    assert len(sessions) == logs.SESSIONS_KEPT
    assert logs.session_log() in sessions and "a click" in logs.session_log().read_text()
    assert "gui-window" in logs.session_log().name


def test_secrets_are_masked(tmp_path):
    for raw, gone in (("GET https://x.org/f?token=abc123&x=1", "abc123"), ("Authorization: Bearer eyJhbGciOiJIUzI1",
                      "eyJhbGciOiJIUzI1"), ("cookie=sessid998877", "sessid998877"), ('password: "hunter22"', "hunter22"),
                      ("nxm_key=QWERTY", "QWERTY"), ("api_key=zzz", "zzz")):
        assert gone not in logs.redact_secrets(raw) and "<redacted>" in logs.redact_secrets(raw), raw
    logs.setup(tmp_path)
    logging.getLogger("leonida.test").info("url %s", "https://h.example/a?sid=SECRET42")
    text = text_of(tmp_path)
    assert "SECRET42" not in text and "sid=<redacted>" in text
    assert logs.host("https://user:pw@www.gta5-mods.com/a/b?c=d") == "www.gta5-mods.com"
    assert logs.host(None) == "?" and logs.host("http://[bad") == "?"


def test_read_only_state_still_works(tmp_path, monkeypatch):
    blocked = tmp_path / "file-not-folder"
    blocked.write_text("x")
    logger = logs.setup(blocked)  # <state>/logs can't be made: no log, but no crash
    assert logs.main_log() is None and logger.handlers


def test_excepthooks_log_and_report(tmp_path, capsys):
    logs.setup(tmp_path)
    seen = []
    logs.install_excepthooks(on_crash=seen.append)
    try:
        raise ValueError("boom token=SECRET")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    assert seen and "ValueError: boom" in seen[0] and "SECRET" not in seen[0] and "Log:" in seen[0]
    t = threading.Thread(target=lambda: 1 / 0, name="worker-x")
    t.start()
    t.join()
    assert any("thread worker-x" in s for s in seen)
    text = text_of(tmp_path)
    assert "CRITICAL" in text and "Unhandled exception in thread worker-x" in text and "ZeroDivisionError" in text
    # without a dialog: the default hook prints, plus where the log is
    logs.setup(tmp_path)
    logs.install_excepthooks(on_crash=None)
    try:
        raise RuntimeError("plain")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    err = capsys.readouterr().err
    assert "RuntimeError: plain" in err and "logged the details in" in err
    # a failing dialog still leaves the crash visible
    logs.install_excepthooks(on_crash=lambda text: 1 / 0)
    try:
        raise KeyError("k")
    except KeyError:
        sys.excepthook(*sys.exc_info())
    assert "KeyError" in capsys.readouterr().err
    logs.uninstall_excepthooks()
    assert sys.excepthook is not logs._excepthook


def test_keyboard_interrupt_is_not_a_crash(tmp_path):
    logs.setup(tmp_path)
    seen = []
    logs.install_excepthooks(on_crash=seen.append)
    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        sys.excepthook(*sys.exc_info())
    assert seen == []


# ------------------------------------------------------------------------------------------- the CLI
def test_cli_logs_commands_and_debug(tmp_path, monkeypatch):
    monkeypatch.delenv(logs.ENV, raising=False)
    state = tmp_path / "st"
    assert main(["--state-dir", str(state), "--debug", "keys"]) in (0, 1)
    text = text_of(state)
    assert "command: leonida --state-dir" in text and " keys" in text and "debug mode on" in text
    assert "exit code" in text


def test_cli_unhandled_exception_points_to_the_log(tmp_path, monkeypatch, capsys):
    from leonida import cli

    def boom(ctx):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(cli, "cmd_check", boom)
    with pytest.raises(RuntimeError):
        main(["--state-dir", str(tmp_path / "st"), "check"])
    assert "logged the details in" in capsys.readouterr().err
    text = text_of(tmp_path / "st")
    assert "Unhandled exception" in text and "RuntimeError: unexpected" in text


# ------------------------------------------------------------------------------------------- module events
def test_installer_and_rollback_are_logged(manifest, game, state, log, downloads):
    logs.setup(state, debug=True)
    z = make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "shv", "bin/xinput1_4.dll": "loader"})
    inst = Installer(manifest, game, state, log, AutoUI())
    step = inst.install(manifest.mod("scripthookv"), z)
    inst.rollback(step.id)
    text = text_of(state)
    assert f"install step {step.id}: scripthookv (copy) from ScriptHookV_1.0.zip" in text
    assert f"step {step.id} done: scripthookv" in text and "add ScriptHookV.dll" in text
    assert f"rollback step {step.id}: scripthookv" in text and "undo add ScriptHookV.dll" in text


def test_matcher_download_and_helper_events(tmp_path, manifest, game):
    from leonida import downloader, matcher
    from leonida import rpf as R

    logs.setup(tmp_path, debug=True)
    f = tmp_path / "ScriptHookV_3889.0.zip"
    f.write_bytes(b"x")
    matcher.match_files(list(manifest.mods.values()), [f], {})
    assert downloader._host_of("https://github.com/a/b/releases/download/v1/x.zip?token=1") == "github.com"
    make_zip(game / "mods" / "x.rpf", {"a.xml": "<a/>"})
    R.run_helper(R.find_helper(), game, [{"op": "list", "rpf": "mods\\x.rpf"}])
    text = text_of(tmp_path)
    assert "match: ScriptHookV_3889.0.zip -> scripthookv" in text
    assert "RPF helper: 1 op(s) (1 list) on x.rpf" in text and "RPF helper done in" in text


# ------------------------------------------------------------------------------------------- the report
HOME = r"C:\Users\JaneDoe"


def test_redact_every_spelling():
    raw = (r"C:\Users\JaneDoe\AppData\x.log | C:/Users/JaneDoe/Desktop | " '{"p": "C:\\\\Users\\\\JaneDoe\\\\Game"} '
           "| c:\\users\\janedoe\\y | user janedoe signed in | JaneDoeX stays | PC DESKTOP-ABC | token=zzz")
    out = D.redact(raw, [HOME], ["JaneDoe"], "DESKTOP-ABC")
    assert "JaneDoe\\" not in out and "janedoe\\" not in out and "/JaneDoe/" not in out
    assert out.count("<user>") == 5 and "JaneDoeX stays" in out and "<pc>" in out and "zzz" not in out
    assert D.redact("a b c", [], ["ab"], "x") == "a b c"  # short names aren't replaced (they'd hit words)
    me = D.redact(f"{Path.home()} and {os.environ.get('USERNAME', 'nobody')}")
    assert str(Path.home()) not in me


def make_report_session(tmp_path, game):
    state = tmp_path / "state"
    s = Session(state, game_dir=str(game), game_build="1.0.1013.20")
    s.config.download_dir = rf"{HOME}\Downloads\LeonidaV"  # a path with the user's name in it
    s.save()
    (state / "install-log.json").write_text(json.dumps({"steps": []}))
    (state / "pack.json").write_text('{"enhanced": {"pack": "core"}}')
    (state / "settings-unlocked.json").write_text("{}")
    (state / "leonida.lock").write_text("{}")
    (state / "playtest").mkdir()
    (state / "playtest" / "last-report.json").write_text('{"status": "passed"}')
    (state / "playtest" / "previous").mkdir()
    (state / "playtest" / "previous" / "ScriptHookV.log").write_text("previous run")
    # what must never be in a report
    (state / "browser").mkdir()
    (state / "browser" / "Cookies").write_text("nexus session cookie")
    (state / "backups").mkdir()
    (state / "backups" / "big.rpf").write_text("backup")
    (state / "Downloads").mkdir()
    (state / "Downloads" / "mod.zip").write_text("download")
    (game / "ScriptHookV.log").write_text(f"[00:00] INIT: Success\npath {HOME}\\Games\nAuthorization: Bearer abcdefghij\n")
    (game / "mods").mkdir()
    (game / "mods" / "update").mkdir()
    (game / "mods" / "update" / "update.rpf").write_bytes(b"RPF7")
    logs.setup(state)
    logging.getLogger("leonida.test").info("something happened for %s", HOME)
    return s


def test_report_contents_and_privacy(tmp_path, game, monkeypatch):
    s = make_report_session(tmp_path, game)
    monkeypatch.setattr(D, "_identity", lambda: ([HOME], ["JaneDoe"], "DESKTOP-ABC"))
    monkeypatch.setattr(D, "system_info", lambda run=None: {"os": "Windows 11", "disks": {}})
    names = [n for n, _ in D.preview(s)]
    assert set(names) >= {"leonida/leonida.log", "game-logs/ScriptHookV.log", "game-logs/previous-run/ScriptHookV.log",
                          "state/install-log.json", "state/config.json", "state/pack.json",
                          "state/settings-unlocked.json", "state/leonida.lock", "state/playtest/last-report.json",
                          "results/check.txt", "results/verify.txt", "results/game.json", "system.json",
                          "game-files.txt", "README.txt"}
    assert not any(k in n.lower() for n in names for k in ("browser", "cookie", "backup", "download"))
    path = D.build(s, tmp_path / "out")
    assert path.parent == tmp_path / "out" and path.name.startswith("Leonida-report-") and path.suffix == ".zip"
    with zipfile.ZipFile(path) as z:
        texts = {n: z.read(n).decode("utf-8") for n in z.namelist()}
    for n, t in texts.items():
        assert "JaneDoe" not in t and "DESKTOP-ABC" not in t, n
        assert "nexus session cookie" not in t and "abcdefghij" not in t, n
    assert "<user>" in texts["state/config.json"] and "<user>" in texts["leonida/leonida.log"]
    assert "update/update.rpf  4" in texts["game-files.txt"].replace("\\", "/")
    game_info = json.loads(texts["results/game.json"])
    assert game_info["game"]["build"] == "1.0.1013.20" and game_info["leonida"]
    assert "Nothing installed" in texts["results/verify.txt"]


def test_report_tail_of_big_logs_and_default_dir(tmp_path, game, monkeypatch):
    s = make_report_session(tmp_path, game)
    monkeypatch.setattr(D, "MAX_FILE", 100)
    (game / "ScriptHookV.log").write_text("x" * 500 + "THE END")
    monkeypatch.setattr(D, "system_info", lambda run=None: {})
    text = dict(D.collect(s))["game-logs/ScriptHookV.log"]
    assert text.startswith("[only the last") and text.endswith("THE END") and len(text) < 200
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    assert D.default_dir() == home / "Desktop"
    (home / "OneDrive" / "Desktop").mkdir(parents=True)
    assert D.default_dir() == home / "OneDrive" / "Desktop"


def test_system_info_from_cim(monkeypatch):
    class P:
        stdout = json.dumps({"os": "Microsoft Windows 11 Pro", "cpu": ["Ryzen"], "gpus": [{"name": "GTX 1070",
                                                                                         "driver": "32.0"}]})

    calls = []
    info = D.system_info(run=lambda *a, **k: calls.append(a) or P())
    assert info["python"] and info["leonida"] and "disks" in info
    if sys.platform == "win32":
        assert info["gpus"][0]["name"] == "GTX 1070" and "Win32_VideoController" in calls[0][0][-1]
        bad = D.system_info(run=lambda *a, **k: (_ for _ in ()).throw(OSError("no powershell")))
        assert bad["cim_error"] == "no powershell"


def test_cli_report_asks_first(tmp_path, game, monkeypatch, capsys):
    monkeypatch.setattr(D, "system_info", lambda run=None: {})
    base = ["--state-dir", str(tmp_path / "st"), "--game-dir", str(game), "report", "--out", str(tmp_path / "out")]
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main(base) == 1 and "Not saved." in capsys.readouterr().out and not (tmp_path / "out").exists()

    def eof(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert main(base) == 1
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert main(base) == 0
    out = capsys.readouterr().out
    assert "It will hold these files:" in out and "system.json" in out and "Saved " in out
    assert main(base + ["--yes"]) == 0 and len(list((tmp_path / "out").glob("*.zip"))) >= 1


def test_playtest_saves_its_last_report(tmp_path, game):
    from leonida import playtest as P

    s = Session(tmp_path / "st", game_dir=str(game))
    rep = P.PlaytestReport(P.PASSED, "fine", timeline=["  1s  started"])
    path = P.save_report(s, rep)
    assert json.loads(path.read_text())["status"] == "passed"
    blocked = Session(tmp_path / "st2", game_dir=str(game))
    (tmp_path / "st2").mkdir()
    (tmp_path / "st2" / "playtest").write_text("not a folder")
    assert P.save_report(blocked, rep) is None
