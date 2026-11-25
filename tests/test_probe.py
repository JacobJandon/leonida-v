"""The in-game probe of `leonida playtest --deep` (leonida/probe), offline: the template, the log, the judgement, the
files it places and removes, and full play tests on a fake game and clock that writes the probe's log the way the
probe does. The C# itself is compiled against the real API by build/check_probe.py (opt-in)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from test_playtest import NORMAL, FakeGame, make_session, never_touch_real_processes, run  # noqa: F401

from leonida import log as L
from leonida import probe as PR
from leonida import rpf as R
from leonida.cli import main
from leonida.verify import FAILED, NOT_SEEN, OK, WARN

FAKE = Path(__file__).resolve().parent / "fake_rpf_helper.py"
HANDLING = """<?xml version="1.0" encoding="UTF-8"?>
<CHandlingDataMgr><HandlingData>
  <Item type="CHandlingData"><handlingName>ADDER</handlingName><fMass value="1800.000000" /></Item>
  <Item type="CHandlingData"><handlingName>SULTAN</handlingName><fMass value="{mass}" />
    <fInitialDriveForce value="{drive}" /><fBrakeForce value="0.800000" /><fTractionCurveMax value="2.450000" /></Item>
</HandlingData></CHandlingDataMgr>"""
DONE_LOG = """START 10:41:00.000 packs=2 car=sultan
TICK n=1 t=0.0 stage=0 ped=True playing=True loading=False fadedIn=True
stage=1 ready
dlc.vihud=True
dlc.mmd_jason_duval_houses={jason}
game_version=1.0.1013.20
stage=2 dlc checked
car_model sultan inCdImage=True vehicle=True
stage=3 model requested
car_spawned=True
stage=4 car spawned
handling.fMass=1500
handling.fInitialDriveForce=0.33
handling.fBrakeForce=0.8
handling.fTractionCurveMax=2.45
stage=9 handling read
DONE ok 10:41:12.500
"""


def fake_rpf(path: Path, members: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name.replace("\\", "/").lower(), data)
    return path


@pytest.fixture
def helper(monkeypatch):
    monkeypatch.setenv(R.HELPER_ENV, str(FAKE))


def installed(session, mod: str, paths: list[str]) -> None:
    step = session.log.new_step(mod, "rpf")
    step.actions = [L.Action(L.ADD, p, "0" * 64) for p in paths]
    step.status, step.finished = "done", step.started
    session.log.save()


def deep_session(tmp_path, game, drivev=True):
    s = make_session(tmp_path, game)
    installed(s, "hud-geckomacabre", ["mods/update/x64/dlcpacks/vihud/dlc.rpf", "scripts/GTA6Hud.dll"])
    installed(s, "jasonhouse", ["mods/update/x64/dlcpacks/mmd_jason_duval_houses/dlc.rpf"])
    fake_rpf(game / "mods/update/x64/dlcpacks/vihud/dlc.rpf",
             {"setup2.xml": "<SSetupData><nameHash>vihud</nameHash></SSetupData>"})
    fake_rpf(game / "mods/update/x64/dlcpacks/mmd_jason_duval_houses/dlc.rpf",
             {"setup2.xml": "﻿<SSetupData>\n <nameHash> mmd_jason_duval_houses </nameHash></SSetupData>"})
    if drivev:
        installed(s, "drivev", ["mods/update/update.rpf"])
        fake_rpf(game / "mods/update/update.rpf",
                 {"common\\data\\handling.meta": HANDLING.format(mass="1500.000000", drive="0.330000")})
        fake_rpf(game / "update/update.rpf",
                 {"common\\data\\handling.meta": HANDLING.format(mass="1400.000000", drive="0.320000")})
    return s


# ------------------------------------------------------------------------------------------- pieces
def test_render_fills_the_template():
    text = PR.render(PR.Plan(packs={"vihud": "hud", 'we"ird': "x"}, car="sultan"))
    assert "/*PACKS*/" not in text and "/*CAR*/" not in text
    assert 'static readonly string[] Packs = { "vihud", "we\\"ird" };' in text
    assert 'const string TestCar = "sultan";' in text
    assert 'const string TestCar = "";' in PR.render(PR.Plan(car="bad car; drop"))
    # it never waits inside a tick (Script Hook V .NET aborts long ticks)
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("//"))
    assert "Model.Request(" not in code and "Wait(" not in code and "Yield(" not in code
    assert "Hash.REQUEST_MODEL" in text and "HAS_MODEL_LOADED" in text and "Aborted += OnAborted" in text
    # handling through Script Hook V .NET's HandlingData: GET_VEHICLE_HANDLING_FLOAT (0x642FC12F) is a FiveM native
    # that single-player GTA V doesn't have (the owner's run stopped ticking right there)
    assert "0x642FC12F" not in code and "car.HandlingData" in code and "h.InitialDriveForce" in code
    assert code.count('W("hb ') >= 8  # a heartbeat after every native call / value read


def test_parse_log_and_diagnose():
    full = PR.parse_log(DONE_LOG.format(jason="False"))
    assert full.started and full.ticks == 1 and full.done.startswith("ok") and full.finished
    assert full.dlc == {"vihud": True, "mmd_jason_duval_houses": False}
    assert full.handling == {"fMass": 1500.0, "fInitialDriveForce": 0.33, "fBrakeForce": 0.8, "fTractionCurveMax": 2.45}
    assert "never started" in PR.diagnose(PR.parse_log(None))
    assert "never ticked" in PR.diagnose(PR.parse_log("START 10:00:00 packs=1 car=sultan\n"))
    waiting = PR.parse_log("START x\nTICK n=1 t=0.0 stage=0 ped=True playing=False loading=True fadedIn=False\n"
                           "TICK n=40 t=9.8 stage=0 ped=True playing=False loading=True fadedIn=False\n")
    assert waiting.ticks == 40 and "waiting for the player" in PR.diagnose(waiting) and "n=40" in PR.diagnose(waiting)
    aborted = PR.parse_log("START x\nTICK n=1 t=0 stage=3\nstage=3 model requested\nABORTED stage=3 ticks=9 10:00\n")
    assert aborted.finished and "stopped from outside" in PR.diagnose(aborted)
    stuck = PR.parse_log("START x\nTICK n=5 t=1 stage=3\nstage=3 model requested\ncar_error=model did not load\n"
                         "handling.fMass=oops\nprobe_error stage=3 X: y\ngate_timeout ped=True\n")
    assert "after stage=3 model requested" in PR.diagnose(stuck) and stuck.car_error == "model did not load"
    assert len(stuck.errors) == 2 and stuck.gate_timeout


def test_the_probes_own_abort_is_not_an_error():
    """The owner's real run: the probe's Abort() after DONE was caught by its catch-all and logged as an error."""
    text = DONE_LOG.format(jason="True") + "probe_error stage=9 ThreadAbortException: Thread was being aborted.\n"
    log = PR.parse_log(text)
    assert log.errors == [] and log.done.startswith("ok")
    plan = PR.Plan(packs={"vihud": "hud"}, car="sultan")
    assert not [r for r in PR.judge(log, plan) if r.code == "probe-error"]
    code = PR.render(plan)
    assert "when (!(ex is System.Threading.ThreadAbortException))" in code
    real = PR.parse_log(DONE_LOG.format(jason="True") + "probe_error stage=4 NullReferenceException: x\n")
    assert len(real.errors) == 1  # other errors still count


def test_handling_values():
    text = HANDLING.format(mass="1500.0", drive="0.33")
    assert PR.handling_values(text, "sultan") == {"fMass": 1500.0, "fInitialDriveForce": 0.33, "fBrakeForce": 0.8,
                                                  "fTractionCurveMax": 2.45}
    assert PR.handling_values(text, "adder") == {"fMass": 1800.0}
    assert PR.handling_values(text, "nope") == {} and PR.handling_values("not xml", "sultan") == {}
    assert PR.handling_values(HANDLING.format(mass="x", drive="1"), "sultan")["fInitialDriveForce"] == 1.0


def test_plan_reads_pack_names_and_handling(tmp_path, game, helper):
    s = deep_session(tmp_path, game)
    plan = PR.make_plan(s)
    assert plan.packs == {"vihud": "hud-geckomacabre", "mmd_jason_duval_houses": "jasonhouse"}
    assert plan.handling_mod == "drivev" and plan.active["fMass"] == 1500.0 and plan.vanilla["fMass"] == 1400.0
    assert plan.notes == []


def test_plan_knows_the_packs_this_build_cant_load(tmp_path, game, helper):
    """Bugstar Fixes' .oiv makes update\\x64\\dlcpacks\\patch2026_01 in mods on 1.0.1013.20 (a newer build's pack):
    not in the game, no dlclist.xml line: IS_DLC_PRESENT false is expected there, not a failure."""
    s = deep_session(tmp_path, game, drivev=False)
    installed(s, "bugstarfixes", ["mods/update/x64/dlcpacks/patch2026_01/dlc.rpf",
                                  "mods/update/x64/dlcpacks/mpheist/dlc.rpf", "mods/update/x64/dlcpacks/newer/dlc.rpf"])
    s.log.steps[-1].notes.append("created empty: mods/update/x64/dlcpacks/newer/dlc.rpf")
    s.log.save()
    for name in ("patch2026_01", "mpheist", "newer"):
        fake_rpf(game / f"mods/update/x64/dlcpacks/{name}/dlc.rpf",
                 {"setup2.xml": f"<SSetupData><nameHash>{name.upper()}</nameHash></SSetupData>"})
    fake_rpf(game / "update/x64/dlcpacks/mpheist/dlc.rpf", {"x": "the game's own"})
    fake_rpf(game / "mods/update/update.rpf", {"common\\data\\dlclist.xml": (
        "<SMandatoryPacksData><Paths><Item>dlcpacks:/mpHeist/</Item><Item>dlcpacks:/vihud/</Item>"
        "<Item>dlcpacks:/mmd_jason_duval_houses/</Item></Paths></SMandatoryPacksData>")})
    plan = PR.make_plan(s)
    assert set(plan.expected_missing) == {"PATCH2026_01", "NEWER"}
    assert "doesn't have it" in plan.expected_missing["NEWER"] and "no dlclist.xml line" in plan.expected_missing[
        "PATCH2026_01"]
    log = PR.parse_log("START x\nTICK n=1\nstage=1 ready\ndlc.PATCH2026_01=False\ndlc.NEWER=True\n"
                       "dlc.MPHEIST=True\ndlc.vihud=True\ndlc.mmd_jason_duval_houses=True\nDONE ok\n")
    res = {r.code: r for r in PR.judge(log, plan) if r.mod == "bugstarfixes" and "PATCH2026_01" in r.message}
    assert res["dlc-not-on-build"].status == NOT_SEEN and "as expected" in res["dlc-not-on-build"].message
    assert not [r for r in PR.judge(log, plan) if r.status == FAILED]


def test_plan_without_helper_or_names(tmp_path, game, monkeypatch):
    monkeypatch.setenv(R.HELPER_ENV, str(tmp_path / "missing.exe"))
    monkeypatch.setattr(R, "__file__", str(tmp_path / "leonida" / "rpf.py"))
    s = deep_session(tmp_path, game, drivev=True)
    plan = PR.make_plan(s)
    assert set(plan.packs) == {"vihud", "mmd_jason_duval_houses"}  # folder names
    assert not plan.active and "isn't built" in plan.notes[0]


def test_plan_falls_back_to_the_folder_name(tmp_path, game, helper):
    s = make_session(tmp_path, game)
    installed(s, "burgershot", ["mods/update/x64/dlcpacks/burgershot/dlc.rpf"])
    fake_rpf(game / "mods/update/x64/dlcpacks/burgershot/dlc.rpf", {"content.xml": "<x/>"})  # no setup2.xml
    installed(s, "drivev", ["mods/update/update.rpf"])
    fake_rpf(game / "mods/update/update.rpf", {"x.meta": "x"})
    plan = PR.make_plan(s)
    assert plan.packs == {"burgershot": "burgershot"} and "no handling for sultan" in plan.notes[0]


def test_judge():
    plan = PR.Plan(packs={"vihud": "hud", "mmd_jason_duval_houses": "jasonhouse", "unchecked": "x"}, car="sultan",
                   active={"fMass": 1500.0, "fInitialDriveForce": 0.33}, vanilla={"fMass": 1400.0,
                                                                                  "fInitialDriveForce": 0.32},
                   handling_mod="drivev")
    res = {(r.mod, r.code): r for r in PR.judge(PR.parse_log(DONE_LOG.format(jason="False")), plan)}
    assert res[("hud", "dlc-loaded")].status == OK
    bad = res[("jasonhouse", "dlc-missing")]
    assert bad.status == FAILED and "dlcpacks:/mmd_jason_duval_houses/" in bad.message
    assert res[("x", "dlc-not-checked")].status == WARN
    assert res[("drivev", "handling-active")].status == OK
    vanilla = DONE_LOG.format(jason="True").replace("fMass=1500", "fMass=1400").replace("=0.33", "=0.32")
    assert [r.code for r in PR.judge(PR.parse_log(vanilla), plan) if r.mod == "drivev"] == ["handling-vanilla"]
    odd = DONE_LOG.format(jason="True").replace("fMass=1500", "fMass=999")
    assert [r.code for r in PR.judge(PR.parse_log(odd), plan) if r.mod == "drivev"] == ["handling-differs"]
    # only fMass / fInitialDriveForce decide (the game may keep the others transformed in memory)
    brakes = DONE_LOG.format(jason="True").replace("fBrakeForce=0.8", "fBrakeForce=0.123")
    assert [r.code for r in PR.judge(PR.parse_log(brakes), plan) if r.mod == "drivev"] == ["handling-active"]
    no_car = "START x\nTICK n=1\nstage=1 ready\ndlc.vihud=True\ncar_error=model not found: sultan\nDONE ok\n"
    nc = [r for r in PR.judge(PR.parse_log(no_car), plan) if r.mod == "drivev"]
    assert nc[0].code == "handling-not-read" and "model not found" in nc[0].message
    empty = PR.judge(PR.parse_log("START x\n"), plan)
    assert [(r.status, r.code) for r in empty] == [(WARN, "probe-incomplete")] and "never ticked" in empty[0].message
    late = PR.judge(PR.parse_log("START x\nTICK n=3\nstage=1 ready\ndlc.vihud=True\nprobe_error stage=1 E: x\n"), plan,
                    finished_in_time=False)
    assert {r.code for r in late} >= {"probe-incomplete", "probe-error"}


def test_place_and_remove(tmp_path, game):
    s = make_session(tmp_path, game)
    assert not (game / "scripts").exists()
    target = PR.place(s, PR.Plan(packs={"vihud": "hud"}, car="sultan"))
    assert target == game / "scripts" / PR.PROBE_FILE and '"vihud"' in target.read_text()
    record = json.loads((s.state / PR.RECORD).read_text())
    assert record == {"files": ["scripts/LeonidaProbe.3.cs", "LeonidaProbe.log"], "made_scripts_dir": True}
    (game / PR.PROBE_LOG).write_text("START x\n")
    assert PR.read_log(s) == "START x\n"
    assert PR.remove(s) == ["scripts/LeonidaProbe.3.cs", "LeonidaProbe.log"]
    assert not (game / "scripts").exists() and not (s.state / PR.RECORD).exists()  # the folder it made is gone too
    assert (s.state / "playtest" / PR.PROBE_LOG).read_text() == "START x\n"     # the log is kept for reading
    assert PR.read_log(s) is None
    # a leftover without a record (an old crash): still removed; a scripts folder that was there stays
    (game / "scripts").mkdir()
    (game / "scripts" / "Other.dll").write_bytes(b"x")
    (game / "scripts" / PR.PROBE_FILE).write_text("old")
    assert PR.remove(s) == ["scripts/LeonidaProbe.3.cs"] and (game / "scripts" / "Other.dll").exists()


def test_run_helper_relative_paths_are_from_the_game(game, helper, monkeypatch, tmp_path):
    fake_rpf(game / "mods/x.rpf", {"a.xml": "<a/>"})
    monkeypatch.chdir(tmp_path)  # the helper's working folder is somewhere else
    res = R.run_helper([__import__("sys").executable, str(FAKE)], game,
                       [{"op": "extract", "rpf": "mods\\x.rpf", "entry": "a.xml", "out": "out\\a.xml"}])
    assert res[0]["op"] == "extract" and (game / "out" / "a.xml").read_text() == "<a/>"


# ------------------------------------------------------------------------------------------- playtest --deep
def probe_writes(text: str):
    def act(fake):
        (fake.game / PR.PROBE_LOG).write_text(text, encoding="utf-8")
    return act


def test_deep_playtest_passes_and_cleans_up(tmp_path, game, helper):
    s = deep_session(tmp_path, game)
    (game / "scripts").mkdir()
    (game / "scripts" / PR.PROBE_FILE).write_text("left by a crash")  # removed before the run, then placed fresh
    placed = []

    def check_placed(fake):
        placed.append((game / "scripts" / PR.PROBE_FILE).read_text())

    fake = FakeGame(game, [*NORMAL, (5, check_placed), (100, probe_writes(DONE_LOG.format(jason="True")))])
    seen = []
    rep = run(s, fake, deep=True, probe_timeout=200, progress=seen.append)
    assert rep.ok, rep.summary()
    assert "mmd_jason_duval_houses" in placed[0] and "left by a crash" not in placed[0]
    codes = {(r.mod, r.code) for r in rep.results}
    assert {("hud-geckomacabre", "dlc-loaded"), ("jasonhouse", "dlc-loaded"), ("drivev", "handling-active")} <= codes
    assert not (game / "scripts" / PR.PROBE_FILE).exists() and not (game / PR.PROBE_LOG).exists()
    assert (s.state / "playtest" / PR.PROBE_LOG).exists() and not (s.state / PR.RECORD).exists()
    assert any("Placed the in-game probe" in m for m in seen) and any("In-game probe finished: ok" in m for m in seen)


def test_deep_playtest_missing_pack_fails(tmp_path, game, helper):
    s = deep_session(tmp_path, game)
    fake = FakeGame(game, [*NORMAL, (100, probe_writes(DONE_LOG.format(jason="False")))])
    rep = run(s, fake, deep=True, probe_timeout=200)
    assert rep.status == "failed" and "mmd_jason_duval_houses is NOT loaded" in rep.message


def test_deep_playtest_probe_that_never_ticks(tmp_path, game, helper):
    s = deep_session(tmp_path, game)
    fake = FakeGame(game, [*NORMAL, (90, probe_writes("START 10:41:00.000 packs=2 car=sultan\n"))])
    seen = []
    rep = run(s, fake, deep=True, probe_timeout=100, progress=seen.append)
    assert rep.status == "passed"  # the logs are fine; the probe's silence is a warning with its reason
    inc = [r for r in rep.results if r.code == "probe-incomplete"]
    assert inc and "never ticked" in inc[0].message
    assert any("Probe still running" in m for m in seen) and any("did not finish" in m for m in seen)
    assert not (game / "scripts" / PR.PROBE_FILE).exists()


def test_deep_playtest_crash_during_the_probe(tmp_path, game, helper):
    s = deep_session(tmp_path, game)
    fake = FakeGame(game, [*NORMAL, (95, probe_writes("START x\nTICK n=1 t=0 stage=0\n")), (110, "exit")])
    rep = run(s, fake, deep=True, probe_timeout=200)
    assert rep.status == "crashed" and "while the in-game probe ran" in rep.message
    assert not (game / "scripts" / PR.PROBE_FILE).exists()


def test_deep_playtest_removes_the_probe_on_ctrl_c(tmp_path, game, helper):
    s = deep_session(tmp_path, game)

    def interrupt(fake):
        assert (game / "scripts" / PR.PROBE_FILE).exists()
        raise KeyboardInterrupt

    fake = FakeGame(game, [*NORMAL, (40, interrupt)])
    with pytest.raises(KeyboardInterrupt):
        run(s, fake, deep=True)
    assert not (game / "scripts" / PR.PROBE_FILE).exists() and not (s.state / PR.RECORD).exists()


def test_deep_playtest_blocked_start_and_no_shvdn(tmp_path, game, helper):
    s = deep_session(tmp_path, game)
    rep = run(s, FakeGame(game, NORMAL, start_error=OSError("nope")), deep=True)
    assert rep.status == "blocked" and not (game / "scripts" / PR.PROBE_FILE).exists()
    s2 = make_session(tmp_path / "two", game, installed=("scripthookv", "straighttostory"))
    rep2 = run(s2, FakeGame(game, [(3, "game"), (12, "shv")]), deep=True, timeout=400)
    assert any("needs Script Hook V .NET" in n for n in rep2.notes)


def test_cli_playtest_deep(tmp_path, game, monkeypatch, capsys):
    from leonida import playtest as P

    calls = []

    def fake_playtest(session, timeout, keep_running, progress, **kw):
        calls.append(kw)
        return P.PlaytestReport(P.PASSED, "fine")

    monkeypatch.setattr(P, "playtest", fake_playtest)
    assert main(["--state-dir", str(tmp_path / "st"), "--game-dir", str(game), "playtest", "--deep",
                 "--probe-timeout", "60"]) == 0
    assert main(["--state-dir", str(tmp_path / "st"), "--game-dir", str(game), "playtest"]) == 0
    assert calls == [{"deep": True, "probe_timeout": 60.0}, {}]
