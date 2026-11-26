"""GTA V's own settings.xml as a locked-settings target outside the game folder (leonida/gamesettings.py): values per
variant and PC, written in a logged step with the player's file backed up, drift, unlock, rollback, file check.
Everything runs on a fake Documents folder (tests/conftest.py sets LEONIDA_DOCUMENTS_DIR)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import AutoUI

from leonida import filecheck
from leonida import gamesettings as G
from leonida import settings as S
from leonida.installer import Installer
from leonida.log import InstallLog
from leonida.manifest import load_manifest

GTX1070 = G.PC(15.8, 8.0, ("NVIDIA GeForce GTX 1070",))
RTX4080 = G.PC(31.9, 16.0, ("NVIDIA GeForce RTX 4080",))
SEL = {"hud-geckomacabre", "trafficvfear"}
# shape and values of the owner's real file (1.0.1013.20, GTX 1070, read 2026-11-25), shortened
SETTINGS_XML = """<?xml version="1.0" encoding="UTF-8"?>\r\n\r\n<Settings>\r\n  <version value="34" />\r\n
  <configSource>SMC_AUTO</configSource>\r\n  <graphics>\r\n    <ShadowQuality value="3" />\r\n
    <TextureQuality value="2" />\r\n    <GrassQuality value="3" />\r\n    <ResScalingType value="0" />\r\n
    <FrameGenType value="0" />\r\n    <CityDensity value="1.000000" />\r\n    <PedVarietyMultiplier value="1.000000" />\r\n
    <VehicleVarietyMultiplier value="1.000000" />\r\n    <HdStreamingInFlight value="true" />\r\n
    <MaxLodScale value="0.000000" />\r\n    <Raytracing_Enabled value="false" />\r\n  </graphics>\r\n  <video>\r\n
    <ScreenWidth value="1920" />\r\n    <Windowed value="0" />\r\n  </video>\r\n
  <VideoCardDescription>NVIDIA GeForce GTX 1070</VideoCardDescription>\r\n</Settings>\r\n""".replace("\r\n\n", "\r\n")


def _values(ws):
    return {w.key.split("/")[1]: (w.value, w.source) for w in ws}


def test_bundled_rules_are_valid_and_documents_based():
    rules = G.load_rules()
    G.validate(rules)
    assert rules["files"]["enhanced"] == "{documents}/Rockstar Games/GTAV Enhanced/settings.xml"
    assert S.resolve("D:/Game", rules["files"]["enhanced"]) == Path(os.environ[S.DOCUMENTS_ENV]) / \
        "Rockstar Games/GTAV Enhanced/settings.xml"
    assert S.resolve("D:/Game", "scripts/x.ini") == Path("D:/Game/scripts/x.ini")


def test_values_follow_the_variant_and_the_pc():
    owner16 = _values(G.wanted("enhanced", "owner-pick", "ram16", SEL, GTX1070))
    assert owner16["Windowed"][0] == "2"                                    # the HUD's minimap needs borderless
    # the card's tier (video memory): the game's own Ultra-level choice, measured at 4.0-4.5 GB of 8 GB
    assert owner16["TextureQuality"] == ("2", "your graphics card (top tier, 16 GB RAM; NVIDIA GeForce GTX 1070; "
                                         "8 GB video memory)")
    assert owner16["CityDensity"] == ("0.800000", "variant ram16")
    assert owner16["HdStreamingInFlight"][0] == "false" and owner16["MaxLodScale"][0] == "0.000000"
    assert owner16["Raytracing_Enabled"][0] == "false" and owner16["ResScalingType"][0] == "0"
    assert owner16["FrameGenType"][0] == "0"
    big = _values(G.wanted("enhanced", "owner-pick", "ram32", SEL, RTX4080))
    assert big["CityDensity"] == ("1.000000", "variant ram32")
    # a 16 GB RTX 40 card: the top tier; ray tracing, upscaling, frame generation and distance stay the player's
    assert big["TextureQuality"][0] == "2" and big["ShadowQuality"][0] == "3"
    assert not {"Raytracing_Enabled", "ResScalingType", "FrameGenType", "MaxLodScale", "HdStreamingInFlight"} & set(big)
    # another pack, no variant: the PC decides; without the HUD the screen type isn't locked
    core = _values(G.wanted("enhanced", "core", None, {"trafficvfear"}, GTX1070))
    assert core["CityDensity"][1].startswith("your PC") and "Windowed" not in core
    # unknown PC facts never match; Legacy's file has no ray tracing / upscaler / frame generation keys
    assert set(_values(G.wanted("enhanced", "core", None, set(), G.PC()))) == set()
    legacy = _values(G.wanted("legacy", "core", None, SEL, GTX1070))
    assert "Raytracing_Enabled" not in legacy and "TextureQuality" not in legacy and "CityDensity" in legacy


def _setup(tmp_path):
    docs = Path(os.environ[S.DOCUMENTS_ENV])
    xml = docs / "Rockstar Games" / "GTAV Enhanced" / "settings.xml"
    xml.parent.mkdir(parents=True, exist_ok=True)
    xml.write_bytes(SETTINGS_XML.encode("utf-8"))
    game, state = tmp_path / "game", tmp_path / "state"
    game.mkdir()
    (game / "GTA5_Enhanced.exe").write_bytes(b"MZ")
    log = InstallLog(state / "log.json")
    inst = Installer(load_manifest(), game, state, log, AutoUI())
    return xml, game, state, log, inst


def test_write_drift_unlock_and_rollback_on_a_fake_documents_folder(tmp_path):
    xml, game, state, log, inst = _setup(tmp_path)
    original = xml.read_bytes()
    wanted = G.wanted("enhanced", "owner-pick", "ram16", SEL, GTX1070)
    # Windowed, density x3, HD streaming; the fixture's Texture 2 / Grass 3 / Shadow 3 are the card's tier already,
    # and the tier's other keys aren't in the shortened fixture
    tier_missing = [d for d in S.drift(game, wanted) if d.have is None]
    assert len(S.drift(game, wanted)) - len(tier_missing) == 5
    # a dry run writes nothing
    dry = Installer(load_manifest(), game, state, log, AutoUI(), dry_run=True)
    assert dry.apply_settings(G.Pseudo(), wanted) is None and xml.read_bytes() == original
    step = inst.apply_settings(G.Pseudo(), wanted)
    assert step.mod == "settings:gta-settings"
    (action,) = step.actions
    assert action.op == "replace" and action.path == "{documents}/Rockstar Games/GTAV Enhanced/settings.xml"
    assert (state / action.backup).read_bytes() == original           # the player's file, backed up first
    text = xml.read_text(encoding="utf-8")
    assert S.xml_get(text, "video/Windowed/@value") == "2" and S.xml_get(text, "graphics/CityDensity/@value") == \
        "0.800000"
    assert S.xml_get(text, "graphics/ShadowQuality/@value") == "3"   # keys Leonida doesn't lock stay the game's
    assert "<VideoCardDescription>NVIDIA GeForce GTX 1070</VideoCardDescription>" in text
    assert S.drift(game, wanted) == [] and inst.apply_settings(G.Pseudo(), wanted) is None
    # the file check follows the {documents} path (no "missing" for it)
    assert not [p for p in filecheck.check_files(log, game, state).problems if "settings.xml" in p.path]
    # the player (or the game's menu) changes the screen type: drift; unlocking keeps their value
    xml.write_text(text.replace('<Windowed value="2" />', '<Windowed value="0" />'), encoding="utf-8")
    (d,) = S.drift(game, wanted)
    assert d.wanted.key == "video/Windowed/@value" and d.have == "0"
    S.set_unlocked(state, G.MOD_ID, d.wanted.file, d.wanted.key, True)
    left = G.wanted("enhanced", "owner-pick", "ram16", SEL, GTX1070, S.unlocked(state))
    assert "video/Windowed/@value" not in {w.key for w in left} and S.drift(game, left) == []
    # rollback puts the player's own file back, byte for byte, and nothing in the game folder changed
    assert inst.rollback(step.id) == []
    assert xml.read_bytes() == original
    assert sorted(p.name for p in game.iterdir()) == ["GTA5_Enhanced.exe"]


def test_no_settings_xml_yet_means_nothing_is_written(tmp_path):
    xml, game, state, log, inst = _setup(tmp_path)
    xml.unlink()                                              # the game never started yet: no file, no step
    assert inst.apply_settings(G.Pseudo(), G.wanted("enhanced", "owner-pick", "ram16", SEL, GTX1070)) is None
    assert not xml.exists()


@pytest.mark.parametrize("ram, vram, gpu, rtx, fg", [
    (15.8, 8.0, "NVIDIA GeForce GTX 1070", False, False),
    (31.9, 12.0, "NVIDIA GeForce RTX 3080", True, False),
    (63.9, 16.0, "NVIDIA GeForce RTX 5080", True, True),
])
def test_pc_facts(ram, vram, gpu, rtx, fg):
    pc = G.PC(ram, vram, (gpu,))
    assert (pc.rtx, pc.frame_gen) == (rtx, fg)
    assert G.PC().rtx is None and G.PC().frame_gen is None


def test_first_run_preselects_the_variant_from_the_pc():
    m = load_manifest()
    owner, show, core = m.get_pack("owner-pick"), m.get_pack("video-setup"), m.get_pack("core")
    assert G.suggest_variant(owner, GTX1070) == "ram16" and G.suggest_variant(owner, RTX4080) == "ram32"
    assert G.suggest_variant(show, GTX1070) == "balanced" and G.suggest_variant(show, RTX4080) == "ultra"
    assert G.suggest_variant(show, G.PC(15.8, 4.0, ("NVIDIA GeForce GTX 1650",))) == "performance"
    assert G.suggest_variant(core, GTX1070) is None and G.suggest_variant(owner, G.PC()) is None
