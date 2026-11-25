import dataclasses

import pytest
from conftest import AutoUI, make_zip

from leonida import log as L
from leonida.installer import Installer, InstallError
from leonida.snapshot import diff, take_snapshot


def _inst(manifest, game, state, log, ui=None, **kw):
    return Installer(manifest, game, state, log, ui or AutoUI(), **kw)


def shv_zip(d):
    return make_zip(d / "ScriptHookV_1.0.zip", {
        "bin/ScriptHookV.dll": "shv",
        "bin/xinput1_4.dll": "asi loader",
        "bin/dinput8.dll": "legacy loader",
        "bin/NativeTrainer.asi": "trainer",
        "readme.txt": "hi",
    })


def test_copy_places_only_named_files_and_rolls_back(manifest, game, state, log, downloads):
    before = take_snapshot(game)
    inst = _inst(manifest, game, state, log)
    step = inst.install(manifest.mod("scripthookv"), shv_zip(downloads))
    assert (game / "ScriptHookV.dll").read_text() == "shv"
    assert (game / "xinput1_4.dll").read_text() == "asi loader"
    assert not (game / "dinput8.dll").exists()  # Legacy loader stays out of Enhanced
    assert not (game / "NativeTrainer.asi").exists()
    assert {a.op for a in step.actions} == {L.ADD}
    inst.rollback(step.id)
    assert diff(before, take_snapshot(game)).empty


def test_replace_is_backed_up_and_restored(manifest, game, state, log, downloads):
    (game / "xinput1_4.dll").write_text("someone else's loader")
    inst = _inst(manifest, game, state, log)
    step = inst.install(manifest.mod("scripthookv"), shv_zip(downloads))
    assert (game / "xinput1_4.dll").read_text() == "asi loader"
    assert any(a.op == L.REPLACE and a.backup for a in step.actions)
    inst.rollback(step.id)
    assert (game / "xinput1_4.dll").read_text() == "someone else's loader"


def test_prefers_enhanced_variant(manifest, game, state, log, downloads):
    z = make_zip(downloads / "ScriptHookV_both.zip", {
        "Legacy/bin/ScriptHookV.dll": "legacy",
        "Enhanced/bin/ScriptHookV.dll": "enhanced",
        "Enhanced/bin/xinput1_4.dll": "loader",
    })
    _inst(manifest, game, state, log).install(manifest.mod("scripthookv"), z)
    assert (game / "ScriptHookV.dll").read_text() == "enhanced"


def test_missing_required_file_stops(manifest, game, state, log, downloads):
    z = make_zip(downloads / "ScriptHookV_broken.zip", {"bin/ScriptHookV.dll": "x"})
    with pytest.raises(InstallError, match="xinput1_4.dll"):
        _inst(manifest, game, state, log).install(manifest.mod("scripthookv"), z)
    assert not (game / "ScriptHookV.dll").exists()
    assert log.steps == []


def test_create_dirs_and_dir_specs(manifest, game, state, log, downloads):
    inst = _inst(manifest, game, state, log)
    shvdne = make_zip(downloads / "ScriptHookVDotNet-Enhanced.zip", {
        "ScriptHookVDotNet.asi": "a", "ScriptHookVDotNet2.dll": "b", "ScriptHookVDotNet3.dll": "c",
        "ScriptHookVDotNet.ini": "d", "MinHook.x64.dll": "e",
    })
    s1 = inst.install(manifest.mod("shvdne"), shvdne)
    assert (game / "scripts").is_dir()
    assert any(a.op == L.MKDIR for a in s1.actions)
    menyoo = make_zip(downloads / "Menyoo.zip", {
        "Menyoo 2.4.4/Menyoo.asi": "m",
        "Menyoo 2.4.4/menyooStuff/Spooner/a.xml": "1",
        "Menyoo 2.4.4/menyooStuff/settings.xml": "2",
    })
    s2 = inst.install(manifest.mod("menyoo"), menyoo)
    assert (game / "Menyoo.asi").exists()
    assert (game / "menyooStuff" / "Spooner" / "a.xml").exists()
    inst.rollback(s2.id)
    inst.rollback(s1.id)
    assert not (game / "menyooStuff").exists()
    assert not (game / "scripts").exists()


def test_rollback_order_enforced(manifest, game, state, log, downloads):
    inst = _inst(manifest, game, state, log)
    s1 = inst.install(manifest.mod("scripthookv"), shv_zip(downloads))
    z = make_zip(downloads / "ResourceExtensions.zip", {"ResourceExtensions.asi": "re"})
    inst.install(manifest.mod("resourceextensions"), z)
    with pytest.raises(InstallError):
        inst.rollback(s1.id)


def test_generic_prefers_enhanced_and_maps_scripts(manifest, game, state, log, downloads):
    z = make_zip(downloads / "All MP Vehicles in SP.zip", {
        "Legacy/AllMP.asi": "legacy",
        "Enhanced/AllMP.asi": "enh",
        "Enhanced/AllMP.ini": "cfg",
        "Enhanced/scripts/AllMPHelper.dll": "helper",
        "readme.txt": "r",
    })
    inst = _inst(manifest, game, state, log)
    plan = inst.plan(manifest.mod("allmpvehicles"), z)
    assert sorted(c.dest for c in plan.copies) == ["AllMP.asi", "AllMP.ini", "scripts/AllMPHelper.dll"]
    inst.install(manifest.mod("allmpvehicles"), z)
    assert (game / "AllMP.asi").read_text() == "enh"


def test_generic_needs_confirmation(manifest, game, state, log, downloads):
    z = make_zip(downloads / "Straight To Story Mode.zip", {"StraightToStory.asi": "x"})
    with pytest.raises(InstallError, match="cancelled"):
        _inst(manifest, game, state, log, AutoUI(confirm=False)).install(manifest.mod("straighttostory"), z)
    assert not (game / "StraightToStory.asi").exists()


def test_guided_step_records_external_changes_and_undoes_them(manifest, game, state, log, downloads):
    # the author's layout: a 'Main Package' folder (Leonida refuses a package without one)
    z = make_zip(downloads / "NaturalVision Enhanced.zip", {"Main Package/readme.txt": "follow me"})

    def user_installs_nve(folder):
        assert (folder / "Main Package" / "readme.txt").exists()
        (game / "onigiri" / "common" / "data").mkdir(parents=True)
        (game / "onigiri" / "common" / "data" / "handling.meta").write_text("nve")
        (game / "bink2w64.dll").write_text("patched by installer")

    before = take_snapshot(game)
    inst = _inst(manifest, game, state, log, AutoUI(on_wait=user_installs_nve))
    step = inst.install(manifest.mod("nve"), z)
    ops = {(a.op, a.path) for a in step.actions}
    assert (L.EXT_ADD, "onigiri/common/data/handling.meta") in ops
    assert (L.EXT_CHANGE, "bink2w64.dll") in ops
    inst.rollback(step.id)
    assert diff(before, take_snapshot(game)).empty
    assert (game / "bink2w64.dll").read_text() == "original bink"


def test_run_method_launches_installer(manifest, game, state, log, downloads):
    z = make_zip(downloads / "GTA VI Inspired HUD Enhanced.zip", {
        "Legacy/GMP Installation/Install_GTA6Hud.bat": "@echo legacy",
        "Enhanced/GMP Installation/Install_GTA6Hud.bat": "@echo enhanced",
    })
    launched = []

    def run(path):
        launched.append(path)
        (game / "scripts").mkdir(exist_ok=True)
        (game / "scripts" / "GTA6Hud.dll").write_text("hud")

    inst = _inst(manifest, game, state, log, AutoUI(on_launch=run))
    step = inst.install(manifest.mod("hud"), z)
    assert launched and "Enhanced" in str(launched[0])
    assert any(a.path == "scripts/GTA6Hud.dll" for a in step.actions)


def test_unconfirmed_guided_step_is_logged_as_failed(manifest, game, state, log, downloads):
    guided = dataclasses.replace(manifest.mod("bugstarfixes"), method="guided", steps=("Do it by hand.",))
    z = make_zip(downloads / "Bugstar Fixes.zip", {"Enhanced/spfixes_gen9/readme.txt": "x"})  # real Enhanced layout

    def partial(folder):
        (game / "half.txt").write_text("half done")

    with pytest.raises(InstallError):
        _inst(manifest, game, state, log, AutoUI(on_wait=partial, done=False)).install(guided, z)
    assert log.steps[-1].status == "failed"
    inst = _inst(manifest, game, state, log)
    inst.rollback(log.steps[-1].id)
    assert not (game / "half.txt").exists()


def test_edited_file_goes_to_orphans(manifest, game, state, log, downloads):
    inst = _inst(manifest, game, state, log)
    step = inst.install(manifest.mod("scripthookv"), shv_zip(downloads))
    (game / "ScriptHookV.dll").write_text("user edited")
    warnings = inst.rollback(step.id)
    assert any("edited" in w for w in warnings)
    assert not (game / "ScriptHookV.dll").exists()
    assert (state / "orphans" / f"step-{step.id}" / "ScriptHookV.dll").exists()


def test_dry_run_writes_nothing(manifest, game, state, log, downloads):
    before = take_snapshot(game)
    ui = AutoUI()
    assert _inst(manifest, game, state, log, ui, dry_run=True).install(manifest.mod("scripthookv"), shv_zip(downloads)) is None
    assert any("copy bin/ScriptHookV.dll -> ScriptHookV.dll" in line for line in ui.lines)
    assert diff(before, take_snapshot(game)).empty
    assert log.steps == []
    assert not (state / "baseline-snapshot.json").exists()


def test_full_uninstall_matches_baseline(manifest, game, state, log, downloads):
    """The core invariant: install several steps, uninstall, game folder == snapshot."""
    before = take_snapshot(game)
    inst = _inst(manifest, game, state, log, AutoUI(on_wait=lambda f: (game / "onigiri").mkdir(exist_ok=True)
                                                     or (game / "onigiri" / "x.rpf").write_text("x")))
    inst.install(manifest.mod("scripthookv"), shv_zip(downloads))
    inst.install(manifest.mod("resourceextensions"),
                 make_zip(downloads / "ResourceExtensions.zip", {"ResourceExtensions.asi": "re", "ResourceExtensions.ini": "i"}))
    inst.install(manifest.mod("nve"), make_zip(downloads / "NaturalVision.zip", {"Main Package/a.txt": "a"}))
    warnings, residual = inst.uninstall()
    assert warnings == []
    assert residual.empty
    assert diff(before, take_snapshot(game)).empty
    assert all(s.status == "rolled-back" for s in log.steps)
