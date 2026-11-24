"""GTA V Legacy next to Enhanced: detection by exe, one manifest set per edition, the Session picking the right one,
checks/install refusing to mix editions, gameBuilds on Legacy builds (1.0.3xxx), and the CLI's --edition."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from leonida import cli
from leonida.checks import ERROR, run_checks
from leonida.cli import main
from leonida.detect import (
    ALL_EXES,
    ENHANCED,
    LEGACY,
    GameInstall,
    detect_games,
    edition_of,
    edition_of_exe,
)
from leonida.manifest import ManifestError, load_manifest, manifest_files
from leonida.session import Session


def _mod(mid, order, **extra):
    return {"id": mid, "order": order, "tier": "core", "layer": "t", "name": extra.pop("name", mid), "version": "1",
            "source": "direct", "page": f"https://{mid}.example/", "archive": [f"{mid}*.zip"],
            "install": {"method": "guided", "steps": ["x"]}, **extra}


def write_set(d: Path, edition: str, mods: list, profiles=None, top=None) -> None:
    mods_file, prof_file, keys_file = manifest_files(edition)
    (d / mods_file).write_text(json.dumps({"pack": "Leonida V", "version": "1", **(top or {}), "mods": mods}))
    (d / prof_file).write_text(json.dumps(profiles or {"default": "core", "profiles": [
        {"id": "core", "name": f"Core ({edition})", "include": [m["id"] for m in mods]}]}))
    (d / keys_file).write_text(json.dumps({"keys": []}))


@pytest.fixture
def mdir(tmp_path) -> Path:
    d = tmp_path / "manifest"
    d.mkdir()
    write_set(d, "enhanced", [_mod("shv-enh", 1, name="Script Hook V (Enhanced)"), _mod("nve", 2)],
              profiles={"default": "core", "profiles": [
                  {"id": "core", "name": "Core", "include": ["shv-enh", "nve"]},
                  {"id": "max-rtx50", "name": "Max", "include": ["shv-enh"]}]},
              top={"testedGameBuilds": ["1.0.1013.20"]})
    write_set(d, "legacy", [
        _mod("shv-leg", 1, name="Script Hook V (Legacy)", minGameBuild="1.0.3407.0",
             gameBuilds=[{"min": "1.0.3258.0", "max": "1.0.3406.99", "version": "old-3337"}]),
        _mod("nvevolved", 2, name="NaturalVision Evolved"),
    ], top={"edition": "legacy", "testedGameBuilds": ["1.0.3411.0"]})
    return d


@pytest.fixture
def legacy_game(tmp_path) -> Path:
    g = tmp_path / "Grand Theft Auto V"
    (g / "update").mkdir(parents=True)
    (g / "GTA5.exe").write_bytes(b"MZ legacy")
    (g / "PlayGTAV.exe").write_bytes(b"MZ launcher")
    return g


# ---------------------------------------------------------------------------------------------- detection
def test_edition_from_the_exe(game, legacy_game, tmp_path):
    assert edition_of(game) == ENHANCED and edition_of(legacy_game) == LEGACY
    assert edition_of(tmp_path) is None and edition_of(None) is None
    assert edition_of_exe("C:/x/gta5.EXE") == LEGACY and edition_of_exe("GTA5_Enhanced.exe") == ENHANCED
    assert edition_of_exe("PlayGTAV.exe") is None and set(ALL_EXES) == {"GTA5_Enhanced.exe", "GTA5.exe"}


def test_detect_lists_both_side_by_side(game, legacy_game, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.3411.0")
    for name in ("_steam_candidates", "_epic_candidates", "_rockstar_candidates", "_common_candidates"):
        monkeypatch.setattr(f"leonida.detect.{name}", lambda *a: [])  # only the folders given here
    found = detect_games(None, [game, legacy_game])
    assert [(g.path, g.edition, g.edition_name) for g in found] == [
        (game, ENHANCED, "GTA V Enhanced"), (legacy_game, LEGACY, "GTA V Legacy")]
    assert [g.edition for g in detect_games(("GTA5_Enhanced.exe",), [game, legacy_game])] == [ENHANCED]  # old call


# ---------------------------------------------------------------------------------------------- manifests
def test_manifest_sets(mdir):
    assert manifest_files("legacy") == ("mods-legacy.json", "profiles-legacy.json", "hotkeys-legacy.json")
    assert manifest_files() == ("mods.json", "profiles.json", "hotkeys.json")
    with pytest.raises(ManifestError, match="Unknown edition"):
        manifest_files("xbox")
    leg = load_manifest(mdir, "legacy")
    assert leg.edition == LEGACY and leg.exe_names == ("GTA5.exe",) and set(leg.mods) == {"shv-leg", "nvevolved"}
    enh = load_manifest(mdir)
    assert enh.edition == ENHANCED and enh.exe_names == ("GTA5_Enhanced.exe",)


def test_bundled_legacy_set_loads():
    leg = load_manifest(edition="legacy")
    assert leg.edition == LEGACY and leg.exe_names == ("GTA5.exe",) and leg.default_profile in leg.profiles


def test_declared_edition_must_match(tmp_path):
    d = tmp_path / "m"
    d.mkdir()
    write_set(d, "legacy", [_mod("a", 1)], top={"edition": "enhanced"})
    with pytest.raises(ManifestError, match="says it is for edition 'enhanced'"):
        load_manifest(d, "legacy")


def test_game_builds_on_legacy_builds(mdir):
    shv = load_manifest(mdir, "legacy").mod("shv-leg")
    assert shv.for_build("1.0.3411.0") is shv
    assert shv.for_build("1.0.3337.0").version == "old-3337"
    assert "needs game build 1.0.3407.0 or newer" in shv.for_build("1.0.3095.0").unsupported


# ----------------------------------------------------------------------------------------------- session
def test_session_picks_the_set_from_the_exe(tmp_path, mdir, game, legacy_game, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.3337.0")
    s = Session(tmp_path / "st", mdir, game_dir=str(legacy_game))
    assert s.game_edition == LEGACY and s.edition == LEGACY and s.edition_mismatch() is None
    assert [m.id for m in s.mods()] == ["shv-leg", "nvevolved"]
    assert s.game_version() == "1.0.3337.0" and s.manifest.mod("shv-leg").version == "old-3337"  # read via GTA5.exe
    s.config.game_dir = str(game)                     # switching folders switches the mod list
    assert s.edition == ENHANCED and [m.id for m in s.mods()] == ["shv-enh", "nve"]
    s.config.game_dir = None
    assert s.edition == ENHANCED and s.game_edition is None  # no game yet: Enhanced


def test_config_from_the_other_edition_is_ignored(tmp_path, mdir, legacy_game):
    s = Session(tmp_path / "st", mdir, game_dir=str(legacy_game))
    s.config.profile = "max-rtx50"                     # an Enhanced profile
    s.config.add, s.config.remove, s.config.swaps = ["nve"], ["shv-enh"], {"shv-enh": "nve"}
    assert s.profile_id == "core" and [m.id for m in s.mods()] == ["shv-leg", "nvevolved"]
    s.config.remove = ["nvevolved"]
    assert [m.id for m in s.mods()] == ["shv-leg"]   # its own ids still count


def test_override_and_mismatch(tmp_path, mdir, game, legacy_game):
    s = Session(tmp_path / "st", mdir, game_dir=str(game), edition="legacy")
    assert s.edition == LEGACY and s.game_edition == ENHANCED
    assert "holds GTA V Enhanced (GTA5_Enhanced.exe), but the mod list in use is for GTA V Legacy" in s.edition_mismatch()
    found = [f for f in s.findings() if f.code == "edition-mismatch"]
    assert len(found) == 1 and found[0].level == ERROR and "don't mix" in found[0].message
    with pytest.raises(ManifestError, match="Unknown edition"):
        Session(tmp_path / "st2", mdir, edition="ps5")


def test_run_checks_refuses_to_mix(mdir, legacy_game, game):
    enh = load_manifest(mdir)
    f = run_checks(enh, enh.resolve("core"), legacy_game, game_edition=LEGACY)
    assert any(x.code == "edition-mismatch" and x.level == ERROR for x in f)
    assert not any(x.code == "edition-mismatch" for x in run_checks(enh, enh.resolve("core"), game, game_edition=ENHANCED))
    assert not any(x.code == "edition-mismatch" for x in run_checks(enh, enh.resolve("core"), game))  # unknown: no claim


# --------------------------------------------------------------------------------------------------- CLI
def base_args(tmp_path, mdir):
    return ["--state-dir", str(tmp_path / "st"), "--manifest-dir", str(mdir)]


def test_cli_detect_set_legacy(tmp_path, mdir, legacy_game, capsys, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.3411.0")
    assert main(base_args(tmp_path, mdir) + ["detect", "--set", str(legacy_game)]) == 0
    out = capsys.readouterr().out
    assert "Game edition:  GTA V Legacy; mod list: GTA V Legacy" in out and "(tested build)" in out
    assert main(base_args(tmp_path, mdir) + ["detect", "--set", str(tmp_path)]) == 1
    assert "No GTA5_Enhanced.exe / GTA5.exe in" in capsys.readouterr().out


def test_cli_detect_lists_both(tmp_path, mdir, game, legacy_game, capsys, monkeypatch):
    monkeypatch.setattr(cli, "detect_games", lambda names, extra: [
        GameInstall(game, "steam", game / "GTA5_Enhanced.exe", "1.0.1013.20", ENHANCED),
        GameInstall(legacy_game, "epic", legacy_game / "GTA5.exe", "1.0.3411.0", LEGACY)])
    assert main(base_args(tmp_path, mdir) + ["--game-dir", str(game), "detect"]) == 0
    out = capsys.readouterr().out
    assert "GTA V Enhanced  version 1.0.1013.20  (tested build)" in out
    assert "GTA V Legacy  version 1.0.3411.0  (tested build)" in out      # tested against the Legacy list
    assert "Both editions are installed" in out


def test_cli_install_refuses_mixed_editions_even_with_force(tmp_path, mdir, game, capsys):
    rc = main(base_args(tmp_path, mdir) + ["--game-dir", str(game), "--edition", "legacy", "install", "--force",
                                           "--yes"])
    out = capsys.readouterr().out
    assert rc == 1 and "mod list in use is for GTA V Legacy" in out
    assert main(base_args(tmp_path, mdir) + ["--game-dir", str(game), "--edition", "legacy", "check"]) == 1
    assert "Enhanced and Legacy mods don't mix" in capsys.readouterr().out
