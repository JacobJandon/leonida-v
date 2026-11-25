"""The bundled GTA V Legacy manifest set: real download names, member rules and game builds."""

from __future__ import annotations

import pytest

from leonida.manifest import build_key, load_manifest
from leonida.matcher import match_files
from leonida.members import member_problem


@pytest.fixture(scope="module")
def legacy():
    return load_manifest(edition="legacy")


# real Legacy download names (the owner's D:\Leonida\Downloads and _wrong-edition, 2026-11-24/25)
REAL_LEGACY_NAMES = {
    "ScriptHookV_3889.0_1158.13.zip": "scripthookv",
    "ScriptHookVDotNet-v3.7.0-nightly.206.zip": "shvdn",
    "GTA-VI-Inspired-HUD-2.8.2-Legacy.oiv": "hud-geckomacabre",
    "MenyooSP.zip": "menyoo",
    "LemonUI.zip": "lemonui",
    "a7e45e-All-MP-Vehicles-in-SP-4.0.1.zip": "allmpvehicles",
    "655b1c-DriveV 7.4.zip": "drivev",
    "GTA-VI-Inspired-HUD-2.8.2-LoadingScreens-Legacy.oiv": "hud-loadingscreens",
    "HeapAdjusterEnhanced.zip": "heapadjuster",                     # the author's GitHub release name
    "PackFileLimitAdjusterEnhanced.zip": "packfilelimit",
    "NextGen Euphoria (Legacy)-1258-1-0-1743616030.rar": "nextgeneuphoria",   # Nexus naming, mod 1258
    "gameconfig.xml": "gameconfig",
    "b719fd-StraightToStoryMode.zip": "straighttostory",
    "5e056b-MapFixes_v21.8.2_NG.rar": "mapfixes",
    "be6621-BugstarFixes_v7.8.1_NG.rar": "bugstarfixes",
    "616d61-Burgershot.rar": "burgershot",
    "28e509-UpnAtomBurger_v11.zip": "upnatom",
    "2cfaff-ElginHawick247shop_v10a.zip": "elgin247",
    "22190d-VinewoodPlaza247shopv102a.zip": "vinewood247",
    "ee7395-StreetFoodVenders.1.2.1.0-Legacy.rar": "streetfood",
    "f5db70-MapUpdates_v3.1.3.rar": "mapupdates",
    "b1d333-IC 1 9.1.zip": "immersivecombat",
    "52ccdb-BennysMotorWorksRevamped_v1.3.2.zip": "bennys",
    "ActionsV.zip": "actionsv",
}


def test_legacy_set_has_a_free_core(legacy):
    core = legacy.resolve("core")
    assert {m.id for m in core} == {"scripthookv", "shvdn", "openiv", "allmpvehicles", "drivev", "nextgeneuphoria",
                                    "hud-geckomacabre", "menyoo", "straighttostory"}
    assert not any(m.is_paid for m in legacy.mods.values())
    for m in legacy.mods.values():
        assert m.page.startswith("https://") and m.archive, m.id
    for p in legacy.profiles:
        assert legacy.resolve(p), p


def test_real_legacy_names_match(legacy, tmp_path):
    files = []
    for name in REAL_LEGACY_NAMES:
        (tmp_path / name).write_bytes(b"x")
        files.append(tmp_path / name)
    got = {mid: p.name for mid, p in match_files(legacy.mods.values(), files).matched.items()}
    for name, mid in REAL_LEGACY_NAMES.items():
        assert got.get(mid) == name, (mid, name)


def test_enhanced_files_are_not_taken_for_legacy(legacy, tmp_path):
    for name in ("NextGen Euphoria-1-1-3-1747367011.rar", "GTA-VI-Inspired-HUD-2.8.2-LoadingScreens-Enhanced.oiv"):
        f = tmp_path / name
        f.write_bytes(b"x")
        assert not match_files(legacy.mods.values(), [f]).matched, name
    hud = tmp_path / "GTA-VI-Inspired-HUD-2.8.2-Enhanced.oiv"
    hud.write_bytes(b"x")
    assert "hud-geckomacabre" not in match_files(legacy.mods.values(), [hud]).matched
    # same names on both editions: the archive contents decide (real member paths)
    assert "spmapfixes_gen9" in member_problem(legacy.mod("mapfixes"), [
        "Enhanced/spMapFixes_Gen9/dlc.rpf", "Enhanced/MP Map Fixes.oiv"]).lower()
    assert member_problem(legacy.mod("mapfixes"), ["Legacy/spmapfixes/dlc.rpf", "Legacy/MP Map Fixes Pack 1.oiv"]) is None
    assert "elg_247shop_g9" in member_problem(legacy.mod("elgin247"), ["SP/elg_247shop_g9/dlc.rpf"])
    assert "ScriptHookVDotNet-Loader.asi" in member_problem(legacy.mod("shvdn"), [
        "ScriptHookVDotNet.asi", "ScriptHookVDotNet3.dll"])            # SHVDNE's layout: not the HUD's pick
    assert member_problem(legacy.mod("gtavremastered"), ["GTA V Enhanced/vremastered/dlc.rpf"]) is not None


@pytest.mark.parametrize("build, drive, gameconfig, out", [
    ("1.0.3442.0", "6.8", "GTA V 3407 - Agents of Sabotage Update", {"mapfixes", "bugstarfixes"}),
    ("1.0.3586.0", "7.3", "GTA V 3570 - Money Fronts Update", {"mapfixes", "bugstarfixes"}),
    ("1.0.3725.0", "7.4", "GTA V 3717 - Safehouse in the Hills Update", set()),
    ("1.0.3788.0", "7.4", "GTA V 3788 - March 2026 minor update", set()),
    ("1.0.3889.0", "7.5 or newer", "GTA V 3899 - Kortz Center Heist Update", set()),
])
def test_legacy_builds_resolve(legacy, build, drive, gameconfig, out):
    m = legacy.for_build(build)
    assert m.mod("drivev").version == drive and m.mod("gameconfig").version == gameconfig
    assert {x.id for x in m.resolve("core-plus") if x.unsupported} == out
    gc = m.mod("gameconfig").download
    assert build_key(build) >= build_key("1.0.3889.0") or gc.get("tag", "").lstrip("v") <= build.split(".")[2]
    for x in m.mods.values():
        assert x.unsupported or x.version, (build, x.id)


def test_legacy_hotkeys_belong_to_legacy_mods(legacy):
    for k in legacy.hotkeys:
        assert k["mod"] in legacy.mods, k


def test_lwe_public_release_is_the_free_edition_and_one_vegetation_mod(legacy):
    from leonida.manifest import load_manifest as lm
    enh = lm()
    route = enh.mod("lwe").free_route
    assert route["type"] == "freeEdition" and route["page"] == legacy.mod("lwe-free").page
    assert "gta5-mods.com/maps/lively-world-expansion-free-2022-release" in route["page"]
    for m in (enh, legacy):  # one vegetation mod at a time (they plant trees in the same places)
        veg = {x.id for x in m.mods.values() if x.slot == "vegetation"}
        assert "gtavremastered" in veg and veg & {"lwe", "lwe-free"}
    assert "re-upload" in enh.mod("nve").notes and enh.mod("nve").free_route["mod"] == "visualv"
