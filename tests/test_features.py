"""Features (leonida/features.py): every mod says what it does; two selected mods that do the same job are an error in
`leonida check` unless the manifest records how they coexist (sharesFeature). Every pack, with every add-on, on both
tested builds, must come out clean."""

from __future__ import annotations

import pytest

from leonida import features as F
from leonida.checks import ERROR, run_checks
from leonida.manifest import load_manifest


@pytest.mark.parametrize("edition", ["enhanced", "legacy"])
def test_every_mod_has_known_features_and_records_point_somewhere(edition):
    assert F.problems(edition) == []
    m = load_manifest(edition=edition)
    assert all(F.features_of(mid, edition) for mid in m.mods)


def _cases():
    for edition, builds in (("enhanced", ("1.0.1013.20", "1.0.1158.16")), ("legacy", ("1.0.3725.0",))):
        m = load_manifest(edition=edition)
        for pid in m.packs:
            for build in builds:
                yield pytest.param(edition, pid, build, id=f"{edition}-{pid}-{build}")


@pytest.mark.parametrize("edition, pid, build", list(_cases()))
def test_no_pack_has_two_mods_doing_the_same_job(tmp_path, edition, pid, build):
    m = load_manifest(edition=edition)
    every = [a.id for lst in m.addons_for(pid).values() for a in lst]
    for addons in (None, every):
        mods = m.for_build(build).resolve_pack(pid, addons=addons)
        sel = {x.id for x in mods}
        chosen = [x.for_selection(sel) for x in mods]
        bad = [c for c in F.clashes(chosen, edition) if not c.settled]
        assert not bad, [(c.a, c.b, c.feature) for c in bad]
        codes = {f.code for f in run_checks(m, mods, tmp_path, game_version=build)}
        assert "feature-clash" not in codes


def test_an_unrecorded_pair_is_an_error(tmp_path):
    m = load_manifest()
    mods = m.resolve_pack("core", addons=[]) + [m.mod("sourcemotion"), m.mod("immersivecombat")]
    # SourceMotion and NextGen Euphoria share the euphoria slot (slot check); Immersive Combat clashes with nothing
    found = run_checks(m, mods, tmp_path, game_version="1.0.1013.20")
    assert "slot-clash" in {f.code for f in found} and "feature-clash" not in {f.code for f in found}
    # Central traffic and All MP Vehicles both fill the traffic, and nothing says how they'd coexist
    mods = m.resolve_pack("core", addons=[]) + [m.mod("centralmods")]
    found = [f for f in run_checks(m, mods, tmp_path, game_version="1.0.1013.20") if f.code == "feature-clash"]
    assert len(found) == 1 and found[0].level == ERROR and "traffic-population" in found[0].message


def test_settled_pairs_say_how_and_whether_it_was_verified():
    rec = F.record_for("fuelreloaded", "hud-geckomacabre", "fuel")
    assert "BurnFuel" in rec["how"] and rec["verified"]
    assert F.record_for("openworldinteriors", "burgershot", "interiors-fastfood")["verified"].startswith("not yet")
