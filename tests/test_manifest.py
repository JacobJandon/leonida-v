import json

import pytest

from leonida.manifest import ManifestError, build_key, load_manifest


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
    "hud-loadingscreens": ("GTA-VI-Inspired-HUD-2.8.2-LoadingScreens-Enhanced.oiv",
                           ["GTA-VI-Inspired-HUD-2.8.2-Enhanced.oiv",
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


def test_owners_build_gets_versions_without_2026_content(manifest):
    # 1.0.1013.20 (Dec 2025) has no Kortz Center Heist (mp2026_01, 1.0.1158.13): Drive V 7.5 and Drive V for NVE
    # 7.5.1 add its cars, so that build gets 7.4 and rejects the 7.5 layouts (real member paths).
    from leonida.members import member_problem
    old, new = manifest.for_build("1.0.1013.20"), manifest.for_build("1.0.1158.13")
    dv, dn, ea = (old.mod(i) for i in ("drivev", "drivevnve", "enableallinteriors"))
    assert (dv.version, dv.pick) == ("7.4", {"versionLabel": "7.4"})
    assert "mp26" in member_problem(dv, ["Install.oiv", "Install/content/mp26/handling.meta"])
    assert member_problem(dv, ["Install.oiv", "Install/content/mp25_2/handling.meta"]) is None
    assert dn.version == "7.4"
    assert "mp2026_01" in member_problem(
        dn, ["DriveV 7.5 GTA V Enhanced NVE/Drive V Main/onigiri/dlc_patch/mp2026_01/common/data/handling.meta"])
    assert member_problem(dn, ["DriveV 7.4/Drive V Main/onigiri/common/data/handling.meta"]) is None
    assert any("TheKortzCenterHeist_" in s for s in ea.steps)
    assert sum("TheKortzCenterHeist_" in k for spec in ea.settings for k in spec["keys"]) == 9
    assert new.mod("drivev").version.startswith("7.5") and new.mod("drivevnve").version.startswith("7.5.1")
    assert not any("Kortz" in s for s in new.mod("enableallinteriors").steps)
    assert not any("Kortz" in k for spec in new.mod("enableallinteriors").settings for k in spec["keys"])


KNOWN_ENHANCED_BUILDS = ["1.0.811.8", "1.0.812.8", "1.0.813.11", "1.0.814.9", "1.0.889.15", "1.0.889.19",
                         "1.0.889.22", "1.0.1013.17", "1.0.1013.20", "1.0.1013.29", "1.0.1013.33", "1.0.1013.34",
                         "1.0.1158.13", "1.0.1158.16"]


def test_every_known_enhanced_build_resolves(manifest):
    # Every mod gives a version or a reason on every known Enhanced build; Core loses only what can't install.
    for build in KNOWN_ENHANCED_BUILDS:
        for m in manifest.for_build(build).mods.values():
            assert m.unsupported or m.version, (build, m.id)
            assert not m.unsupported or len(m.unsupported) > 40, (build, m.id)
        core_out = {m.id for m in manifest.for_build(build).resolve("core") if m.unsupported}
        assert core_out == (set() if build_key(build) >= build_key("1.0.1013.17") else {"mapfixes", "bugstarfixes"}), build
    versions = {b: manifest.for_build(b).mod("drivev").version for b in ("1.0.811.8", "1.0.889.22", "1.0.1013.17")}
    assert versions == {"1.0.811.8": "6.8", "1.0.889.22": "7.3", "1.0.1013.17": "7.4"}
    assert "mp2025_02" in manifest.for_build("1.0.889.22").mod("mapfixes").unsupported


def test_every_paid_mod_has_a_free_route(manifest):
    # F1: no paid mod without a recorded free route; alternatives are free mods in the manifest.
    for edition in ("enhanced", "legacy"):
        m = load_manifest(edition=edition)
        for mod in m.mods.values():
            if mod.tier != "paid":
                continue
            assert mod.free_route, (edition, mod.id)
            if mod.free_route["type"] == "alternative":
                assert m.mods[mod.free_route["mod"]].tier != "paid", mod.id
            assert "no free route" not in m.free_route_text(mod.id), mod.id
    assert manifest.mod("nve").free_route["mod"] == "visualv"


def test_modpacks_are_free_and_keep_the_profile_ids():
    # F4: Leonida Core / Plus / Showcase for both editions; nothing paid in any pack or add-on.
    for edition in ("enhanced", "legacy"):
        m = load_manifest(edition=edition)
        assert {"core", "core-plus", "video-setup"} <= set(m.packs) and m.default_pack == "core"
        for pid, pack in m.packs.items():
            assert pack.name.startswith("Leonida") and pack.picture.startswith("https://"), (edition, pid)
            every_addon = [a for lst in m.addons_for(pid).values() for a in lst]
            for mod in m.resolve_pack(pid) + m.resolve_pack(pid, addons=[a.id for a in every_addon]):
                assert not mod.is_paid, (edition, pid, mod.id)
        show = {x.id for x in m.resolve_pack("video-setup")}
        assert {"hud-geckomacabre", "visualv", "burgershot"} <= show, edition
        assert [x.id for x in m.resolve_pack("core")] == [x.id for x in m.resolve("core")]


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

