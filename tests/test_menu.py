"""LeonidaMenu, the in-game menu: its zip, the manifest entry, the install round trip, the bridge both ways (Python
and the menu's own C# JSON code), the deep play test's self-test, and C# 5 compiles. Never the real game."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from conftest import AutoUI

from leonida import menu as M
from leonida import menubridge as B
from leonida import settings as S
from leonida.manifest import load_manifest
from leonida.session import Session

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------------------------------------ the zip
def test_zip_is_made_locally_and_stable(tmp_path):
    a = M.make_zip(tmp_path / "a")
    b = M.make_zip(tmp_path / "b")
    assert a.name == M.zip_name() and a.read_bytes() == b.read_bytes()        # same SHA-256 on every PC
    with zipfile.ZipFile(a) as z:
        assert z.namelist() == [M.SCRIPT_NAME, M.INI_NAME]
        script = z.read(M.SCRIPT_NAME).decode("utf-8")
        ini = z.read(M.INI_NAME).decode("utf-8")
    assert f'const string Version = "{M.__version__}";' in script and "/*VERSION*/" not in script
    assert "StateDir={state}" in ini and "Open=F5" in ini and "\r\n" in ini


def test_downloader_makes_it_without_network(tmp_path, monkeypatch):
    from leonida import downloader

    monkeypatch.setattr(downloader, "_open", lambda *a, **k: pytest.fail("no network for Leonida's own files"))
    plan = downloader.plan_for(load_manifest().mods["leonidamenu"])
    assert plan.mode == "auto" and downloader.download(plan, tmp_path).name == M.zip_name()


# ---------------------------------------------------------------------------------------------- the manifest
def test_in_every_pack_with_a_free_key():
    from leonida.checks import hotkey_map

    m = load_manifest()
    mod = m.mods["leonidamenu"]
    assert mod.tier == "core" and mod.method == "copy" and mod.download == {"type": "leonida", "package": "menu"}
    for pid in m.packs:
        assert "leonidamenu" in {x.id for x in m.resolve_pack(pid)}, pid
    owner = m.resolve_pack("owner-pick")
    keys = hotkey_map(m, owner)
    assert keys["F5"] == [("leonidamenu", "Open the Leonida menu")]           # Food Delivery's reload moved off F5
    assert ("fooddelivery", "Reload its settings") in keys["NUMPAD9"]
    rules = mod.settings[0]["keys"]
    assert rules["Leonida/StateDir"]["value"] == "{state}" and "F12" in rules["Keys/Open"]["choices"]


def test_choices_are_validated(tmp_path):
    from leonida.manifest import ManifestError, _check_settings

    good = [{"file": "scripts/x.ini", "keys": {"K": {"value": "A", "choices": ["A", "B"]}}}]
    assert _check_settings(good, "t")
    with pytest.raises(ManifestError, match="choices"):
        _check_settings([{"file": "scripts/x.ini", "keys": {"K": {"value": "A", "choices": []}}}], "t")


# ------------------------------------------------------------------------------------- install + bridge
def menu_session(tmp_path, game) -> Session:
    """A session on a fake game with Script Hook V .NET's ini and the menu really installed (logged step)."""
    (game / "ScriptHookVDotNet.ini").write_text("ReloadKeyBinding=Insert\nConsoleKeyBinding=F4\n", encoding="utf-8")
    s = Session(tmp_path / "st", game_dir=str(game), game_build="1.0.1013.20")
    s.choose_pack("owner-pick")
    step = s.log.new_step("shvdne", "copy")
    step.status, step.finished = "done", step.started
    s.log.save()
    archive = M.make_zip(tmp_path / "dl")
    s.installer(AutoUI()).install(s.manifest.mods["leonidamenu"], archive)
    return s


def test_install_writes_the_state_folder_and_rolls_back(tmp_path, game):
    from leonida.snapshot import diff, take_snapshot

    (game / "ScriptHookVDotNet.ini").write_text("ReloadKeyBinding=Insert\nConsoleKeyBinding=F4\n", encoding="utf-8")
    before = take_snapshot(game)
    s = menu_session(tmp_path, game)
    ini = (game / "scripts" / M.INI_NAME).read_text(encoding="utf-8")
    assert f"StateDir={s.state}" in ini and "Open=F5" in ini                 # the locked {state} filled in
    assert (game / "scripts" / M.SCRIPT_NAME).is_file() and "leonidamenu" in s.log.installed_mods()
    warnings, residual = s.installer(AutoUI()).uninstall()
    assert not warnings and residual.empty and diff(before, take_snapshot(game)).empty


def requests(s: Session, *reqs: dict) -> None:
    d = B.bridge_dir(s.state)
    d.mkdir(parents=True, exist_ok=True)
    (d / B.REQUESTS).write_text(json.dumps({"schema": 1, "requests": list(reqs)}), encoding="utf-8")


def answers(s: Session) -> dict[str, dict]:
    model = json.loads((B.bridge_dir(s.state) / B.MODEL).read_text(encoding="utf-8"))
    return {a["id"]: a for a in model["applied"]}


def test_model_has_every_page(tmp_path, game):
    s = menu_session(tmp_path, game)
    m = B.build_model(s)
    assert m["schema"] == B.SCHEMA and m["reload_key"] == "Insert" and m["heartbeat"] > 0
    assert m["status"]["pack"] and m["status"]["build"] == "1.0.1013.20"
    menu = next(x for x in m["mods"] if x["id"] == "leonidamenu")
    assert menu["on"] and not menu["can_toggle"]                              # the menu doesn't switch itself off
    open_key = next(x for x in menu["settings"] if x["key"] == "Keys/Open")
    assert open_key["value"] == "F5" and "F12" in open_key["choices"] and open_key["live"]
    state_dir = next(x for x in menu["settings"] if x["key"] == "Leonida/StateDir")
    assert state_dir["value"] == str(s.state) and state_dir["choices"] is None
    assert any(k["key"] == "F5" and not k["clash"] for k in m["keys"])
    assert {p["id"] for p in m["packs"]["list"]} >= {"owner-pick", "core"}
    assert "values" in m["game"] and isinstance(m["game"]["note"], str)


def test_requests_both_ways(tmp_path, game, monkeypatch):
    s = menu_session(tmp_path, game)
    calls = []
    monkeypatch.setattr(s, "disable_mod", lambda mod, ui: calls.append(("off", mod)) or (["rolled back"], []))
    monkeypatch.setattr(s, "choose_pack", lambda *a: calls.append(("pack", *a)))
    monkeypatch.setattr("leonida.diagnostics.build", lambda session: tmp_path / "Leonida-report-1.zip")
    requests(s,
             {"id": "1", "kind": "ping"},
             {"id": "2", "kind": "setting", "mod": "leonidamenu", "file": "scripts/LeonidaMenu.ini",
              "key": "Keys/Open", "value": "F12"},
             {"id": "3", "kind": "setting", "mod": "leonidamenu", "file": "scripts/LeonidaMenu.ini",
              "key": "Keys/Open", "value": "F1"},
             {"id": "4", "kind": "setting", "mod": "shvdne", "file": "ScriptHookVDotNet.ini",
              "key": "ConsoleKeyBinding", "value": "F2"},
             {"id": "5", "kind": "mod", "mod": "shvdne", "on": False},
             {"id": "6", "kind": "report"},
             {"id": "7", "kind": "open_leonida"},
             {"id": "8", "kind": "format_c"},
             {"id": "9", "kind": "pack", "pack": "core"})
    bridge = B.Bridge(s)
    got = {a.id: a for a in bridge.tick(game_running=True)}
    assert got["1"].status == B.APPLIED
    assert got["2"].status == B.APPLIED and "Reload scripts" in got["2"].message   # a script's ini: live
    assert "Open=F12" in (game / "scripts" / M.INI_NAME).read_text(encoding="utf-8")
    assert S.chosen(s.state)["leonidamenu|scripts/LeonidaMenu.ini|Keys/Open"] == "F12"
    assert got["3"].status == B.REFUSED and "can be F5" in got["3"].message       # not one of its choices
    assert got["4"].status == B.REFUSED and "locked" in got["4"].message          # no choices: unlock instead
    assert got["5"].status == got["7"].status == got["9"].status == B.PENDING     # wait for the game to close
    assert got["6"].status == B.APPLIED and "Leonida-report-1.zip" in got["6"].message
    assert got["8"].status == B.REFUSED and calls == []
    assert set(answers(s)) == set("123456789")                                    # the menu sees every answer
    assert bridge.tick(game_running=True) == []                                   # nothing applied twice
    later = {a.id: a for a in bridge.tick(game_running=False)}                    # the game closed
    assert later["5"].status == later["7"].status == later["9"].status == B.APPLIED
    assert ("off", "shvdne") in calls and ("pack", "core") in calls
    assert B.want_window(s.state) and not B.want_window(s.state)                  # once
    assert len(B.read_requests(s.state)) == 9 and B.Bridge(s).tick(False) == []   # a new launcher: the same record


def test_unlock_and_lock_again(tmp_path, game):
    s = menu_session(tmp_path, game)
    requests(s, {"id": "u1", "kind": "unlock", "mod": "leonidamenu", "file": "scripts/LeonidaMenu.ini",
                 "key": "Keys/Open", "on": True})
    assert B.Bridge(s).tick(True)[0].status == B.APPLIED
    assert "leonidamenu|scripts/LeonidaMenu.ini|Keys/Open" in S.unlocked(s.state)
    ini = game / "scripts" / M.INI_NAME
    ini.write_text(ini.read_text(encoding="utf-8").replace("Open=F5", "Open=F7"), encoding="utf-8")
    requests(s, {"id": "u2", "kind": "unlock", "mod": "leonidamenu", "file": "scripts/LeonidaMenu.ini",
                 "key": "Keys/Open", "on": False})
    assert B.Bridge(s).tick(True)[0].status == B.APPLIED
    assert "Open=F5" in ini.read_text(encoding="utf-8")                          # the locked value is back


def test_poll_heartbeat_and_game_closing(tmp_path, game, monkeypatch):
    s = menu_session(tmp_path, game)
    t = [1000.0]
    bridge = B.Bridge(s, now=lambda: t[0])
    ticks = []
    real_tick = bridge.tick
    monkeypatch.setattr(bridge, "tick", lambda running: ticks.append(running) or real_tick(running))
    bridge.poll(True)
    assert ticks == []                                                    # no requests: only the model
    t[0] += 5
    mtime = (B.bridge_dir(s.state) / B.MODEL).stat().st_mtime_ns
    bridge.poll(True)
    assert (B.bridge_dir(s.state) / B.MODEL).stat().st_mtime_ns == mtime  # not yet: heartbeat every 15 s
    requests(s, {"id": "m1", "kind": "mod", "mod": "shvdne", "on": False})
    monkeypatch.setattr(s, "disable_mod", lambda mod, ui: (["off"], []))
    bridge.poll(True)
    assert ticks == [True] and bridge.done["m1"]["status"] == B.PENDING
    bridge.poll(False)                                                     # the game closed: applied now
    assert ticks == [True, False] and bridge.done["m1"]["status"] == B.APPLIED


def test_judge_selftest():
    assert B.judge_selftest(None)[0][0] == "failed"
    good = {"menu": "1.0.0", "model": True, "pages": dict.fromkeys(B.EXPECTED_PAGES, 3), "ping_answer": "applied: ok",
            "errors": [], "key": "F5", "phone": "call \"Leonida\""}
    assert [x[0] for x in B.judge_selftest(good)] == ["ok", "ok", "ok", "info"]
    bad = dict(good, pages={"Status": 1}, ping_answer="", errors=["draw Keys: boom"], model=False)
    statuses = [x[0] for x in B.judge_selftest(bad)]
    assert statuses.count("failed") == 4


# ------------------------------------------------------------------------------------- deep play test
def test_deep_playtest_runs_the_menu_selftest(tmp_path, game, monkeypatch):
    from test_playtest import FakeGame, run

    from leonida import playtest as P
    from leonida import probe as PR

    s = menu_session(tmp_path, game)
    (game / "PlayGTAV.exe").write_bytes(b"MZ")
    for mid in ("scripthookv", "straighttostory"):
        st = s.log.new_step(mid, "copy")
        st.status, st.finished = "done", st.started
    s.log.save()
    monkeypatch.setattr(PR, "make_plan", lambda session: PR.Plan(packs={}, car="sultan"))
    monkeypatch.setattr(PR, "place", lambda session, plan: game / "scripts" / PR.PROBE_FILE)
    monkeypatch.setattr(PR, "read_log", lambda session: "START\nDONE ok\n")
    d = B.bridge_dir(s.state)

    def menu_pings(fake):     # the menu, in game: a request to Leonida
        assert (d / B.SELFTEST_FLAG).is_file()
        requests(s, {"id": "ping-1", "kind": "ping"})

    def menu_reports(fake):   # ... then its report, with Leonida's answer read back from the model
        ans = answers(s).get("ping-1", {})
        (d / B.SELFTEST_REPORT).write_text(json.dumps({
            "menu": M.__version__, "model": True, "pages": dict.fromkeys(B.EXPECTED_PAGES, 2), "errors": [],
            "ping_answer": f"{ans.get('status')}: {ans.get('message')}", "key": "F5", "phone": "no iFruitAddon2"}))

    shv = "SCRIPT HOOK (build x, v1.0.3889.0)\nsuccess, game version is 1.0.1013.20"
    story = "[00:00:20] Initializing\n[00:01:10] Loading scripts from D:\\scripts"
    fake = FakeGame(game, [(3, "game"), (12, lambda f: (game / "ScriptHookV.log").write_text(shv)),
                           (25, lambda f: (game / "ScriptHookVDotNet.log").write_text(story)),
                           (70, menu_pings), (90, menu_reports)])
    rep = run(s, fake, deep=True, probe_timeout=20)
    menu = [r for r in rep.results if r.mod == "leonidamenu" and r.code.startswith("menu-")]
    # (Leonida's log check covers the menu like any script: here the fake log doesn't name it)
    assert any(r.code == "script-not-mentioned" and r.mod == "leonidamenu" for r in rep.results)
    assert [r.code for r in menu] == ["menu-selftest"] * 3 + ["menu-info"], [r.message for r in menu]
    assert all(r.status == "ok" for r in menu), [r.message for r in menu]
    assert any("talk both ways" in r.message for r in menu)
    assert not (d / B.SELFTEST_FLAG).exists()                                    # never left for the next start
    assert any("Asked LeonidaMenu to test itself" in t for t in rep.timeline)
    assert P.MENU_ID == "leonidamenu"


# --------------------------------------------------------------------------------------- C# 5 compiles
def _csc():
    sys.path.insert(0, str(ROOT / "build"))
    from check_probe import compile_cs5, csc_path

    return compile_cs5, csc_path()


@pytest.mark.skipif(sys.platform != "win32", reason=".NET Framework's csc.exe (Windows)")
def test_menu_compiles_with_csharp5_against_the_stub(tmp_path):
    compile_cs5, csc = _csc()
    if csc is None:
        pytest.skip("csc.exe not found")
    src = tmp_path / "LeonidaMenu.3.cs"
    src.write_text(M.script_text(), encoding="utf-8")
    forms = csc.parent / "System.Windows.Forms.dll"
    ok, out = compile_cs5([src, ROOT / "tests" / "menu_api_stub.cs"], [forms], tmp_path / "menu.dll")
    assert ok, out


HARNESS = r"""
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
public static class Harness
{
    public static int Main(string[] args)
    {
        // read the model Python wrote, write a request Python reads (the menu's own JSON code, both ways)
        Dictionary<string, object> model = (Dictionary<string, object>)LeonidaJson.Parse(File.ReadAllText(args[0], Encoding.UTF8));
        List<object> mods = (List<object>)model["mods"];
        Dictionary<string, object> first = (Dictionary<string, object>)mods[0];
        Dictionary<string, object> req = new Dictionary<string, object>();
        req["id"] = "cs-1";
        req["kind"] = "setting";
        req["value"] = "quote \" backslash \\ tab \t ü";
        req["mods_seen"] = (double)mods.Count;
        req["first"] = first["name"];
        req["heartbeat_ok"] = (double)model["heartbeat"] > 0;
        Dictionary<string, object> outer = new Dictionary<string, object>();
        outer["requests"] = new List<object>(new object[] { req });
        File.WriteAllText(args[1], LeonidaJson.Write(outer), new UTF8Encoding(false));
        return 0;
    }
}
"""


@pytest.mark.skipif(sys.platform != "win32", reason=".NET Framework's csc.exe (Windows)")
def test_the_menus_json_code_reads_the_model_and_writes_requests(tmp_path, game):
    compile_cs5, csc = _csc()
    if csc is None:
        pytest.skip("csc.exe not found")
    s = menu_session(tmp_path, game)
    model = B.Bridge(s).write_model()
    harness = tmp_path / "harness.cs"
    harness.write_text(HARNESS, encoding="utf-8")
    src = tmp_path / "LeonidaMenu.3.cs"
    src.write_text(M.script_text(), encoding="utf-8")
    exe = tmp_path / "harness.exe"
    forms = csc.parent / "System.Windows.Forms.dll"
    args = [str(csc), "-nologo", "-langversion:5", "-target:exe", "-warn:0", f"-out:{exe}", f"-reference:{forms}",
            str(src), str(ROOT / "tests" / "menu_api_stub.cs"), str(harness)]
    p = subprocess.run(args, capture_output=True, text=True, errors="replace")
    assert p.returncode == 0, p.stdout + p.stderr
    out = B.bridge_dir(s.state) / B.REQUESTS
    r = subprocess.run([str(exe), str(model), str(out)], capture_output=True, text=True, timeout=60,
                       env={**os.environ})
    assert r.returncode == 0, r.stdout + r.stderr
    req = B.read_requests(s.state)[0]
    assert req["id"] == "cs-1" and req["value"] == "quote \" backslash \\ tab \t ü" and req["heartbeat_ok"] is True
    assert req["mods_seen"] == len(json.loads(model.read_text(encoding="utf-8"))["mods"]) and req["first"]
    assert B.Bridge(s).tick(True)[0].status == B.REFUSED            # read by Python: no mod/key given -> refused


LAYOUT_HARNESS = r"""
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
public static class LayoutHarness
{
    static List<string> errors = new List<string>();
    static void Check(bool ok, string what) { if (!ok) errors.Add(what); }

    public static int Main(string[] args)
    {
        Func<string, float> w = delegate(string s) { return LeonidaLayout.Estimate(s, 0.3f); };
        float max = 0.34f - 2 * 0.006f;   // the panel's text width (PanelW - 2 * Pad)
        foreach (string text in File.ReadAllLines(args[0], Encoding.UTF8))
        {
            List<string> lines = LeonidaLayout.Wrap(text, max, w);
            foreach (string line in lines) Check(w(line) <= max, "too wide: " + line);
            string words = string.Join(" ", text.Split(new char[] { ' ' }, StringSplitOptions.RemoveEmptyEntries));
            Check(string.Join(" ", lines.ToArray()) == words, "words lost or cut: " + text);
            Check(lines.Count <= 1 || w(lines[0] + " " + lines[1].Split(' ')[0]) > max, "wrapped too early: " + lines[0]);
        }
        string l, r;
        bool cut = LeonidaLayout.FitPair("Script Hook V", "on", max, 0.012f, w, out l, out r);
        Check(!cut && l == "Script Hook V" && r == "on", "short pair changed");
        string longText = "Food Delivery Job (Uber Eats, DoorDash driver): open the delivery app and take an order, "
            + "then drive it to the customer before the timer runs out";
        Check(LeonidaLayout.FitPair("DELETE", longText, max, 0.012f, w, out l, out r), "long pair not reported as shortened");
        Check(l == "DELETE" && r.EndsWith("...") && w(l) + 0.012f + w(r) <= max, "key name kept, description fitted: " + r);
        Check(LeonidaLayout.Fit("short", max, w) == "short", "Fit changed a short label");
        List<string> huge = LeonidaLayout.Wrap(new string('W', 400), max, w);
        Check(huge.Count > 1 && string.Join("", huge.ToArray()) == new string('W', 400), "a giant word is broken, not lost");
        foreach (string e in errors) Console.WriteLine(e);
        Console.WriteLine(errors.Count == 0 ? "OK" : "FAILED");
        return errors.Count == 0 ? 0 : 1;
    }
}
"""


@pytest.mark.skipif(sys.platform != "win32", reason=".NET Framework's csc.exe (Windows)")
def test_menu_wraps_text_to_the_panel_width_without_cutting_it(tmp_path, game):
    """In game, notes were wrapped at 60 characters then cut at 46 ("A switch happens after you quit the game; L…").
    Now they wrap by width on screen: every line fits the panel and no word is lost."""
    compile_cs5, csc = _csc()
    if csc is None:
        pytest.skip("csc.exe not found")
    s = menu_session(tmp_path, game)
    model = json.loads(B.Bridge(s).write_model().read_text(encoding="utf-8"))
    texts = [model["packs"]["note"], model["game"]["note"]]
    texts += [m.get(k, "") for m in model["mods"] for k in ("what", "help") if m.get(k)]
    texts.append("A switch happens after you quit the game; Leonida's Manage page then adds or removes the mods "
                 "that differ, one logged step at a time (undoable).")
    src_texts = tmp_path / "texts.txt"
    src_texts.write_text("\n".join(t.replace("\n", " ") for t in texts), encoding="utf-8")
    harness = tmp_path / "layout.cs"
    harness.write_text(LAYOUT_HARNESS, encoding="utf-8")
    src = tmp_path / "LeonidaMenu.3.cs"
    src.write_text(M.script_text(), encoding="utf-8")
    exe = tmp_path / "layout.exe"
    forms = csc.parent / "System.Windows.Forms.dll"
    args = [str(csc), "-nologo", "-langversion:5", "-target:exe", "-warn:0", f"-out:{exe}", f"-reference:{forms}",
            str(src), str(ROOT / "tests" / "menu_api_stub.cs"), str(harness)]
    p = subprocess.run(args, capture_output=True, text=True, errors="replace")
    assert p.returncode == 0, p.stdout + p.stderr
    r = subprocess.run([str(exe), str(src_texts)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip().endswith("OK"), r.stdout + r.stderr


def test_menu_title_footer_and_no_character_cuts():
    text = M.script_text()
    assert 'stack.Count == 1 ? "LEONIDA V" : "LEONIDA V  "' in text          # the main page: the brand once
    assert "Open Leonida to apply changes (or they apply next time it starts)" in text
    assert "changes wait for it" not in text
    assert "Cut(" not in text and ", 60)" not in text                      # no character-count cuts or wraps
    assert "END_TEXT_COMMAND_GET_SCREEN_WIDTH_OF_DISPLAY_TEXT" in text        # measured by the game
