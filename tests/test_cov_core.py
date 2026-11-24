"""Coverage for the engine's core modules: paths, log, onlinesafe, snapshot, matcher, checks, manifest, session.

Everything runs against tmp_path folders and small hand-written manifests; nothing touches the real game.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest
from conftest import make_zip

from leonida import paths, snapshot
from leonida import session as session_mod
from leonida.checks import ERROR, INFO, WARNING, hotkey_map, run_checks
from leonida.log import ADD, Action, InstallLog, Step
from leonida.manifest import GameBuild, ManifestError, build_key, in_build_range, load_manifest
from leonida.matcher import (
    build_lock,
    match_files,
    read_lock,
    scan_folder,
    sha256_file,
    verify_lock,
    write_lock,
)
from leonida.onlinesafe import OFFLINE_DIR, RECORD, OnlineSafeError, go_online_safe, mod_items, restore_mods, status
from leonida.session import Session

BUILD = "1.0.1013.20"


# ------------------------------------------------------------------------------------------------ helpers
def mod_entry(mid: str, order: int, files=None, **extra) -> dict:
    """A minimal valid mods.json entry (copy method unless ``install`` is given)."""
    raw = {"id": mid, "order": order, "tier": "core", "layer": "test", "name": mid.title(), "version": "1.0",
           "source": "direct", "page": f"https://{mid}.example/page", "archive": [f"{mid}-*.zip"],
           "install": {"method": "copy", "files": [{"match": f} for f in (files or [f"{mid}.asi"])]}}
    raw.update(extra)
    return raw


def mini_manifest(root: Path, mods: list[dict], profiles: list[dict] | None = None, keys: list[dict] | None = None,
                  default: str | None = None, **top) -> Path:
    """Write mods.json/profiles.json/hotkeys.json into ``root`` and return it."""
    root.mkdir(parents=True, exist_ok=True)
    data = {"pack": "Leonida V", "version": "9", "testedGameBuilds": [BUILD],
            "gameExeNames": ["GTA5_Enhanced.exe"], "onlineSafeItems": ["*.asi", "scripts"], "mods": mods}
    data.update(top)
    (root / "mods.json").write_text(json.dumps(data), encoding="utf-8")
    profiles = profiles or [{"id": "all", "name": "All", "include": [m["id"] for m in mods]}]
    prof = {"profiles": profiles, "default": default or profiles[0]["id"]}
    (root / "profiles.json").write_text(json.dumps(prof), encoding="utf-8")
    (root / "hotkeys.json").write_text(json.dumps({"keys": keys or []}), encoding="utf-8")
    return root


def bundled_copy(root: Path) -> Path:
    src = load_manifest.__globals__["resources"].files("leonida.manifest")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("mods.json", "profiles.json", "hotkeys.json"):
        (root / name).write_text(src.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8")
    return root


def edit_json(path: Path, fn) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data), encoding="utf-8")


# ------------------------------------------------------------------------------------------------- paths
def test_state_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LEONIDA_STATE_DIR", str(tmp_path / "s"))
    assert paths.state_dir() == tmp_path / "s"


def test_state_dir_windows_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.delenv("LEONIDA_STATE_DIR", raising=False)
    monkeypatch.setattr(paths, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert paths.state_dir() == tmp_path / "Local" / "LeonidaV"
    monkeypatch.delenv("LOCALAPPDATA")
    assert paths.state_dir() == Path.home() / "AppData" / "Local" / "LeonidaV"


def test_state_dir_elsewhere_uses_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("LEONIDA_STATE_DIR", raising=False)
    monkeypatch.setattr(paths, "sys", types.SimpleNamespace(platform="linux"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.state_dir() == tmp_path / "xdg" / "leonida-v"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert paths.state_dir() == Path.home() / ".local" / "share" / "leonida-v"


def test_default_download_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LEONIDA_DOWNLOAD_DIR", str(tmp_path / "dl"))
    assert paths.default_download_dir() == tmp_path / "dl"
    assert paths.Config().downloads() == tmp_path / "dl"
    monkeypatch.delenv("LEONIDA_DOWNLOAD_DIR")
    assert paths.default_download_dir() == Path.home() / "Downloads" / "LeonidaV"


def test_config_roundtrip_ignores_unknown_keys(tmp_path):
    assert paths.Config.load(tmp_path / "nothing-here") == paths.Config()
    cfg = paths.Config(game_dir="G", download_dir=str(tmp_path / "d"), profile="p", swaps={"a": "b"})
    saved = cfg.save(tmp_path / "st")
    assert saved.name == paths.CONFIG_NAME and not saved.with_suffix(".tmp").exists()
    edit_json(saved, lambda d: d.update(future_option=1))
    loaded = paths.Config.load(tmp_path / "st")
    assert loaded == cfg
    assert loaded.downloads() == tmp_path / "d"


# --------------------------------------------------------------------------------------------------- log
def test_log_roundtrip_get_and_last_active(tmp_path):
    log = InstallLog(tmp_path / "log.json")
    assert log.last_active() is None and log.installed_mods() == set()
    s1 = log.new_step("alpha", "copy")
    s1.actions.append(Action(ADD, "alpha.asi", "abc"))
    s1.status = "done"
    s2 = log.new_step("beta", "guided")
    s2.status = "rolled-back"
    log.save()
    again = InstallLog(tmp_path / "log.json")
    assert [s.id for s in again.steps] == [1, 2]
    assert again.get(1).actions[0] == Action(ADD, "alpha.asi", "abc")
    assert again.installed_mods() == {"alpha"}
    assert again.last_active().id == 1
    assert not again.get(2).active
    with pytest.raises(KeyError, match="No step 9"):
        again.get(9)


def test_step_active_states():
    for st, active in (("running", True), ("done", True), ("failed", True), ("rolled-back", False)):
        assert Step(1, "m", "copy", "t", status=st).active is active


# -------------------------------------------------------------------------------------------- onlinesafe
PATS = ("*.asi", "scripts", "dinput8.dll")


def test_online_safe_dry_run_moves_nothing(game):
    (game / "a.asi").write_text("x")
    assert go_online_safe(game, PATS, dry_run=True) == ["a.asi"]
    assert (game / "a.asi").exists() and not (game / OFFLINE_DIR).exists()


def test_online_safe_without_mods_returns_empty(game):
    assert status(game, PATS) == "clean"
    assert go_online_safe(game, PATS) == []
    assert not (game / OFFLINE_DIR).exists()


def test_restore_without_record_raises(game):
    with pytest.raises(OnlineSafeError, match="Nothing to restore"):
        restore_mods(game)


def test_restore_dry_run_and_mixed_status(game):
    (game / "a.asi").write_text("x")
    (game / "scripts").mkdir()
    assert go_online_safe(game, PATS) == ["a.asi", "scripts"]
    assert [p.name for p in mod_items(game, PATS)] == []  # the offline folder itself never counts
    assert restore_mods(game, dry_run=True) == ["a.asi", "scripts"]
    assert not (game / "a.asi").exists()
    (game / "new.asi").write_text("y")  # something new appeared while mods were out
    assert status(game, PATS) == "mixed"
    (game / "new.asi").unlink()
    # one recorded item vanished from storage: restore skips it and still cleans up
    import shutil
    shutil.rmtree(game / OFFLINE_DIR / "scripts")
    assert restore_mods(game) == ["a.asi", "scripts"]
    assert (game / "a.asi").exists() and not (game / "scripts").exists()
    assert not (game / OFFLINE_DIR).exists()


def test_restore_keeps_offline_dir_with_extra_files(game):
    (game / "a.asi").write_text("x")
    go_online_safe(game, PATS)
    (game / OFFLINE_DIR / "note.txt").write_text("user's file")
    restore_mods(game)
    assert not (game / OFFLINE_DIR / RECORD).exists()
    assert (game / OFFLINE_DIR / "note.txt").exists()  # rmdir failed quietly


# ---------------------------------------------------------------------------------------------- snapshot
def test_snapshot_ignores_offline_dir_and_records_empty_managed_dirs(game, tmp_path):
    (game / OFFLINE_DIR).mkdir()
    (game / OFFLINE_DIR / "x.asi").write_text("x")
    (game / "scripts" / "empty").mkdir(parents=True)
    (game / "scripts" / "a.dll").write_text("a")
    (game / "other").mkdir()
    (game / "other" / "deep.txt").write_text("not walked")
    snap = snapshot.take_snapshot(game)
    assert not any(k.startswith(OFFLINE_DIR) for k in snap["files"])
    assert snap["files"]["scripts/empty/"] == [0, 0, "dir"]
    assert "scripts/a.dll" in snap["files"] and "other/deep.txt" not in snap["files"]
    assert "other" in snap["top_dirs"] and OFFLINE_DIR not in snap["top_dirs"]
    out = tmp_path / "snaps" / "s.json"
    snapshot.save_snapshot(snap, out)
    assert snapshot.load_snapshot(out) == snap
    assert snapshot.load_snapshot(tmp_path / "missing.json") is None


def test_snapshot_diff_dirs_and_summary(game):
    before = snapshot.take_snapshot(game)
    (game / "scripts" / "empty").mkdir(parents=True)
    (game / "bink2w64.dll").write_text("patched")
    (game / "update" / "update.rpf").unlink()
    (game / "update").rmdir()
    (game / "new.asi").write_text("n")
    d = snapshot.diff(before, snapshot.take_snapshot(game))
    assert d.added == ["new.asi", "scripts/empty/"]
    assert d.changed == ["bink2w64.dll"]
    assert d.added_dirs == ["scripts"] and d.removed_dirs == ["update"]
    assert d.summary() == "2 added, 1 changed, 0 removed, top-level folders +1/-1"
    assert not d.empty
    assert snapshot.Diff().summary() == "0 added, 0 changed, 0 removed" and snapshot.Diff().empty


def test_snapshot_same_rules():
    same = snapshot._same
    assert same([0, 0, "dir"], [0, 0, "dir"])
    assert not same([0, 0, "dir"], [1, 5, "abc"])
    assert not same([1, 5, "abc"], [2, 5, "abc"])          # size differs
    assert same([1, 5, "abc"], [1, 9, "abc"])              # same hash, mtime ignored
    assert not same([1, 5, "abc"], [1, 5, "abd"])
    assert same([1, 5, None], [1, 5, None])                # big files: size + mtime
    assert not same([1, 5, None], [1, 6, None])


def test_snapshot_big_files_skip_hash(game, monkeypatch):
    monkeypatch.setattr(snapshot, "HASH_LIMIT", 0)
    snap = snapshot.take_snapshot(game)
    assert snap["files"]["bink2w64.dll"][2] is None


# ----------------------------------------------------------------------------------------------- matcher
def test_scan_folder_missing_and_filters(tmp_path):
    assert scan_folder(tmp_path / "nope") == []
    (tmp_path / "a.zip").write_text("a")
    (tmp_path / "b.zip.crdownload").write_text("b")
    (tmp_path / ".hidden.zip").write_text("h")
    (tmp_path / "readme.txt").write_text("r")
    (tmp_path / "sub").mkdir()
    assert scan_folder(tmp_path) == [tmp_path / "a.zip"]


def test_match_ambiguous_unmatched_and_assignment(tmp_path):
    m = load_manifest(mini_manifest(tmp_path / "m", [
        mod_entry("alpha", 1, archive=["mod-*.zip"]),
        mod_entry("beta", 2, archive=["mod-*.zip"]),
        mod_entry("gamma", 3),
    ]))
    mods = list(m.mods.values())
    f1 = tmp_path / "mod-1.zip"
    f2 = tmp_path / "random.zip"
    f3 = tmp_path / "gamma-1.zip"
    for f in (f1, f2, f3):
        f.write_text(f.name)
    r = match_files(mods, [f1, f2, f3])
    assert r.ambiguous == {f1: ["alpha", "beta"]}
    assert r.unmatched == [f2]
    assert r.matched == {"gamma": f3}
    assert [x.id for x in r.missing(mods)] == ["alpha", "beta"]
    # an assignment to a mod that isn't in the list is ignored; a valid one wins over pattern matches
    r = match_files(mods, [f1, f2, f3], {"MOD-1.ZIP": "unknown", "random.zip": "gamma"})
    assert f1 in r.ambiguous
    assert r.matched["gamma"] == f2 and r.duplicates["gamma"] == [f3]


def test_lock_problems(tmp_path):
    a = tmp_path / "a.zip"
    a.write_bytes(b"aaaa")
    b = tmp_path / "b.zip"
    b.write_bytes(b"bbbb")
    lock = build_lock("Leonida V", "9", {"alpha": a, "beta": b})
    assert [e["mod"] for e in lock["entries"]] == ["alpha", "beta"]
    assert lock["entries"][0]["sha256"] == sha256_file(a)
    write_lock(tmp_path / "st" / "leonida.lock", lock)
    assert read_lock(tmp_path / "st" / "leonida.lock") == lock
    assert read_lock(tmp_path / "missing.lock") is None
    assert verify_lock(lock, {"alpha": a, "beta": b}) == []
    a.write_bytes(b"AAAA")  # same size, other content
    problems = verify_lock(lock, {"alpha": a})
    assert any("alpha: a.zip differs" in p for p in problems)
    assert any("beta: locked file b.zip is no longer" in p for p in problems)
    # installing only alpha must not report beta (the lock may come from a bigger profile)
    assert verify_lock(lock, {"alpha": a}, only=["alpha"]) == [p for p in problems if p.startswith("alpha")]


# ------------------------------------------------------------------------------------------------ checks
def codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level == level}


def test_checks_nve_gameconfig_is_left_alone_and_others_warn(manifest, game):
    mods = manifest.resolve("core")
    data = game / "onigiri" / "common" / "data"
    data.mkdir(parents=True)
    (data / "gameconfig.xml").write_text("<nve/>")
    f = run_checks(manifest, mods, game, game_version=BUILD)
    assert "gameconfig-onigiri" not in codes(f)
    (game / "onigiri" / "other").mkdir()
    (game / "onigiri" / "other" / "GameConfig.xml").write_text("<x/>")
    (game / "onigiri" / "other" / "readme.txt").write_text("x")
    f = run_checks(manifest, mods, game, game_version=BUILD)
    warn = [x for x in f if x.code == "gameconfig-onigiri"]
    assert len(warn) == 1 and warn[0].level == WARNING and "onigiri\\other\\GameConfig.xml" in warn[0].message


def test_checks_unknown_prereq_paid_and_manual_sources(manifest, game):
    paid = [m for m in manifest.mods.values() if m.tier == "paid"]
    f = run_checks(manifest, paid, game, game_version=BUILD,
                   prerequisites={"dotnet48": None, "vcredist": True, "made-up": None})
    unknown = [x for x in f if x.code == "prereq-unknown"]
    assert {x.level for x in unknown} == {INFO}
    assert any("Microsoft .NET Framework 4.8" in x.message for x in unknown)
    assert any("made-up" in x.message for x in unknown)  # unknown id: shown by its id
    assert {x.mod for x in f if x.code == "paid"} == {m.id for m in paid}


def test_checks_loader_dlls(manifest, game):
    (game / "xinput1_4.dll").write_text("someone's loader")
    (game / "version.dll").write_text("another loader")
    (game / "winmm.dll").write_text("placed by leonida")
    mods = manifest.resolve("core")
    f = run_checks(manifest, mods, game, game_version=BUILD, installed_paths={"winmm.dll"})
    by = {x.code: x for x in f if x.code.startswith("loader")}
    assert "xinput1_4.dll" in by["loader-overwrite"].message and by["loader-overwrite"].level == WARNING
    assert "version.dll" in by["loader-dll"].message and by["loader-dll"].level == INFO
    assert not any("winmm.dll" in x.message for x in f)


def test_checks_build_findings(tmp_path, game):
    m = load_manifest(mini_manifest(tmp_path / "m", [
        mod_entry("hud-a", 1, slot="hud", minGameBuild="1.0.2000.0"),
        mod_entry("hud-b", 2, slot="hud", tier="alternative"),
        mod_entry("solo", 3, minGameBuild="1.0.2000.0"),
        mod_entry("older", 4, minGameBuild="1.0.1100.0",
                  gameBuilds=[{"min": "1.0.1000.0", "max": "1.0.1099.0", "version": "0.9"}]),
    ], profiles=[{"id": "p", "name": "P", "include": ["hud-a", "solo", "older"]}]))
    mods = m.for_build(BUILD).resolve("p")
    f = run_checks(m, mods, game, game_version=BUILD)
    errs = {x.mod: x.message for x in f if x.code == "build-unsupported"}
    assert "leonida swap hud-a <alternative>" in errs["hud-a"] and "Hud-B" in errs["hud-a"]
    assert "Pick another profile" in errs["solo"]
    assert any(x.code == "build-variant" and "Older 0.9" in x.message for x in f)
    assert "version-untested" not in codes(f)  # BUILD is the tested one
    assert "version-untested" in codes(run_checks(m, mods, game, game_version="1.0.900.0"))
    assert "version-unknown" in codes(run_checks(m, mods, game, game_version=None))
    assert "version-newer" in codes(run_checks(m, mods, game, game_version="1.0.9999.0"), WARNING)


def test_checks_resource_extensions_slots_pairs_and_gpu(manifest, game):
    re_only = [manifest.mod("resourceextensions")]
    (game / "gameconfig.xml").write_text("<x/>")
    f = run_checks(manifest, re_only, game, game_version=BUILD)
    assert "gameconfig" in codes(f, ERROR) and "gameconfig-rpf" in codes(f, INFO)
    f = run_checks(manifest, re_only + [manifest.mod("nve")], game, game_version=BUILD)
    assert "gameconfig-nve" in codes(f, INFO) and "gameconfig-rpf" not in codes(f)
    huds = [manifest.mod("hud"), manifest.mod("hud-fbicat")]
    f = run_checks(manifest, huds, game, game_version=BUILD, gpu_names=[], profile_requires={"gpu": "rtx50"})
    assert "slot-clash" in codes(f, ERROR)
    gpu = [x for x in f if x.code == "gpu"]
    assert gpu and "this profile needs" in gpu[0].message and "no GPU detected" in gpu[0].message


def test_hotkey_map_applies_overrides(tmp_path):
    m = load_manifest(mini_manifest(tmp_path / "m", [mod_entry("alpha", 1), mod_entry("beta", 2)], keys=[
        {"mod": "alpha", "action": "Open", "key": "F5"}, {"mod": "beta", "action": "Menu", "key": "f5"}]))
    mods = list(m.mods.values())
    assert hotkey_map(m, mods) == {"F5": [("alpha", "Open"), ("beta", "Menu")]}
    assert hotkey_map(m, mods, {"beta/Menu": "f6"}) == {"F5": [("alpha", "Open")], "F6": [("beta", "Menu")]}
    assert hotkey_map(m, mods[:1]) == {"F5": [("alpha", "Open")]}
    f = run_checks(m, mods, None)
    assert "hotkey" in codes(f, WARNING) and "no-game" in codes(f, ERROR)


# ---------------------------------------------------------------------------------------------- manifest
def test_build_helpers():
    assert build_key(None) is None and build_key("abc") is None
    assert build_key("1.0") == (1, 0, 0, 0)
    assert not in_build_range(None, None, None)
    assert in_build_range("1.0.5", "1.0.1", None) and not in_build_range("1.0.5", None, "1.0.4")
    assert GameBuild("1.0.1", "1.0.2").label == "1.0.1 to 1.0.2"
    assert GameBuild("1.0.1").label == "1.0.1 or newer"
    assert GameBuild(None, "1.0.2").label == "up to 1.0.2"
    assert GameBuild().label == "any build"
    assert GameBuild("1.0.1", "1.0.2").contains("1.0.1.5")


def test_mod_properties(tmp_path):
    m = load_manifest(mini_manifest(tmp_path / "m", [
        mod_entry("alpha", 1, maxGameBuild="1.0.2000.0",
                  redistribution={"allowed": True, "proof": "https://alpha.example/licence"}),
        mod_entry("beta", 2, source="patreon", install={"method": "guided", "steps": ["do it"]}),
    ]))
    a, b = m.mod("alpha"), m.mod("beta")
    assert a.automatic and not b.automatic
    assert b.manual_download and not a.manual_download
    assert a.redistributable and not b.redistributable
    assert a.supported_builds == "up to 1.0.2000.0" and b.supported_builds == "any build"
    assert a.for_build("1.0.3000.0").unsupported.startswith("Alpha supports game builds up to 1.0.2000.0")
    assert [x.id for x in m.ordered(["beta", "alpha", "beta"])] == ["alpha", "beta"]
    assert m.is_tested(BUILD) and not m.is_tested(None) and not m.newer_than_tested(None)


@pytest.mark.parametrize("mutate, match", [
    (lambda d: d["mods"][0].pop("page"), "is missing 'page'"),
    (lambda d: d["mods"][0].update(tier="legendary"), "unknown tier"),
    (lambda d: d["mods"][0]["install"].update(files="x.asi"), "'files' must be a list"),
    (lambda d: d["mods"][0]["install"].update(files=[{"match": "a", "type": "link"}]), "type must be 'file' or 'dir'"),
    (lambda d: d["mods"][0]["install"].update(files=[{"to": "x"}]), "needs a 'match'"),
    (lambda d: d["mods"][0]["install"].update(method="teleport"), "unknown install method"),
    (lambda d: d["mods"][0]["install"].update(files=[]), "method 'copy' needs a 'files' list"),
    (lambda d: d["mods"][0].update(install={"method": "run"}), "method 'run' needs a 'run'"),
    (lambda d: d["mods"][0].update(download={"type": "direct", "url": "http://x/y.zip", "file": "y.zip"}),
     "direct download needs an https"),
    (lambda d: d["mods"][0].update(download={"type": "github", "repo": "o/r"}), "needs 'repo' and 'asset'"),
    (lambda d: d["mods"][0].update(download={"type": "github", "repo": "o/r", "asset": "*.zip", "tag": " "}),
     "'tag' must be a non-empty string"),
    (lambda d: d["mods"][0].update(download={"type": "ftp"}), "download type must be"),
    (lambda d: d["mods"][0].update(minGameBuild="new"), "game build must look like"),
    (lambda d: d["mods"][0].update(minGameBuild="1.0.2", maxGameBuild="1.0.1"), "is greater than max"),
    (lambda d: d["mods"][1].update(id="alpha"), "Duplicate mod id 'alpha'"),
    (lambda d: d["mods"][1].update(replaces="ghost"), "replaces unknown mod 'ghost'"),
    (lambda d: d["mods"][1].update(warnings=[{"with": "ghost", "message": "m"}]), "warning about unknown mod 'ghost'"),
    (lambda d: d["mods"][1].update(whenSelected={"alpha": {"run": 5}}), "'run' must be a string"),
    (lambda d: d["mods"][1].update(whenSelected={"ghost": {"notes": "n"}}), "refers to unknown mod 'ghost'"),
    (lambda d: d["mods"][1].update(whenMissing={"alpha": {"warnings": [{"with": "ghost", "message": "m"}]}}),
     r"whenMissing\['alpha'\] has a warning about unknown mod"),
    (lambda d: d.update(testedGameBuilds="1.0"), "testedGameBuilds must be a list"),
    (lambda d: d["mods"][0]["install"].update(files=[{"match": "a", "to": "../x"}]), "must stay inside"),
    (lambda d: d["mods"][0].update(image="http://img.example/a.png"), "image must be an https URL"),
    (lambda d: d["mods"][0].update(redistribution={"allowed": "yes"}), "redistribution must be"),
    (lambda d: d["mods"][0].update(redistribution={"allowed": False, "why": 1}), "unknown key"),
    (lambda d: d["mods"][0].update(redistribution={"allowed": True}), "needs an https 'proof'"),
    (lambda d: d["mods"][0].update(gameBuilds={}), "'gameBuilds' must be a list"),
    (lambda d: d["mods"][0].update(gameBuilds=["x"]), r"gameBuilds\[0\]: must be an object"),
    (lambda d: d["mods"][0].update(gameBuilds=[{"min": "1.0.1", "colour": "red"}]), "unknown key"),
    (lambda d: d["mods"][0].update(minGameBuild="1.0.5", gameBuilds=[{"min": "1.0.6", "version": "2"}]),
     "would never be used"),
    (lambda d: d["mods"][0].update(minGameBuild="1.0.5", gameBuilds=[{"max": "1.0.4", "unsupported": " "}]),
     "'unsupported' must be a non-empty reason"),
    (lambda d: d["mods"][0].update(minGameBuild="1.0.5",
                                   gameBuilds=[{"max": "1.0.4", "unsupported": "no", "version": "1"}]),
     "can't also override"),
    (lambda d: d["mods"][0].update(minGameBuild="1.0.5", gameBuilds=[{"max": "1.0.4"}]),
     "give the values that differ"),
    (lambda d: d["mods"][0].update(minGameBuild="1.0.5", gameBuilds=[{"max": "1.0.4", "archive": []}]),
     "'archive' can't be empty"),
    (lambda d: d["mods"][0].update(minGameBuild="1.0.5", gameBuilds=[{"max": "1.0.4", "steps": [1]}]),
     "'steps' must be a list of strings"),
    (lambda d: d["mods"][0].update(minGameBuild="1.0.5", gameBuilds=[{"max": "1.0.4", "page": "ftp://x"}]),
     "page must be an https URL"),
    (lambda d: d["mods"][0].update(minGameBuild="1.0.5",
                                   gameBuilds=[{"max": "1.0.4", "download": {"type": "x"}}]),
     "download type must be"),
    (lambda d: d["mods"][1].update(whenSelected=[]), "must be an object"),
    (lambda d: d["mods"][1].update(whenSelected={"beta": {"notes": "n"}}), "can't depend on itself"),
    (lambda d: d["mods"][1].update(whenSelected={"alpha": {}}), "give the values to use"),
    (lambda d: d["mods"][1].update(whenSelected={"alpha": {"page": "https://x"}}), "unknown key"),
    (lambda d: d["mods"][1].update(whenSelected={"alpha": {"skip": "r", "run": "x"}}), "can't also override"),
    (lambda d: d["mods"][1].update(whenSelected={"alpha": {"skip": " "}}), "'skip' must be a non-empty reason"),
    (lambda d: d["mods"][1].update(whenSelected={"alpha": {"warnings": "w"}}), "'warnings' must be a list"),
    (lambda d: d["mods"][1].update(whenSelected={"alpha": {"files": []}}), "needs a 'files' list"),
])
def test_manifest_validation_errors(tmp_path, mutate, match):
    d = mini_manifest(tmp_path / "m", [mod_entry("alpha", 1), mod_entry("beta", 2)])
    edit_json(d / "mods.json", mutate)
    with pytest.raises(ManifestError, match=match):
        load_manifest(d)


def test_manifest_profile_and_hotkey_errors(tmp_path):
    mods = [mod_entry("alpha", 1)]
    d = mini_manifest(tmp_path / "loop", mods, profiles=[
        {"id": "a", "name": "A", "include": ["@profile:b"]}, {"id": "b", "name": "B", "include": ["@profile:a"]}])
    with pytest.raises(ManifestError, match="Profile include loop"):
        load_manifest(d)
    d = mini_manifest(tmp_path / "default", mods, default="ghost")
    with pytest.raises(ManifestError, match="Default profile 'ghost'"):
        load_manifest(d)
    d = mini_manifest(tmp_path / "keys", mods, keys=[{"mod": "ghost", "action": "x", "key": "F1"}])
    with pytest.raises(ManifestError, match="hotkeys.json refers to unknown mod 'ghost'"):
        load_manifest(d)


def test_manifest_tier_and_profile_tokens(tmp_path):
    d = mini_manifest(tmp_path / "m", [mod_entry("alpha", 1), mod_entry("beta", 2, tier="optional")], profiles=[
        {"id": "base", "name": "Base", "include": ["@tier:core"]},
        {"id": "more", "name": "More", "include": ["@profile:base", "@tier:optional"]}],
        testedGameBuild="1.0.1158.13")
    m = load_manifest(d)
    assert [x.id for x in m.resolve("base")] == ["alpha"]
    assert [x.id for x in m.resolve("more")] == ["alpha", "beta"]
    assert m.tested_builds == (BUILD, "1.0.1158.13") and m.tested_build == "1.0.1158.13"


def test_manifest_file_errors(tmp_path):
    d = bundled_copy(tmp_path / "m")
    (d / "hotkeys.json").unlink()
    with pytest.raises(ManifestError, match="Manifest file not found: hotkeys.json"):
        load_manifest(d)
    (d / "hotkeys.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError, match="hotkeys.json is not valid JSON"):
        load_manifest(d)


# ------------------------------------------------------------------------------------------------ session
@pytest.fixture
def sess_manifest(tmp_path):
    return mini_manifest(tmp_path / "sm", [
        mod_entry("alpha", 1, slot="hud"),
        mod_entry("alpha2", 2, slot="hud", tier="alternative"),
        mod_entry("beta", 3, whenMissing={"alpha2": {"skip": "Only needed with Alpha2."}}),
    ], profiles=[{"id": "all", "name": "All", "include": ["alpha", "beta"]},
                 {"id": "alt", "name": "Alt", "include": ["alpha2", "beta"]}])


def test_session_bad_saved_selection_keeps_manifest_working(sess_manifest, state):
    paths.Config(swaps={"alpha": "beta"}).save(state)  # not the same slot -> resolve() raises
    s = Session(state, sess_manifest)
    assert set(s.manifest.mods) == {"alpha", "alpha2", "beta"}
    with pytest.raises(ManifestError, match="do not share a slot"):
        s.mods()


def test_session_other_profile_and_not_needed(sess_manifest, state, monkeypatch):
    monkeypatch.setattr(session_mod, "detect_gpus", lambda: ["GPU X"])
    s = Session(state, sess_manifest, game_build=BUILD)
    assert [m.id for m in s.mods()] == ["alpha"]
    assert [m.id for m in s.not_needed()] == ["beta"]
    assert [m.id for m in s.mods("alt")] == ["alpha2", "beta"]
    assert s.not_needed("alt") == []
    assert s.gpus() == ["GPU X"] and s.gpus() is s.gpus()
    s.manifest = load_manifest(sess_manifest)  # setter resets the resolved cache
    assert s.manifest.game_build == BUILD


def test_session_refresh_game_version_and_installer(sess_manifest, state, game, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1000.0")
    s = Session(state, sess_manifest)
    with pytest.raises(RuntimeError, match="Game folder is not set"):
        s.installer(object())
    assert s.game_version() is None  # no game folder
    s.config.game_dir = str(game)
    assert s.game_version() == "1.0.1000.0"
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1100.0")
    assert s.refresh_game_version() == "1.0.1100.0"
    monkeypatch.setattr(session_mod, "find_7zip", lambda: None)
    inst = s.installer(object(), dry_run=True)
    assert inst.game == game and inst.dry_run


def test_session_save_and_overrides(sess_manifest, state, tmp_path):
    s = Session(state, sess_manifest, download_dir=str(tmp_path / "dl"), game_dir=str(tmp_path / "g"))
    assert s.config.downloads() == tmp_path / "dl" and s.game_dir() == tmp_path / "g"
    s.config.profile = "alt"
    s.save()
    assert Session(state, sess_manifest).profile_id == "alt"
    make_zip(tmp_path / "dl" / "alpha-1.zip", {"alpha.asi": "a"})
    assert s.matches().matched == {}  # the "alt" profile has no alpha
    assert set(s.matches(s.mods("all")).matched) == {"alpha"}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_state_dir_on_this_windows_pc(monkeypatch):
    monkeypatch.delenv("LEONIDA_STATE_DIR", raising=False)
    assert paths.state_dir() == Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "LeonidaV"
