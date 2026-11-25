"""F5 data: the locked settings of every pack and variant (both editions) are consistent and apply cleanly."""

from __future__ import annotations

import pytest

from leonida import settings as S
from leonida.manifest import load_manifest

OWNER_BUILD = {"enhanced": "1.0.1013.20", "legacy": "1.0.3725.0"}


def _cases():
    for edition, build in OWNER_BUILD.items():
        m = load_manifest(edition=edition).for_build(build)
        for pid, pack in m.packs.items():
            for v in pack.variants or (None,):
                yield pytest.param(edition, pid, v.id if v else None, id=f"{edition}-{pid}-{v.id if v else 'none'}")


def _wanted(edition, pid, vid, add=(), build=None):
    m = load_manifest(edition=edition).for_build(build or OWNER_BUILD[edition])
    pack = m.packs[pid]
    v = pack.variant(vid) if vid else None
    mods = m.resolve_pack(pid, variant=vid, add=add)
    sel = {x.id for x in mods}
    return [w for mod in mods for w in S.wanted_for(mod, pid, v, sel)]


@pytest.mark.parametrize("edition, pid, vid", list(_cases()))
def test_pack_settings_have_no_clash_and_no_drift_after_apply(tmp_path, edition, pid, vid):
    wanted = _wanted(edition, pid, vid, add=["actionsv"])
    assert wanted
    seen = {}
    for w in wanted:  # two mods (or rules) never lock the same key to different values
        k = (w.file.lower(), w.key.lower())
        assert k not in seen or S.same(seen[k].value, w.value), (k, seen[k].mod, w.mod)
        seen[k] = w
    for f, items in S.by_file(wanted).items():  # an existing (empty) config file of each mod
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("; shipped by the mod\n", encoding="utf-8")
        assert len(S.drift(tmp_path, items)) == len(items)
        p.write_bytes(S.render(p, items))
    assert S.drift(tmp_path, wanted) == []


def _val(wanted, key):
    return next(w.value for w in wanted if w.key == key)


def test_variant_and_selection_values():
    perf, bal, ultra = (_wanted("enhanced", "video-setup", v) for v in ("performance", "balanced", "ultra"))
    # Resource Extensions' densities work from 1.0.1158.13 (on 1.0.1013.20 its log says 'Population Density (INI):
    # Inactive', so they aren't locked there: tests/test_gameconfig_pools.py)
    NEW = "1.0.1158.16"
    new = [_wanted("enhanced", "video-setup", v, build=NEW) for v in ("performance", "balanced", "ultra")]
    assert [_val(w, "density/AmbientPeds") for w in new] == ["1.00", "1.50", "2.00"]
    assert not [w for w in perf + bal + ultra if w.key.startswith("density/")]
    assert [_val(w, "budget/BvhVertexArena") for w in (perf, bal, ultra)] == ["0", "0", "1"]
    assert [_val(w, "MAIN/max_traffic_vehicles") for w in (perf, bal, ultra)] == [3, 3, 5]
    core = _wanted("enhanced", "core", None)
    assert _val(core, "ReloadKeyBinding") == "None"
    assert _val(_wanted("enhanced", "core", None, build=NEW), "density/AmbientPeds") == "1.00"
    assert _val(perf, "ReloadKeyBinding") == "Insert"            # Enable All Interiors is in the pack
    assert _val(core, "MAIN/blips") == 0 and _val(core, "Hitmarkers/Enabled") == "False"
    assert _val(_wanted("enhanced", "max-rtx50", None, build=NEW), "density/AmbientPeds") == "2.00"
    # the owner's build has no Kortz Center Heist: Enable All Interiors' nine switches are locked off
    kortz = [w for w in perf if "TheKortzCenterHeist_" in w.key]
    assert len(kortz) == 9 and all(w.value == "False" for w in kortz)
    newer = load_manifest().for_build("1.0.1158.13")
    assert not [w for w in S.wanted_for(newer.mod("enableallinteriors")) if "Kortz" in w.key]


def test_old_f8_hud_moves_menyoo_and_actionsv():
    m = load_manifest()
    sel = {"menyoo", "actionsv", "hud"}
    keys = {w.key: w.value for mid in ("menyoo", "actionsv") for w in S.wanted_for(m.mod(mid), "core", None, sel)}
    assert keys["settings/open_key"] == 121 and keys["Input/MenuKey"] == "F7"


@pytest.mark.parametrize("edition", ["enhanced", "legacy"])
def test_no_hotkey_clash_in_any_pack_with_every_add_on(edition):
    # the HUD reloads its settings on F10, so ActionsV moves to F7 and AuraV's menu to F11
    m = load_manifest(edition=edition)
    for pid in m.packs:
        every = [a.id for lst in m.addons_for(pid).values() for a in lst]
        sel = {x.id for x in m.resolve_pack(pid, addons=every)}
        keys = [(k["key"], k["mod"]) for k in m.hotkeys if k["mod"] in sel]
        dup = {k for k, _ in keys if sum(1 for kk, _ in keys if kk == k) > 1}
        assert not dup, (edition, pid, sorted(x for x in keys if x[0] in dup))
    assert {"F7"} == {w.value for w in S.wanted_for(m.mod("actionsv"))}


def test_every_showcase_mod_has_in_game_checks():
    # docs/IN-GAME-CHECKS.md: each Showcase mod says what to look for in game (mods.json "checks")
    import json
    from pathlib import Path

    raw = {m["id"]: m for m in json.loads(
        (Path(__file__).parents[1] / "leonida/manifest/mods.json").read_text(encoding="utf-8"))["mods"]}
    m = load_manifest().for_build("1.0.1013.20")
    for mod in m.resolve_pack("video-setup"):
        checks = raw[mod.id].get("checks")
        assert checks and all(isinstance(c, str) and c for c in checks), mod.id
    ryde = {w.key: w.value for w in S.wanted_for(m.mod("rideshare"))}
    assert ryde == {"Keys/Menu": "PageUp", "Keys/CancelJob": "PageDown", "Keys/Accept": "Home", "Keys/Decline": "End"}
    # N declines in Food Delivery / Ryde and is Dynamic First Person's car camera key (conflict audit 2026-11-25)
    assert {w.key: w.value for w in S.wanted_for(m.mod("fooddelivery"))} == {"Keys/Decline": "Delete"}


def test_shvdn_timeout_is_raised_for_enable_all_interiors():
    # real play test 2026-11-25: SHVDNE terminated EAI's LoadMPMaps at the default 5000 ms
    for edition, mid in (("enhanced", "shvdne"), ("legacy", "shvdn")):
        m = load_manifest(edition=edition)
        for sel, want in (({mid}, 5000), ({mid, "enableallinteriors"}, 15000)):
            got = {w.key: w.value for w in S.wanted_for(m.mod(mid), "core", None, sel)}
            assert got["ScriptTimeoutThreshold"] == want, (edition, sel)
    perf = _wanted("enhanced", "video-setup", "performance")
    assert _val(perf, "ScriptTimeoutThreshold") == 15000
    assert _val(_wanted("enhanced", "core", None), "ScriptTimeoutThreshold") == 5000
