import json
import os
import time

import pytest
from conftest import make_zip

from leonida.archive import ArchiveError, extract, list_members
from leonida.detect import _epic_candidates, compare_versions, is_rtx50, parse_vdf_library_paths
from leonida.matcher import build_lock, match_files, scan_folder, verify_lock

REAL_NAMES = {
    "ScriptHookV_1.0.1158.13.zip": "scripthookv",
    "ScriptHookVDotNet-Enhanced-v1.1.0.6.zip": "shvdne",
    "ResourceExtensions_2.3.1.zip": "resourceextensions",
    "NaturalVision Enhanced Update 3.zip": "nve",
    "Drive V for NVE.zip": "drivevnve",
    "NextGen Euphoria 2.0.zip": "nextgeneuphoria",
    "GTA VI Combat Camera Enhanced.zip": "combatcamera",
    "GTA VI Inspired HUD Enhanced 0.9.9.zip": "hud",
    "MenyooSP 2.4.4.zip": "menyoo",
    "Bugstar Fixes 7.8.zip": "bugstarfixes",
    "All MP Vehicles in SP 4.0.1.zip": "allmpvehicles",
    "Better Vehicle Deformation for NVE.zip": "bettervehdeform",
    "DLSS5-Swapper-Setup-2.2.9.exe": "dlss5swapper",
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
