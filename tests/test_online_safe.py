"""Online-safe, as checked in the real game on the owner's PC (2026-11-25): "clean" means clean. Besides the
manifest's patterns, everything Leonida's install log added at the top of the game folder goes out (ActionsV.ini,
the DynamicVehicleFirstPerson data folder), and so do the mods' logs; stock files and the game's own version.dll stay.
Both directions refuse while GTA runs. Fake folders only."""

from __future__ import annotations

import pytest
from conftest import AutoUI, make_zip

from leonida import onlinesafe as O
from leonida.installer import Installer
from leonida.log import InstallLog
from leonida.manifest import FileSpec, Mod, load_manifest
from leonida.snapshot import diff, take_snapshot

PATS = ("*.asi", "ScriptHookV.dll", "scripts", "mods")


def _mod(mid, files, create_dirs=()):
    return Mod(id=mid, order=1, tier="core", layer="x", name=mid, author="a", version="1", source="direct",
               page="https://x", archive=(f"{mid}*.zip",), method="copy", files=files, create_dirs=create_dirs)


@pytest.fixture
def installed(game, state, downloads):
    """A game with stock files (version.dll, update/) and two Leonida installs: ActionsV (asi + ini at the top) and a
    first-person camera mod with its own data folder."""
    (game / "version.dll").write_text("the game's own")         # not Leonida's: never moved
    before = take_snapshot(game)
    inst = Installer(load_manifest(), game, state, InstallLog(state / "install-log.json"), AutoUI())
    inst.install(_mod("actionsv", (FileSpec("ActionsV.asi"), FileSpec("ActionsV.ini"))),
                 make_zip(downloads / "actionsv-1.zip", {"ActionsV.asi": "asi", "ActionsV.ini": "ini"}))
    inst.install(_mod("dvfp", (FileSpec("DynamicVehicleFirstPerson.asi"),
                               FileSpec("DynamicVehicleFirstPerson", type="dir"))),
                 make_zip(downloads / "dvfp-1.zip", {"DynamicVehicleFirstPerson.asi": "a",
                                                    "DynamicVehicleFirstPerson/settings.ini": "s"}))
    (game / "ScriptHookV.log").write_text("log")
    (game / "asiloader.log.prev").write_text("log")
    return game, inst, before


def _scope(inst):
    from leonida.snapshot import load_snapshot

    extra, protected = O.leonida_items(inst.log, load_snapshot(inst.baseline_path))
    return {"extra": extra, "protected": protected}


def test_everything_leonida_added_goes_out_and_comes_back(installed):
    game, inst, before = installed
    scope = _scope(inst)
    assert {"actionsv.ini", "dynamicvehiclefirstperson"} <= scope["extra"] and "version.dll" in scope["protected"]
    moved = O.go_online_safe(game, PATS, running=lambda: [], **scope)
    assert set(moved) == {"ActionsV.asi", "ActionsV.ini", "DynamicVehicleFirstPerson.asi",
                          "DynamicVehicleFirstPerson", "ScriptHookV.log", "asiloader.log.prev"}
    left = {p.name for p in game.iterdir()} - {O.OFFLINE_DIR}
    assert left == {"GTA5_Enhanced.exe", "bink2w64.dll", "update", "x64", "version.dll"}   # vanilla, stock kept
    state, out, present = O.report(game, PATS, **scope)
    assert state == "online-safe" and set(out) == set(moved) and present == []
    assert O.restore_mods(game, running=lambda: []) == moved
    assert O.report(game, PATS, **scope)[0] == "mods-on"
    inst.uninstall()
    after = diff(before, take_snapshot(game))
    assert after.removed == [] and set(after.added) <= {"ScriptHookV.log", "asiloader.log.prev"}


def test_dry_run_lists_and_moves_nothing(installed):
    game, inst, _ = installed
    names = O.go_online_safe(game, PATS, dry_run=True, running=lambda: ["GTA5_Enhanced.exe"], **_scope(inst))
    assert "ActionsV.ini" in names and (game / "ActionsV.ini").exists() and not (game / O.OFFLINE_DIR).exists()


def test_refuses_while_gta_runs(installed):
    game, inst, _ = installed
    with pytest.raises(O.OnlineSafeError, match=r"GTA V is running \(GTA5_Enhanced.exe\): close the game first"):
        O.go_online_safe(game, PATS, running=lambda: ["GTA5_Enhanced.exe"], **_scope(inst))
    assert (game / "ActionsV.asi").exists() and not (game / O.OFFLINE_DIR).exists()   # nothing moved
    O.go_online_safe(game, PATS, running=lambda: [], **_scope(inst))
    with pytest.raises(O.OnlineSafeError, match="GTA V is running"):
        O.restore_mods(game, running=lambda: ["PlayGTAV.exe"])
    assert not (game / "ActionsV.asi").exists()


def test_a_stock_log_and_stock_folders_stay(game, state, downloads):
    (game / "launcher.log").write_text("the game's own log")     # in the baseline: stock
    inst = Installer(load_manifest(), game, state, InstallLog(state / "install-log.json"), AutoUI())
    inst.install(_mod("upd", (FileSpec("x.meta", to="update"),)), make_zip(downloads / "upd-1.zip", {"x.meta": "m"}))
    scope = _scope(inst)
    assert "update" not in scope["extra"] and "launcher.log" in scope["protected"]   # a stock folder never moves
    assert [p.name for p in O.mod_items(game, PATS, logs=True, **scope)] == []


def test_find_running_reads_the_process_list():
    class Ops:
        def running(self, name):
            if name == "PlayGTAV.exe":
                raise OSError("tasklist failed")
            return [4242] if name == "GTA5_Enhanced.exe" else []

    assert O.find_running(O.GAME_PROCESSES, Ops()) == ["GTA5_Enhanced.exe"]


def test_session_and_cli_use_the_whole_scope(installed, tmp_path, downloads, capsys):
    from leonida.cli import main
    from leonida.session import Session

    game, inst, _ = installed
    base = ["--state-dir", str(inst.state), "--game-dir", str(game), "--download-dir", str(downloads)]
    s = Session(inst.state, download_dir=str(downloads), game_dir=str(game))
    assert "dynamicvehiclefirstperson" in s.online_safe_scope()["extra"]
    assert main(base + ["online-safe", "on", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Would move 6 item(s): ") and "ActionsV.ini" in out and "DynamicVehicleFirstPerson" in out
    assert main(base + ["online-safe", "on"]) == 0
    assert main(base + ["online-safe", "status"]) == 0
    out = capsys.readouterr().out
    assert "online-safe" in out and "Moved out (6):" in out and "In the game folder (0): nothing" in out
    assert s.online_status() == "online-safe"
    assert main(base + ["online-safe", "off"]) == 0
    assert (game / "DynamicVehicleFirstPerson" / "settings.ini").exists()
