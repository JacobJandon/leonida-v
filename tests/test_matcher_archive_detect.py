import json
import os
import time

import pytest
from conftest import make_zip

from leonida.archive import ArchiveError, extract, list_members
from leonida.detect import _epic_candidates, compare_versions, is_rtx50, parse_vdf_library_paths
from leonida.matcher import build_lock, match_files, scan_folder, verify_lock

REAL_NAMES = {
    "ScriptHookV_3889.0_1158.13.zip": "scripthookv",
    "ScriptHookVDotNetEnhanced-v1.1.0.6.zip": "shvdne",
    "3ba441-ResourceExtensions_v2.5.zip": "resourceextensions",
    "NaturalVision Enhanced Update 3.zip": "nve",
    "NextGen Euphoria-1-1-3-1747367011.rar": "nextgeneuphoria",
    "03acfd-VI_Combat_Camera_for_GTA_V_Enhanced_v1.0_by_klennys.zip": "combatcamera",
    "GTA VI Inspired HUD Enhanced 0.9.9.zip": "hud",
    "MenyooSP.zip": "menyoo",
    "LemonUI.zip": "lemonui",
    "ActionsV.zip": "actionsv",
    "b719fd-StraightToStoryMode.zip": "straighttostory",
    "GTA-VI-Inspired-HUD-2.8.2-Enhanced.oiv": "hud-geckomacabre",
    "978dba-BugstarFixes_v7.8.1_Gen9.rar": "bugstarfixes",
    "6b9a30-DriveV 7.5.zip": "drivev",
    "a7e45e-All-MP-Vehicles-in-SP-4.0.1.zip": "allmpvehicles",
    "62594c-Realistic Deformation for NVE v3.rar": "bettervehdeform",
    # real downloads (gta5-mods adds a random hex prefix), 2026-11-24
    "58cd7d-DirectStorageFix.zip": "directstoragefix",
    "6d0158-OpenRPF.zip": "openrpf",
    "383134-MapFixes_v21.8.2_Gen9.rar": "mapfixes",
    "0dee19-Enable All Interiors Mod FIles 47.1.1 (Fix Missing Method for GTAO Mansions In SP).zip": "enableallinteriors",
    "b1d333-IC 1 9.1.zip": "immersivecombat",
    "51cc88-StreetFoodVenders.1.2.1.0-Enhanced.rar": "streetfood",
    "Better Fist Fighting-36-1-1748117059.rar": "betterfistfighting",
    "DriveV 7.5.1 GTA V Enhanced NVE 1093 7.5.1 2026-10-02T19-18Z DwRrugWLu.rar": "drivevnve",
    "Mmd Jason Duval Houses 1265 1 2026-08-07T16-37Z Ge12K4vko.7z": "jasonhouse",
    "52ccdb-BennysMotorWorksRevamped_v1.3.2.zip": "bennys",
    "f5db70-MapUpdates_v3.1.3.rar": "mapupdates",
    "820510-OpenWorldInteriors0.4.zip": "openworldinteriors",
    "fea021-VI Camera Flinch.rar": "cameraflinch",
    "66ab92-Burgershot_new.rar": "burgershot",
    "adffac-UpnAtomBurger_v11Enh.zip": "upnatom",
    "291712-ElginHawick247shop_v10aEnh.zip": "elgin247",
    "9e9e72-VinewoodPlaza247shopv102aEnh.zip": "vinewood247",
    "58b535-GTA V Remastered Enhanced v6.0-SP.zip": "gtavremastered",
    "de70de-Natural Vision Enhanced Traffic V FEAR Edition v1.3.rar": "trafficvfear",
}


def test_real_world_names_match(manifest, tmp_path):
    files = []
    for name in REAL_NAMES:
        p = tmp_path / name
        p.write_bytes(b"x")
        files.append(p)
    res = match_files(manifest.mods.values(), files)
    got = {mid: p.name for mid, p in res.matched.items()}
    for name, mid in REAL_NAMES.items():
        assert got.get(mid) == name, (mid, name, res.ambiguous)
    assert not res.unmatched



# Real downloads of the Legacy build of a mod Leonida only installs for Enhanced: must not be accepted.
LEGACY_ONLY_NAMES = {
    "ee7395-StreetFoodVenders.1.2.1.0-Legacy.rar": "streetfood",
    "616d61-Burgershot.rar": "burgershot",  # Legacy v2.0: same contents layout as the Enhanced file
    "28e509-UpnAtomBurger_v11.zip": "upnatom",
}


def test_legacy_downloads_are_not_accepted(manifest, tmp_path):
    for name, mid in LEGACY_ONLY_NAMES.items():
        p = tmp_path / name
        p.write_bytes(b"x")
        res = match_files(manifest.mods.values(), [p])
        assert mid not in res.matched, (mid, name)
    hit = tmp_path / "f00baa-StreetFoodVenders.1.2.1.0-Enhanced.rar"
    hit.write_bytes(b"x")
    assert match_files(manifest.mods.values(), [hit]).matched.get("streetfood") == hit


def test_partial_downloads_ignored(downloads):
    (downloads / "Drive V for NVE.zip.crdownload").write_bytes(b"x")
    (downloads / "Drive V for NVE.zip").write_bytes(b"x")
    assert [p.name for p in scan_folder(downloads)] == ["Drive V for NVE.zip"]


def test_assignment_overrides(manifest, downloads):
    p = downloads / "random-name-123.zip"
    p.write_bytes(b"x")
    res = match_files(manifest.mods.values(), [p], {"random-name-123.zip": "openrpf"})
    assert res.matched["openrpf"] == p


def test_newest_duplicate_wins(manifest, downloads):
    old = downloads / "Menyoo 2.4.3.zip"
    new = downloads / "Menyoo 2.4.4.zip"
    old.write_bytes(b"a")
    new.write_bytes(b"b")
    past = time.time() - 1000
    os.utime(old, (past, past))
    res = match_files(manifest.mods.values(), [old, new])
    assert res.matched["menyoo"] == new
    assert res.duplicates["menyoo"] == [old]


def test_lock_roundtrip(downloads):
    p = downloads / "a.zip"
    p.write_bytes(b"hello")
    lock = build_lock("Leonida V", "1.0.0", {"m": p})
    assert verify_lock(lock, {"m": p}) == []
    p.write_bytes(b"changed!")
    assert verify_lock(lock, {"m": p})


def test_zip_slip_rejected(tmp_path):
    z = make_zip(tmp_path / "evil.zip", {"../../outside.txt": "x"})
    with pytest.raises(ArchiveError):
        extract(z, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()


def test_list_members_skips_dirs(tmp_path):
    z = make_zip(tmp_path / "a.zip", {"bin/ScriptHookV.dll": "x", "bin/dinput8.dll": "y"})
    assert sorted(list_members(z)) == ["bin/ScriptHookV.dll", "bin/dinput8.dll"]


def test_7z_without_7zip(tmp_path):
    p = tmp_path / "a.7z"
    p.write_bytes(b"7z")
    with pytest.raises(ArchiveError, match="7-Zip"):
        list_members(p, None)


def test_vdf_paths():
    text = ('"libraryfolders"\n{\n "0"\n {\n  "path"  "C:\\\\Program Files (x86)\\\\Steam"\n }\n'
            ' "1"\n {\n  "path"  "D:\\\\SteamLibrary"\n }\n}')
    assert parse_vdf_library_paths(text) == [r"C:\Program Files (x86)\Steam", r"D:\SteamLibrary"]


def test_epic_manifest(tmp_path):
    (tmp_path / "x.item").write_text(json.dumps({"DisplayName": "Grand Theft Auto V Enhanced",
                                                 "InstallLocation": "E:/Epic/GTAV"}))
    (tmp_path / "y.item").write_text(json.dumps({"DisplayName": "Fortnite", "InstallLocation": "E:/Epic/FN"}))
    assert [str(p) for p in _epic_candidates(tmp_path)] == [str(__import__("pathlib").Path("E:/Epic/GTAV"))]


def test_versions_and_gpu():
    assert compare_versions("1.0.1158.14", "1.0.1158.13") == 1
    assert compare_versions("1.0.1158.13", "1.0.1158.13") == 0
    assert compare_versions("1.0.1013.34", "1.0.1158.13") == -1
    assert compare_versions(None, "1") is None
    assert is_rtx50(["NVIDIA GeForce RTX 5080"])
    assert not is_rtx50(["NVIDIA GeForce RTX 4090", "AMD Radeon RX 9070"])
