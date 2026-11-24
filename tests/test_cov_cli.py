"""Coverage for the `leonida` CLI (leonida/cli.py and leonida/__main__.py): every subcommand and its main branches.

All commands run against a small hand-written manifest and tmp_path folders (--state-dir/--manifest-dir/
--download-dir/--game-dir). Network, browsers, Explorer and installers are monkeypatched away.
"""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import types
import warnings
from pathlib import Path

import pytest
from conftest import make_zip
from test_cov_core import BUILD, mini_manifest, mod_entry

from leonida import cli, downloader, session, updater
from leonida import modpack as mp
from leonida import modupdate as mu
from leonida import verify as verify_mod
from leonida.detect import GameInstall
from leonida.downloader import DownloadError, DownloadPlan
from leonida.matcher import build_lock, write_lock
from leonida.paths import LOCK_NAME, Config

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

MODS = [
    mod_entry("alpha", 1, slot="hud", conflicts=["oldhud.asi"]),
    mod_entry("alpha2", 2, slot="hud", tier="alternative"),
    mod_entry("beta", 3, archive=["beta-*.zip", "pack-*.zip"],
              redistribution={"allowed": True, "proof": "https://beta.example/licence"}),
    mod_entry("older", 4, archive=["older-*.zip", "pack-*.zip"], minGameBuild="1.0.1100.0",
              gameBuilds=[{"min": "1.0.1000.0", "max": "1.0.1099.0", "version": "0.9"}]),
    mod_entry("gone", 5, tier="optional", minGameBuild="1.0.2000.0"),
    mod_entry("guided", 6, tier="optional", install={"method": "guided", "steps": ["Copy the files", "Start it"]}),
    mod_entry("shop", 7, tier="optional", source="patreon"),
]
PROFILES = [
    {"id": "core", "name": "Core", "description": "The basics", "include": ["alpha", "beta", "older"]},
    {"id": "solo", "name": "Solo", "description": "Just alpha", "include": ["alpha"]},
    {"id": "full", "name": "Full", "description": "Everything",
     "include": ["@profile:core", "gone", "guided", "shop"]},
]
KEYS = [{"mod": "alpha", "action": "Open", "key": "F5"}, {"mod": "beta", "action": "Menu", "key": "F5"}]


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Defaults point at tmp_path; nothing reads the registry for prerequisites or launches anything."""
    monkeypatch.setenv("LEONIDA_STATE_DIR", str(tmp_path / "default-state"))
    monkeypatch.setenv("LEONIDA_DOWNLOAD_DIR", str(tmp_path / "default-downloads"))
    monkeypatch.setenv("LEONIDA_NO_OPEN", "1")
    monkeypatch.delenv("LEONIDA_FAKE_GAME_VERSION", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(cli, "_COLOR", False)
    monkeypatch.setattr(cli, "find_7zip", lambda: None)
    monkeypatch.setattr(session, "check_prerequisites", lambda: {})
    monkeypatch.setattr(session, "find_7zip", lambda: None)
    monkeypatch.setattr(cli, "check_prerequisites", lambda: {"dotnet48": True, "vcredist": False, "7zip": None})
    monkeypatch.setattr(cli, "detect_gpus", lambda: ["NVIDIA GeForce RTX 4070"])
    # module-level stand-ins, so only cli's own use is blocked (tests may still run python in a subprocess)
    monkeypatch.setattr(cli, "subprocess", types.SimpleNamespace(run=_forbidden("subprocess.run")))
    monkeypatch.setattr(cli, "webbrowser", types.SimpleNamespace(open_new_tab=_forbidden("webbrowser.open_new_tab")))
    if hasattr(cli.os, "startfile"):
        monkeypatch.setattr(cli.os, "startfile", _forbidden("os.startfile"))


def _forbidden(name):
    def fail(*a, **k):
        raise AssertionError(f"{name} must not run in tests: {a}")
    return fail


@pytest.fixture
def mdir(tmp_path):
    return mini_manifest(tmp_path / "manifest", MODS, PROFILES, KEYS, default="core")


@pytest.fixture
def run(tmp_path, mdir, downloads, capsys):
    """run(*args, game=None, build=BUILD) -> (exit code, stdout)."""
    state = tmp_path / "cli-state"

    def _run(*args, game=None, build=BUILD):
        base = ["--state-dir", str(state), "--manifest-dir", str(mdir), "--download-dir", str(downloads)]
        if game is not None:
            base += ["--game-dir", str(game)]
        if build:
            base += ["--game-build", build]
        rc = cli.main(base + [str(a) for a in args])
        return rc, capsys.readouterr().out

    _run.state = state
    return _run


def zips(downloads: Path, *ids: str) -> dict[str, Path]:
    return {i: make_zip(downloads / f"{i}-1.0.zip", {f"{i}/{i}.asi": f"{i} v1"}) for i in ids}


def inputs(monkeypatch, *answers):
    """Feed answers to input(); an Exception instance in the list is raised instead."""
    it = iter(answers)

    def fake(prompt=""):
        ans = next(it)
        if isinstance(ans, BaseException):
            raise ans
        return ans
    monkeypatch.setattr("builtins.input", fake)


# ---------------------------------------------------------------------------------------------- ConsoleUI
def test_console_ui_confirm(monkeypatch):
    assert cli.ConsoleUI(assume_yes=True).confirm("ok?") is True
    ui = cli.ConsoleUI()
    inputs(monkeypatch, "", "", "Yes", "nope", EOFError(), EOFError())
    assert ui.confirm("a?") is True
    assert ui.confirm("b?", default=False) is False
    assert ui.confirm("c?", default=False) is True
    assert ui.confirm("d?") is False
    assert ui.confirm("e?") is True
    assert ui.confirm("f?", default=False) is False


def test_console_ui_wait_done(monkeypatch, tmp_path, capsys):
    ui = cli.ConsoleUI()
    inputs(monkeypatch, "done", "cancel", EOFError())
    assert ui.wait_done("Mod", ["one", "two"], tmp_path) is True
    out = capsys.readouterr().out
    assert "== Manual step: Mod ==" in out and "  1. one" in out and "  2. two" in out and f"Files: {tmp_path}" in out
    assert ui.wait_done("Mod", [], None) is False
    assert "Files:" not in capsys.readouterr().out
    assert ui.wait_done("Mod", [], None) is False
    assert cli.ConsoleUI(assume_yes=True).wait_done("Mod", ["x"], None) is True


def test_console_ui_info_warn_and_color(monkeypatch, capsys):
    ui = cli.ConsoleUI()
    ui.info("hello")
    ui.warn("careful")
    assert capsys.readouterr().out == "hello\n! careful\n"
    monkeypatch.setattr(cli, "_COLOR", True)
    assert cli._c("31", "red") == "\033[31mred\033[0m"
    assert cli._level(cli.ERROR).startswith("\033[31m")
    monkeypatch.setattr(cli, "_COLOR", False)
    assert [cli._level(x) for x in (cli.ERROR, cli.WARNING, cli.INFO)] == ["ERROR  ", "WARNING", "info   "]


def test_open_path_respects_no_open(monkeypatch, tmp_path):
    cli.ConsoleUI.open_path(tmp_path)  # LEONIDA_NO_OPEN=1: os.startfile would raise if called


@windows_only
def test_open_path_uses_startfile_and_ignores_errors(monkeypatch, tmp_path):
    monkeypatch.delenv("LEONIDA_NO_OPEN")
    opened = []
    monkeypatch.setattr(cli.os, "startfile", opened.append)
    cli.ConsoleUI.open_path(tmp_path)
    assert opened == [str(tmp_path)]

    def broken(p):
        raise OSError("no association")
    monkeypatch.setattr(cli.os, "startfile", broken)
    cli.ConsoleUI.open_path(tmp_path)  # swallowed


@windows_only
def test_launch_runs_windows_command(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    target = tmp_path / "Setup Me.bat"
    cli.ConsoleUI().launch(target)
    assert calls == [(cli.windows_launch_command(target), {"check": False, "cwd": str(tmp_path)})]


def test_launch_elsewhere_only_warns(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "sys", types.SimpleNamespace(platform="linux"))
    cli.ConsoleUI().launch(tmp_path / "setup.exe")
    assert "Run this on Windows" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------- detect
def test_detect_set_folder_without_exe(run, tmp_path):
    (tmp_path / "empty").mkdir()
    rc, out = run("detect", "--set", tmp_path / "empty")
    assert rc == 1 and "No GTA5_Enhanced.exe / GTA5.exe in" in out  # either edition's exe


def test_detect_set_prints_build_summary(run, game):
    assert run("profiles", "--use", "full")[0] == 0
    rc, out = run("detect", "--set", game)
    assert rc == 0 and f"Game folder set: {game}" in out
    assert f"Game build:    {BUILD} (from --game-build) (tested build)" in out
    assert "older versions for this build: Older 0.9" in out
    assert "not available on this build: Gone needs game build 1.0.2000.0 or newer" in out
    assert json.loads((run.state / "config.json").read_text())["game_dir"] == str(game)


def test_detect_untested_and_unreadable_builds(run, game):
    rc, out = run("detect", "--set", game, build="1.0.1050.0")
    assert "(not a tested build; tested: 1.0.1013.20)" in out
    rc, out = run("detect", "--set", game, build=None)  # the fake exe has no version resource
    assert rc == 0 and "Game build:    unknown (version unreadable; tested builds: 1.0.1013.20)" in out
    assert "older versions" not in out


def test_detect_nothing_found(run, monkeypatch):
    monkeypatch.setattr(cli, "detect_games", lambda names, extra: [])
    rc, out = run("detect")
    assert rc == 1 and "not found automatically" in out


def test_detect_found_saves_first_then_keeps_setting(run, game, monkeypatch):
    found = [GameInstall(game, "steam", game / "GTA5_Enhanced.exe", BUILD),
             GameInstall(game.parent, "epic", game / "GTA5_Enhanced.exe", None)]
    monkeypatch.setattr(cli, "detect_games", lambda names, extra: found)
    rc, out = run("detect")
    assert rc == 0 and f"1. {game}  [steam]  GTA V  version {BUILD}  (tested build)" in out  # no edition given
    assert "[epic]  GTA V  version unknown  (version unreadable" in out
    assert f"Using: {game}" in out
    rc, out = run("detect")
    assert f"Current setting: {game}" in out


# ----------------------------------------------------------------------------------------------- profiles
def test_profiles_list_and_bad_use(run, capsys):
    rc, out = run("profiles")
    assert rc == 0 and "* core  Core" in out and "  solo  Solo" in out and "Alpha, Beta, Older" in out
    rc = cli.main(["--state-dir", str(run.state), "--manifest-dir", str(run.state.parent / "manifest"),
                   "profiles", "--use", "nope"])
    assert rc == 3 and "Manifest error: Unknown profile: 'nope'" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------------- get
def test_get_nothing_downloaded(run):
    rc, out = run("get", "--no-open")
    assert rc == 2 and "3 still missing." in out
    assert "[ ]  1. Alpha" in out and "https://alpha.example/page" in out


def test_get_opens_pages(run, monkeypatch):
    monkeypatch.delenv("LEONIDA_NO_OPEN")
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open_new_tab", opened.append)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    rc, out = run("get")
    assert rc == 2 and "Opening 3 download page(s)" in out
    assert opened == ["https://alpha.example/page", "https://beta.example/page", "https://older.example/page"]


def test_get_all_present_writes_lock_and_reports_extras(run, downloads):
    files = zips(downloads, "alpha", "beta", "older")
    make_zip(downloads / "alpha-2.0.zip", {"alpha.asi": "v2"})
    os.utime(files["alpha"], (1, 1))  # the 1.0 file is older
    make_zip(downloads / "pack-1.zip", {"x": "y"})
    rc, out = run("get", "--no-open")
    assert rc == 0 and "All 3 files present. Lockfile written" in out
    alpha_line = next(line for line in out.splitlines() if line.startswith("[x]  1. Alpha"))
    assert alpha_line.endswith("alpha-2.0.zip")
    assert '?? pack-1.zip could be: beta, older -> leonida assign "pack-1.zip" <mod>' in out
    assert "!! alpha: using newest file, ignoring alpha-1.0.zip" in out
    lock = json.loads((run.state / LOCK_NAME).read_text())
    assert {e["mod"] for e in lock["entries"]} == {"alpha", "beta", "older"}


def test_get_watch_until_complete(run, downloads, monkeypatch):
    zips(downloads, "alpha")
    calls = []

    def arrive(seconds):
        calls.append(seconds)
        zips(downloads, "beta", "older")
    monkeypatch.setattr(cli.time, "sleep", arrive)
    rc, out = run("get", "--no-open", "--watch")
    assert rc == 0 and calls == [3]
    assert "Watching the folder" in out and "got Beta: beta-1.0.zip" in out and "got Older: older-1.0.zip" in out


def test_get_watch_ctrl_c(run, monkeypatch):
    def interrupt(seconds):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli.time, "sleep", interrupt)
    rc, out = run("get", "--no-open", "--watch")
    assert rc == 2 and "3 still missing." in out


def test_get_auto(run, downloads, monkeypatch):
    modes = {"alpha": "auto", "beta": "auto", "older": "browser", "gone": "browser", "guided": "browser",
             "shop": "manual"}
    monkeypatch.setattr(downloader, "plan_for", lambda m: DownloadPlan(m.id, modes[m.id], m.page))

    def fake_download(plan, folder, progress=None):
        if plan.mod_id == "beta":
            raise DownloadError("rate limited")
        progress(0, None)            # unknown size
        progress(1048576, 4194304)   # throttled: too soon after the last update
        progress(4194304, 4194304)   # done: always shown
        return make_zip(folder / "alpha-1.0.zip", {"alpha.asi": "a"})
    monkeypatch.setattr(downloader, "download", fake_download)
    rc, out = run("get", "--auto", "--no-open", "--profile", "full")
    assert rc == 2
    assert "Downloading 2 file(s) from the authors' own releases/links..." in out
    assert "0.0 MB" in out and "4.0 / 4.0 MB (100%)" in out and "1.0 / 4.0" not in out
    assert "saved alpha-1.0.zip" in out and "! rate limited" in out
    assert "  - Beta: https://beta.example/page" in out and "  - Older: https://older.example/page" in out
    assert "Get these yourself" in out and "  - Shop [patreon]: https://shop.example/page" in out
    assert "[x]  1. Alpha" in out


def test_get_auto_opens_only_browser_pages_still_missing(run, monkeypatch):
    monkeypatch.delenv("LEONIDA_NO_OPEN")
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open_new_tab", opened.append)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(downloader, "plan_for",
                        lambda m: DownloadPlan(m.id, "manual" if m.id == "alpha" else "browser", m.page))
    rc, out = run("get", "--auto", "--profile", "core")
    assert rc == 2 and "Downloading" not in out
    assert opened == ["https://beta.example/page", "https://older.example/page"]


# ------------------------------------------------------------------------------------------- assign/check
def test_assign(run):
    rc, out = run("assign", "C:/somewhere/weird name.zip", "beta")
    assert rc == 0 and "weird name.zip -> beta" in out
    assert Config.load(run.state).assignments == {"weird name.zip": "beta"}
    assert run("assign", "x.zip", "ghost")[0] == 3


def test_check_errors_and_clean(run, game):
    rc, out = run("check")
    assert rc == 1 and "ERROR   GTA V Enhanced folder not set" in out
    rc, out = run("check", "--profile", "core", game=game)
    assert rc == 0 and "WARNING F5 is used by more than one mod" in out
    rc, out = run("check", "--profile", "solo", game=game)
    assert rc == 0 and "All checks passed." in out


# ------------------------------------------------------------------------------------------------ install
def test_install_needs_game(run):
    rc, out = run("install")
    assert rc == 1 and "Set the game folder first" in out


def test_install_stops_on_errors_unless_forced(run, game, downloads):
    (game / "oldhud.asi").write_text("old")
    rc, out = run("install", "--profile", "solo", game=game)
    assert rc == 1 and "ERROR   Remove oldhud.asi" in out and "Fix the errors above" in out
    zips(downloads, "alpha")
    rc, out = run("install", "--profile", "solo", "--force", "--yes", game=game)
    assert rc == 0 and "Profile installed." in out


def test_install_unknown_only_mod(run, game):
    assert run("install", "--only", "ghost", game=game)[0] == 3


def test_install_dry_run_skips_unsupported_and_tolerates_missing(run, game, downloads):
    zips(downloads, "alpha")
    rc, out = run("install", "--profile", "full", "--only", "alpha", "gone", "--dry-run", game=game)
    assert rc == 0
    assert "Skipping (not available on this game build): Gone" in out
    assert "--- 1. Alpha ---" in out and "Dry run finished: nothing was written." in out
    assert not (game / "alpha.asi").exists() and not (run.state / "baseline-snapshot.json").exists()


def test_install_missing_downloads(run, game, downloads):
    zips(downloads, "alpha")
    rc, out = run("install", "--no-pause", game=game)
    assert rc == 2 and "Missing downloads: Beta, Older" in out and "Run: leonida get" in out


def test_install_yes_then_already_installed_and_lock_warning(run, game, downloads):
    files = zips(downloads, "alpha", "beta", "older")
    lock = build_lock("Leonida V", "9", files)
    lock["entries"][0]["sha256"] = "0" * 64
    write_lock(run.state / LOCK_NAME, lock)
    rc, out = run("install", "--yes", game=game)
    assert rc == 0 and "! alpha: alpha-1.0.zip differs from the locked file alpha-1.0.zip" in out
    assert "Step 1 done: 1 file change(s) logged." in out and "Profile installed." in out
    assert (game / "alpha.asi").read_text() == "alpha v1" and (game / "older.asi").exists()
    rc, out = run("install", "--yes", game=game)
    assert rc == 0 and "Everything in this profile is already installed." in out


def test_install_pause_continue_then_undo(run, game, downloads, monkeypatch):
    zips(downloads, "alpha", "beta", "older")
    inputs(monkeypatch, "what?", "c", "u")
    rc, out = run("install", game=game)
    assert rc == 0 and "Step undone." in out
    assert (game / "alpha.asi").exists() and not (game / "beta.asi").exists()
    assert [s.status for s in session.InstallLog(run.state / "install-log.json").steps] == ["done", "rolled-back"]


def test_install_undo_reports_rollback_warnings(run, game, downloads, monkeypatch):
    zips(downloads, "alpha")

    def edit_then_undo(prompt=""):
        (game / "alpha.asi").write_text("tweaked while testing")
        return "u"
    monkeypatch.setattr("builtins.input", edit_then_undo)
    rc, out = run("install", "--profile", "solo", game=game)
    assert rc == 0 and "! alpha.asi was edited after install" in out and "Step undone." in out


@pytest.mark.parametrize("answer", ["q", EOFError()])
def test_install_pause_quit(run, game, downloads, monkeypatch, answer):
    zips(downloads, "alpha", "beta", "older")
    inputs(monkeypatch, answer)
    rc, out = run("install", game=game)
    assert rc == 0 and "Profile installed." not in out
    assert (game / "alpha.asi").exists() and not (game / "beta.asi").exists()


def test_install_broken_archive_stops(run, game, downloads):
    make_zip(downloads / "alpha-1.0.zip", {"readme.md": "no asi in here"})
    rc, out = run("install", "--profile", "solo", "--yes", game=game)
    assert rc == 1 and "Stopped: Alpha:" in out


def test_install_guided_step(run, game, downloads, monkeypatch):
    make_zip(downloads / "guided-1.0.zip", {"guided/readme.txt": "follow me"})

    def user_does_it(prompt=""):
        (game / "scripts").mkdir(exist_ok=True)
        (game / "scripts" / "guided.dll").write_text("g")
        return "done"
    monkeypatch.setattr("builtins.input", user_does_it)
    rc, out = run("install", "--profile", "full", "--only", "guided", "--no-pause", game=game)
    assert rc == 0 and "== Manual step: Guided ==" in out and "  1. Copy the files" in out
    assert "Step 1 done: 1 file change(s) logged." in out


# ------------------------------------------------------------------------------------------ status/rollback
def test_status(run, game, downloads):
    rc, out = run("status")
    assert rc == 0 and "Game folder:     (not set)" in out and "Mods state" not in out and "Steps:" not in out
    zips(downloads, "alpha")
    run("install", "--profile", "solo", "--yes", game=game)
    rc, out = run("status", game=game)
    assert "Mods state:      mods-on" in out and "Profile:         core" in out
    assert "Steps:" in out and "done         alpha" in out


def test_rollback_paths(run, game, downloads):
    with pytest.raises(SystemExit, match="Set the game folder first"):
        run("rollback")
    rc, out = run("rollback", game=game)
    assert rc == 0 and "Nothing to roll back." in out
    zips(downloads, "alpha", "beta", "older")
    run("install", "--yes", game=game)
    rc, out = run("rollback", "1", game=game)
    assert rc == 1 and "Roll back later steps first: 2, 3" in out
    rc, out = run("rollback", "99", game=game)
    assert rc == 1 and "No step 99" in out
    rc, out = run("rollback", "--dry-run", game=game)
    assert rc == 0 and "undo add older.asi" in out and (game / "older.asi").exists()
    (game / "older.asi").write_text("edited by the user")
    rc, out = run("rollback", game=game)
    assert rc == 0 and "! older.asi was edited after install" in out and "Step 3 rolled back." in out
    rc, out = run("rollback", "3", game=game)
    assert "! Step 3 is already rolled back." in out


# ---------------------------------------------------------------------------------------------- uninstall
def test_uninstall_declined(run, game, monkeypatch):
    inputs(monkeypatch, "n")
    assert run("uninstall", game=game)[0] == 1


def test_uninstall_without_baseline(run, game, monkeypatch):
    inputs(monkeypatch, "y")
    rc, out = run("uninstall", game=game)
    assert rc == 0 and "No baseline snapshot; nothing to compare." in out


def test_uninstall_reports_residual_differences(run, game, downloads):
    zips(downloads, "alpha")
    run("install", "--profile", "solo", "--yes", game=game)
    (game / "alpha.asi").write_text("edited")
    (game / "stray.txt").write_text("added by something else")
    (game / "bink2w64.dll").write_text("patched")
    (game / "GTA5_Enhanced.exe").unlink()
    rc, out = run("uninstall", "--yes", game=game)
    assert rc == 0 and "! alpha.asi was edited after install" in out
    assert "Differences from the pre-install snapshot: 1 added, 1 changed, 1 removed" in out
    assert "  + stray.txt" in out and "  ~ bink2w64.dll" in out and "  - GTA5_Enhanced.exe" in out


def test_uninstall_clean(run, game, downloads):
    zips(downloads, "alpha")
    run("install", "--profile", "solo", "--yes", game=game)
    rc, out = run("uninstall", "--yes", game=game)
    assert rc == 0 and "Game folder matches the pre-install snapshot." in out
    assert not (game / "alpha.asi").exists()


# -------------------------------------------------------------------------------------------- online-safe
def test_online_safe(run, game):
    rc, out = run("online-safe", "on")
    assert rc == 1 and "Set the game folder first" in out
    rc, out = run("online-safe", "on", game=game)
    assert rc == 0 and "No mod files found in the game folder." in out
    (game / "alpha.asi").write_text("a")
    assert "mods-on" in run("online-safe", "status", game=game)[1]
    rc, out = run("online-safe", "on", "--dry-run", game=game)
    assert "Moved 1 item(s)" in out and (game / "alpha.asi").exists()
    rc, out = run("online-safe", "on", game=game)
    assert rc == 0 and "Moved 1 item(s) out of the game folder. Safe to launch GTA Online." in out
    rc, out = run("online-safe", "on", game=game)
    assert rc == 1 and "already moved out" in out
    rc, out = run("online-safe", "off", game=game)
    assert rc == 0 and "Restored 1 item(s)." in out and (game / "alpha.asi").exists()


# -------------------------------------------------------------------------------------------- keys / swap
def test_keys_and_rebind(run, monkeypatch):
    rc, out = run("keys")
    assert rc == 0 and "F5       Alpha: Open; Beta: Menu   <- clash" in out
    monkeypatch.setattr(cli, "_COLOR", True)
    assert "\033[33mF5" in run("keys")[1]
    monkeypatch.setattr(cli, "_COLOR", False)
    rc, out = run("keys", "set", "beta", "Menu", "F6")
    assert rc == 0 and "clash" not in out and "F6       Beta: Menu" in out
    assert Config.load(run.state).key_overrides == {"beta/Menu": "F6"}


def test_swap(run):
    rc, out = run("swap", "alpha", "alpha2")
    assert rc == 0 and "alpha -> alpha2" in out
    assert Config.load(run.state).swaps == {"alpha": "alpha2"}
    assert run("swap", "alpha", "beta")[0] == 3


# ------------------------------------------------------------------------------------------------- doctor
def test_doctor(run, game, monkeypatch):
    monkeypatch.setattr(cli, "python_bits", lambda: 64)
    rc, out = run("doctor", build=None)
    assert rc == 0 and "GPU(s):        NVIDIA GeForce RTX 4070  (RTX 50: False)" in out
    assert "dotnet48       ok" in out and "vcredist       missing" in out and "7zip           unknown" in out
    assert "7-Zip:         not found" in out and "(64-bit)" in out and "Game build:" not in out
    rc, out = run("doctor", game=game)
    assert f"Game build:    {BUILD}" in out and "32-bit" not in out
    monkeypatch.setattr(cli, "detect_gpus", lambda: [])
    monkeypatch.setattr(cli, "find_7zip", lambda: Path("C:/7z/7z.exe"))
    out = run("doctor", build=None)[1]
    assert "GPU(s):        unknown" in out and "7z.exe" in out


@windows_only
def test_doctor_warns_about_32bit_python(run, monkeypatch):
    monkeypatch.setattr(cli, "python_bits", lambda: 32)
    out = run("doctor", build=None)[1]
    assert "This Python is 32-bit" in out


# ------------------------------------------------------------------------------------------------- verify
def _vr(status, message, line=None):
    return verify_mod.VerifyResult(status, "code", message, "alpha", "ScriptHookV.log", line)


def test_verify(run, game, monkeypatch):
    with pytest.raises(SystemExit, match="Set the game folder first"):
        run("verify")
    rc, out = run("verify", game=game)
    assert rc == 0 and "Nothing installed by Leonida V yet" in out
    results = [_vr(verify_mod.OK, "alpha loaded", "line ok"), _vr(verify_mod.FAILED, "beta crashed", "boom"),
               _vr(verify_mod.WARN, "odd"), _vr(verify_mod.NOT_SEEN, "older not seen"), _vr("no-log", "no log")]
    monkeypatch.setattr(verify_mod, "verify_session", lambda ctx: results)
    rc, out = run("verify", "--lines", game=game)
    assert rc == 1 and "OK       alpha loaded" in out and "FAILED   beta crashed" in out
    assert "WARNING  odd" in out and "NOT SEEN older not seen" in out and "info     no log" in out
    assert "ScriptHookV.log: boom" in out and "1 problem(s) found" in out
    monkeypatch.setattr(verify_mod, "verify_session", lambda ctx: results[:1] + results[3:4])
    rc, out = run("verify", game=game)
    assert rc == 0 and "line ok" not in out and "Start the game once" in out
    monkeypatch.setattr(verify_mod, "verify_session", lambda ctx: results[:1])
    rc, out = run("verify", game=game)
    assert rc == 0 and "Start the game once" not in out


# -------------------------------------------------------------------------------------------- self-update
def _info(latest="1.2.0", newer=True, notes="Better things.", checked_at=None):
    return updater.UpdateInfo(current="1.0.0", latest=latest, newer=newer, notes=notes,
                              page="https://github.com/x/y/releases/tag/v1.2.0", zip_url=None, exe_url=None,
                              checked_at=checked_at)


@pytest.fixture
def fake_updater(monkeypatch, tmp_path):
    state = {"info": _info(), "cached": None, "applied": [], "checks": [], "reinstall": "Start it again."}
    monkeypatch.setattr(updater, "project_dir", lambda: tmp_path / "project")
    monkeypatch.setattr(updater, "install_kind", lambda p: "zip")
    monkeypatch.setattr(updater, "cached_check", lambda st: state["cached"])

    def check(timeout=15, cache_dir=None, max_age=None):
        state["checks"].append((cache_dir, max_age))
        if isinstance(state["info"], Exception):
            raise state["info"]
        return state["info"]

    def apply(info, project, st, progress=None, force=False):
        if state.get("fail"):
            raise DownloadError("checksum mismatch")
        progress(0, 2097152)
        progress(1048576, 2097152)
        progress(1048576, 2097152)  # same percentage: not printed again
        progress(5, None)
        state["applied"].append((info.latest, project, st, force))
        return "Updated to 1.2.0. Restart Leonida V."

    def reinstall(project):
        if isinstance(state["reinstall"], Exception):
            raise state["reinstall"]
        return state["reinstall"]
    monkeypatch.setattr(updater, "check", check)
    monkeypatch.setattr(updater, "apply", apply)
    monkeypatch.setattr(updater, "request_reinstall", reinstall)
    return state


def test_ago():
    assert [cli._ago(s) for s in (None, 30, 600, 7200, 3 * 86400)] ==         ["never", "just now", "10 min ago", "2 h ago", "3 days ago"]


def test_self_update_reinstall(run, fake_updater):
    rc, out = run("self-update", "--reinstall")
    assert rc == 0 and "(zip install)" in out and "Start it again." in out and not fake_updater["checks"]
    fake_updater["reinstall"] = updater.UpdateError("The .exe build has no Python package")
    rc, out = run("self-update", "--reinstall")
    assert rc == 1 and "no Python package" in out


def test_self_update_check_failures_and_no_release(run, fake_updater):
    fake_updater["info"] = DownloadError("offline")
    rc, out = run("self-update", "--check")
    assert rc == 1 and "Could not check for updates: offline" in out and "Last check" not in out
    assert fake_updater["checks"] == [(run.state, 0)]
    fake_updater["info"] = _info(latest=None, newer=False)
    rc, out = run("self-update", "--check")
    assert rc == 0 and "No Leonida V release published yet." in out
    rc, out = run("self-update", "--force")
    assert rc == 1 and "No Leonida V release has been published yet." in out
    fake_updater["info"] = _info(latest="1.0.0", newer=False)
    rc, out = run("self-update")
    assert rc == 0 and "You have the latest version." in out and not fake_updater["applied"]


def test_self_update_offline_falls_back_to_saved_result(run, fake_updater):
    import time
    fake_updater["cached"] = _info(checked_at=time.time() - 600)
    fake_updater["info"] = DownloadError("offline")
    rc, out = run("self-update", "--check")
    assert rc == 0 and "Last check: 10 min ago (latest then: 1.2.0)" in out
    assert "Showing the saved result from 10 min ago." in out and "Update available" in out
    rc, out = run("self-update")  # applying needs a fresh answer
    assert rc == 1 and not fake_updater["applied"]
    rc, out = run("self-update", "--check", "--force")
    assert rc == 1
    fake_updater["cached"] = _info(latest=None, newer=False)
    fake_updater["info"] = _info()
    out = run("self-update", "--check")[1]
    assert "Last check: never (latest then: no release)" in out


def test_self_update_check_only(run, fake_updater):
    rc, out = run("self-update", "--check")
    assert rc == 0 and "Latest release: 1.2.0" in out and "Better things." in out
    assert "Update available. Run: leonida self-update" in out and not fake_updater["applied"]
    fake_updater["info"] = _info(latest="1.0.0", newer=False)
    rc, out = run("self-update", "--check", "--force")
    assert rc == 0 and "Run: leonida self-update --force" in out and "Better things." not in out


def test_self_update_apply(run, fake_updater, tmp_path):
    fake_updater["info"] = _info(notes="")
    rc, out = run("self-update")
    assert rc == 0 and "1.0 MB (50%)" in out and out.count("(50%)") == 1 and "Updated to 1.2.0" in out
    assert fake_updater["applied"] == [("1.2.0", tmp_path / "project", run.state, False)]
    fake_updater["info"] = _info(latest="1.0.0", newer=False)
    assert run("self-update", "--force")[0] == 0
    assert fake_updater["applied"][-1][3] is True
    fake_updater["info"] = _info()
    fake_updater["fail"] = True
    rc, out = run("self-update")
    assert rc == 1 and "checksum mismatch" in out


# ------------------------------------------------------------------------------------------------ modpack
def test_modpack_needs_a_build(run):
    rc, out = run("modpack", "build", build=None)
    assert rc == 1 and "Can't read the game build" in out


def test_modpack_build_and_merge(run, downloads, tmp_path):
    zips(downloads, "alpha", "beta")
    rc, out = run("modpack", "build", "--profile", "full")
    default_out = run.state / mp.ASSET
    assert rc == 0 and f"Recorded 2 mod file(s) for game build {BUILD} -> {default_out}" in out
    assert "not downloaded, left out: Older, Guided, Shop" in out
    assert "not available on this build: Gone" in out
    assert "re-hostable (mods.json has permission): Beta" in out
    rc, out = run("modpack", "build", "--profile", "solo", build="1.0.1158.13")
    assert rc == 0 and f"{mp.ASSET} now covers builds: {BUILD}, 1.0.1158.13" in out
    assert "left out" not in out and "none; every file comes from its author" in out
    assert set(mp.load_file(default_out)["builds"]) == {BUILD, "1.0.1158.13"}
    out_file = tmp_path / "release" / "pack.json"
    rc, out = run("modpack", "build", "--out", out_file)
    assert rc == 0 and out_file.is_file() and "now covers" not in out


def test_modpack_bad_existing_file(run, downloads, tmp_path):
    zips(downloads, "alpha")
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    rc, out = run("modpack", "build", "--out", bad)
    assert rc == 1 and "Could not read" in out


# ------------------------------------------------------------------------------------------------- update
def test_update_skip(run):
    rc, out = run("update", "--skip", "alpha@2.0")
    assert rc == 0 and "Won't offer alpha 2.0 again." in out
    assert mu.load_skips(run.state) == {"alpha": "2.0"}
    rc, out = run("update", "--skip", "alpha")
    assert rc == 0 and "Cleared the skipped version of alpha." in out
    assert mu.load_skips(run.state) == {}
    assert run("update", "--skip", "ghost@1")[0] == 3
    assert run("update", "--mod", "ghost")[0] == 3


def test_update_fetch_problems(run, monkeypatch):
    def offline(*a, **k):
        raise DownloadError("no internet")
    monkeypatch.setattr(mp, "fetch_latest", offline)
    rc, out = run("update", "--check")
    assert rc == 1 and "Could not get the modpack: no internet" in out
    monkeypatch.setattr(mp, "fetch_latest", lambda *a, **k: None)
    rc, out = run("update")
    assert rc == 0 and "No modpack published yet" in out


def test_update_with_local_modpack_file(run, game, downloads, tmp_path):
    zips(downloads, "alpha")
    pack = tmp_path / "pack.json"
    assert run("modpack", "build", "--out", pack, game=game)[0] == 0
    rc, out = run("update", "--modpack", pack, "--check", game=game)
    assert rc == 0 and f"Game build {BUILD}; modpack set for build {BUILD}" in out
    assert "[new] Alpha -> 1.0: not installed" in out
    assert "Modpack from release" not in out
    rc, out = run("update", "--modpack", pack, "--check", game=game, build="1.0.900.0")
    assert rc == 1 and "HELD: The modpack has no tested set for game build 1.0.900.0" in out


class FakePlan:
    def __init__(self, held=None, pending=(), lines=("[update] Alpha -> 2.0",)):
        self.build, self.modpack_build = BUILD, BUILD
        self.held, self.pending, self._lines = held, list(pending), list(lines)

    def summary(self):
        return ([f"HELD: {self.held}"] if self.held else []) + self._lines


@pytest.fixture
def fake_update(monkeypatch):
    st = {"plan": FakePlan(pending=["alpha"]), "runs": [], "fail": False, "only": []}
    monkeypatch.setattr(mp, "fetch_latest", lambda *a, **k: {"builds": {}, "_release": {"tag": "v1.2.0",
                                                                                         "verified": st.get("verified", True)}})

    def plan(ctx, pack, only=None):
        st["only"].append(only)
        return st["plan"]

    def run_updates(ctx, plan, ui, progress=None):
        if st["fail"]:
            raise DownloadError("hash mismatch")
        progress(0, 100)
        progress(50, 100)
        progress(50, 100)
        progress(7, None)
        st["runs"].append(ui.assume_yes)
        return ["Alpha updated to 2.0", "Done."]
    monkeypatch.setattr(mu, "plan_updates", plan)
    monkeypatch.setattr(mu, "run_updates", run_updates)
    return st


def test_update_held_and_check(run, fake_update, monkeypatch):
    fake_update["plan"] = FakePlan(held="game build unreadable")
    rc, out = run("update")
    assert rc == 1 and "Modpack from release v1.2.0 (verified against SHA256SUMS)" in out
    assert "  HELD: game build unreadable" in out and not fake_update["runs"]
    fake_update["plan"] = FakePlan(pending=["alpha", "beta"])
    fake_update["verified"] = False
    rc, out = run("update", "--check", "--mod", "alpha")
    assert rc == 0 and "(not verified: no SHA256SUMS)" in out and "2 update(s) available" in out
    assert fake_update["only"][-1] == "alpha" and not fake_update["runs"]
    fake_update["plan"] = FakePlan(lines=["Every installed mod is the modpack's tested version."])
    rc, out = run("update")
    assert rc == 0 and "update(s) available" not in out and not fake_update["runs"]
    monkeypatch.setattr(cli, "_COLOR", True)
    fake_update["plan"] = FakePlan(held="x")
    assert "\033[31mHELD: x" in run("update")[1]


def test_update_runs(run, fake_update):
    rc, out = run("update", "--yes")
    assert rc == 0 and "0.0 MB (0%)" in out and out.count("(50%)") == 1 and "Alpha updated to 2.0" in out
    assert fake_update["runs"] == [True]
    fake_update["fail"] = True
    rc, out = run("update")
    assert rc == 1 and "hash mismatch" in out


# ----------------------------------------------------------------------------------------------- main
def test_main_ctrl_c_returns_130(run, monkeypatch):
    def interrupted(ctx):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, "cmd_status", interrupted)
    assert run("status")[0] == 130


def test_main_requires_a_command(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2 and "required" in capsys.readouterr().err


def test_python_dash_m_leonida(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["leonida", "--state-dir", str(tmp_path / "s"), "status"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("leonida", run_name="__main__")
    assert exc.value.code == 0 and "State folder:" in capsys.readouterr().out


def test_cli_module_as_script(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--state-dir", str(tmp_path / "s"), "status"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # "found in sys.modules" when re-running leonida.cli
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("leonida.cli", run_name="__main__")
    assert exc.value.code == 0 and "Profile:" in capsys.readouterr().out


def test_cli_imports_without_stdout():
    code = "import sys; sys.stdout = None; import leonida.cli"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                          cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0, proc.stderr
