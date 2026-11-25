"""Whole-product acceptance: every edition x game build x modpack runs the full user flow on a fake game folder
(tests/acceptance_flow.py), plus the product bugs that flow found."""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

import acceptance_flow as A
import pytest
from conftest import AutoUI, make_zip

from leonida import log as L
from leonida.installer import Installer
from leonida.log import InstallLog
from leonida.manifest import FileSpec, Mod, load_manifest
from leonida.modupdate import dependents
from leonida.session import Session
from leonida.snapshot import diff, take_snapshot


# ------------------------------------------------------------------------------------------------ the matrix
@pytest.mark.parametrize("edition, build, pack", A.combos(), ids=lambda v: str(v))
def test_full_user_flow(tmp_path, edition, build, pack):
    res = A.run(tmp_path, edition, build, pack)
    assert res.ok, f"{edition} {build} {pack}: FAIL at {res.step}: {res.detail}"
    assert res.mods > 0


def test_full_flow_with_locked_settings_and_variants(tmp_path):
    """Give one more copy mod of a pack with variants locked settings (with pack and variant values) and run the
    flow, so writing at install, the variant switch and the byte-for-byte uninstall are covered for an ini the real
    data doesn't lock yet."""
    d = tmp_path / "manifest"
    src = resources.files("leonida.manifest")
    d.mkdir()
    for name in ("mods.json", "profiles.json", "hotkeys.json", "modpacks.json"):
        (d / name).write_text(src.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8")
    m = load_manifest(d)
    pack = next(p for p in m.packs.values() if len(p.variants) > 1)
    target = next(x for x in m.resolve_pack(pack.id)
                  if x.method == "copy" and not x.require_members and any(f.match.lower().endswith(".ini") and
                                                                          f.type == "file" for f in x.files))
    ini = next(f for f in target.files if f.match.lower().endswith(".ini"))
    path = (Path(ini.to) / ini.match).as_posix().removeprefix("./")
    data = json.loads((d / "mods.json").read_text(encoding="utf-8"))
    raw = next(x for x in data["mods"] if x["id"] == target.id)
    raw.setdefault("settings", []).append({"file": path, "keys": {"Leonida/Density": {
        "value": "1.00", "packs": {pack.id: "1.50"}, "variants": {pack.variants[-1].id: "2.00"},
        "why": "acceptance"}, "Leonida/Mode": "locked"}})
    (d / "mods.json").write_text(json.dumps(data), encoding="utf-8")
    plain = A.run(tmp_path / "plain", "enhanced", "1.0.1013.20", pack.id)
    res = A.run(tmp_path / "work", "enhanced", "1.0.1013.20", pack.id, manifest_dir=d)
    assert plain.ok and res.ok, f"FAIL at {res.step or plain.step}: {res.detail or plain.detail}"

    def count(r, prefix):
        return next((int(n.split(prefix)[1].split()[0]) for n in r.notes if n.startswith(prefix)), 0)

    written, variant = "locked settings written: ", f"variant {pack.variants[-1].id}: settings re-applied for "
    assert count(res, written) == count(plain, written) + 2       # the two injected keys, on top of the real ones
    assert count(res, variant) == count(plain, variant) + 1       # the target mod has a variant value


def test_report_script_prints_the_matrix(tmp_path, capsys, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("acceptance_report",
                                                  Path(__file__).parents[1] / "build" / "acceptance_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    monkeypatch.setattr(A, "combos", lambda: [("enhanced", "1.0.1013.20", "core"), ("legacy", "1.0.3411.0", "core")])
    real_run = A.run
    monkeypatch.setattr(A, "run", lambda work, e, b, p, manifest_dir=None: (
        real_run(work, e, b, p) if e == "enhanced" else A.Result(e, b, p, False, "check", "edition-mismatch: x")))
    assert report.main(["--work", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "enhanced 1.0.1013.20" in out and "core" in out and "PASS" in out
    assert "FAIL at check" in out and "edition-mismatch: x" in out and "1 of 2 passed" in out


# ------------------------------------------------------------------------------- bugs the flow found (fixed)
def _mod(mid, order, archive, **extra):
    return {"id": mid, "order": order, "tier": "core", "layer": "t", "name": mid, "version": "1", "source": "direct",
            "page": f"https://{mid}.example/", "archive": archive, "install": {"method": "guided", "steps": ["x"]},
            **extra}


def test_another_mods_file_is_not_the_wrong_edition_of_a_selected_one(tmp_path, game, downloads):
    """A file that belongs to a mod outside the selection (better-fitting name) used to be handed to the closest
    selected mod and reported as its "wrong edition"."""
    d = tmp_path / "m"
    d.mkdir()
    mods = [_mod("drivev", 1, ["*Drive*V*.zip"], rejectMembers=["*onigiri/*"]),
            _mod("drivevnve", 2, ["*Drive*V*NVE*.zip"]),
            _mod("hud-a", 3, ["*HUD*.zip"], slot="hud"), _mod("hud-b", 4, ["*HUD*.zip"], slot="hud", tier="alternative")]
    (d / "mods.json").write_text(json.dumps({"pack": "L", "version": "1", "mods": mods}))
    (d / "profiles.json").write_text(json.dumps({"default": "p", "profiles": [{"id": "p", "name": "P",
                                                                                "include": ["drivev", "hud-a"]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    nve = make_zip(downloads / "DriveV_NVE_2.zip", {"DriveV/onigiri/x.ytd": "n"})
    plain = make_zip(downloads / "DriveV_2.zip", {"DriveV/x.ytd": "p"})
    hud = make_zip(downloads / "GTA6_HUD.zip", {"hud.asi": "h"})
    s = Session(tmp_path / "st", d, download_dir=str(downloads), game_dir=str(game))
    res = s.matches()
    assert res.matched == {"drivev": plain, "hud-a": hud}      # the tie with unselected hud-b goes to hud-a
    assert res.others == {nve: "drivevnve"} and res.wrong == {} and res.unmatched == [] and res.ambiguous == {}
    s.config.assignments["GTA6_HUD.zip"] = "hud-b"             # the user says it's hud-b's file
    res = s.matches()
    assert "hud-a" not in res.matched and res.others[hud] == "hud-b"


def _installer(game, state, ui=None):
    return Installer(load_manifest(), game, state, InstallLog(state / "log.json"), ui or AutoUI())


def _mod_obj(**kw):
    base = dict(id="m", order=1, tier="core", layer="x", name="M", author="a", version="1", source="direct",
                page="https://x", archive=("m*.zip",), method="copy")
    base.update(kw)
    return Mod(**base)


def test_guided_step_filling_an_empty_folder_logs_no_removal(tmp_path, game, state, downloads):
    """A guided step that puts files into a folder that was empty used to log the folder as removed, and rollback
    then warned 'scripts/: no backup (file was too big)'."""
    before = take_snapshot(game)
    inst = _installer(game, state, AutoUI(on_wait=lambda f: (game / "scripts" / "hud.dll").write_text("x")))
    inst.install(_mod_obj(id="a", create_dirs=("scripts",), files=(FileSpec("a.asi"),)),
                 make_zip(downloads / "a-1.zip", {"a.asi": "a"}))
    step = inst.install(_mod_obj(id="b", method="guided"), make_zip(downloads / "b-1.zip", {"r.txt": "r"}))
    assert [(a.op, a.path) for a in step.actions] == [(L.EXT_ADD, "scripts/hud.dll")]
    warnings, residual = inst.uninstall()
    assert warnings == [] and residual.empty and diff(before, take_snapshot(game)).empty


def test_guided_step_removing_an_empty_folder_is_undone(tmp_path, game, state, downloads):
    (game / "mods" / "empty").mkdir(parents=True)
    before = take_snapshot(game)
    inst = _installer(game, state, AutoUI(on_wait=lambda f: (game / "mods" / "empty").rmdir()))
    step = inst.install(_mod_obj(id="b", method="guided"), make_zip(downloads / "b-1.zip", {"r.txt": "r"}))
    assert (L.EXT_REMOVE, "mods/empty/") in [(a.op, a.path) for a in step.actions]
    assert inst.rollback(step.id) == [] and (game / "mods" / "empty").is_dir()
    assert diff(before, take_snapshot(game)).empty


def test_a_created_folder_is_not_a_dependency(tmp_path, game, state, downloads):
    """Pack switching kept a mod installed only because it had created a shared folder (scripts) that later mods
    write into; rolling a created folder back only removes it when empty, so that's no dependency."""
    inst = _installer(game, state)
    a = inst.install(_mod_obj(id="a", create_dirs=("scripts",), files=(FileSpec("a.dll", to="scripts"),)),
                     make_zip(downloads / "a-1.zip", {"a.dll": "a"}))
    inst.install(_mod_obj(id="b", files=(FileSpec("b.dll", to="scripts"),)), make_zip(downloads / "b-1.zip", {"b.dll": "b"}))
    assert dependents(inst.log, a) == []
    c = inst.install(_mod_obj(id="c", files=(FileSpec("a.dll", to="scripts"),)), make_zip(downloads / "c-1.zip",
                                                                                          {"a.dll": "c"}))
    assert [d.id for d in dependents(inst.log, a)] == [c.id]    # a real shared file still counts


def test_an_added_top_folder_still_is_a_dependency(tmp_path, game, state, downloads):
    ui = AutoUI(on_wait=lambda f: ((game / "NewTop").mkdir(), (game / "NewTop" / "x.txt").write_text("x")))
    inst = _installer(game, state, ui)
    a = inst.install(_mod_obj(id="a", method="guided"), make_zip(downloads / "a-1.zip", {"r": "r"}))
    b = inst.install(_mod_obj(id="b", files=(FileSpec("b.dll", to="NewTop"),)), make_zip(downloads / "b-1.zip",
                                                                                         {"b.dll": "b"}))
    assert [d.id for d in dependents(inst.log, a)] == [b.id]    # rolling a back would rmtree NewTop


def test_fixture_names_match_their_mods():
    for edition in A.EDITION_BUILDS:
        for m in load_manifest(edition=edition).mods.values():
            name = A.fixture_name(m)
            assert name, m.id
            if m.method in ("copy", "generic", "run") or m.require_members:
                assert name.lower().endswith(".zip"), (m.id, name)


def test_harness_cleans_up(tmp_path):
    res = A.run(tmp_path, "legacy", "1.0.3411.0", "core")
    assert res.ok and not (tmp_path / "Grand Theft Auto V" / "ScriptHookV.log").exists()
    shutil.rmtree(tmp_path / "Grand Theft Auto V")


def test_cli_install_only_on_the_real_data_leaves_no_drift(tmp_path, capsys):
    """The owner's real-PC run: `pack choose video-setup --variant balanced`, then `install --only <8 mods> --yes
    --no-pause` left EnableAllInteriors.ini / ActionsV.ini with the archive's values (drift) until `settings apply`."""
    from leonida.cli import main

    only = ["lemonui", "enableallinteriors", "jasonhouse", "streetfood", "cameraflinch", "actionsv",
            "dynamicfirstperson", "rideshare"]
    game, state, downloads = A.make_game(tmp_path, "enhanced"), tmp_path / "state", tmp_path / "downloads"
    before = A.fingerprint(game)
    m = load_manifest()
    for mid in only:
        A.write_fixture(downloads, m.mods[mid])
    base = ["--state-dir", str(state), "--game-dir", str(game), "--download-dir", str(downloads),
            "--game-build", "1.0.1013.20"]
    with A.fake_pc(rtx50=False):
        assert main(base + ["pack", "choose", "video-setup", "--variant", "balanced"]) == 0
        assert main(base + ["install", "--only", *only, "--yes", "--no-pause"]) == 0, capsys.readouterr().out
        s = Session(state, download_dir=str(downloads), game_dir=str(game), game_build="1.0.1013.20")
        assert s.log.installed_mods() == set(only)
        locked = {w.file for w in s.installed_settings()}
        assert {"scripts/EnableAllInteriors.ini", "ActionsV.ini"} <= locked
        assert s.settings_drift() == []
        capsys.readouterr()
        assert main(base + ["settings", "show"]) == 0 and "DRIFT" not in capsys.readouterr().out
        warnings, residual = s.installer(AutoUI()).uninstall()
    assert warnings == [] and residual.empty and A.fingerprint(game) == before


def test_an_old_logs_backslash_created_folder_rolls_back_whole(tmp_path, game, state, downloads):
    """Logs written before the fix hold createDirs as "mods<bs>update<bs>x64<bs>dlcpacks" (the owner's real log
    does): rolling back must still remove every folder of it that the step created, not only the last one."""
    bs = chr(92)
    before = take_snapshot(game)
    inst = _installer(game, state)
    step = inst.install(_mod_obj(id="a", files=(FileSpec("a.asi"),)), make_zip(downloads / "a-1.zip", {"a.asi": "a"}))
    (game / "mods" / "update" / "x64" / "dlcpacks").mkdir(parents=True)
    step.actions.insert(0, L.Action(L.MKDIR, bs.join(["mods", "update", "x64", "dlcpacks"])))
    inst.log.save()
    warnings, residual = inst.uninstall()
    assert warnings == [] and residual.empty and not (game / "mods").exists()
    assert diff(before, take_snapshot(game)).empty
