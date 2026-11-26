"""The owner: "it should remember and not have to set up entirely again on reinstalls or restarts, and never
redownload everything". Every way Leonida could forget, tested on fake games and temp data folders:

  - uninstall (keeping the data) -> setup again: the same data folder, silently in /S, no first-run setup;
  - Windows reinstalled (no registry at all): the setup finds <drive>:\\<folder>\\State (e.g. D:\\Leonida);
  - the installed exe whose registry entry can't be read never starts over with an empty State;
  - restarts keep the pack, add-ons, variant, unlocked settings and the game folder;
  - the game repaired or reinstalled by Steam / Rockstar (mods gone, install log says installed): found, and Repair
    puts every mod back from Downloads without downloading, and uninstall still gives the baseline back.
(`get --auto` with everything present downloads nothing: tests/test_cov_cli.py.) Never the real registry, Start
menu, data folder or game.
"""

from __future__ import annotations

import json
import sys
import uuid

import pytest
from conftest import AutoUI, make_zip
from test_cov_core import BUILD, mini_manifest, mod_entry

from leonida import firstrun, repair
from leonida import settings as S
from leonida.session import Session

win_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows setup (registry)")


# ------------------------------------------------------------------------------------------- setup + data folder
@pytest.fixture
def reg(monkeypatch, tmp_path):
    from test_winsetup import _delete_tree

    from leonida import winsetup

    root = f"Software\\LeonidaV-pytest-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("LEONIDA_REG_ROOT", root)
    monkeypatch.setenv("LEONIDA_NO_SHORTCUTS", "1")
    monkeypatch.setenv("LEONIDA_STARTMENU_DIR", str(tmp_path / "menu"))
    monkeypatch.setenv("LEONIDA_DESKTOP_DIR", str(tmp_path / "desk"))
    monkeypatch.setenv("LEONIDA_DATA_SEARCH", str(tmp_path / "drive"))       # the "fixed drives" searched
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))        # the default data folder
    monkeypatch.setattr(winsetup, "leonida_running", lambda d: [])
    (tmp_path / "drive").mkdir()
    yield root
    _delete_tree(root)


def _payload(tmp_path, version="1.0.2"):
    from test_winsetup import make_payload

    return make_payload(tmp_path, version)


def _used(data, game="C:\\Games\\GTA V"):
    """A data folder Leonida has used: config with the game, a chosen pack, an install log."""
    state = data / "State"
    state.mkdir(parents=True, exist_ok=True)
    (state / "config.json").write_text(json.dumps({"game_dir": game, "profile": "owner-pick",
                                                   "update_channel": "stable"}), encoding="utf-8")
    (state / "install-log.json").write_text('{"steps": []}', encoding="utf-8")
    (data / "Downloads").mkdir(exist_ok=True)
    (data / "Downloads" / "ScriptHookV_1.0.zip").write_bytes(b"zip")
    return state


@win_only
def test_uninstall_keeping_data_then_setup_again_finds_it(tmp_path, reg):
    from leonida import winsetup

    data = tmp_path / "drive" / "Leonida"
    winsetup.install(_payload(tmp_path), tmp_path / "prog", data)
    state = _used(data)
    res = winsetup.uninstall(remove_program_now=True)                         # keep State and Downloads
    assert str(data / "State") in res.kept and winsetup.registered() is None
    assert winsetup.suggested_data_dir() == data                              # remembered across the uninstall
    again = winsetup.install(_payload(tmp_path), tmp_path / "prog")          # no data folder given (setup /S)
    assert again.data_dir == data and winsetup.registered()["DataDir"] == str(data)
    assert json.loads((state / "config.json").read_text())["game_dir"] == "C:\\Games\\GTA V"
    assert firstrun.should_run(state) is None                                 # no first-run setup again
    assert (data / "Downloads" / "ScriptHookV_1.0.zip").read_bytes() == b"zip"


@win_only
def test_setup_exe_silent_uses_the_found_data_folder(tmp_path, reg, monkeypatch):
    from test_winsetup import _entry, _payload_dir

    from leonida import winsetup

    data = tmp_path / "drive" / "Leonida"
    _used(data)                                     # Windows reinstalled: data on D:, nothing in the registry
    es = _entry()
    payload = _payload_dir(tmp_path, _payload(tmp_path), "1.0.2")
    monkeypatch.setattr(es, "payload_dir", lambda: payload)
    assert es.main(["/S", "--dir", str(tmp_path / "prog"), "--log", str(tmp_path / "setup.log")]) == 0
    assert winsetup.registered()["DataDir"] == str(data)
    assert json.loads((data / "State" / "config.json").read_text())["game_dir"] == "C:\\Games\\GTA V"


@win_only
def test_found_data_folders_best_first_and_only_leonidas(tmp_path, reg, monkeypatch):
    from leonida import winsetup

    drive = tmp_path / "drive"
    _used(drive / "Leonida")
    _used(drive / "AnotherCopy")
    other = drive / "SomeApp" / "State"
    other.mkdir(parents=True)
    (other / "config.json").write_text('{"theme": "dark"}', encoding="utf-8")   # not Leonida's
    (drive / "Windows").mkdir()
    assert winsetup.find_data_dirs() == [drive / "AnotherCopy", drive / "Leonida"]
    winsetup.remember_data_dir(drive / "Leonida")                              # the last one used comes first
    assert winsetup.find_data_dirs()[0] == drive / "Leonida"
    monkeypatch.delenv("LEONIDA_DATA_SEARCH")
    assert winsetup._search_roots() == []        # a test registry root never searches the real drives


@win_only
def test_uninstall_deleting_the_data_forgets_it(tmp_path, reg):
    from leonida import winsetup

    data = tmp_path / "elsewhere" / "Leonida"
    winsetup.install(_payload(tmp_path), tmp_path / "prog", data)
    _used(data)
    winsetup.uninstall(delete_state=True, delete_downloads=True, remove_program_now=True)
    assert winsetup.find_data_dirs() == [] and winsetup.suggested_data_dir() == winsetup.default_data_dir()


@win_only
def test_installed_exe_never_starts_over_when_its_registry_entry_is_unreadable(tmp_path, reg, monkeypatch):
    from leonida import paths, winsetup

    prog = tmp_path / "localappdata" / "Programs" / "Leonida V"               # the usual program folder
    data = tmp_path / "drive" / "Leonida"
    winsetup.install(_payload(tmp_path), prog, data)
    _used(data)
    monkeypatch.delenv("LEONIDA_STATE_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(prog / "LeonidaV.exe"))
    assert paths.state_dir() == data / "State" and "installed" in paths.state_origin()
    monkeypatch.setattr(winsetup, "registered", lambda: None)                  # the 17:06 case
    assert paths.state_dir() == data / "State"
    monkeypatch.setattr(sys, "executable", str(tmp_path / "portable" / "LeonidaV.exe"))
    assert paths.state_dir() != data / "State"                                # a portable copy keeps its own


# ------------------------------------------------------------------------------------------- restarts
def test_a_restart_keeps_the_choices(tmp_path, game):
    state = tmp_path / "st"
    s = Session(state, game_dir=str(game), game_build="1.0.1013.20")
    choice = s.choose_pack("owner-pick", variant="ram32")
    S.set_unlocked(state, "leonidamenu", "scripts/LeonidaMenu.ini", "Keys/Open", True)
    again = Session(state)                                                    # Leonida started again
    c = again.pack_choice()
    assert (c.pack, c.variant, c.addons) == (choice.pack, choice.variant, choice.addons)
    assert (c.pack, c.variant) == ("owner-pick", "ram32")
    assert again.config.game_dir == str(game)
    assert S.unlock_key("leonidamenu", "scripts/LeonidaMenu.ini", "Keys/Open") in S.unlocked(state)
    assert firstrun.should_run(state) is None


# ------------------------------------------------------------------------------------------- the game lost its mods
@pytest.fixture
def mini(tmp_path, game):
    mods = [mod_entry("alpha", 1), mod_entry("beta", 2, files=["scripts/beta.dll"], install={
        "method": "copy", "createDirs": ["scripts"], "files": [{"match": "beta.dll", "to": "scripts"}]}),
        mod_entry("gamma", 3)]
    mdir = mini_manifest(tmp_path / "manifest", mods)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    for mid, name in (("alpha", "alpha.asi"), ("beta", "beta.dll"), ("gamma", "gamma.asi")):
        make_zip(downloads / f"{mid}-1.0.zip", {f"{mid}/{name}": f"{mid} v1"})
    s = Session(tmp_path / "st", manifest_dir=mdir, game_dir=str(game), download_dir=str(downloads), game_build=BUILD)
    matched = s.matches().matched
    inst = s.installer(AutoUI())
    for m in s.mods():
        inst.install(m, matched[m.id])
    return s


def _steam_verify(game, *names):
    """What a verify / reinstall does: the files Leonida added are gone, the game's own are back."""
    for n in names:
        (game / n).unlink()


def test_a_healthy_game_has_nothing_lost(mini):
    assert repair.lost(mini) is None


def test_lost_mods_are_found_and_repaired_from_downloads(mini, game, monkeypatch):
    from leonida import downloader
    from leonida.snapshot import diff, load_snapshot, take_snapshot

    monkeypatch.setattr(downloader, "download", lambda *a, **k: pytest.fail("Repair never downloads"))
    _steam_verify(game, "alpha.asi", "scripts/beta.dll")
    found = repair.lost(mini)
    assert found.mods == ["alpha", "beta"] and found.missing == {"alpha": 1, "beta": 1}
    assert "lost 2 mod(s)" in found.text() and "nothing is downloaded" in found.text()
    rep = repair.repair(mini, repair.QuietUI(), found)
    assert rep.repaired == ["alpha", "beta"] and not rep.failed and not rep.no_download
    assert (game / "alpha.asi").read_text() == "alpha v1" and (game / "scripts" / "beta.dll").is_file()
    assert repair.lost(mini) is None and mini.log.installed_mods() == {"alpha", "beta", "gamma"}
    assert [st.status for st in mini.log.steps if st.mod == "alpha"] == [repair.LOST, "done"]
    # the invariant still holds: uninstall gives the pre-install snapshot back
    warnings, residual = mini.installer(AutoUI()).uninstall()
    assert not warnings and residual.empty
    assert diff(load_snapshot(mini.state / "baseline-snapshot.json"), take_snapshot(game)).empty


def test_repair_lists_what_it_cant_do_and_never_downloads(mini, game, tmp_path):
    _steam_verify(game, "alpha.asi", "gamma.asi")
    (tmp_path / "Downloads" / "gamma-1.0.zip").unlink()                        # the user deleted that download
    rep = repair.repair(mini, repair.QuietUI())
    assert rep.repaired == ["alpha"] and rep.no_download == ["gamma"]
    assert any("Not in Downloads" in line and "Gamma" in line for line in rep.lines({"gamma": "Gamma"}))
    assert repair.lost(mini).mods == ["gamma"]                                # still lost: not marked repaired


def test_moved_out_for_online_is_not_lost(mini, game, monkeypatch):
    _steam_verify(game, "alpha.asi")
    monkeypatch.setattr(type(mini), "online_status", lambda self: "online-safe")
    assert repair.lost(mini) is None


def test_cli_repair(mini, game, monkeypatch, capsys):
    from leonida import cli

    _steam_verify(game, "alpha.asi")
    args = ["--state-dir", str(mini.state), "--manifest-dir", str(mini.manifest_dir), "--game-dir", str(game),
            "--download-dir", str(mini.config.downloads()), "--game-build", BUILD]
    assert cli.main(args + ["status"]) == 0 and "leonida repair" in capsys.readouterr().out
    assert cli.main(args + ["repair", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Repaired: Alpha" in out and (game / "alpha.asi").is_file()
    assert cli.main(args + ["repair"]) == 0 and "nothing to repair" in capsys.readouterr().out
