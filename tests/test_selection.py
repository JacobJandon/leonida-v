"""whenSelected / whenMissing, the selection-aware gameconfig check and the loader-DLL check."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from conftest import AutoUI, make_zip

from leonida import modpack as mp
from leonida.checks import ERROR, INFO, WARNING, run_checks
from leonida.manifest import ManifestError, load_manifest
from leonida.session import Session
from leonida.snapshot import diff as snap_diff
from leonida.snapshot import load_snapshot, take_snapshot


def _mod(mid, order, method="guided", files=(), **extra):
    inst = {"method": method, "steps": [f"install {mid}"]}
    if files:
        inst["files"] = [dict(f) for f in files]
    return {"id": mid, "order": order, "tier": "core", "layer": "t", "name": mid.upper(), "version": "1",
            "source": "direct", "page": f"https://{mid}.example/", "archive": [f"{mid}*.zip"], "install": inst, **extra}


ONIGIRI_CAM = {"files": [{"match": "cameras.ymt", "to": "onigiri/common"}],
               "steps": ["cameras.ymt goes into NVE's onigiri folder"], "notes": "NVE layout"}
MODS = [
    _mod("shv", 1, "copy", [{"match": "dinput8.dll"}, {"match": "ScriptHookV.dll"}]),
    _mod("nve", 2),
    _mod("openrpf", 3, whenSelected={"nve": {"skip": "Not needed: NVE's onigiri folder does this job."}}),
    _mod("resourceextensions", 4, "copy", [{"match": "ResourceExtensions.asi"}]),
    _mod("combatcam", 5, "copy", [{"match": "cameras.ymt", "to": "mods/update"}],
         whenSelected={"nve": ONIGIRI_CAM},
         minGameBuild="1.0.1013.17",
         gameBuilds=[{"max": "1.0.1013.16", "version": "0.9", "files": [{"match": "cameras.ymt", "to": "old"}]}]),
    _mod("oivmod", 6, whenSelected={"nve": {"steps": ["Install the .oiv into onigiri with OpenIV's onigiri mode"]}},
         whenMissing={"nve": {"steps": ["Install the .oiv into mods with OpenIV"],
                              "warnings": [{"with": "openrpf", "message": "needs OpenRPF"}]}}),
]


def write_manifest(root: Path, mods=None) -> Path:
    mods = mods if mods is not None else MODS
    d = root / "manifest"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "1", "testedGameBuilds": ["1.0.1013.20"],
                                             "mods": mods}))
    ids = [m["id"] for m in mods]
    (d / "profiles.json").write_text(json.dumps({"default": "all", "profiles": [
        {"id": "all", "name": "All", "include": ids},
        {"id": "plain", "name": "No NVE", "include": [i for i in ids if i != "nve"]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    return d


@pytest.fixture
def mdir(tmp_path):
    return write_manifest(tmp_path)


def session(tmp_path, mdir, game=None, downloads=None, build="1.0.1013.20", profile=None) -> Session:
    s = Session(tmp_path / "st", mdir, download_dir=str(downloads) if downloads else None,
                game_dir=str(game) if game else None, game_build=build)
    if profile:
        s.config.profile = profile
    return s


def by_id(mods):
    return {m.id: m for m in mods}


# ---------------------------------------------------------------------------------------------- selection
def test_selected_on(tmp_path, mdir):
    s = session(tmp_path, mdir)
    mods = by_id(s.mods())
    assert "openrpf" not in mods  # skipped because NVE is selected
    cam = mods["combatcam"]
    assert cam.files[0].to == "onigiri/common" and cam.notes == "NVE layout" and cam.conditions == ("+nve",)
    assert mods["oivmod"].steps == ("Install the .oiv into onigiri with OpenIV's onigiri mode",)
    nn = s.not_needed()
    assert [m.id for m in nn] == ["openrpf"] and "onigiri" in nn[0].not_needed
    assert s.manifest.mod("openrpf").not_needed  # the GUI sees the reason too


def test_selected_off(tmp_path, mdir):
    s = session(tmp_path, mdir, profile="plain")
    mods = by_id(s.mods())
    assert "openrpf" in mods and mods["openrpf"].not_needed is None
    assert mods["combatcam"].files[0].to == "mods/update" and mods["combatcam"].conditions == ()
    oiv = mods["oivmod"]
    assert oiv.steps == ("Install the .oiv into mods with OpenIV",) and oiv.conditions == ("-nve",)
    assert oiv.warnings == ({"with": "openrpf", "message": "needs OpenRPF"},)


def test_selection_follows_config_changes(tmp_path, mdir):
    s = session(tmp_path, mdir)
    assert s.manifest.mod("combatcam").files[0].to == "onigiri/common"
    s.config.remove.append("nve")
    assert s.manifest.mod("combatcam").files[0].to == "mods/update"
    assert "openrpf" in by_id(s.mods())
    assert by_id(s.mods("all"))["combatcam"].files[0].to == "mods/update"  # 'all' minus the user's removal
    s.config.remove.clear()
    assert "openrpf" not in by_id(s.mods())


def test_mod_level_api(mdir):
    base = load_manifest(mdir).mod("combatcam")
    on, off = base.for_selection({"nve", "combatcam"}), base.for_selection({"combatcam"})
    assert on.files[0].to == "onigiri/common" and off.files[0].to == "mods/update"
    assert on.for_selection({"combatcam"}).files == off.files  # re-resolving starts from the pre-selection mod
    assert off.for_selection({"nve"}) == on.for_selection({"nve"})
    plain = load_manifest(mdir).mod("shv")
    assert plain.for_selection({"nve"}) is plain  # no conditions: unchanged


def test_interaction_with_game_builds(tmp_path, mdir):
    base = load_manifest(mdir).mod("combatcam")
    old = base.for_build("1.0.1013.10")
    assert old.version == "0.9" and old.files[0].to == "old"
    old_nve = old.for_selection({"nve"})
    assert old_nve.version == "0.9" and old_nve.files[0].to == "onigiri/common"  # selection wins over the variant
    assert old_nve.variant == 0
    assert old_nve.for_build("1.0.1013.20").files[0].to == "onigiri/common"      # keeps the selection
    assert old_nve.for_build("1.0.1013.20").version == "1"
    assert old_nve.for_build("1.0.1013.20").for_selection(set()).files[0].to == "mods/update"
    s = session(tmp_path, mdir, build="1.0.1013.10", profile="plain")
    cam = by_id(s.mods())["combatcam"]
    assert (cam.version, cam.files[0].to) == ("0.9", "old")


def test_install_uses_overridden_files(tmp_path, mdir, game, downloads):
    s = session(tmp_path, mdir, game, downloads)
    z = make_zip(downloads / "combatcam-1.zip", {"Combat Camera/cameras.ymt": "cam"})
    baseline = take_snapshot(game)
    s.installer(AutoUI()).install(by_id(s.mods())["combatcam"], z)
    assert (game / "onigiri" / "common" / "cameras.ymt").read_text() == "cam"
    assert not (game / "mods").exists()
    _, residual = s.installer(AutoUI()).uninstall()
    assert residual.empty and snap_diff(baseline, take_snapshot(game)).empty


def test_modpack_and_matching_skip_not_needed(tmp_path, mdir, game, downloads):
    for mid in ("shv", "nve", "openrpf", "resourceextensions", "combatcam", "oivmod"):
        make_zip(downloads / f"{mid}-1.zip", {"x.txt": mid})
    s = session(tmp_path, mdir, game, downloads)
    assert "openrpf" not in s.matches().matched
    pack = mp.build_modpack(s)
    assert "openrpf" not in pack["builds"]["1.0.1013.20"]["mods"] and "nve" in pack["builds"]["1.0.1013.20"]["mods"]


# ---------------------------------------------------------------------------------------------- validation
@pytest.mark.parametrize("field, value, message", [
    ("whenSelected", ["nve"], "must be an object"),
    ("whenSelected", {"nope": {"notes": "x"}}, "unknown mod 'nope'"),
    ("whenSelected", {"combatcam": {"notes": "x"}}, "can't depend on itself"),
    ("whenMissing", {"nve": {}}, "give the values"),
    ("whenMissing", {"nve": {"page": "https://x"}}, "unknown key"),
    ("whenSelected", {"nve": {"skip": "x", "files": []}}, "can't also override"),
    ("whenSelected", {"nve": {"skip": " "}}, "non-empty reason"),
    ("whenSelected", {"nve": {"files": [{"to": "x"}]}}, "needs a 'match'"),
    ("whenSelected", {"nve": {"files": [{"match": "a", "to": "../x"}]}}, "inside the game folder"),
    ("whenSelected", {"nve": {"files": []}}, "needs a 'files' list"),
    ("whenSelected", {"nve": {"method": "magic"}}, "unknown install method"),
    ("whenSelected", {"nve": {"steps": "one"}}, "list of strings"),
    ("whenSelected", {"nve": {"warnings": [{"with": "ghost", "message": "m"}]}}, "unknown mod 'ghost'"),
    ("whenSelected", {"nve": {"warnings": ["m"]}}, "'warnings' must be"),
])
def test_validation(tmp_path, field, value, message):
    mods = copy.deepcopy(MODS)
    mods[4][field] = value
    with pytest.raises(ManifestError, match=message):
        load_manifest(write_manifest(tmp_path, mods))


def test_bundled_manifest_conditions_resolve(manifest):
    ids = {m.id for m in manifest.resolve(manifest.default_profile)}
    for m in manifest.mods.values():
        assert m.for_build("1.0.1013.20").for_selection(ids).id == m.id
        assert m.for_selection(ids - {"nve"}).id == m.id


# ------------------------------------------------------------------------------------------------ gameconfig
def codes(findings, level=None):
    return [f.code for f in findings if level is None or f.level == level]


def test_gameconfig_depends_on_selection(tmp_path, mdir, game):
    m = load_manifest(mdir)
    with_nve = run_checks(m, m.resolve("all"), game, game_version="1.0.1013.20")  # raw mods: checks resolve them
    assert "gameconfig-nve" in codes(with_nve, INFO) and "gameconfig-rpf" not in codes(with_nve)
    plain = run_checks(m, m.resolve("plain"), game, game_version="1.0.1013.20")
    assert "gameconfig-rpf" in codes(plain, INFO) and "gameconfig-nve" not in codes(plain)
    (game / "gameconfig.xml").write_text("<x/>")
    assert "gameconfig" in codes(run_checks(m, m.resolve("all"), game), ERROR)


def test_loose_gameconfig_in_onigiri(tmp_path, mdir, game):
    m = load_manifest(mdir)
    nve_own = game / "onigiri" / "common" / "data" / "gameconfig.xml"
    nve_own.parent.mkdir(parents=True)
    nve_own.write_text("<nve/>")
    assert "gameconfig-onigiri" not in codes(run_checks(m, m.resolve("all"), game))
    stray = game / "onigiri" / "somemod" / "GameConfig.xml"
    stray.parent.mkdir(parents=True)
    stray.write_text("<other/>")
    found = [f for f in run_checks(m, m.resolve("all"), game) if f.code == "gameconfig-onigiri"]
    assert len(found) == 1 and found[0].level == WARNING
    assert "onigiri\\somemod\\GameConfig.xml" in found[0].message and "Resource Extensions" in found[0].message
    assert stray.exists() and nve_own.exists()  # never touched


# ----------------------------------------------------------------------------------------------- loader DLLs
def test_loader_dlls(tmp_path, mdir, game):
    m = load_manifest(mdir)
    (game / "version.dll").write_bytes(b"MZ someone else's")
    (game / "dinput8.dll").write_bytes(b"MZ old loader")
    (game / "d3d12.dll").write_bytes(b"MZ")
    f = run_checks(m, m.resolve("all"), game, game_version="1.0.1013.20")
    info = {x.message.split(" ")[0] for x in f if x.code == "loader-dll"}
    assert info == {"version.dll", "d3d12.dll"} and all(x.level == INFO for x in f if x.code == "loader-dll")
    assert any("load twice" in x.message for x in f if x.code == "loader-dll")
    warn = [x for x in f if x.code == "loader-overwrite"]
    assert len(warn) == 1 and warn[0].level == WARNING and warn[0].message.startswith("dinput8.dll")
    assert "SHV" in warn[0].message and "puts it back" in warn[0].message
    plain = run_checks(m, m.resolve("all"), game, installed_paths={"dinput8.dll"})
    assert "loader-overwrite" not in codes(plain) and "dinput8.dll" not in " ".join(x.message for x in plain)
    assert (game / "version.dll").read_bytes() == b"MZ someone else's"  # never touched


def test_loader_overwrite_is_reversible(tmp_path, mdir, game, downloads):
    (game / "dinput8.dll").write_bytes(b"MZ old loader")
    s = session(tmp_path, mdir, game, downloads)
    assert "loader-overwrite" in codes(s.findings())
    baseline = take_snapshot(game)
    z = make_zip(downloads / "shv-1.zip", {"bin/dinput8.dll": "MZ shv loader", "bin/ScriptHookV.dll": "MZ shv"})
    s.installer(AutoUI()).install(by_id(s.mods())["shv"], z)
    assert (game / "dinput8.dll").read_text() == "MZ shv loader"
    assert not {"loader-overwrite", "loader-dll"} & set(codes(s.findings()))  # now Leonida's own file
    s.installer(AutoUI()).uninstall()
    assert (game / "dinput8.dll").read_bytes() == b"MZ old loader"
    assert snap_diff(load_snapshot(s.state / "baseline-snapshot.json"), take_snapshot(game)).empty
    assert snap_diff(baseline, take_snapshot(game)).empty
