"""Zero-touch in game (plan F8, leonida/ingame.py + LeonidaMenu.cs): the menu's setup list and checks in its model,
its "setup" reports over the bridge, the deep play test's per-mod "on and checked in game", and the menu's C# rules
for it. Never the real game."""

from __future__ import annotations

import json
import re

from test_menu import answers, menu_session, requests

from leonida import ingame as G
from leonida import menu as M
from leonida import menubridge as B
from leonida import zerotouch as Z
from leonida.verify import FAILED, OK


def _installed(s, *mods):
    for mid in mods:
        st = s.log.new_step(mid, "copy")
        st.status, st.finished = "done", st.started
    s.log.save()


# ------------------------------------------------------------------------------------------- the model
def test_model_lists_each_installed_mods_setup_and_checks(tmp_path, game):
    s = menu_session(tmp_path, game)
    _installed(s, "enableallinteriors", "hud-geckomacabre")
    m = B.build_model(s)
    setup = {x["mod"]: x for x in m["setup"]}
    assert set(setup) >= {"enableallinteriors", "hud-geckomacabre"}
    eai = setup["enableallinteriors"]
    assert eai["actions"] == Z.in_game_setup("enableallinteriors") and eai["stamp"] == G.stamp(s, "enableallinteriors")
    assert eai["actions"][0]["action"] == "reload-scripts" and eai["actions"][0]["when"] == "verify-fails"
    checks = {x["mod"]: x["verify"] for x in m["checks"]}
    assert {"kind": "ipl", "in": "game", "name": "vw_casino_main"} in checks["enableallinteriors"]
    assert any(c["kind"] == "dlc" and c["name"] == "vihud" for c in checks["hud-geckomacabre"])
    for verify in checks.values():   # only what the menu can check itself
        assert all(c["kind"] in G.MENU_READABLE for c in verify)
        assert all(c["name"].startswith(G.NATIVE_PREFIXES) for c in verify if c["kind"] == "native")
    assert "mapfixes" not in setup and "mapfixes" not in checks                  # not installed: not listed


def test_stamp_changes_on_reinstall_and_disabled_mods_drop_out(tmp_path, game):
    s = menu_session(tmp_path, game)
    _installed(s, "enableallinteriors")
    first = G.stamp(s, "enableallinteriors")
    _installed(s, "enableallinteriors")                                          # updated: a new step
    assert G.stamp(s, "enableallinteriors") != first and G.stamp(s, "nosuchmod") == ""
    s.config.disabled = ["enableallinteriors"]
    assert "enableallinteriors" not in {x["mod"] for x in G.model_setup(s)}


# ------------------------------------------------------------------------------------------- the bridge
def test_setup_reports_are_recorded(tmp_path, game):
    s = menu_session(tmp_path, game)
    _installed(s, "enableallinteriors")
    stamp = G.stamp(s, "enableallinteriors")
    requests(s, {"id": "s-1", "kind": "setup", "mod": "enableallinteriors", "stamp": stamp,
                 "results": [{"action": "reload-scripts", "ok": True, "message": "pressed Insert"}]},
             {"id": "s-2", "kind": "setup", "mod": "hud-geckomacabre", "stamp": "x",
              "results": [{"action": "check", "ok": False, "message": "not ok: GET_CURRENT_LANGUAGE = 2"}]})
    got = {a.id: a for a in B.Bridge(s).tick(True)}                              # at once, even while playing
    assert got["s-1"].status == B.APPLIED and "1/1 ok" in got["s-1"].message
    assert got["s-2"].status == B.APPLIED and "0/1 ok" in got["s-2"].message and "LANGUAGE" in got["s-2"].message
    rec = G.setup_results(s.state)
    assert rec["enableallinteriors"]["stamp"] == stamp and rec["enableallinteriors"]["results"][0]["ok"] is True
    assert answers(s)["s-1"]["status"] == B.APPLIED                              # the menu reads the answer back
    assert not B.Bridge(s).tick(True)                                            # never twice


# ------------------------------------------------------------------------------------------- the play test
def _report(**ingame):
    return {"ingame": ingame}


def test_judge_marks_each_mod_on_and_checked(tmp_path, game, monkeypatch):
    s = menu_session(tmp_path, game)
    _installed(s, "enableallinteriors", "hud-geckomacabre")
    monkeypatch.setattr(Z, "check_files", lambda *a, **k: [])
    report = _report(**{
        "hud-geckomacabre": [{"kind": "dlc", "what": "DLC pack vihud present", "ok": True, "detail": ""}],
        "enableallinteriors": [{"kind": "ipl", "what": "IPL vw_casino_main active", "ok": False, "detail": "no"},
                               {"kind": "log", "what": "x.log", "detail": "checked by Leonida"}],
        "notinstalled": [{"kind": "dlc", "what": "x", "ok": True}],
    })
    results, state = G.judge(s, report, since=0, now=1000.0)
    codes = {(r.mod, r.code, r.status) for r in results}
    assert ("hud-geckomacabre", "ingame-ok", OK) in codes and ("enableallinteriors", "ingame-failed", FAILED) in codes
    assert ("enableallinteriors", "ingame-skipped", "not-seen") in codes
    assert not any(r.mod == "notinstalled" for r in results)
    assert state["hud-geckomacabre"]["ok"] is True and state["enableallinteriors"]["ok"] is False
    assert G.checked(s.state) == state                                            # saved for the launcher
    label, tip = G.checked_line(s.state, "hud-geckomacabre")
    assert label == G.ON and "vihud" in tip
    assert G.checked_line(s.state, "enableallinteriors")[0] == G.NOT_CONFIRMED
    assert G.checked_line(s.state, "mapfixes") is None


def test_judge_adds_the_files_proofs(tmp_path, game, monkeypatch):
    s = menu_session(tmp_path, game)
    _installed(s, "hud-geckomacabre")
    proofs = [Z.Proof("hud-geckomacabre", {"kind": "file", "in": "files", "path": "x"}, False, "x is missing"),
              Z.Proof("hud-geckomacabre", {"kind": "dlc", "in": "game", "name": "vihud"}, None, "checked in game")]
    monkeypatch.setattr(Z, "check_files", lambda *a, **k: proofs)
    results, state = G.judge(s, _report(**{"hud-geckomacabre": [{"kind": "dlc", "what": "v", "ok": True}]}), 0)
    assert [r.code for r in results if r.mod == "hud-geckomacabre"] == ["ingame-ok", "files-failed"]
    assert state["hud-geckomacabre"]["ok"] is False and "x is missing" in state["hud-geckomacabre"]["failed"][0]


def test_no_report_changes_nothing(tmp_path, game, monkeypatch):
    s = menu_session(tmp_path, game)
    monkeypatch.setattr(Z, "check_files", lambda *a, **k: [])
    assert G.judge(s, None, 0) == ([], {})


def test_deep_playtest_saves_the_in_game_state(tmp_path, game, monkeypatch):
    from test_playtest import FakeGame, run

    from leonida import probe as PR

    s = menu_session(tmp_path, game)
    (game / "PlayGTAV.exe").write_bytes(b"MZ")
    _installed(s, "scripthookv", "straighttostory", "hud-geckomacabre")
    monkeypatch.setattr(PR, "make_plan", lambda session: PR.Plan(packs={}, car="sultan"))
    monkeypatch.setattr(PR, "place", lambda session, plan: game / "scripts" / PR.PROBE_FILE)
    monkeypatch.setattr(PR, "read_log", lambda session: "START\nDONE ok\n")
    monkeypatch.setattr(Z, "check_files", lambda *a, **k: [])
    d = B.bridge_dir(s.state)

    def menu_reports(fake):
        (d / B.SELFTEST_REPORT).write_text(json.dumps({
            "menu": M.__version__, "model": True, "pages": dict.fromkeys(B.EXPECTED_PAGES, 2), "errors": [],
            "ping_answer": "applied: ok", "key": "F5", "phone": "-", "setup": "done",
            "ingame": {"hud-geckomacabre": [{"kind": "dlc", "what": "DLC pack vihud present", "ok": True}]}}))

    shv = "SCRIPT HOOK (build x, v1.0.3889.0)\nsuccess, game version is 1.0.1013.20"
    story = "[00:00:20] Initializing\n[00:01:10] Loading scripts from D:\\scripts"
    fake = FakeGame(game, [(3, "game"), (12, lambda f: (game / "ScriptHookV.log").write_text(shv)),
                           (25, lambda f: (game / "ScriptHookVDotNet.log").write_text(story)), (80, menu_reports)])
    rep = run(s, fake, deep=True, probe_timeout=20)
    assert any(r.code == "ingame-ok" and r.mod == "hud-geckomacabre" for r in rep.results)
    assert G.checked(s.state)["hud-geckomacabre"]["ok"] is True
    assert any("In game: 1 mod(s) on and checked" in t for t in rep.timeline)


def test_an_aborted_probe_gets_time_to_start_again(tmp_path, game, monkeypatch):
    """The menu's reload-scripts restarts every script, the probe too: an ABORTED line isn't the end."""
    from test_playtest import FakeGame, run

    from leonida import probe as PR

    s = menu_session(tmp_path, game)
    (game / "PlayGTAV.exe").write_bytes(b"MZ")
    _installed(s, "scripthookv", "straighttostory")
    monkeypatch.setattr(PR, "make_plan", lambda session: PR.Plan(packs={"vihud": "hud-geckomacabre"}, car=""))
    monkeypatch.setattr(PR, "place", lambda session, plan: game / "scripts" / PR.PROBE_FILE)
    monkeypatch.setattr(Z, "check_files", lambda *a, **k: [])
    shv = "SCRIPT HOOK (build x, v1.0.3889.0)\nsuccess, game version is 1.0.1013.20"
    story = "[00:00:20] Initializing\n[00:01:10] Loading scripts from D:\\scripts"
    fake = FakeGame(game, [(3, "game"), (12, lambda f: (game / "ScriptHookV.log").write_text(shv)),
                           (25, lambda f: (game / "ScriptHookVDotNet.log").write_text(story))])
    calls = {"n": 0}

    def read_log(session):   # aborted by the reload at first, then the new instance's run
        calls["n"] += 1
        return "START\nABORTED stage=1\n" if calls["n"] < 4 else "START\ndlc.vihud=True\nDONE ok\n"

    monkeypatch.setattr(PR, "read_log", read_log)
    rep = run(s, fake, deep=True, probe_timeout=120)
    assert any(r.code == "dlc-loaded" for r in rep.results), [r.message for r in rep.results]


# ------------------------------------------------------------------------------------------- the menu's C#
def test_menu_saves_before_it_reloads_and_only_reads_the_game():
    text = M.script_text()
    tick = text[text.index("void SetupTick()"):text.index("bool StepSetup(")]
    assert tick.index("SaveSetupDone();") < tick.index("ReportSetup();") < tick.index("PressKeys(keys)")
    checks = text[text.index("int Check(Dictionary<string, object> c"):text.index("bool InGameChecksDone()")]
    natives = set(re.findall(r"Hash\.([A-Z_0-9]+)", checks))
    assert natives == {"IS_DLC_PRESENT", "GET_HASH_KEY", "IS_IPL_ACTIVE"}          # read-only natives only
    assert 'name.StartsWith("GET_") || name.StartsWith("IS_") || name.StartsWith("HAS_")' in checks
    assert "File.Write" not in checks and "File.Delete" not in checks
    assert '"Run the in-game setup again"' in text and 'rows.Add(Info("In-game setup", setupState))' in text


def test_every_in_game_setup_uses_what_the_menu_knows():
    """The real data: every action and when value is one the menu handles."""
    from leonida.manifest import load_manifest

    for mid in load_manifest().mods:
        for a in Z.in_game_setup(mid):
            assert a["action"] in ("reload-scripts", "check") and a["when"] in Z.WHENS, (mid, a)
            v = a["verify"]
            assert G._menu_check(v), (mid, v)                                      # the menu can check it
