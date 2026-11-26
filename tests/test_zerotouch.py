"""Zero-touch (plan F8, leonida/zerotouch.py): every mod has a proof it's on; the owner's pick needs no hand step;
what still needs the player says why; the in-game half (inGameSetup) is well-formed; the files half works."""

from __future__ import annotations

import pytest

from leonida import zerotouch as Z
from leonida.manifest import load_manifest


@pytest.mark.parametrize("edition", ["enhanced", "legacy"])
def test_every_mod_has_a_proof_and_the_data_is_valid(edition):
    assert Z.problems(edition) == []
    m = load_manifest(edition=edition)
    assert all(Z.verify_for(mid, edition) for mid in m.mods)


def _chosen(pid, build="1.0.1013.20", addons=None):
    m = load_manifest().for_build(build)
    mods = m.resolve_pack(pid, addons=addons)
    sel = {x.id for x in mods}
    return [x.for_selection(sel) for x in mods]


def test_the_owners_pick_needs_no_hand_step():
    assert Z.hand_steps(_chosen("owner-pick")) == []
    for pid in ("core", "core-plus", "video-setup"):
        assert Z.hand_steps(_chosen(pid)) == [], pid


def test_every_remaining_hand_step_says_why():
    m = load_manifest()
    for pid in m.packs:
        every = [a.id for lst in m.addons_for(pid).values() for a in lst]
        for h in Z.hand_steps(_chosen(pid, addons=every)):
            assert h.why, (pid, h.mod)


def test_hand_steps_leonida_now_does_are_gone():
    m = load_manifest()
    eai, hud = m.mod("enableallinteriors"), m.mod("hud-geckomacabre")
    assert not any("press Insert" in s for s in eai.steps)
    # the HUD keeps its two "before you play" lines for the launcher's card; Leonida writes / checks both
    assert len(hud.steps) == 2 and Z.hand_steps([hud]) == []
    (reload,) = Z.in_game_setup("enableallinteriors")
    assert reload["action"] == "reload-scripts" and reload["when"] == "verify-fails"
    assert reload["verify"]["contains"] == "MP MAPS LOADED"
    (lang,) = Z.in_game_setup("hud-geckomacabre")
    assert lang["verify"] == {"kind": "native", "in": "game", "name": "GET_CURRENT_LANGUAGE", "equals": 0}
    assert m.mod("aurav").method == "copy" and m.mod("dlcpopgroups").method == "copy"


def test_files_half_on_a_fake_game(tmp_path):
    game = tmp_path / "game"
    (game / "scripts").mkdir(parents=True)
    (game / "ActionsV.asi").write_bytes(b"asi")
    (game / "scripts" / "EAIInitalization.log").write_text("State 4 (MP MAPS LOADED)\nState 9 (INITIALIZATION DONE)\n")
    m = load_manifest()
    proofs = Z.check_files(game, [m.mod("actionsv"), m.mod("enableallinteriors"), m.mod("menyoo"), m.mod("burgershot")])
    s = Z.summary(proofs)
    assert s["actionsv"] == "on" and s["burgershot"] == "not checked"     # a DLC pack is proven in game
    assert s["menyoo"] == "off"                                            # Menyoo.asi and its log are missing
    eai = [p for p in proofs if p.mod == "enableallinteriors"]
    assert {p.ok for p in eai if p.check["kind"] == "log"} == {True}
    assert s["enableallinteriors"] == "off"                                # its scripts aren't in place
    assert Z.describe({"kind": "dlc", "in": "game", "name": "vihud"}) == "DLC pack vihud present (in game)"


# setup2.xml <nameHash> of the installed packs, read from the owner's real dlc.rpf files (2026-11-26). IS_DLC_PRESENT
# takes that name, not the folder name: the two frdfare shops' folders end in _g9, their nameHash doesn't
REAL_NAME_HASH = {
    "bennys": {"bennys_sp"}, "elgin247": {"elg_247shop"}, "jasonhouse": {"mmd_jason_duval_houses"},
    "qolvehicles": {"qolpack_g9"}, "mapupdates": {"spMapUpdates_Gen9", "spMapUpdates_Patch_Gen9"},
    "hud-geckomacabre": {"vihud", "vihudanims", "vihudfonts"}, "gtavremastered": {"vremastered"},
    "vinewood247": {"vwp_247shop"}, "upnatom": {"vw_upna"}, "burgershot": {"burgershot"},
}


def test_dlc_proofs_use_the_packs_own_name_hash():
    for mid, names in REAL_NAME_HASH.items():
        assert {v["name"] for v in Z.verify_for(mid, "enhanced") if v["kind"] == "dlc"} == names, mid
