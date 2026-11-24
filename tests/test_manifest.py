import json

import pytest

from leonida.manifest import ManifestError, load_manifest


def test_loads_and_core_has_14_mods(manifest):
    core = manifest.resolve("core")
    assert len(core) == 14
    assert all(m.tier == "core" for m in core) and "nve" not in {m.id for m in core}  # Core is free: NVE is paid
    assert [m.order for m in core] == sorted(m.order for m in core)
    assert core[0].id == "scripthookv"


def test_every_profile_resolves(manifest):
    for pid in manifest.profiles:
        assert manifest.resolve(pid)


def test_profile_nesting(manifest):
    plus = {m.id for m in manifest.resolve("core-plus")}
    mx = {m.id for m in manifest.resolve("max-rtx50")}
    assert plus < mx
    assert mx - plus == {"bettervehdeform"}


def test_every_page_is_https(manifest):
    for m in manifest.mods.values():
        assert m.page.startswith("https://"), m.id


def test_every_page_is_a_real_page_not_a_search(manifest):
    for m in manifest.mods.values():
        host = m.page.split("/")[2].lower()
        assert host not in ("duckduckgo.com", "www.google.com", "google.com", "www.bing.com", "bing.com"), m.id
        assert "?q=" not in m.page and "/search" not in m.page, m.id


def test_every_image_is_https(manifest):
    for m in manifest.mods.values():
        if m.image:
            assert m.image.startswith("https://"), m.id


# Asset names of each GitHub-sourced mod's latest release (checked 2026-11-24), plus siblings that must NOT match.
GITHUB_ASSETS = {
    "shvdne": ("ScriptHookVDotNetEnhanced-v1.1.0.6.zip", []),
    "menyoo": ("MenyooSP.zip", []),
    "lemonui": ("LemonUI.zip", []),
    "actionsv": ("ActionsV.zip", []),
    "hud-geckomacabre": ("GTA-VI-Inspired-HUD-2.8.2-Enhanced.oiv",
                         ["GTA-VI-Inspired-HUD-2.8.2-Legacy.oiv",
                          "GTA-VI-Inspired-HUD-2.8.2-LoadingScreens-Enhanced.oiv",
                          "GTA-VI-Inspired-HUD-2.8.2-LoadingScreens-Legacy.oiv"]),
}


def test_github_assets_match_download_glob_and_matcher(manifest, tmp_path):
    from fnmatch import fnmatchcase

    from leonida.matcher import match_files

    github = {m.id for m in manifest.mods.values() if m.download and m.download["type"] == "github"}
    assert github == set(GITHUB_ASSETS)
    for mid, (asset, others) in GITHUB_ASSETS.items():
        glob = manifest.mods[mid].download["asset"].lower()
        assert fnmatchcase(asset.lower(), glob), mid
        for other in others:
            assert not fnmatchcase(other.lower(), glob), (mid, other)
        p = tmp_path / asset
        p.write_bytes(b"x")
        assert match_files(manifest.mods.values(), [p]).matched.get(mid) == p, mid


def test_swap_hud(manifest):
    ids = [m.id for m in manifest.resolve("core", swaps={"hud-geckomacabre": "hud-fbicat"})]
    assert "hud-fbicat" in ids and "hud-geckomacabre" not in ids and "hud" not in ids


def test_bad_swap_rejected(manifest):
    with pytest.raises(ManifestError):
        manifest.resolve("core", swaps={"hud-geckomacabre": "menyoo"})


def test_unknown_profile(manifest):
    with pytest.raises(ManifestError):
        manifest.resolve("nope")


def test_add_and_remove(manifest):
    ids = {m.id for m in manifest.resolve("core", add=["immersivecombat"], remove=["menyoo"])}
    assert "immersivecombat" in ids and "menyoo" not in ids


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

def test_core_works_on_the_owners_build_1013_20(manifest):
    # The owner's game is 1.0.1013.20 and can't be updated: no Core mod may be unsupported there.
    mods = manifest.for_build("1.0.1013.20").resolve("core")
    assert [m.id for m in mods if m.unsupported] == []
    # NVE is a paid add-on now; added on top of Core it uses its 1013.20 release
    nve = manifest.for_build("1.0.1013.20").mod("nve")
    assert nve.variant is not None and "1013.20" in nve.notes


def test_every_mod_with_build_data_explains_it(manifest):
    for m in manifest.mods.values():
        if m.min_game_build or m.max_game_build or m.game_builds:
            assert m.notes or all(gb.unsupported or gb.overrides.get("notes") for gb in m.game_builds), m.id


def _selected(manifest, ids):
    return {m.id: m for m in manifest.for_selection(ids).mods.values() if m.id in ids}


def test_core_with_nve_skips_openrpf_and_uses_onigiri(manifest):
    ids = {m.id for m in manifest.resolve("core")} | {"nve", "drivevnve"}
    mods = _selected(manifest, ids)
    assert mods["openrpf"].not_needed and "onigiri" in mods["openrpf"].not_needed
    assert sorted(m for m, x in mods.items() if x.not_needed) == ["drivev", "openrpf"]
    assert not mods["drivevnve"].not_needed
    cam = mods["combatcamera"]
    assert cam.method == "copy" and cam.files[0].to.replace("\\", "/") == "onigiri/platform/data/metadata"
    for mid in ("mapfixes", "bugstarfixes", "hud-geckomacabre"):
        assert any("onigiri" in s for s in mods[mid].steps), mid


def test_core_without_nve_needs_openrpf_and_drops_nve_only_mods(manifest):
    ids = {m.id for m in manifest.resolve("core")} | {"drivevnve", "bettervehdeform"}
    assert "nve" not in ids
    mods = _selected(manifest, ids)
    assert sorted(m for m, x in mods.items() if x.not_needed) == ["bettervehdeform", "drivevnve"]
    assert not mods["drivev"].not_needed
    assert not mods["openrpf"].not_needed
    assert mods["combatcamera"].method == "guided"
    for mid in ("mapfixes", "bugstarfixes", "hud-geckomacabre", "combatcamera"):
        assert not any("onigiri" in s for s in mods[mid].steps), mid

