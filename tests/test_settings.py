"""Locked mod settings (F5): file formats, value rules, schema, writing at install (rollback restores the user's file),
variant switching without reinstalling, drift, unlock/lock, and the CLI."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from conftest import AutoUI, make_zip

from leonida import settings as S
from leonida.cli import main
from leonida.manifest import ManifestError, Variant, load_manifest
from leonida.session import Session
from leonida.snapshot import diff, take_snapshot

SHVDN_INI = "[Settings]\r\nReloadKeyBinding = None\r\nConsoleKeyBinding=F4 ; console\r\nScriptsLocation=\"scripts\"\r\n"
MENYOO_INI = "[settings]\nopen_key = 119\nFreeCamButton = 114\n"


def _mod(mid, order, files, **extra):
    return {"id": mid, "order": order, "tier": "core", "layer": "t", "name": mid.upper(), "version": "1",
            "source": "direct", "page": f"https://{mid}.example/", "archive": [f"{mid}*.zip"],
            "install": {"method": "copy", "files": [{"match": f} for f in files]}, **extra}


SHVDN_SETTINGS = [{"file": "ScriptHookVDotNet.ini", "keys": {
    "Settings/ReloadKeyBinding": {"value": "None", "whenSelected": {"eai": "Insert"},
                                  "why": "Enable All Interiors needs a reload key"},
    "Settings/ConsoleKeyBinding": "F4",
    "Settings/PoolDensity": {"value": "1.00", "packs": {"plus": "1.50"}, "variants": {"ultra": "2.00"}}}}]
MENYOO_SETTINGS = [{"file": "menyooStuff/menyooConfig.ini", "keys": {"settings/open_key": {"value": 119,
                                                                                         "why": "F8 is the HUD's"}}}]
MODS = [
    _mod("shvdne", 1, ["ScriptHookVDotNetCore.dll", "ScriptHookVDotNet.ini"], settings=SHVDN_SETTINGS),
    _mod("menyoo", 2, ["Menyoo.asi"], settings=MENYOO_SETTINGS),
    _mod("eai", 3, ["eai.dll"]),
]
MODPACKS = {
    "default": "plus",
    "categories": [{"id": "world", "name": "World"}],
    "addons": [{"id": "interiors", "name": "Interiors", "category": "world", "mods": ["eai"]}],
    "packs": [{"id": "plus", "name": "Plus", "base": ["shvdne", "menyoo"], "categories": ["world"],
               "variants": [{"id": "balanced", "name": "Balanced"},
                            {"id": "ultra", "name": "Ultra", "settings": {
                                "menyoo": {"menyooStuff/menyooConfig.ini": {"settings/open_key": 121}}}}],
               "defaultVariant": "balanced"}]}


def write_manifest(root: Path, mods=MODS, modpacks=MODPACKS) -> Path:
    d = root / "manifest"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "1", "mods": mods}))
    (d / "profiles.json").write_text(json.dumps({"default": "plus", "profiles": [
        {"id": "plus", "name": "Plus", "include": ["shvdne", "menyoo"]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    (d / "modpacks.json").write_text(json.dumps(modpacks))
    return d


@pytest.fixture
def kit(tmp_path, game, downloads):
    s = Session(tmp_path / "st", write_manifest(tmp_path), download_dir=str(downloads), game_dir=str(game))
    make_zip(downloads / "shvdne-1.zip", {"bin/ScriptHookVDotNetCore.dll": "dll",
                                          "bin/ScriptHookVDotNet.ini": SHVDN_INI})
    make_zip(downloads / "menyoo-1.zip", {"Menyoo.asi": "asi"})
    make_zip(downloads / "eai-1.zip", {"eai.dll": "eai"})
    (game / "menyooStuff").mkdir()
    (game / "menyooStuff" / "menyooConfig.ini").write_text(MENYOO_INI.replace("119", "120"))  # the user's own file
    return s


def install_all(s: Session):
    inst = s.installer(AutoUI())
    res = s.matches()
    for m in s.mods():
        inst.install(m, res.matched[m.id])
    return inst


# ------------------------------------------------------------------------------------------------- formats
def test_ini_edit_in_place():
    text = SHVDN_INI.replace("\r\n", "\n")
    assert S.ini_get(text, "Settings/consolekeybinding") == "F4 ; console" and S.ini_get(text, "Nope/X") is None
    t2 = S.ini_set(text, "settings/ReloadKeyBinding", "Insert")
    assert "ReloadKeyBinding = Insert\n" in t2 and t2.count("\n") == text.count("\n")   # spelling/spacing kept
    t3 = S.ini_set(t2, "Settings/NewKey", 5)
    assert t3.split("\n").index("NewKey=5") == 4                                          # at the end of its section
    t4 = S.ini_set(t3, "Other/Key", "x")
    assert t4.endswith("\n[Other]\nKey=x") and S.ini_get(t4, "Other/Key") == "x"
    t5 = S.ini_set(t4, "TopKey", "1")
    assert t5.startswith("TopKey=1\n[Settings]") and S.ini_get(t5, "TopKey") == "1"


def test_xml_and_json():
    xml = '<?xml version="1.0"?>\n<Config><Hud scale="1.0"><Mode>classic</Mode></Hud></Config>\n'
    assert S.xml_get(xml, "Hud/Mode") == "classic" and S.xml_get(xml, "Hud/@scale") == "1.0"
    x2 = S.xml_set(S.xml_set(xml, "Hud/@scale", 0.8), "Radar/Size", "big")
    assert S.xml_get(x2, "Hud/@scale") == "0.8" and S.xml_get(x2, "Radar/Size") == "big" and x2.startswith("<?xml")
    with pytest.raises(S.SettingsError):
        S.xml_get("<broken", "a")
    js = '{"camera": {"fov": 60}}'
    assert S.json_get(js, "camera/fov") == 60 and S.json_get(js, "camera/x") is None
    assert json.loads(S.json_set(js, "camera/shake/on", True)) == {"camera": {"fov": 60, "shake": {"on": True}}}
    with pytest.raises(S.SettingsError):
        S.json_set("{", "a", 1)


def test_render_keeps_encoding_and_line_endings(tmp_path):
    f = tmp_path / "a.ini"
    f.write_bytes(b"\xef\xbb\xbf" + SHVDN_INI.encode())
    w = S.Wanted("m", "a.ini", "ini", "Settings/ReloadKeyBinding", "Insert")
    data = S.render(f, [w])
    assert data.startswith(b"\xef\xbb\xbf") and b"ReloadKeyBinding = Insert\r\n" in data and b"\n[" not in data
    f.write_bytes(data)
    assert S.render(f, [w]) is None                              # already right: nothing to write
    u = tmp_path / "u.ini"
    u.write_bytes("[S]\r\nK=1\r\n".encode("utf-16"))
    assert S.render(u, [S.Wanted("m", "u.ini", "ini", "S/K", 2)]).decode("utf-16") == "[S]\r\nK=2\r\n"
    assert S.render(tmp_path / "missing.ini", [w]) is None       # doesn't exist and may not be created
    created = S.render(tmp_path / "new.ini", [S.Wanted("m", "new.ini", "ini", "S/K", 1, create=True)])
    assert created.decode() == "[S]\r\nK=1"


def test_same():
    assert S.same("1.0", 1) and S.same(" None ", "none") and S.same(True, "true") and not S.same("F8", "F9")
    assert S.same(None, None) and not S.same(None, "x")


# --------------------------------------------------------------------------------------------- values
def test_rule_precedence_and_wanted(tmp_path):
    rule = {"value": "a", "packs": {"plus": "p"}, "whenSelected": {"eai": "w"}, "variants": {"ultra": "v"}}
    assert S.rule_value(rule, None, None, set()) == "a"
    assert S.rule_value(rule, "plus", None, set()) == "p"
    assert S.rule_value(rule, "plus", None, {"eai"}) == "w"
    assert S.rule_value(rule, "plus", "ultra", {"eai"}) == "v"
    assert S.rule_value("F4", "plus", "ultra", {"eai"}) == "F4"
    m = load_manifest(write_manifest(tmp_path))
    ultra = Variant("ultra", "Ultra", settings={"menyoo": {"menyooStuff/menyooConfig.ini": {"settings/open_key": 121}}})
    w = {x.key: x.value for x in S.wanted_for(m.mod("menyoo"), "plus", ultra)}
    assert w == {"settings/open_key": 121}                       # the variant's override wins
    keys = {x.key: x.value for x in S.wanted_for(m.mod("shvdne"), "plus", None, {"eai"},
                                                 {S.unlock_key("shvdne", "ScriptHookVDotNet.ini", "Settings/ConsoleKeyBinding")})}
    assert keys == {"Settings/ReloadKeyBinding": "Insert", "Settings/PoolDensity": "1.50"}  # unlocked key left out


# ---------------------------------------------------------------------------------------------- schema
@pytest.mark.parametrize("settings, message", [
    ({"file": "a.ini"}, "non-empty list"),
    ([], "non-empty list"),
    ([{"keys": {"a": 1}}], "'file' is required"),
    ([{"file": "../a.ini", "keys": {"a": 1}}], "inside the game folder"),
    ([{"file": "a.ini", "format": "yaml", "keys": {"a": 1}}], "ini, xml or json"),
    ([{"file": "a.ini", "keys": {}}], "at least one key"),
    ([{"file": "a.ini", "keys": {"a": 1}, "mode": "x"}], "unknown key"),
    ([{"file": "a.ini", "keys": {"/a": 1}}], "not a valid key path"),
    ([{"file": "a.ini", "keys": {"a": [1]}}], "give a value"),
    ([{"file": "a.ini", "keys": {"a": {"why": "x"}}}], "give a value"),
    ([{"file": "a.ini", "keys": {"a": {"value": 1, "default": 2}}}], "unknown key"),
    ([{"file": "a.ini", "keys": {"a": {"packs": {"x": [1]}}}}], "map ids to values"),
    ([{"file": "a.ini", "keys": {"a": {"whenSelected": {"ghost": 1}}}}], "unknown mod 'ghost'"),
    ([{"file": "a.ini", "create": "yes", "keys": {"a": 1}}], "true or false"),
])
def test_settings_schema(tmp_path, settings, message):
    mods = copy.deepcopy(MODS)
    mods[2]["settings"] = settings
    with pytest.raises(ManifestError, match=message):
        load_manifest(write_manifest(tmp_path, mods=mods))


@pytest.mark.parametrize("vset, message", [
    ({"ghost": {}}, "unknown mod 'ghost'"),
    ({"menyoo": {"f.ini": {"k": [1]}}}, "settings must be"),
    ([], "'settings' must be an object"),
])
def test_variant_settings_schema(tmp_path, vset, message):
    packs = copy.deepcopy(MODPACKS)
    packs["packs"][0]["variants"][1]["settings"] = vset
    with pytest.raises(ManifestError, match=message):
        load_manifest(write_manifest(tmp_path, modpacks=packs))


# ------------------------------------------------------------------------------------- install / rollback
def test_install_writes_locked_values_and_rollback_restores(kit, game):
    before = take_snapshot(game)
    user_menyoo = (game / "menyooStuff" / "menyooConfig.ini").read_bytes()
    inst = install_all(kit)
    ini = (game / "ScriptHookVDotNet.ini").read_text()
    assert "ReloadKeyBinding = None" in ini and "PoolDensity=1.50" in ini              # pack value, appended
    assert S.ini_get((game / "menyooStuff" / "menyooConfig.ini").read_text(), "settings/open_key") == "119"
    shv_step = next(s for s in kit.log.steps if s.mod == "shvdne")
    ini_action = next(a for a in shv_step.actions if a.path == "ScriptHookVDotNet.ini")
    assert ini_action.op == "add"                                                         # still the mod's own file
    assert kit.settings_drift() == [] and kit.log.installed_mods() == {"shvdne", "menyoo"}
    warnings, residual = inst.uninstall()
    assert warnings == [] and residual.empty                                              # no "edited after install"
    assert (game / "menyooStuff" / "menyooConfig.ini").read_bytes() == user_menyoo        # the user's file is back
    assert diff(before, take_snapshot(game)).empty


def test_selection_changes_a_locked_value(kit, game):
    kit.choose_pack("plus", ["interiors"])                     # Enable All Interiors selected: reload key Insert
    install_all(kit)
    assert S.ini_get((game / "ScriptHookVDotNet.ini").read_text(), "Settings/ReloadKeyBinding") == "Insert"


def test_variant_switch_without_reinstalling(kit, game):
    before = take_snapshot(game)
    inst = install_all(kit)
    n_steps = len(kit.log.steps)
    kit.choose_pack("plus", None, "ultra")
    report = kit.apply_settings(AutoUI())
    ini = (game / "ScriptHookVDotNet.ini").read_text()
    assert "PoolDensity=2.00" in ini
    assert S.ini_get((game / "menyooStuff" / "menyooConfig.ini").read_text(), "settings/open_key") == "121"
    assert [s.mod for s in kit.log.steps[n_steps:]] == ["settings:shvdne", "settings:menyoo"] and len(report) == 2
    assert kit.apply_settings(AutoUI()) == []                  # already right: no new step
    assert kit.log.installed_mods() == {"shvdne", "menyoo"}    # settings steps aren't mods
    assert kit.apply_settings(AutoUI(), dry_run=True) == []
    inst.uninstall()
    assert diff(before, take_snapshot(game)).empty


def test_drift_unlock_lock(kit, game):
    install_all(kit)
    cfg = game / "menyooStuff" / "menyooConfig.ini"
    cfg.write_text(cfg.read_text().replace("open_key = 119", "open_key = 118"))
    (d,) = kit.settings_drift()
    assert (d.wanted.mod, d.have) == ("menyoo", "118") and "F8 is the HUD's" in d.message()
    f = [x for x in kit.findings() if x.code == "setting-drift"]
    assert len(f) == 1 and f[0].level == "warning" and f[0].mod == "menyoo"
    S.set_unlocked(kit.state, "menyoo", "menyooStuff/menyooConfig.ini", "settings/open_key", True)
    assert kit.settings_drift() == []                          # the user's value is kept
    assert kit.apply_settings(AutoUI()) == []
    S.set_unlocked(kit.state, "menyoo", "menyooStuff/menyooConfig.ini", "settings/open_key", False)
    assert len(kit.settings_drift()) == 1
    kit.apply_settings(AutoUI())
    assert kit.settings_drift() == [] and "open_key = 119" in cfg.read_text()
    (kit.state / S.UNLOCK_FILE).write_text("{broken")
    assert S.unlocked(kit.state) == set()


def test_installed_mods_without_settings_steps(kit, game):
    install_all(kit)
    kit.choose_pack("plus", None, "ultra")
    kit.apply_settings(AutoUI())
    assert {s.mod for s in kit.log.steps} >= {"settings:shvdne"} and "settings:shvdne" not in kit.log.installed_mods()


# --------------------------------------------------------------------------------------------------- CLI
def test_cli_settings(tmp_path, kit, game, downloads, capsys):
    base = ["--state-dir", str(kit.state), "--manifest-dir", str(tmp_path / "manifest"), "--game-dir", str(game),
            "--download-dir", str(downloads)]
    install_all(kit)
    assert main(base + ["settings", "show"]) == 0
    out = capsys.readouterr().out
    assert "ScriptHookVDotNet.ini: Settings/PoolDensity = 1.50  ok" in out and "F8 is the HUD's" in out
    cfg = game / "menyooStuff" / "menyooConfig.ini"
    cfg.write_text(cfg.read_text().replace("open_key = 119", "open_key = 118"))
    assert main(base + ["settings", "show"]) == 1
    assert "DRIFT (now '118')" in capsys.readouterr().out
    main(base + ["verify"])
    assert "the locked value is '119'" in capsys.readouterr().out
    assert main(base + ["settings", "unlock", "menyoo", "menyooStuff/menyooConfig.ini", "settings/open_key"]) == 0
    assert "unlocked" in capsys.readouterr().out
    assert main(base + ["settings", "show"]) == 0
    assert "(unlocked)" in capsys.readouterr().out
    main(base + ["settings", "lock", "menyoo", "menyooStuff/menyooConfig.ini", "settings/open_key"])
    assert main(base + ["settings", "apply", "--dry-run"]) == 0
    assert "set settings/open_key=119 in menyooStuff/menyooConfig.ini" in capsys.readouterr().out
    assert main(base + ["settings", "apply"]) == 0
    assert "open_key = 119" in cfg.read_text()


def test_cli_install_only_writes_locked_values_in_the_mods_step(tmp_path, kit, game, downloads, capsys):
    """Real-PC bug: `leonida pack choose plus --variant ultra` then `leonida install --only ... --yes --no-pause` left
    the mods' own (archive) ini values in place; the CLI built its Installer without the locked settings."""
    base = ["--state-dir", str(kit.state), "--manifest-dir", str(tmp_path / "manifest"), "--game-dir", str(game),
            "--download-dir", str(downloads)]
    assert main(base + ["pack", "choose", "plus", "--variant", "ultra"]) == 0
    assert main(base + ["install", "--only", "shvdne", "menyoo", "--yes", "--no-pause"]) == 0
    ini = (game / "ScriptHookVDotNet.ini").read_text()
    assert "PoolDensity=2.00" in ini                                     # the variant's value, not the archive's
    assert S.ini_get((game / "menyooStuff" / "menyooConfig.ini").read_text(), "settings/open_key") == "121"
    s = Session(kit.state, tmp_path / "manifest", download_dir=str(downloads), game_dir=str(game))
    assert s.settings_drift() == []
    assert [st.mod for st in s.log.steps] == ["shvdne", "menyoo"]        # inside the mods' own steps, no extra step
    shv = s.log.steps[0]
    assert [a.op for a in shv.actions if a.path == "ScriptHookVDotNet.ini"] == ["add"]
    capsys.readouterr()
    assert main(base + ["settings", "show"]) == 0                        # no drift
    assert "DRIFT" not in capsys.readouterr().out
    warnings, residual = s.installer(AutoUI()).uninstall()
    assert warnings == [] and residual.empty
