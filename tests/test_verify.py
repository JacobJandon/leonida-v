"""leonida.verify: read the mods' logs after a game start. Sample log texts are quoted with their source."""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

from leonida import log as L
from leonida.cli import main as cli_main
from leonida.verify import FAILED, NO_LOG, NOT_SEEN, OK, WARN, verify

# ---------------------------------------------------------------- sample logs
# ScriptHookV.log, Enhanced: real log pasted in itsjustcurtis/MenyooSP#643 (paths/addresses as posted, build line
# changed to the owner's game build 1.0.1013.20 -> VER_EN_1_0_1013_20, same tag scheme).
SHV_OK = """\
// GTA V SCRIPT HOOK (build Jul 15 2026, v3889.0/1158.13)
//          (C) Alexander Blade 2015-2026
[02:39:17] INIT: Started
[02:39:17] INIT: Success, game version is VER_EN_1_0_1013_20
[02:39:17] INIT: Registering script 'Menyoo.asi' (0x00007FFDEC11EB20)
[02:39:17] INIT: Registering additional script thread 'Menyoo.asi' (0x00007FFDEC12FF80)
[02:39:17] INIT: Registering script 'ScriptHookVDotNet.asi' (0x00007FFDF0A1C000)
[02:40:46] CORE: Created 4 threads (including control)
[02:40:52] CORE: Launching main() for 'Menyoo.asi' (0x00007FFDEC11EB20), id 4
"""
# Same log, later in that issue: Script Hook V catching a crash inside an .asi.
SHV_EXCEPTION = SHV_OK + """\
[04:05:26] CORE: An exception occurred while executing 'Menyoo.asi', id 4
Exception addr 0x00007FF752A0A5EA is GTA5_Enhanced.exe+0x0013A5EA
"""
# Unknown build: real (Legacy) log in scripthookvdotnet/scripthookvdotnet#599.
SHV_UNKNOWN = """\
// GTA V SCRIPT HOOK (build Mar 16 2016, v1.0.678.1)
//          (C) Alexander Blade 2015
[11:47:26] FATAL: Unknown game version
"""
# asiloader.log, Enhanced: real logs in Parik27/V.Rainbomizer#141 and itsjustcurtis/MenyooSP#282 (names swapped in).
ASI_OK = r"""
// GTA V ENHANCED ASI LOADER (build Mar 22 2025)
LIB: "C:\WINDOWS\system32\xinput1_4.dll" => 00007FFDA4930000
LOADER: Loading *.asi plugins
ASI: Loading "E:\SteamLibrary\steamapps\common\Grand Theft Auto V Enhanced\Menyoo.asi"
     "Menyoo.asi" => 00007FFDA8B80000
ASI: Loading "E:\SteamLibrary\steamapps\common\Grand Theft Auto V Enhanced\ScriptHookVDotNet.asi"
     "ScriptHookVDotNet.asi" => 00007FFDA9C00000
ASI: Loading "E:\SteamLibrary\steamapps\common\Grand Theft Auto V Enhanced\OpenRPF.asi"
     "OpenRPF.asi" failed to load
LOADER: Finished loading *.asi plugins
""".lstrip("\n")
# ScriptHookVDotNet.log: format from Chiheb-Bacha/ScriptHookVDotNetEnhanced source/core/Log.cs, version string from
# source/core/ScriptDomain.cs; script lines from the real log in fredakilla/Quadcopter-Redux-Guide#5.
SHVDN = r"""
[02:40:52] [INFO] ScriptHookV .Net Enhanced 3.9.0.6 (1.1.0.6)
[02:40:53] [DEBUG] Loading scripts from E:\Grand Theft Auto V Enhanced\scripts ...
[02:40:53] [INFO] Found 1 script(s) in GTA5-Quadcopter.dll resolved to API version 3.7.0 (target API version: 3.6.0).
[02:40:53] [DEBUG] Instantiating script Quadcopter.MainScript ...
[02:40:53] [INFO] Started script Quadcopter.MainScript.
[02:40:53] [INFO] Found 1 script(s) in GoodScript.dll resolved to API version 3.7.0 (target API version: 3.6.0).
[02:40:53] [DEBUG] Instantiating script Good.Main ...
[02:40:53] [INFO] Started script Good.Main.
[02:41:28] [ERROR] The exception was thrown while executing the script Quadcopter.MainScript from "E:\GTAV\scripts\GTA5-Quadcopter.dll".
[02:41:28] [WARNING] Aborted script Quadcopter.MainScript.
""".lstrip("\n")
# menyooLog.txt: real log in itsjustcurtis/MenyooSP#643; format from Solution/source/Util/FileLogger.cpp.
MENYOO_OK = """\
Menyoo Version: 2.4.4
Game Version: Enhanced b1013.20
Date: 18/09/2026
[02:39:17] INFO - Logging level 2 active. Edit loglevel in menyooconfig.ini to change.
[02:39:17] INIT - GTAMemory Init Done
"""
MENYOO_UNKNOWN = """\
Menyoo Version: 2.4.4
Game Version: Enhanced Unknown
Date: 18/09/2026
[02:39:17] ERROR - Pattern not found: 48 8B 05 ? ? ? ? 48 8B 0C C8
"""
# The placeholder menyoolog.txt inside the MenyooSP release zip (first line verbatim).
MENYOO_PLACEHOLDER = "Menyoo failed to initialise.\r\n\r\nBe sure that\r\n- ScripthookV ... is installed.\r\n"
# DirectStorageFix.log: spdlog pattern "[%H:%M:%S.%e] [%l] %v" and messages from alloc8or/DirectStorageFix src/dllmain.cpp.
DSF_OK = """\
[02:39:15.101] [info] Init started
[02:39:15.101] [info] Windows NT build: 26300
[02:39:15.102] [info] Game build: 1013.20
[02:39:15.102] [info] Base: 0x7FF7528D0000, Size: 0x5A3C000
[02:39:15.130] [info] Init finished
"""
DSF_FAIL = """\
[02:39:15.101] [info] Init started
[02:39:15.102] [info] Game build: 1013.20
[02:39:15.120] [error] Failed to find fiDeviceDirectStorage::RegisterFile
"""


# ---------------------------------------------------------------- helpers
def installed(log: L.InstallLog, mod: str, files: list[str], when: float | None = None) -> L.Step:
    step = log.new_step(mod, "copy")
    step.actions = [L.Action(L.ADD, f, "0" * 64) for f in files]
    step.status = "done"
    step.finished = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(when if when is not None else time.time() - 60))
    log.save()
    return step


def write_log(game: Path, name: str, text: str, age: float = 0.0) -> Path:
    p = game / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    t = time.time() - age
    os.utime(p, (t, t))
    return p


def by_mod(results):
    out: dict[str, list] = {}
    for r in results:
        out.setdefault(r.mod, []).append(r)
    return out


def statuses(results, mod):
    return [r.status for r in results if r.mod == mod]


# ---------------------------------------------------------------- tests
def test_nothing_started_yet_is_not_seen(manifest, game, log):
    installed(log, "scripthookv", ["ScriptHookV.dll", "dinput8.dll"])
    installed(log, "menyoo", ["Menyoo.asi", "menyooStuff/menyooConfig.ini"])
    res = verify(game, [manifest.mod("scripthookv"), manifest.mod("menyoo")], log)
    assert statuses(res, "scripthookv") == [NOT_SEEN]
    assert statuses(res, "menyoo") and set(statuses(res, "menyoo")) == {NOT_SEEN}
    assert "Start the game" in res[0].message


def test_shv_success_reports_build_and_asi_loaded(manifest, game, log):
    installed(log, "scripthookv", ["ScriptHookV.dll", "dinput8.dll"])
    installed(log, "menyoo", ["Menyoo.asi"])
    write_log(game, "ScriptHookV.log", SHV_OK)
    write_log(game, "asiloader.log", ASI_OK)
    res = verify(game, [manifest.mod("scripthookv"), manifest.mod("menyoo")], log)
    shv = by_mod(res)["scripthookv"]
    assert [r.status for r in shv] == [OK]
    assert "1.0.1013.20 (Enhanced)" in shv[0].message and shv[0].line.endswith("VER_EN_1_0_1013_20")
    assert statuses(res, "menyoo")[0] == OK
    assert not [r for r in res if r.mod is None]


def test_shv_unknown_game_version_fails_with_line(manifest, game, log):
    installed(log, "scripthookv", ["ScriptHookV.dll"])
    write_log(game, "ScriptHookV.log", SHV_UNKNOWN)
    (r,) = verify(game, [manifest.mod("scripthookv")], log)
    assert r.status == FAILED and r.code == "shv-unknown-version"
    assert "Unknown game version" in r.line and r.log == "ScriptHookV.log"
    assert r.level == "error"


def test_log_older_than_install_says_start_game_first(manifest, game, log):
    write_log(game, "ScriptHookV.log", SHV_OK, age=3600)
    installed(log, "scripthookv", ["ScriptHookV.dll"], when=time.time() - 60)
    res = verify(game, [manifest.mod("scripthookv")], log)
    assert statuses(res, "scripthookv") == [NOT_SEEN]
    assert res[0].code == "log-older-than-install"
    general = [r for r in res if r.mod is None]
    assert general and general[0].code == "start-game-first"


def test_asi_missing_from_fresh_loader_log_is_a_warning(manifest, game, log):
    installed(log, "resourceextensions", ["ResourceExtensions.asi"])
    write_log(game, "asiloader.log", ASI_OK)
    res = verify(game, [manifest.mod("resourceextensions")], log)
    assert WARN in statuses(res, "resourceextensions")


def test_log_lookup_is_case_insensitive(manifest, game, log):
    installed(log, "scripthookv", ["ScriptHookV.dll"])
    write_log(game, "scripthookv.LOG", SHV_OK)
    assert statuses(verify(game, [manifest.mod("scripthookv")], log), "scripthookv") == [OK]


def test_mod_without_any_log_is_no_log(manifest, game, log):
    installed(log, "mapfixes", [])
    res = verify(game, [manifest.mod("mapfixes")], log)
    assert statuses(res, "mapfixes") == [NO_LOG]


def test_verify_never_writes_to_the_game_folder(manifest, game, log):
    installed(log, "scripthookv", ["ScriptHookV.dll"])
    write_log(game, "ScriptHookV.log", SHV_OK)
    before = sorted((p.relative_to(game).as_posix(), p.stat().st_mtime_ns) for p in game.rglob("*"))
    verify(game, list(manifest.mods.values()), log)
    assert sorted((p.relative_to(game).as_posix(), p.stat().st_mtime_ns) for p in game.rglob("*")) == before


def test_shv_tag_to_build():
    from leonida.verify import game_version_from_shv

    assert game_version_from_shv("VER_EN_1_0_1158_13") == "1.0.1158.13 (Enhanced)"
    assert game_version_from_shv("VER_1_0_2245_0_STEAM") == "1.0.2245.0"


def test_asi_failed_to_load_names_the_mod(manifest, game, log):
    installed(log, "openrpf", ["OpenRPF.asi"])
    write_log(game, "asiloader.log", ASI_OK)
    (r,) = verify(game, [manifest.mod("openrpf")], log)
    assert r.status == FAILED and r.code == "asi-failed"
    assert r.line.strip() == '"OpenRPF.asi" failed to load' and r.log == "asiloader.log"


def test_guided_mod_asi_found_in_game_folder(manifest, game, log):
    """OpenRPF is a guided install (no actions recorded for the .asi): it is checked when OpenRPF.asi is there."""
    installed(log, "openrpf", [])
    (game / "OpenRPF.asi").write_bytes(b"asi")
    write_log(game, "asiloader.log", ASI_OK.replace('"OpenRPF.asi" failed to load', '"OpenRPF.asi" => 00007FFAB3FE0000'))
    assert statuses(verify(game, [manifest.mod("openrpf")], log), "openrpf") == [OK]


def test_shv_exception_in_asi_is_a_failure(manifest, game, log):
    installed(log, "menyoo", ["Menyoo.asi"])
    write_log(game, "ScriptHookV.log", SHV_EXCEPTION)
    write_log(game, "menyooLog.txt", MENYOO_OK)
    res = by_mod(verify(game, [manifest.mod("menyoo")], log))["menyoo"]
    exc = [r for r in res if r.code == "asi-exception"]
    assert exc and "exception occurred while executing 'Menyoo.asi'" in exc[0].line


def test_shvdn_version_and_script_owner(manifest, game, log):
    installed(log, "shvdne", ["ScriptHookVDotNet.asi", "ScriptHookVDotNet3.dll"])
    installed(log, "combatcamera", ["scripts/GTA5-Quadcopter.dll"])
    installed(log, "immersivecombat", ["scripts/GoodScript.dll"])
    write_log(game, "ScriptHookV.log", SHV_OK)
    write_log(game, "asiloader.log", ASI_OK)
    write_log(game, "ScriptHookVDotNet.log", SHVDN)
    mods = [manifest.mod(m) for m in ("shvdne", "combatcamera", "immersivecombat")]
    res = by_mod(verify(game, mods, log))
    assert [r.status for r in res["shvdne"]] == [OK]
    assert "1.1.0.6" in res["shvdne"][0].message
    bad = res["combatcamera"]
    assert [r.status for r in bad] == [FAILED] and "GTA5-Quadcopter.dll" in bad[0].message
    assert "exception was thrown" in bad[0].line
    assert [r.status for r in res["immersivecombat"]] == [OK]


# The owner's real log after a Showcase play test (2026-11-25): Script Hook V .NET Enhanced lists every assembly
# first and starts the scripts afterwards, so ViWasted.dll is the last file found before EnableAllinteriors' scripts
# start. The blocking line names its own file and must not be pinned on the HUD's ViWasted.dll.
BLOCKING = ("[10:28:02] [ERROR] Blocking script! Script EnableAllinteriors.LoadMPMaps (file name: "
            "EnableAllinteriors.dll) was terminated because it caused the game to freeze too long.")
SHVDN_BATCHED = r"""
[10:26:40] [INFO] ScriptHookV .Net Enhanced 3.9.0.6 (1.1.0.6)
[10:26:41] [INFO] Found 2 script(s) in EnableAllinteriors.dll resolved to API version 3.7.0 (target API version: 3.7.0).
[10:26:41] [INFO] Found 1 script(s) in ViWasted.dll resolved to API version 3.7.0 (target API version: 3.7.0).
[10:26:42] [INFO] Started script EnableAllinteriors.Main.
[10:26:42] [INFO] Started script EnableAllinteriors.LoadMPMaps.
[10:26:42] [INFO] Started script ViWasted.ViWasted.
@BLOCKING@
[10:28:03] [WARNING] Aborted script Mystery.Thing.
""".lstrip("\n").replace("@BLOCKING@", BLOCKING)


def test_shvdn_failure_goes_to_the_file_it_names(manifest, game, log):
    installed(log, "shvdne", ["ScriptHookVDotNet.asi", "ScriptHookVDotNet3.dll"])
    installed(log, "hud-geckomacabre", ["scripts/ViWasted.dll"])
    installed(log, "enableallinteriors", ["scripts/EnableAllinteriors.dll"])
    write_log(game, "ScriptHookV.log", SHV_OK)
    write_log(game, "asiloader.log", ASI_OK)
    write_log(game, "ScriptHookVDotNet.log", SHVDN_BATCHED)
    mods = [manifest.mod(m) for m in ("shvdne", "hud-geckomacabre", "enableallinteriors")]
    res = by_mod(verify(game, mods, log))
    hud = [r for r in res["hud-geckomacabre"] if r.code.startswith("script")]
    assert [(r.status, r.code) for r in hud] == [(OK, "script-loaded")], [r.message for r in hud]
    eai = [r for r in res["enableallinteriors"] if r.code.startswith("script")]
    assert [r.status for r in eai] == [FAILED] and "EnableAllinteriors.dll" in eai[0].message
    assert "Blocking script!" in eai[0].line
    # a failure that names no file and whose class no file owns: listed under Script Hook V .NET, not guessed
    unknown = [r for r in res["shvdne"] if r.code == "script-failed-unknown"]
    assert [r.status for r in unknown] == [WARN] and "Mystery.Thing" in unknown[0].line


def test_shvdn_owner_map_only_from_evidence():
    from leonida.verify import LogFile, _line_mentions_file, _shvdn_owner_map

    lf = LogFile("ScriptHookVDotNet.log", 0.0, SHVDN_BATCHED.splitlines())
    owners = _shvdn_owner_map(lf)
    assert owners == {"EnableAllinteriors.Main": "EnableAllinteriors.dll",
                      "EnableAllinteriors.LoadMPMaps": "EnableAllinteriors.dll", "ViWasted.ViWasted": "ViWasted.dll"}
    blocking = BLOCKING
    assert not _line_mentions_file(blocking, "ViWasted.dll", owners)
    assert _line_mentions_file(blocking, "EnableAllinteriors.dll", owners)
    assert _line_mentions_file("[INFO] Started script ViWasted.ViWasted.", "ViWasted.dll", owners)
    # one file loaded: its scripts are its own whatever their namespace
    one = LogFile("x", 0.0, ["[INFO] Found 1 script(s) in GTA5-Quadcopter.dll resolved to API version 3.7.0",
                        "[INFO] Started script Quadcopter.MainScript."])
    assert _shvdn_owner_map(one) == {"Quadcopter.MainScript": "GTA5-Quadcopter.dll"}


# Exact lines of the owner's real ScriptHookVDotNet.log (full Showcase play test, 2026-11-25): every "Found N
# script(s)" first (.cs files, then .dll files), then the scripts start; All MP Vehicles in SP.dll (a name with
# spaces) runs SpawnMP / TrafficMP / SaveVehicleScript, names that say nothing about their file.
SHVDN_REAL = [
    '[10:39:50] [INFO] ScriptHookV .Net Enhanced 3.9.0.6 (1.1.0.6)',
    '[10:39:56] [DEBUG] Loading scripts from D:\\Games\\Grand Theft Auto V Enhanced\\scripts ...',
    ('[10:39:57] [DEBUG] Successfully compiled BulletNearMissFlinch.cs using API version 3.9.0. If you fin'
     'd the script not working as the author(s) intended, you could annotate an API version by adding a do'
     't and a single-digit number for API version before the extension (e.g. "BulletNearMissFlinch.2.cs").'),
    ('[10:39:57] [INFO] Found 1 script(s) in BulletNearMissFlinch.cs resolved to API version 3.9.0 (target'
     ' API version: 3.9.0).'),
    '[10:39:57] [DEBUG] Successfully compiled MapUpdates.3.cs.',
    ('[10:39:57] [INFO] Found 1 script(s) in MapUpdates.3.cs resolved to API version 3.9.0 (target API ver'
     'sion: 3.9.0).'),
    '[10:39:57] [DEBUG] Loading assembly All MP Vehicles in SP.dll ...',
    ('[10:39:57] [INFO] Found 3 script(s) in All MP Vehicles in SP.dll resolved to API version 3.9.0 (targ'
     'et API version: 3.6.0).'),
    '[10:39:57] [DEBUG] Loading assembly BennysMotorworksRevamped.dll ...',
    ('[10:39:57] [INFO] Found 2 script(s) in BennysMotorworksRevamped.dll resolved to API version 3.9.0 (t'
     'arget API version: 3.7.0).'),
    '[10:39:57] [DEBUG] Loading assembly EnableAllinteriors.dll ...',
    ('[10:39:57] [INFO] Found 6 script(s) in EnableAllinteriors.dll resolved to API version 3.9.0 (target '
     'API version: 3.7.0).'),
    '[10:39:57] [DEBUG] Loading assembly ViWasted.dll ...',
    ('[10:39:57] [INFO] Found 1 script(s) in ViWasted.dll resolved to API version 3.9.0 (target API versio'
     'n: 3.7.0).'),
    '[10:39:57] [DEBUG] Instantiating script SaveVehicleScript ...',
    '[10:39:57] [INFO] Started script SaveVehicleScript.',
    '[10:39:57] [DEBUG] Instantiating script SpawnMP ...',
    '[10:39:58] [INFO] Started script SpawnMP.',
    '[10:39:58] [DEBUG] Instantiating script TrafficMP ...',
    '[10:39:58] [INFO] Started script TrafficMP.',
    '[10:39:58] [DEBUG] Instantiating script BennysMotorworksRevamped.Bennys ...',
    '[10:39:58] [INFO] Started script BennysMotorworksRevamped.Bennys.',
    '[10:39:58] [DEBUG] Instantiating script BennysMotorworksRevamped.BennysMenu ...',
    '[10:39:58] [INFO] Started script BennysMotorworksRevamped.BennysMenu.',
    '[10:39:58] [DEBUG] Instantiating script EnableAllinteriors.CayoMines ...',
    '[10:39:58] [INFO] Started script EnableAllinteriors.CayoMines.',
    '[10:39:58] [DEBUG] Instantiating script EnableAllinteriors.Class1 ...',
    '[10:39:59] [INFO] Started script EnableAllinteriors.Class1.',
    '[10:39:59] [DEBUG] Instantiating script EnableAllinteriors.LoadMPMaps ...',
    '[10:39:59] [INFO] Started script EnableAllinteriors.LoadMPMaps.',
    '[10:39:59] [DEBUG] Instantiating script EnableAllinteriors.ManageCayoPerico ...',
    '[10:39:59] [INFO] Started script EnableAllinteriors.ManageCayoPerico.',
    '[10:39:59] [DEBUG] Instantiating script EnableAllinteriors.ManageSnow ...',
    '[10:39:59] [INFO] Started script EnableAllinteriors.ManageSnow.',
    '[10:39:59] [DEBUG] Instantiating script EnableAllinteriors.OpenClosedDoors ...',
    '[10:39:59] [INFO] Started script EnableAllinteriors.OpenClosedDoors.',
    '[10:39:59] [DEBUG] Instantiating script MapUpdates.Main ...',
    '[10:39:59] [INFO] Started script MapUpdates.Main.',
    '[10:39:59] [DEBUG] Instantiating script BulletNearMissFlinch ...',
    '[10:39:59] [INFO] Started script BulletNearMissFlinch.',
    '[10:40:00] [INFO] Started script ViWasted.ViWasted.',
]


def test_shvdn_real_log_scripts_go_to_their_files(manifest, game, log):
    installed(log, "shvdne", ["ScriptHookVDotNet.asi", "ScriptHookVDotNet3.dll"])
    owned = {"allmpvehicles": "All MP Vehicles in SP.dll", "hud-geckomacabre": "ViWasted.dll",
             "enableallinteriors": "EnableAllinteriors.dll", "bennys": "BennysMotorworksRevamped.dll",
             "mapupdates": "MapUpdates.3.cs", "cameraflinch": "BulletNearMissFlinch.cs"}
    for mod, name in owned.items():
        installed(log, mod, [f"scripts/{name}"])
    write_log(game, "ScriptHookV.log", SHV_OK)
    write_log(game, "asiloader.log", ASI_OK)
    write_log(game, "ScriptHookVDotNet.log", "\n".join([*SHVDN_REAL, BLOCKING]) + "\n")
    res = by_mod(verify(game, [manifest.mod(m) for m in ("shvdne", *owned)], log))
    scripts = {m: [(r.status, r.code) for r in res[m] if r.code.startswith("script")] for m in owned}
    assert scripts == {m: [(OK, "script-loaded")] for m in owned if m != "enableallinteriors"} | {
        "enableallinteriors": [(FAILED, "script-failed")]}, scripts
    eai = next(r for r in res["enableallinteriors"] if r.code == "script-failed")
    assert eai.line == BLOCKING and "EnableAllinteriors.dll" in eai.message
    allmp = next(r for r in res["allmpvehicles"] if r.code == "script-loaded")
    assert "Found 3 script(s) in All MP Vehicles in SP.dll" in allmp.line
    assert not [r for r in res["shvdne"] if r.code == "script-failed-unknown"]


def test_shvdn_real_log_owner_map():
    from leonida.verify import LogFile, _line_mentions_file, _shvdn_owner_map

    lf = LogFile("ScriptHookVDotNet.log", 0.0, [*SHVDN_REAL, BLOCKING])
    owners = _shvdn_owner_map(lf)
    assert {c: owners[c] for c in ("SaveVehicleScript", "SpawnMP", "TrafficMP")} == dict.fromkeys(
        ("SaveVehicleScript", "SpawnMP", "TrafficMP"), "All MP Vehicles in SP.dll")
    assert owners["EnableAllinteriors.LoadMPMaps"] == "EnableAllinteriors.dll"
    assert owners["ViWasted.ViWasted"] == "ViWasted.dll"
    assert owners["MapUpdates.Main"] == "MapUpdates.3.cs" and owners["BulletNearMissFlinch"] == "BulletNearMissFlinch.cs"
    assert owners["BennysMotorworksRevamped.BennysMenu"] == "BennysMotorworksRevamped.dll"
    mine = [ln for ln in lf.lines if _line_mentions_file(ln, "All MP Vehicles in SP.dll", owners)]
    assert mine[:2] == ["[10:39:57] [DEBUG] Loading assembly All MP Vehicles in SP.dll ...",
                        "[10:39:57] [INFO] Found 3 script(s) in All MP Vehicles in SP.dll resolved to API version "
                        "3.9.0 (target API version: 3.6.0)."]
    assert "[10:39:58] [INFO] Started script SpawnMP." in mine and BLOCKING not in mine
    assert not [ln for ln in lf.lines if _line_mentions_file(ln, "SP.dll", owners)]  # not half of a spaced name
    assert not _line_mentions_file(BLOCKING, "ViWasted.dll", owners)
    # counts that don't add up: the scripts left get no file rather than a guess
    odd = LogFile("x", 0.0, ["[INFO] Found 2 script(s) in A.dll resolved to API version 3.9.0",
                             "[INFO] Started script One.", "[INFO] Started script Two.", "[INFO] Started script Three."])
    assert _shvdn_owner_map(odd) == {}


def test_shvdn_missing_script_is_warning(manifest, game, log):
    installed(log, "shvdne", ["ScriptHookVDotNet.asi"])
    installed(log, "combatcamera", ["scripts/NotThere.dll"])
    write_log(game, "ScriptHookVDotNet.log", SHVDN)
    res = verify(game, [manifest.mod("shvdne"), manifest.mod("combatcamera")], log)
    assert statuses(res, "combatcamera") == [WARN]


def test_menyoo_ok_unknown_build_and_placeholder(manifest, game, log):
    installed(log, "menyoo", ["Menyoo.asi"])
    write_log(game, "asiloader.log", ASI_OK)
    write_log(game, "menyooLog.txt", MENYOO_OK)
    res = verify(game, [manifest.mod("menyoo")], log)
    assert statuses(res, "menyoo") == [OK] and "2.4.4" in res[0].message

    write_log(game, "menyooLog.txt", MENYOO_UNKNOWN)
    codes = {r.code: r.status for r in verify(game, [manifest.mod("menyoo")], log)}
    assert codes == {"menyoo-unknown-build": WARN, "menyoo-error": FAILED}

    write_log(game, "menyooLog.txt", MENYOO_PLACEHOLDER)
    codes = [r.code for r in verify(game, [manifest.mod("menyoo")], log)]
    assert "menyoo-placeholder" in codes


def test_directstoragefix(manifest, game, log):
    installed(log, "directstoragefix", ["DirectStorageFix.asi"])
    write_log(game, "asiloader.log", '     "DirectStorageFix.asi" => 00007FFDA0000000\n')
    write_log(game, "DirectStorageFix.log", DSF_OK)
    (r,) = verify(game, [manifest.mod("directstoragefix")], log)
    assert r.status == OK and "1013.20" in r.message
    write_log(game, "DirectStorageFix.log", DSF_FAIL)
    (r,) = verify(game, [manifest.mod("directstoragefix")], log)
    assert r.status == FAILED and "RegisterFile" in r.line
    write_log(game, "DirectStorageFix.log", "[02:39:15.102] [info] Game build < 1013. Stopping.\n")
    (r,) = verify(game, [manifest.mod("directstoragefix")], log)
    assert r.status == WARN and "doesn't need it" in r.message


def test_verify_session(manifest, game, state):
    from leonida.session import Session
    from leonida.verify import verify_session

    s = Session(state=state, game_dir=str(game), game_build="1.0.1013.20")
    assert verify_session(s) == []
    installed(s.log, "scripthookv", ["ScriptHookV.dll"])
    write_log(game, "ScriptHookV.log", SHV_OK)
    res = verify_session(s)
    assert [r.status for r in res] == [OK] and "1.0.1013.20 (Enhanced)" in res[0].message


def test_cli_verify(game, state, capsys):
    lg = L.InstallLog(state / "install-log.json")
    installed(lg, "scripthookv", ["ScriptHookV.dll"])
    write_log(game, "ScriptHookV.log", SHV_UNKNOWN)
    code = cli_main(["--state-dir", str(state), "--game-dir", str(game), "verify", "--lines"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAILED" in out and "Unknown game version" in out


def test_cli_verify_nothing_installed(game, state, capsys):
    assert cli_main(["--state-dir", str(state), "--game-dir", str(game), "verify"]) == 0
    assert "Nothing installed" in capsys.readouterr().out


# ---------------------------------------------------------------- opt-in real-file e2e
E2E_DOWNLOADS = os.environ.get("LEONIDA_E2E_DOWNLOADS")


@pytest.mark.e2e
@pytest.mark.skipif(not E2E_DOWNLOADS, reason="set LEONIDA_E2E_DOWNLOADS (folder with the real SHVDNE and Menyoo "
                                               "zips) to run the real-file install test")
def test_real_archives_install_rollback_uninstall(tmp_path):
    """build/e2e_real_install.py on the real downloaded archives, in a temp folder with a fake game folder."""
    script = Path(__file__).resolve().parent.parent / "build" / "e2e_real_install.py"
    spec = importlib.util.spec_from_file_location("e2e_real_install", script)
    e2e = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = e2e  # dataclasses look the module up while the class is created
    spec.loader.exec_module(e2e)
    rep = e2e.run(Path(E2E_DOWNLOADS), workdir=tmp_path / "e2e")
    assert rep.passed, "\n".join(rep.problems)
    assert not [m for m in rep.manifest_issues if "REQUIRED" in m], rep.manifest_issues
