"""`leonida settings tune` (leonida/tune.py) and the graphics card tiers (gamesettings.json gpuTiers): settings come
from the card's video memory and are pushed up only while play tests pass and stay in budget."""

from __future__ import annotations

from dataclasses import dataclass, field

from leonida import cli
from leonida import gamesettings as G
from leonida import tune as T
from leonida.session import Session

GTX1070 = G.PC(15.8, 8.0, ("NVIDIA GeForce GTX 1070",))
SEL = {"hud-geckomacabre"}


def test_tiers_follow_video_memory():
    assert G.tier_for(GTX1070)["id"] == "top"
    assert G.tier_for(G.PC(16, 6.0, ("NVIDIA GeForce GTX 1060",)))["id"] == "high"
    assert G.tier_for(G.PC(16, 4.0, ("NVIDIA GeForce GTX 1650",)))["id"] == "medium"
    assert G.tier_for(G.PC(8, 2.0, ("Intel UHD",)))["id"] == "low"
    assert G.tier_for(G.PC(16, None, ())) is None                           # unknown: the game's own values stay
    top = {w.key.split("/")[1]: (w.value, w.source) for w in G.wanted("enhanced", "owner-pick", "ram16", SEL, GTX1070)}
    # the game's own auto choice on this card, measured at 4.0-4.5 GB of 8 GB with the whole pack
    assert top["TextureQuality"][0] == "2" and top["GrassQuality"][0] == "3" and top["ShadowQuality"][0] == "3"
    assert top["TextureQuality"][1].startswith("your graphics card (top tier")
    assert top["CityDensity"] == ("0.800000", "variant ram16")              # RAM decides densities, not the card
    legacy = {w.key.split("/")[1] for w in G.wanted("legacy", "core", None, SEL, GTX1070)}
    assert "ShadowQuality" not in legacy                                     # tiers are Enhanced's scales


def test_plan_starts_from_the_values_now_and_skips_known_crashes():
    current = {w.key: str(w.value) for w in G.wanted("enhanced", "owner-pick", "ram16", SEL, GTX1070)}
    steps = {k.split("/")[1]: ups for k, _now, ups, _c in T.plan(current)}
    assert steps["TextureQuality"] == [] and steps["Shadow_LongShadows"] == ["true"]
    assert steps["MaxLodScale"] == ["0.250000", "0.500000", "0.750000", "1.000000"]
    assert steps["CityDensity"] == ["0.900000", "1.000000"]
    rules = G.load_rules()
    rules["tune"]["knownCrash"] = {"graphics/MaxLodScale/@value": ["0.750000", "1.000000"]}
    steps = {k.split("/")[1]: ups for k, _now, ups, _c in T.plan(current, rules)}
    assert steps["MaxLodScale"] == ["0.250000", "0.500000"]


@dataclass
class _Report:
    status: str
    memory: dict = field(default_factory=dict)

    @property
    def ok(self):
        return self.status == "passed"


class _FakeSession:
    def __init__(self, state):
        self.state = state
        self.writes = 0

    def pc_specs(self):
        return GTX1070

    def game_settings(self):
        return G.wanted("enhanced", "owner-pick", "ram16", SEL, GTX1070, tuned=T.load_tuned(self.state))

    def apply_game_settings(self, ui):
        self.writes += 1
        return []


def _fake_test(session):
    v = {w.key.split("/")[1]: str(w.value) for w in session.game_settings()}
    lod = float(v["MaxLodScale"])
    vram = 4400 + 4000 * lod                       # 0.25 -> 5.4 GB, 0.5 -> 6.4 GB, 0.75 -> 7.4 GB (over 90% of 8)
    free = 2500 - (1300 if v["VehicleVarietyMultiplier"] == "1.000000" else 0)
    status = "crashed" if v["CityDensity"] == "1.000000" else "passed"
    return _Report(status, {"peak": {"gpu_used_mb": vram, "sys_free_mb": free}})


def test_tune_keeps_what_fits_and_backs_off_the_rest(tmp_path):
    s = _FakeSession(tmp_path)
    runs = T.tune(s, _fake_test)
    kept = {r.key.split("/")[1]: r.value for r in runs if r.kept}
    final = T.load_tuned(tmp_path)
    assert final["graphics/MaxLodScale/@value"] == "0.500000"                # 0.75 went over the budget
    assert final["graphics/Shadow_LongShadows/@value"] == "true" and kept["Shadow_LongShadows"] == "true"
    assert final["graphics/VehicleVarietyMultiplier/@value"] == "0.900000"   # 1.0 left too little free RAM
    assert final["graphics/CityDensity/@value"] == "0.900000"                # 1.0 crashed
    over = next(r for r in runs if r.key.endswith("MaxLodScale/@value") and r.value == "0.750000")
    assert not over.kept and "over 90%" in over.why and over.vram_total_mb == 8192
    crash = next(r for r in runs if r.key.endswith("CityDensity/@value") and r.value == "1.000000")
    assert crash.status == "crashed+crashed" and not crash.kept               # RAM steps run twice
    got = {w.key.split("/")[1]: (w.value, w.source) for w in s.game_settings()}
    assert got["MaxLodScale"] == ("0.500000", "tuned on this PC (leonida settings tune)")
    assert len(T.load_tuned(tmp_path)) == len(final) and s.writes > len(runs)
    again = T.tune(s, _fake_test)                                              # starts from the kept values
    assert all(r.value not in ("0.250000", "0.500000") for r in again if r.key.endswith("MaxLodScale/@value"))


GPU_ORDER = ["AnisotropicFiltering", "Shadow_SoftShadows", "TextureQuality", "ShaderQuality", "Shadow_LongShadows",
             "ShadowQuality", "ReflectionQuality", "SSAOType", "Tessellation", "WaterQuality", "ParticleQuality",
             "PostFX", "GrassQuality"]


def test_graphics_steps_first_by_look_per_video_memory():
    steps = G.load_rules()["tune"]["steps"]
    names = [s["key"].split("/")[1] for s in steps]
    assert names[:len(GPU_ORDER)] == GPU_ORDER and {s["cost"] for s in steps[:len(GPU_ORDER)]} <= {"gpu", "vram"}
    assert all(s["cost"] == "ram" for s in steps[len(GPU_ORDER):])
    # the owner's 8 GB card is at the game's top value for every graphics key already: only long shadows is left
    top = {w.key: str(w.value) for w in G.wanted("enhanced", "owner-pick", "ram16", SEL, GTX1070)}
    ups = {k.split("/")[1]: u for k, _n, u, c in T.plan(top) if c != "ram"}
    assert {k for k, u in ups.items() if u} == {"Shadow_LongShadows"}
    # a 4 GB card starts lower: every graphics key has room, up to the game's maximum
    gtx1650 = G.PC(16, 4.0, ("NVIDIA GeForce GTX 1650",))
    mid = {w.key: str(w.value) for w in G.wanted("enhanced", "core", None, set(), gtx1650)}
    ups = {k.split("/")[1]: u for k, _n, u, c in T.plan(mid) if c != "ram"}
    assert ups["AnisotropicFiltering"] == ["16"] and ups["TextureQuality"] == ["2"] and ups["ShaderQuality"] == ["1", "2"]


def test_a_graphics_step_that_spills_into_ram_is_undone(tmp_path, monkeypatch):
    rules = G.load_rules()
    rules["tune"]["steps"] = [{"key": "graphics/Shadow_LongShadows/@value", "values": ["false", "true"], "cost": "gpu"},
                              {"key": "graphics/ShadowQuality/@value", "values": ["0", "1", "2", "3"], "cost": "vram"}]
    monkeypatch.setattr(G, "load_rules", lambda: rules)
    pc = G.PC(16, 4.0, ("NVIDIA GeForce GTX 1650",))
    s = _FakeSession(tmp_path)
    s.pc_specs = lambda: pc
    s.game_settings = lambda: G.wanted("enhanced", "core", None, set(), pc, tuned=T.load_tuned(tmp_path))

    def test(session):  # other apps leave 1.2 GB free (under the floor); Shadow 3 spills another 0.8 GB
        v = {w.key.split("/")[1]: str(w.value) for w in session.game_settings()}
        return _Report("passed", {"peak": {"gpu_used_mb": 3000, "sys_free_mb": 400 if v["ShadowQuality"] == "3"
                                           else 1200}})

    runs = T.tune(s, test)
    got = {(r.key.split("/")[1], r.value): r for r in runs}
    assert got[("Shadow_LongShadows", "true")].kept                          # low RAM from open apps: not its fault
    assert got[("ShadowQuality", "2")].kept
    spill = got[("ShadowQuality", "3")]
    assert not spill.kept and "spills out of video memory" in spill.why
    assert T.load_tuned(tmp_path)["graphics/ShadowQuality/@value"] == "2"


def test_cli_tune_dry_run(tmp_path, game, downloads, monkeypatch, capsys):
    monkeypatch.setenv("LEONIDA_STATE_DIR", str(tmp_path / "st"))
    monkeypatch.setattr(Session, "pc_specs", lambda self: GTX1070)
    monkeypatch.setattr(Session, "game_settings", lambda self: G.wanted("enhanced", "owner-pick", "ram16", SEL,
                                                                          GTX1070))
    assert cli.main(["--game-dir", str(game), "--download-dir", str(downloads), "settings", "tune", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "MaxLodScale/@value: 0.000000 -> 0.250000" in out and "TextureQuality" not in out
