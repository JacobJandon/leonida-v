import pytest
from conftest import make_zip

from leonida.checks import ERROR, WARNING, has_errors, run_checks
from leonida.cli import main
from leonida.onlinesafe import OnlineSafeError, go_online_safe, restore_mods, status


def codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level == level}


# --- checks --------------------------------------------------------------------
def test_core_flags_f8_clash(manifest, game):
    f = run_checks(manifest, manifest.resolve("core"), game, game_version="1.0.1158.13")
    assert "hotkey" in codes(f, WARNING)
    assert not has_errors(f)


def test_key_override_clears_clash(manifest, game):
    f = run_checks(manifest, manifest.resolve("core"), game, game_version="1.0.1158.13",
                   key_overrides={"menyoo/Open trainer menu": "F9"})
    assert "hotkey" not in codes(f)


def test_leftover_adjuster_is_an_error(manifest, game):
    (game / "PackfileLimitAdjuster.asi").write_text("old")
    (game / "gameconfig.xml").write_text("<x/>")
    f = run_checks(manifest, manifest.resolve("core"), game, game_version="1.0.1158.13")
    assert {"conflict-file", "gameconfig"} <= codes(f, ERROR)


def test_two_huds_clash(manifest, game):
    mods = manifest.resolve("core", add=["hud-fbicat"])
    assert "slot-clash" in codes(run_checks(manifest, mods, game), ERROR)


def test_newer_game_warns(manifest, game):
    assert "version-newer" in codes(run_checks(manifest, manifest.resolve("core"), game, game_version="1.0.1200.1"))


def test_max_profile_needs_rtx50(manifest, game):
    mods = manifest.resolve("max-rtx50")
    f = run_checks(manifest, mods, game, gpu_names=["NVIDIA GeForce RTX 4070"], profile_requires={"gpu": "rtx50"})
    assert "gpu" in codes(f, WARNING)
    assert "pair-warning" in codes(f)  # DLSS5 + NVE HDR, BVD + Drive V
    f2 = run_checks(manifest, mods, game, gpu_names=["NVIDIA GeForce RTX 5090"], profile_requires={"gpu": "rtx50"})
    assert "gpu" not in codes(f2)


def test_missing_prereq_is_error(manifest, game):
    f = run_checks(manifest, manifest.resolve("core"), game, prerequisites={"dotnet48": False, "vcredist": True})
    assert "prereq" in codes(f, ERROR)


def test_no_game_is_error(manifest):
    assert "no-game" in codes(run_checks(manifest, manifest.resolve("core"), None), ERROR)


# --- online-safe -----------------------------------------------------------------
PATTERNS = ("dinput8.dll", "ScriptHookV.dll", "*.asi", "scripts", "mods", "onigiri")


def test_online_safe_roundtrip(game):
    (game / "dinput8.dll").write_text("x")
    (game / "Menyoo.asi").write_text("x")
    (game / "scripts").mkdir()
    (game / "scripts" / "a.dll").write_text("x")
    assert status(game, PATTERNS) == "mods-on"
    moved = go_online_safe(game, PATTERNS)
    assert set(moved) == {"dinput8.dll", "Menyoo.asi", "scripts"}
    assert status(game, PATTERNS) == "online-safe"
    assert (game / "GTA5_Enhanced.exe").exists() and (game / "bink2w64.dll").exists()
    with pytest.raises(OnlineSafeError):
        go_online_safe(game, PATTERNS)
    restore_mods(game)
    assert status(game, PATTERNS) == "mods-on"
    assert (game / "scripts" / "a.dll").exists()


def test_restore_refuses_to_overwrite(game):
    (game / "dinput8.dll").write_text("mine")
    go_online_safe(game, PATTERNS)
    (game / "dinput8.dll").write_text("new one")
    with pytest.raises(OnlineSafeError):
        restore_mods(game)


# --- CLI end to end -------------------------------------------------------------
@pytest.fixture
def cli(tmp_path, game, downloads, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1158.13")
    base = ["--state-dir", str(tmp_path / "cli-state"), "--download-dir", str(downloads)]
    return lambda *a: main(base + list(a))


def test_cli_flow(cli, game, downloads, capsys):
    assert cli("detect", "--set", str(game)) == 0
    assert cli("get", "--no-open") == 2  # nothing downloaded yet
    make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "s", "bin/dinput8.dll": "d"})
    make_zip(downloads / "ScriptHookVDotNet-Enhanced.zip", {
        "ScriptHookVDotNet.asi": "a", "ScriptHookVDotNet2.dll": "b", "ScriptHookVDotNet3.dll": "c",
        "ScriptHookVDotNet.ini": "d", "MinHook.x64.dll": "e"})
    assert cli("install", "--only", "scripthookv", "shvdne", "--dry-run") == 0
    assert not (game / "ScriptHookV.dll").exists()
    assert cli("install", "--only", "scripthookv", "shvdne", "--yes", "--no-pause", "--force") == 0
    assert (game / "ScriptHookVDotNet.asi").exists()
    assert cli("status") == 0
    assert cli("online-safe", "on") == 0
    assert not (game / "ScriptHookV.dll").exists()
    assert cli("online-safe", "off") == 0
    assert (game / "ScriptHookV.dll").exists()
    assert cli("keys") == 0
    assert cli("uninstall", "--yes") == 0
    out = capsys.readouterr().out
    assert "matches the pre-install snapshot" in out
    assert not (game / "ScriptHookV.dll").exists()


def test_cli_swap_and_profiles(cli, capsys):
    assert cli("swap", "hud", "hud-fbicat") == 0
    assert cli("profiles", "--use", "core-plus") == 0
    assert "Profile set: core-plus" in capsys.readouterr().out
