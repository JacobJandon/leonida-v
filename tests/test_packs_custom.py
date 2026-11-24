"""Modpacks (packs, add-on categories, variants, migration from profiles), switching packs, and the user's own mods
going through the same matching / Installer / rollback / checks as curated mods."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from conftest import AutoUI, make_zip

from leonida import custommods, packs
from leonida.cli import main
from leonida.manifest import ManifestError, load_manifest
from leonida.session import Session
from leonida.snapshot import diff, take_snapshot


def _mod(mid, order, method="copy", files=None, **extra):
    inst = {"method": method}
    if method == "copy":
        inst["files"] = files or [{"match": f"{mid}.asi"}]
    else:
        inst["steps"] = ["x"]
    return {"id": mid, "order": order, "tier": extra.pop("tier", "core"), "layer": "t", "name": mid.title(),
            "version": "1", "source": "direct", "page": f"https://{mid}.example/", "archive": [f"{mid}*.zip"],
            "install": inst, **extra}


MODS = [_mod("shv", 1), _mod("nve", 2), _mod("interiors", 3), _mod("food", 4), _mod("bennys", 5),
        _mod("trainer", 6), _mod("ultra", 7, tier="optional")]
PROFILES = {"default": "core", "profiles": [
    {"id": "core", "name": "Core", "description": "The basics", "include": ["shv", "nve"]},
    {"id": "showcase", "name": "Showcase", "include": ["@profile:core", "interiors", "food", "bennys"]}]}
MODPACKS = {
    "default": "core",
    "categories": [{"id": "world", "name": "World & interiors"}, {"id": "tools", "name": "Tools & trainers"},
                   {"id": "graphics", "name": "Graphics"}],
    "addons": [
        {"id": "interiors", "name": "Open interiors", "category": "world", "mods": ["interiors"]},
        {"id": "food", "name": "Street food", "category": "world", "mods": ["food"]},
        {"id": "trainer", "name": "Trainer", "category": "tools", "mods": ["trainer"]},
        {"id": "ultra-gfx", "name": "Ultra graphics", "category": "graphics", "mods": ["ultra"]}],
    "packs": [
        {"id": "core", "name": "Leonida Core", "description": "Stable and minimal", "base": ["@profile:core"],
         "categories": ["tools"]},
        {"id": "plus", "name": "Leonida Plus", "base": ["@profile:core", "bennys"], "defaultAddons": ["interiors"],
         "categories": ["world", "tools", "graphics"],
         "variants": [{"id": "balanced", "name": "Balanced"},
                      {"id": "ultra", "name": "Ultra", "addons": ["ultra-gfx"], "settings": {}}],
         "defaultVariant": "balanced"}]}


def write_manifest(root: Path, modpacks=MODPACKS, mods=MODS) -> Path:
    d = root / "manifest"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "1", "mods": mods}))
    (d / "profiles.json").write_text(json.dumps(PROFILES))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    if modpacks is not None:
        (d / "modpacks.json").write_text(json.dumps(modpacks))
    return d


@pytest.fixture
def mdir(tmp_path):
    return write_manifest(tmp_path)


def ids(mods):
    return [m.id for m in mods]


# ------------------------------------------------------------------------------------------------- packs
def test_packs_load_and_resolve(mdir):
    m = load_manifest(mdir)
    assert list(m.packs) == ["core", "plus"] and m.default_pack == "core" and m.default_profile == "core"
    assert ids(m.resolve_pack("plus")) == ["shv", "nve", "interiors", "bennys"]          # base + default add-ons
    assert ids(m.resolve_pack("plus", addons=[])) == ["shv", "nve", "bennys"]
    assert ids(m.resolve_pack("plus", addons=["food", "trainer"])) == ["shv", "nve", "food", "bennys", "trainer"]
    assert ids(m.resolve_pack("plus", addons=[], variant="ultra")) == ["shv", "nve", "bennys", "ultra"]
    assert ids(m.resolve_pack("plus", addons=["ghost"])) == ["shv", "nve", "bennys"]      # vanished add-on: skipped
    assert {c: [a.id for a in lst] for c, lst in m.addons_for("plus").items()} == {
        "world": ["interiors", "food"], "tools": ["trainer"], "graphics": ["ultra-gfx"]}
    assert list(m.addons_for("core")) == ["tools"]
    assert ids(m.resolve("plus")) == ["shv", "nve", "interiors", "bennys"]               # a pack is a profile too
    assert ids(m.resolve("showcase")) == ["shv", "nve", "interiors", "food", "bennys"]   # plain profile still there
    assert ids(m.resolve_pack("showcase")) == ids(m.resolve("showcase"))
    assert m.get_pack("plus").variant(None).id == "balanced" and m.get_pack("plus").variant("nope") is None


def test_without_modpacks_every_profile_is_a_pack(tmp_path):
    m = load_manifest(write_manifest(tmp_path, modpacks=None))
    assert list(m.packs) == ["core", "showcase"] and m.default_pack == "core" and m.addons == {}
    assert ids(m.resolve_pack("showcase")) == ids(m.resolve("showcase"))


def test_bundled_manifest_has_packs(manifest):
    assert manifest.default_pack in manifest.packs and set(manifest.profiles) <= set(manifest.profiles)
    for pid in manifest.packs:
        assert manifest.resolve_pack(pid)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(packs=[]), "no packs"),
    (lambda d: d.update(default="nope"), "default pack 'nope'"),
    (lambda d: d.update(extra=1), "unknown key"),
    (lambda d: d["packs"][0].update(colour="red"), "unknown key"),
    (lambda d: d["packs"][0].pop("base"), "missing base"),
    (lambda d: d["packs"][0].update(base=["ghost"]), "unknown mod 'ghost'"),
    (lambda d: d["packs"][0].update(base=["@profile:ghost"]), "unknown profile 'ghost'"),
    (lambda d: d["packs"][0].update(defaultAddons=["food"]), "doesn't offer"),
    (lambda d: d["packs"][0].update(defaultAddons=["ghost"]), "unknown add-on"),
    (lambda d: d["packs"][0].update(categories=["sound"]), "unknown category"),
    (lambda d: d["addons"][0].update(category="sound"), "unknown category"),
    (lambda d: d["addons"][0].update(mods=["ghost"]), "unknown mod"),
    (lambda d: d["addons"][0].update(mods=[]), "can't be empty"),
    (lambda d: d["addons"].append(dict(d["addons"][0])), "duplicate add-on"),
    (lambda d: d["packs"][1].update(defaultVariant="fast"), "defaultVariant"),
    (lambda d: d["packs"][1]["variants"][0].update(settings=[]), "settings"),
    (lambda d: d["packs"][1]["variants"][1].update(addons=["ghost"]), "unknown add-on"),
    (lambda d: d["packs"][0].update(picture="http://x"), "https"),
])
def test_modpacks_validation(tmp_path, mutate, message):
    data = copy.deepcopy(MODPACKS)
    mutate(data)
    with pytest.raises(ManifestError, match=message):
        load_manifest(write_manifest(tmp_path, modpacks=data))


# --------------------------------------------------------------------------------------- choice and session
def test_choice_and_migration(tmp_path, mdir, game):
    s = Session(tmp_path / "st", mdir, game_dir=str(game))
    assert s.pack_choice().pack == "core" and s.profile_id == "core" and ids(s.mods()) == ["shv", "nve"]
    s.config.profile = "plus"                                  # an old config: the profile carries over
    assert s.pack_choice().pack == "plus" and ids(s.mods()) == ["shv", "nve", "interiors", "bennys"]
    s.choose_pack("plus", ["food"], "ultra")
    assert json.loads((tmp_path / "st" / "pack.json").read_text())["enhanced"] == {
        "pack": "plus", "addons": ["food"], "variant": "ultra"}
    assert ids(s.mods()) == ["shv", "nve", "food", "bennys", "ultra"]
    assert ids(s.mods("core")) == ["shv", "nve"]               # another pack: its defaults
    s2 = Session(tmp_path / "st", mdir, game_dir=str(game))    # remembered
    assert s2.pack_choice() == packs.PackChoice("plus", ("food",), "ultra") and s2.config.profile == "plus"
    with pytest.raises(ManifestError, match="Not an add-on of Leonida Core"):
        s.choose_pack("core", ["food"])
    with pytest.raises(ManifestError, match="no variant"):
        s.choose_pack("plus", None, "fast")
    with pytest.raises(ManifestError, match="Unknown modpack"):
        s.choose_pack("ghost")
    s.config.add = ["trainer"]                                 # extras still apply on top
    assert "trainer" in ids(s.mods())


def test_pack_json_per_edition_and_broken_file(tmp_path, mdir, game):
    st = tmp_path / "st"
    packs.save_choice(st, "legacy", packs.PackChoice("x"))
    s = Session(st, mdir, game_dir=str(game))
    assert s.pack_choice().pack == "core"                      # the legacy entry doesn't apply to Enhanced
    (st / "pack.json").write_text("{broken")
    assert s.pack_choice().pack == "core" and packs.load_choice(st, "enhanced") is None


def write_zips(downloads: Path, names) -> None:
    for n in names:
        make_zip(downloads / f"{n}-1.zip", {f"{n}.asi": n})


def test_switch_pack_rolls_back_what_left(tmp_path, mdir, game, downloads):
    write_zips(downloads, ["shv", "nve", "interiors", "bennys"])
    s = Session(tmp_path / "st", mdir, download_dir=str(downloads), game_dir=str(game))
    s.choose_pack("plus")
    before = take_snapshot(game)
    inst = s.installer(AutoUI())
    res = s.matches()
    for m in s.mods():
        inst.install(m, res.matched[m.id])
    assert (game / "bennys.asi").exists() and (game / "interiors.asi").exists()
    report = packs.rollback_mods(s, AutoUI(), {"interiors", "bennys"})
    assert report == ["bennys: rolled back", "interiors: rolled back"]
    assert not (game / "bennys.asi").exists() and (game / "shv.asi").exists()
    inst.uninstall()
    assert diff(before, take_snapshot(game)).empty


def test_switch_keeps_a_mod_a_kept_mod_depends_on(tmp_path, mdir, game, downloads):
    mods = copy.deepcopy(MODS)
    mods[5]["install"]["files"] = [{"match": "trainer.asi"}, {"match": "interiors.asi"}]  # trainer overwrites it
    d = write_manifest(tmp_path / "m2", mods=mods)
    write_zips(downloads, ["shv", "nve", "interiors"])
    make_zip(downloads / "trainer-1.zip", {"trainer.asi": "t", "interiors.asi": "trainer's copy"})
    s = Session(tmp_path / "st", d, download_dir=str(downloads), game_dir=str(game))
    s.choose_pack("plus", ["interiors", "trainer"])
    inst = s.installer(AutoUI())
    res = s.matches()
    for mid in ("shv", "nve", "interiors", "trainer"):
        inst.install(s.manifest.mod(mid), res.matched[mid])
    report = packs.rollback_mods(s, AutoUI(), {"interiors"})
    assert report[0].startswith("interiors: kept, because trainer") and (game / "interiors.asi").exists()


# ----------------------------------------------------------------------------------------------- custom mods
def test_custom_mod_entries_and_validation(tmp_path, mdir):
    m = load_manifest(mdir)
    st = tmp_path / "st"
    e = custommods.add(st, m, name="My Trainer!", file=str(tmp_path / "MyTrainer_2.zip"), files=["mt.asi"], to="scripts")
    assert e["id"] == "my-trainer" and e["order"] == 1 and e["files"] == [{"match": "mt.asi", "to": "scripts"}]
    e2 = custommods.add(st, m, name="Shv", page="https://x.example/mod", archive=["Cool*.zip"], method="guided")
    assert e2["id"] == "my-shv" and e2["order"] == 2                       # "shv" is a curated mod's id
    merged = custommods.merge(m, custommods.load_entries(st))
    mt = merged.mod("my-trainer")
    assert (mt.tier, mt.layer, mt.order, mt.archive, mt.method) == ("custom", "Your mods", 10001, ("MyTrainer_2.zip",), "copy")
    assert mt.files[0].to == "scripts" and merged.mod("my-shv").method == "guided"
    assert custommods.remove(st, "my-shv") and not custommods.remove(st, "my-shv")
    out = custommods.export(st, tmp_path / "share" / "mine.json")
    assert [x["id"] for x in json.loads(out.read_text())["mods"]] == ["my-trainer"]


@pytest.mark.parametrize("entry, message", [
    ({"id": "a", "name": "A"}, "file on your disk or the mod's page"),
    ({"id": "A B", "name": "A", "file": "x.zip"}, "id must be"),
    ({"id": "a", "name": " ", "file": "x.zip"}, "give it a name"),
    ({"id": "a", "name": "A", "page": "https://x"}, "how its download is named"),
    ({"id": "a", "name": "A", "page": "ftp://x", "archive": ["x"]}, "web address"),
    ({"id": "a", "name": "A", "file": "x.zip", "colour": 1}, "unknown key"),
    ({"id": "a", "name": "A", "file": "x.zip", "method": "copy"}, "needs a 'files' list"),
    ({"id": "a", "name": "A", "file": "x.zip", "files": [{"match": "x", "to": "../.."}]}, "inside the game folder"),
    ({"id": "a", "name": "A", "file": "x.zip", "order": -1}, "whole number"),
])
def test_custom_mod_errors(entry, message):
    with pytest.raises(custommods.CustomModError, match=message):
        custommods.to_mod(entry, 0)


def test_custom_mod_id_clash(mdir):
    m = load_manifest(mdir)
    with pytest.raises(custommods.CustomModError, match="already used by a curated mod"):
        custommods.merge(m, [{"id": "shv", "name": "x", "file": "x.zip"}])
    with pytest.raises(custommods.CustomModError, match="another of your mods"):
        custommods.merge(m, [{"id": "a", "name": "x", "file": "x.zip"}, {"id": "a", "name": "y", "file": "y.zip"}])
    with pytest.raises(custommods.CustomModError, match="--to needs --files"):
        custommods.add(Path("unused"), m, name="x", file="x.zip", to="scripts")


def test_custom_mod_installs_rolls_back_and_is_checked(tmp_path, mdir, game, downloads):
    write_zips(downloads, ["shv", "nve"])
    elsewhere = make_zip(tmp_path / "my stuff" / "MyTrainer.zip", {"mt.asi": "mine", "readme.txt": "r"})
    s = Session(tmp_path / "st", mdir, download_dir=str(downloads), game_dir=str(game))
    custommods.add(s.state, s.manifest_for("enhanced"), name="My trainer", file=str(elsewhere), files=["mt.asi"],
                   to="scripts")
    assert ids(s.mods()) == ["shv", "nve", "my-trainer"]               # selected, after the curated mods
    res = s.matches()
    assert res.matched["my-trainer"] == elsewhere                      # its own file, wherever it is
    before = take_snapshot(game)
    inst = s.installer(AutoUI())
    step = inst.install(s.manifest.mod("my-trainer"), res.matched["my-trainer"])
    assert (game / "scripts" / "mt.asi").read_text() == "mine" and step.mod == "my-trainer"
    assert not [f for f in s.findings() if f.mod == "my-trainer" and f.level == "error"]
    inst.rollback(step.id)
    assert diff(before, take_snapshot(game)).empty
    entries = custommods.load_entries(s.state)
    entries[0]["enabled"] = False
    custommods.save_entries(s.state, entries)
    assert ids(s.mods()) == ["shv", "nve"]                              # switched off: not selected


def test_custom_mod_conflict_check(tmp_path, mdir, game):
    (game / "old.asi").write_bytes(b"x")
    s = Session(tmp_path / "st", mdir, game_dir=str(game))
    custommods.save_entries(s.state, [{"id": "mine", "name": "Mine", "file": "x.zip", "conflicts": ["old.asi"]}])
    assert any(f.code == "conflict-file" and f.mod == "mine" for f in s.findings())


# --------------------------------------------------------------------------------------------------- CLI
def test_cli_pack_and_custom(tmp_path, mdir, game, downloads, capsys):
    base = ["--state-dir", str(tmp_path / "st"), "--manifest-dir", str(mdir), "--game-dir", str(game),
            "--download-dir", str(downloads)]
    assert main(base + ["pack", "list"]) == 0
    out = capsys.readouterr().out
    assert "* core  Leonida Core" in out and "  plus  Leonida Plus" in out and "variants: balanced, ultra" in out
    assert main(base + ["pack", "choose", "plus", "--addons", "food,trainer", "--variant", "ultra"]) == 0
    out = capsys.readouterr().out
    assert "Modpack: Leonida Plus (ultra)" in out and "New in the selection: bennys, food, trainer, ultra" in out
    assert main(base + ["pack", "addons", "--remove", "trainer", "--add", "interiors"]) == 0
    out = capsys.readouterr().out
    assert "World & interiors" in out and "[x] interiors" in out and "[ ] trainer" in out
    assert main(base + ["custom", "add", "--name", "My ENB", "--file", str(tmp_path / "enb.zip"), "--files",
                        "d3d11.dll", "--files", "enbseries.ini"]) == 0
    assert "Added my-enb" in capsys.readouterr().out
    assert main(base + ["custom", "list"]) == 0
    assert "my-enb  My ENB  [auto]" in capsys.readouterr().out
    assert main(base + ["custom", "export", str(tmp_path / "x.json")]) == 0
    assert main(base + ["custom", "remove", "my-enb"]) == 0 and main(base + ["custom", "remove", "my-enb"]) == 1
