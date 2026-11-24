import json

import pytest

from leonida.manifest import ManifestError, load_manifest


def test_loads_and_core_has_14_mods(manifest):
    core = manifest.resolve("core")
    assert len(core) == 14
    assert [m.order for m in core] == sorted(m.order for m in core)
    assert core[0].id == "scripthookv"


def test_every_profile_resolves(manifest):
    for pid in manifest.profiles:
        assert manifest.resolve(pid)


def test_profile_nesting(manifest):
    plus = {m.id for m in manifest.resolve("core-plus")}
    mx = {m.id for m in manifest.resolve("max-rtx50")}
    assert plus < mx
    assert {"bettervehdeform", "dlss5swapper"} <= mx


def test_every_page_is_https(manifest):
    for m in manifest.mods.values():
        assert m.page.startswith("https://"), m.id


def test_swap_hud(manifest):
    ids = [m.id for m in manifest.resolve("core", swaps={"hud": "hud-fbicat"})]
    assert "hud-fbicat" in ids and "hud" not in ids


def test_bad_swap_rejected(manifest):
    with pytest.raises(ManifestError):
        manifest.resolve("core", swaps={"hud": "menyoo"})


def test_unknown_profile(manifest):
    with pytest.raises(ManifestError):
        manifest.resolve("nope")


def test_add_and_remove(manifest):
    ids = {m.id for m in manifest.resolve("core", add=["projectvice"], remove=["menyoo"])}
    assert "projectvice" in ids and "menyoo" not in ids


def test_duplicate_order_rejected(tmp_path, manifest):
    src = load_manifest.__globals__["resources"].files("leonida.manifest")
    for name in ("mods.json", "profiles.json", "hotkeys.json"):
        (tmp_path / name).write_text(src.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8")
    data = json.loads((tmp_path / "mods.json").read_text(encoding="utf-8"))
    data["mods"][1]["order"] = data["mods"][0]["order"]
    (tmp_path / "mods.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(tmp_path)


def test_copy_targets_stay_inside_game(tmp_path):
    src = load_manifest.__globals__["resources"].files("leonida.manifest")
    for name in ("mods.json", "profiles.json", "hotkeys.json"):
        (tmp_path / name).write_text(src.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8")
    data = json.loads((tmp_path / "mods.json").read_text(encoding="utf-8"))
    data["mods"][0]["install"]["files"][0]["to"] = "../../Windows"
    (tmp_path / "mods.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(tmp_path)
