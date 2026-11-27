"""Pure GTA (leonida/puremode.py): the game with no mods at all, then the mods back by themselves. Fake folders only;
the game is never started (a fake Popen)."""

from __future__ import annotations

import pytest
from test_online_safe import installed  # noqa: F401  (fixture)

from leonida import onlinesafe as O
from leonida import puremode as P
from leonida.session import Session


def _session(installed, downloads):  # noqa: F811
    game, inst, _ = installed
    (game / "PlayGTAV.exe").write_text("launcher")
    return Session(inst.state, download_dir=str(downloads), game_dir=str(game))


def test_pure_gta_moves_every_mod_out_starts_the_game_and_brings_them_back(installed, downloads,  # noqa: F811
                                                                          monkeypatch):
    monkeypatch.delenv("LEONIDA_NO_OPEN", raising=False)   # the fake Popen below starts nothing
    s = _session(installed, downloads)
    game = s.game_dir()
    started = []
    lines = P.start(s, running=lambda: [], popen=lambda cmd, cwd: started.append((cmd, cwd)))
    assert P.active(s) and started and started[0][1] == str(game)
    assert lines[0].startswith("Pure GTA: moved 6 mod item(s)") and "with no mods" in lines[1]
    assert not (game / "ActionsV.asi").exists() and not (game / "DynamicVehicleFirstPerson").exists()
    assert s.online_status() == "online-safe"           # the game folder is vanilla
    # while the game still runs, nothing comes back
    assert "stays on while GTA V runs" in P.finish(s, running=lambda: ["GTA5_Enhanced.exe"])[0]
    assert P.active(s) and not (game / "ActionsV.asi").exists()
    # closed: the mods are back, the record is gone
    assert "6 mod item(s) are back" in P.finish(s, running=lambda: [])[0]
    assert not P.active(s) and (game / "ActionsV.asi").exists() and (game / "DynamicVehicleFirstPerson").is_dir()
    assert P.finish(s, running=lambda: []) == []         # nothing to do the second time


def test_refuses_while_the_game_runs(installed, downloads):  # noqa: F811
    s = _session(installed, downloads)
    with pytest.raises(P.PureModeError, match="GTA V is running"):
        P.start(s, running=lambda: ["GTA5_Enhanced.exe"], popen=lambda *a, **k: None)
    assert not P.active(s) and (s.game_dir() / "ActionsV.asi").exists()


def test_online_safe_mods_stay_out_after_pure_gta(installed, downloads):  # noqa: F811
    s = _session(installed, downloads)
    s.online_safe_on(running=lambda: [])
    P.start(s, launch_game=False, running=lambda: [])
    assert P.info(s)["was_online_safe"] is True
    assert "Online-safe was on before" in P.finish(s, running=lambda: [])[0]
    assert not P.active(s) and not (s.game_dir() / "ActionsV.asi").exists()   # still Online-safe


def test_no_launcher_puts_the_mods_straight_back(installed, downloads):  # noqa: F811
    s = _session(installed, downloads)
    (s.game_dir() / "PlayGTAV.exe").unlink()
    (s.game_dir() / "GTA5_Enhanced.exe").unlink()
    with pytest.raises(P.PureModeError, match="No PlayGTAV.exe"):
        P.start(s, running=lambda: [], popen=lambda *a, **k: None)
    assert not P.active(s) and (s.game_dir() / "ActionsV.asi").exists()


def test_cli_pure(installed, downloads, monkeypatch, capsys):  # noqa: F811
    from leonida.cli import main

    game, inst, _ = installed
    (game / "PlayGTAV.exe").write_text("launcher")
    monkeypatch.setattr(O, "game_running", lambda names=O.GAME_PROCESSES: [])
    monkeypatch.setenv("LEONIDA_NO_OPEN", "1")
    base = ["--state-dir", str(inst.state), "--game-dir", str(game), "--download-dir", str(downloads)]
    assert main(base + ["pure", "--status"]) == 0 and "Pure GTA is off." in capsys.readouterr().out
    assert main(base + ["pure"]) == 0
    out = capsys.readouterr().out
    assert "moved 6 mod item(s)" in out and "Would start PlayGTAV.exe" in out and "leonida pure --back" in out
    assert main(base + ["pure", "--status"]) == 0 and "Pure GTA is on" in capsys.readouterr().out
    assert main(base + ["pure", "--back"]) == 0 and "are back in the game folder" in capsys.readouterr().out
    assert (game / "ActionsV.asi").exists()
    assert main(base + ["pure", "--back"]) == 0 and "isn't on" in capsys.readouterr().out
