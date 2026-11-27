"""The owner's pick (owner's rule 2026-11-25): only mods from the owner's own sources plus what they strictly need;
paid ones as add-ons; mods that do the same job are either/or, never installed together (docs/OWNER-SOURCES.md,
docs/CONFLICTS.md)."""

from __future__ import annotations

import pytest

from leonida import settings as S
from leonida.checks import ERROR, run_checks
from leonida.manifest import load_manifest
from leonida.session import Session, _off_on_build

OLD, NEW = "1.0.1013.20", "1.0.1158.16"
DEPS = {"scripthookv", "shvdne", "directstoragefix", "openrpf", "resourceextensions", "lemonui",
        "straighttostory",   # a Leonida tool: the play test and Play need the game to go straight to story mode
        "leonidamenu"}       # Leonida's own in-game menu (our code, in every pack)
FROM_SOURCES = {
    "menyoo", "nextgeneuphoria", "combatcamera", "hud-geckomacabre", "hud-loadingscreens", "drivev", "trafficvfear",
    "mapupdates", "bennys", "streetfood", "cameraflinch", "actionsv", "burgershot", "upnatom", "elgin247",
    "vinewood247", "gtavremastered", "openworldinteriors", "enableallinteriors", "jasonhouse", "dynamicfirstperson",
    "qolvehicles", "fooddelivery", "rideshare", "betterfistfighting",
    # either/or and paid add-ons
    "libertysuspension", "libertydamage", "dlcpopgroups", "downtowncab", "fuelreloaded", "chinosounds",
    "nve", "drivevnve", "lwe", "jasonlucia",
}
OUR_OWN_PICKS = {"visualv", "primerealismv", "maxedv", "aurav", "fh6roads", "ios26icons",
                 "allmpvehicles", "immersivecombat", "mapfixes", "bugstarfixes", "sourcemotion", "hud-fbicat", "hud",
                 "mpjasonlucia", "bettervehdeform", "chromatix", "centralmods"}


def _every_addon(m):
    return [a.id for lst in m.addons_for("owner-pick").values() for a in lst]


def _chosen(m, addons, build):
    """The mods that would really be installed (whenSelected/whenMissing skips applied)."""
    mods = m.for_build(build).resolve_pack("owner-pick", addons=addons)
    sel = {x.id for x in mods}
    return {x.id: x for x in (x.for_selection(sel) for x in mods) if not x.not_needed}


def test_only_the_owners_sources_and_their_dependencies():
    m = load_manifest()
    base = {x.id for x in m.resolve_pack("owner-pick", addons=[])}
    assert base == DEPS | (FROM_SOURCES - {"libertysuspension", "libertydamage", "dlcpopgroups", "downtowncab",
                                           "fuelreloaded", "chinosounds", "nve", "drivevnve", "lwe", "jasonlucia"})
    every = {x.id for x in m.resolve_pack("owner-pick", addons=_every_addon(m))}
    assert every <= DEPS | FROM_SOURCES and not every & OUR_OWN_PICKS
    assert not any(x.is_paid for x in m.resolve_pack("owner-pick"))            # paid = add-ons you tick
    assert {c for c in m.addons_for("owner-pick")} == {"owner-choices", "owner-paid"}
    for pid in m.packs:                                                        # no other pack offers them
        assert pid == "owner-pick" or not {"owner-choices", "owner-paid"} & set(m.addons_for(pid))


@pytest.mark.parametrize("addon, gone, build, extra", [
    ("owner-gta4-handling", {"drivev"}, OLD, []),
    ("owner-dlc-traffic", {"trafficvfear", "drivev"}, NEW, []),
    ("owner-lwe", {"gtavremastered"}, OLD, []),
    ("owner-nve", {"drivev", "openrpf"}, OLD, []),
])
def test_either_or_choices_never_install_both(addon, gone, build, extra):
    m = load_manifest()
    without = _chosen(m, [], build)
    chosen = _chosen(m, [addon, *extra], build)
    assert gone <= set(without) and not gone & set(chosen)
    for x in chosen.values():                                                 # one mod per slot
        assert sum(1 for y in chosen.values() if x.slot and y.slot == x.slot) <= 1, x.id


def test_dlc_popgroups_needs_nve_and_kortz_cars():
    m = load_manifest()
    assert "Kortz" in m.for_build(OLD).mod("dlcpopgroups").unsupported
    sel = {"dlcpopgroups", "trafficvfear"}                                   # picked alone, without NVE: skipped
    assert m.for_build(NEW).mod("dlcpopgroups").for_selection(sel).not_needed
    assert {"nve", "dlcpopgroups"} <= set(m.addons["owner-dlc-traffic"].mods)  # so the pack's choice brings NVE


STUB_LOD = "x64\\levels\\gta5\\basev.rpf\\vb_03_bld2_e_slod_children.ydd"


def test_burger_shot_on_1013_without_its_empty_lod_stub(tmp_path, game):
    # 2026-11-26, owner's PC on 1.0.1013.20: the 0xBCC6AD loading crash from a west-coast save (1 load in 3), 8 of 8
    # clean with only the Burger Shot off. The pack's vb_03_bld2_e_slod_children.ydd (146 bytes) holds one empty model,
    # 'hash_E2FD295F' (vb_03_bld2_e_lod), with no shader behind it; the game has its own (x64m.rpf, venice.rpf). On
    # 1013.x Leonida deletes the stub from the user's copy in mods\ so the game's own is used (2026-11-27).
    m = load_manifest()
    old = m.for_build(OLD).mod("burgershot")
    assert not old.unsupported and old.method == "rpf"
    assert {"archive": "update\\x64\\dlcpacks\\burgershot\\dlc.rpf", "delete": STUB_LOD} in old.rpf
    assert {"archive": "update\\update.rpf", "dlclist": "dlcpacks:/burgershot/"} in old.rpf     # still listed
    assert not any("delete" in op for op in m.for_build(NEW).mod("burgershot").rpf)              # newer builds: as is
    assert not any("delete" in op for op in m.for_build("1.0.1014.0").mod("burgershot").rpf)
    assert "burgershot" in {x.id for x in m.resolve_pack("owner-pick", addons=[])}               # the pack keeps it
    assert "0xBCC6AD" in old.notes and "nothing is re-hosted" in old.notes
    core = m.for_build("1.0.1013.16").mod("mapfixes")                                           # core: still an error
    assert core.tier == "core" and core.unsupported and _off_on_build(core) is core
    s = Session(tmp_path / "st", game_dir=str(game), game_build=OLD)
    s.config.profile = "owner-pick"
    assert "burgershot" in {x.id for x in s.mods()}                                             # installed there again
    s.game_build_override = NEW
    assert "burgershot" in {x.id for x in s.mods()}


def test_fuel_reloaded_switches_the_huds_fuel_off():
    m = load_manifest()
    hud = m.mod("hud-geckomacabre")
    burn = {False: None, True: None}
    for on in burn:
        sel = {"hud-geckomacabre"} | ({"fuelreloaded"} if on else set())
        burn[on] = {w.key: w.value for w in S.wanted_for(hud, "owner-pick", None, sel)}["FuelStation/BurnFuel"]
    assert burn == {False: "True", True: "False"}


@pytest.mark.parametrize("build", [OLD, NEW])
def test_no_check_errors_and_no_key_clash(tmp_path, build):
    m = load_manifest()
    addons = [a for a in _every_addon(m) if not (build == OLD and a == "owner-dlc-traffic")]
    # as the session hands them to the checks: optional mods the build can't run are left out (_off_on_build)
    mods = [x for x in map(_off_on_build, m.for_build(build).resolve_pack("owner-pick", addons=addons))
            if not x.not_needed]
    assert not [f for f in run_checks(m, mods, tmp_path, game_version=build) if f.level == ERROR]
    chosen = _chosen(m, addons, build)
    keys = [(k["key"].lower(), k["mod"]) for k in m.hotkeys if k["mod"] in chosen]
    assert len({k for k, _ in keys}) == len(keys), sorted(keys)


def test_memory_variants_16_and_32_gb():
    # owner's PC: 8/8 loads with ~6 GB free vs ~4 crashes in 19 at ~4.6 GB, so the default keeps RE's budgets vanilla
    m = load_manifest()
    pack = m.get_pack("owner-pick")
    assert pack.default_variant == "ram16" and [v.id for v in pack.variants] == ["ram16", "ram32"]
    for build, densities in ((OLD, False), (NEW, True)):
        re_ = m.for_build(build).mod("resourceextensions")
        got = {v: {w.key: w.value for w in S.wanted_for(re_, "owner-pick", pack.variant(v), {re_.id})}
               for v in ("ram16", "ram32")}
        assert all(got["ram16"][k] == "0" for k in ("budget/StreamingMemoryBudget", "budget/VehicleModelBudget",
                                                       "budget/BvhVertexArena"))
        assert got["ram32"]["budget/StreamingMemoryBudget"] == "1"
        assert ("density/AmbientPeds" in got["ram16"]) == densities      # Inactive before 1.0.1158.13: not locked


def test_paid_mods_are_offered_without_stand_ins(tmp_path):
    # owner's rule: "paid by its creator: buy it from them to enable it", plus only the same author's own free edition
    m = load_manifest()
    assert not [x.id for x in m.mods.values() if x.is_paid and (x.free_route or {}).get("type") == "alternative"]
    every = _every_addon(m)
    f = run_checks(m, m.resolve_pack("owner-pick", addons=every), tmp_path, game_version=NEW)
    paid = {x.mod: x.message for x in f if x.code == "paid"}
    assert {"nve", "lwe", "jasonlucia"} <= set(paid)
    assert all("paid by its creator: buy it from them to enable it" in msg and " instead" not in msg for msg in paid.values())
    assert "author's own official free edition" in paid["lwe"]
