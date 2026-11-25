"""Game-build-specific gameconfig.xml pools (mods.json): Resource Extensions 2.5 leaves the engine pools, the packfile
limit and its densities vanilla on builds before 1.0.1158.13 (the owner's ResourceExtensions.log on 1.0.1013.20), so
there the GTA VI-Inspired HUD and GTA V Remastered raise their pools in gameconfig.xml, raise-only."""

from __future__ import annotations

import re

import pytest

from leonida import settings as S
from leonida.checks import INFO, run_checks
from leonida.manifest import load_manifest

OLD, NEW = "1.0.1013.20", "1.0.1158.16"
GC = "common\\data\\gameconfig.xml"


def _pools(mod) -> dict[str, int]:
    """Pool -> value the mod's own gameconfig.xml edits raise it to (from the replace edits)."""
    out = {}
    for op in mod.rpf or ():
        if op.get("xml") == GC:
            for e in op["edits"]:
                if e["type"] == "replace":
                    name = re.search(r"PoolName='(\w+)'|/(MaxExtraPedModelInfos)\[", e["xpath"])
                    out[name.group(1) or name.group(2)] = int(re.search(r'value="(\d+)"', e["xml"]).group(1))
    return out


def _skips_gameconfig(mod) -> bool:
    return any(GC in op.get("skip", []) for op in mod.rpf or () if "oiv" in op)


def _pack(build, pack="video-setup", variant="balanced"):
    return {m.id: m for m in load_manifest().for_build(build).resolve_pack(pack, variant=variant)}


def test_old_builds_raise_the_pools_resource_extensions_cant():
    old = _pack(OLD)
    hud, rem = old["hud-geckomacabre"], old["gtavremastered"]
    # the HUD .oiv's own five raises (its 2.8.2 assembly.xml), applied by Leonida so the check can see them
    assert _skips_gameconfig(hud)
    assert _pools(hud) == {"MetaDataStore": 4000, "ExprDictStore": 400, "TxdStore": 150000, "DwdStore": 30000,
                           "MaxExtraPedModelInfos": 600}
    # GTA V Remastered's troubleshooting.txt / the HUD's Legacy guide; DwdStore stays the HUD's (higher) 30000
    assert _pools(rem) == {"Building": 70000, "phInstGta": 20000, "StaticBounds": 20000}
    assert any(op.get("dlclist") == "dlcpacks:/vremastered/" for op in rem.rpf)
    for m in (hud, rem):
        assert m.variant == 0 and not m.unsupported and m.version == m.base.version  # same version, other install
    # every raise is raise-only: add a scratch node, replace only a smaller value (or the scratch), drop the extra
    for m in (hud, rem):
        edits = [e for op in m.rpf if op.get("xml") == GC for e in op["edits"]]
        assert [e["type"] for e in edits] == ["add", "replace", "remove"] * (len(edits) // 3)
        assert all("[@value < " in e["xpath"] for e in edits if e["type"] == "replace")


def test_new_builds_leave_the_pools_to_resource_extensions():
    new = _pack(NEW)
    hud, rem = new["hud-geckomacabre"], new["gtavremastered"]
    assert _skips_gameconfig(hud) and _pools(hud) == {} and _pools(rem) == {}
    assert hud.variant is None and rem.variant is None


@pytest.mark.parametrize("build", [OLD, NEW])
def test_without_resource_extensions_the_mods_raise_their_own_pools(build):
    m = load_manifest().for_build(build)
    sel = {"hud-geckomacabre", "gtavremastered", "openrpf"}
    hud = m.mod("hud-geckomacabre").for_selection(sel)
    rem = m.mod("gtavremastered").for_selection(sel)
    assert not _skips_gameconfig(hud) and [list(op) for op in hud.rpf] == [["oiv"]]  # the .oiv's own edits
    assert _pools(rem) == {"Building": 70000, "phInstGta": 20000, "StaticBounds": 20000}


def test_resource_extensions_densities_only_where_they_work():
    def keys(build, variant):
        pack = load_manifest().for_build(build).get_pack("video-setup")
        mod = _pack(build, variant=variant)["resourceextensions"]
        return {w.key: w.value for w in S.wanted_for(mod, "video-setup", pack.variant(variant), {mod.id})}

    old, new = keys(OLD, "balanced"), keys(NEW, "balanced")
    assert not [k for k in old if k.startswith(("density/", "population/"))]   # 'Population Density (INI): Inactive'
    assert new["density/AmbientPeds"] == "1.50" and new["population/Cyclists"] == "1.00"
    for k in ("decals/Persistence", "budget/VehicleModelBudget", "logging/EnableLog"):  # Active on 1.0.1013.20
        assert old[k] == new[k]


def test_check_explains_the_pools_on_old_builds(tmp_path):
    m = load_manifest()
    mods = m.resolve_pack("video-setup", variant="balanced")
    old = [f for f in run_checks(m, mods, tmp_path, game_version=OLD) if f.code.startswith("gameconfig")]
    assert [(f.level, f.code) for f in old] == [(INFO, "gameconfig-pools")]
    assert "GTA V Remastered" in old[0].message and "GTA VI-Inspired HUD" in old[0].message
    assert "DLC pack" in old[0].message
    new = [f for f in run_checks(m, mods, tmp_path, game_version=NEW) if f.code.startswith("gameconfig")]
    assert [f.code for f in new] == ["gameconfig-rpf"]
