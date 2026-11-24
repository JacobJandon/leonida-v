"""requireMembers / rejectMembers (Legacy files behind Enhanced names), the listing cache, and gta5-mods' version
picker. Member layouts are the real ones of Map Fixes, Bugstar Fixes and the 24/7 / Up-n-Atom MLOs."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import AutoUI, make_zip

from leonida import members as M
from leonida.cli import main
from leonida.detect import find_7zip
from leonida.installer import Installer, InstallError
from leonida.log import InstallLog
from leonida.manifest import ManifestError, load_manifest
from leonida.pagehints import (
    ModVersion,
    gta5mods_versions,
    parse_pick_result,
    pick_version,
    pick_version_script,
)
from leonida.session import Session


def _mod(mid, order, archive, **extra):
    return {"id": mid, "order": order, "tier": "core", "layer": "Map", "name": extra.pop("name", mid.title()),
            "version": "1", "source": "direct", "page": f"https://www.gta5-mods.com/maps/{mid}",
            "archive": archive, "install": {"method": "guided", "steps": ["do it"]}, **extra}


# rules as mod-sources wrote them in mods.json
MODS = [
    _mod("mapfixes", 1, ["MapFixes*"], name="Map Fixes", requireMembers=["*spmapfixes_gen9/*"],
         rejectMembers=["*spmapfixes/*"], pick={"versionMatch": "(?i)\\benhanced\\b"}),
    _mod("bugstarfixes", 2, ["*Fixes*Improvements*", "BugstarFixes*"], name="Bugstar Fixes",
         requireMembers=["*spfixes_gen9/*"], rejectMembers=["*spfixes/*"], pick={"versionMatch": "(?i)\\benhanced\\b"}),
    _mod("upnatom", 3, ["*Up-n-Atom*"], name="Up-n-Atom MLO", requireMembers=["*vw_upna_g9/*"],
         rejectMembers=["*vw_upna/*"]),
    _mod("elgin247", 4, ["*Elgin*24*7*"], name="Elgin 24/7", requireMembers=["*elg_247shop_g9/*"],
         rejectMembers=["*elg_247shop/*"]),
    _mod("plain", 5, ["Plain*"]),
]

# real layouts
MAPFIXES_ENHANCED = {"Enhanced/SPMapFixes_gen9/dlc.rpf": "e", "Readme.txt": "r"}
MAPFIXES_LEGACY = {"Legacy/SPMapFixes/dlc.rpf": "l", "Readme.txt": "r"}       # served as MapFixes_v21.8.2_NG.rar
BUGSTAR_ENHANCED = {"Enhanced/spfixes_gen9/dlc.rpf": "e"}
BUGSTAR_LEGACY = {"Legacy/spfixes/dlc.rpf": "l"}
UPNA_ENHANCED = {"Up-n-Atom MLO/vw_upna_g9/dlc.rpf": "e"}
UPNA_LEGACY = {"Up-n-Atom MLO/vw_upna/dlc.rpf": "l"}
ELGIN_LEGACY = {"Elgin Ave 24-7/elg_247shop/dlc.rpf": "l"}


def write_manifest(root: Path, mods=None) -> Path:
    mods = mods if mods is not None else MODS
    d = root / "manifest"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "1", "testedGameBuilds": ["1.0.1013.20"],
                                             "mods": mods}))
    (d / "profiles.json").write_text(json.dumps({"default": "all", "profiles": [
        {"id": "all", "name": "All", "include": [m["id"] for m in mods]},
        {"id": "nve", "name": "NVE", "include": [m["id"] for m in mods]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    return d


@pytest.fixture
def man(tmp_path):
    return load_manifest(write_manifest(tmp_path))


def members(layout):
    return list(layout)


# ---------------------------------------------------------------------------------------------- rule check
def test_real_layouts(man):
    mf, bf, up, el = (man.mod(i) for i in ("mapfixes", "bugstarfixes", "upnatom", "elgin247"))
    assert M.member_problem(mf, members(MAPFIXES_ENHANCED)) is None
    assert "Legacy/SPMapFixes/dlc.rpf" in M.member_problem(mf, members(MAPFIXES_LEGACY))
    assert M.member_problem(bf, members(BUGSTAR_ENHANCED)) is None
    assert "spfixes" in M.member_problem(bf, members(BUGSTAR_LEGACY))
    assert M.member_problem(up, members(UPNA_ENHANCED)) is None
    assert M.member_problem(up, members(UPNA_LEGACY)).startswith("it contains Up-n-Atom MLO/vw_upna/dlc.rpf")
    assert "elg_247shop" in M.member_problem(el, members(ELGIN_LEGACY))
    assert M.member_problem(man.mod("plain"), ["anything"]) is None and not M.has_rules(man.mod("plain"))


def test_require_only_and_case(man):
    up = man.mod("upnatom")
    assert M.member_problem(up, ["UP-N-ATOM MLO\\VW_UPNA_G9\\DLC.RPF"]) is None   # case + backslashes
    assert M.member_problem(up, ["readme.txt"]) == "it has no file matching '*vw_upna_g9/*'"
    assert M.wrong_message(up, "x") == "wrong edition/version of Up-n-Atom MLO: x"


# ------------------------------------------------------------------------------------------------- cache
def test_listing_cache(tmp_path, monkeypatch):
    z = make_zip(tmp_path / "dl" / "MapFixes_v21.8.2_NG.zip", MAPFIXES_LEGACY)
    calls = []
    real = M.list_members
    monkeypatch.setattr(M, "list_members", lambda p, sz=None: calls.append(p) or real(p, sz))
    cache = M.ListingCache(tmp_path / "state")
    assert sorted(cache.members(z)) == sorted(MAPFIXES_LEGACY) and len(calls) == 1
    assert cache.members(z) and len(calls) == 1                         # cached in memory
    assert M.ListingCache(tmp_path / "state").members(z) and len(calls) == 1  # and on disk
    st = z.stat()
    os.utime(z, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))            # the file changed
    assert M.ListingCache(tmp_path / "state").members(z) and len(calls) == 2
    data = json.loads((tmp_path / "state" / M.CACHE_NAME).read_text())
    assert len(data) == 1                                               # the stale listing was dropped
    (tmp_path / "state" / M.CACHE_NAME).write_text("{broken")
    assert M.ListingCache(tmp_path / "state").members(z) and len(calls) == 3
    assert M.ListingCache(None).members(z)                              # no state folder: no cache, still works


def test_cache_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "MAX_ENTRIES", 3)
    cache = M.ListingCache(tmp_path / "state")
    for i in range(5):
        cache.members(make_zip(tmp_path / f"a{i}.zip", {f"f{i}.txt": "x"}))
    assert len(json.loads((tmp_path / "state" / M.CACHE_NAME).read_text())) == 3


def test_check_file(tmp_path, man):
    cache = M.ListingCache(tmp_path / "state")
    up = man.mod("upnatom")
    exe = tmp_path / "Up-n-Atom.exe"
    exe.write_bytes(b"MZ")
    assert "is not an archive" in M.check_file(up, exe, cache)
    broken = tmp_path / "Up-n-Atom.zip"
    broken.write_bytes(b"not a zip")
    assert "can't read what's inside" in M.check_file(up, broken, cache)
    assert M.check_file(man.mod("plain"), broken, cache) is None       # no rules: not even opened


@pytest.mark.skipif(find_7zip() is None, reason="7-Zip not installed")
def test_7z_archives_are_listed_with_7zip(tmp_path, man):
    src = tmp_path / "src"
    for name, data in ELGIN_LEGACY.items():
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text(data)
    archive = tmp_path / "dl" / "Elgin Ave 24-7 MLO.7z"
    archive.parent.mkdir()
    subprocess.run([str(find_7zip()), "a", "-bd", str(archive), "."], cwd=src, check=True, capture_output=True)
    cache = M.ListingCache(tmp_path / "state", find_7zip())
    assert "elg_247shop" in M.check_file(man.mod("elgin247"), archive, cache)


# ----------------------------------------------------------------------------------------------- matching
def session(tmp_path, game, downloads, mods=None) -> Session:
    return Session(tmp_path / "st", write_manifest(tmp_path, mods), download_dir=str(downloads), game_dir=str(game),
                   game_build="1.0.1013.20")


def test_session_matches_reject_legacy(tmp_path, game, downloads):
    legacy = make_zip(downloads / "MapFixes_v21.8.2_NG.zip", MAPFIXES_LEGACY)
    upna = make_zip(downloads / "Up-n-Atom MLO.zip", UPNA_ENHANCED)
    s = session(tmp_path, game, downloads)
    res = s.matches()
    assert "mapfixes" not in res.matched and res.matched["upnatom"] == upna
    assert res.wrong[legacy][0] == "mapfixes" and "Legacy/SPMapFixes/dlc.rpf" in res.wrong[legacy][1]
    assert legacy in res.unmatched
    assert [m.id for m in res.missing(s.mods())] == ["mapfixes", "bugstarfixes", "elgin247", "plain"]
    assert (tmp_path / "st" / M.CACHE_NAME).is_file()


def test_older_right_file_wins_over_newer_wrong_one(tmp_path, game, downloads):
    right = make_zip(downloads / "MapFixes_v21.8.2_Enhanced.zip", MAPFIXES_ENHANCED)
    wrong = make_zip(downloads / "MapFixes_v21.8.2_NG.zip", MAPFIXES_LEGACY)
    st = right.stat()
    os.utime(wrong, ns=(st.st_atime_ns, st.st_mtime_ns + 10**10))       # the Legacy one is newer
    res = session(tmp_path, game, downloads).matches()
    assert res.matched["mapfixes"] == right and wrong in res.wrong and "mapfixes" not in res.duplicates


def test_forced_assignment_cannot_force_a_wrong_file(tmp_path, game, downloads):
    wrong = make_zip(downloads / "anything.zip", BUGSTAR_LEGACY)
    s = session(tmp_path, game, downloads)
    s.config.assignments["anything.zip"] = "bugstarfixes"
    res = s.matches()
    assert "bugstarfixes" not in res.matched and res.wrong[wrong][0] == "bugstarfixes"


def test_variant_and_selection_overrides(tmp_path, game, downloads):
    mods = copy.deepcopy(MODS)
    mods[0]["minGameBuild"] = "1.0.1013.17"
    mods[0]["gameBuilds"] = [{"max": "1.0.1013.16", "requireMembers": ["*spmapfixes/*"], "rejectMembers": ["*_gen9/*"],
                              "pick": {"versionLabel": "20.1 Legacy-era"}}]
    mods[2]["whenSelected"] = {"plain": {"requireMembers": ["*vw_upna/*"], "rejectMembers": ["*_g9/*"]}}
    man = load_manifest(write_manifest(tmp_path, mods))
    old = man.mod("mapfixes").for_build("1.0.1013.10")
    assert old.require_members == ("*spmapfixes/*",) and old.pick == {"versionLabel": "20.1 Legacy-era"}
    assert M.member_problem(old, members(MAPFIXES_LEGACY)) is None
    up = man.mod("upnatom")
    assert M.member_problem(up.for_selection({"plain"}), members(UPNA_LEGACY)) is None
    assert M.member_problem(up.for_selection(set()), members(UPNA_LEGACY)) is not None


# ---------------------------------------------------------------------------------------------- installing
def test_installer_never_installs_a_wrong_file(tmp_path, game, man, downloads):
    legacy = make_zip(downloads / "Up-n-Atom MLO.zip", UPNA_LEGACY)
    inst = Installer(man, game, tmp_path / "st", InstallLog(tmp_path / "st" / "log.json"), AutoUI())
    plan = inst.plan(man.mod("upnatom"), legacy)
    assert plan.wrong and "wrong edition/version of Up-n-Atom MLO" in plan.problems[0]
    with pytest.raises(InstallError, match="wrong edition/version of Up-n-Atom MLO"):
        inst.install(man.mod("upnatom"), legacy)  # a guided mod, refused before any step starts
    assert inst.log.steps == []
    ok = make_zip(downloads / "Up-n-Atom MLO e.zip", UPNA_ENHANCED)
    assert inst.plan(man.mod("upnatom"), ok).wrong is None


# ------------------------------------------------------------------------------------------------- schema
@pytest.mark.parametrize("field, value, message", [
    ("requireMembers", "x/*", "list of strings"),
    ("requireMembers", [], "can't be empty"),
    ("rejectMembers", ["ok/*", " "], "can't be empty"),
    ("pick", {"versionLabel": "a", "versionMatch": "b"}, "pick must be"),
    ("pick", {"label": "a"}, "pick must be"),
    ("pick", {"versionLabel": " "}, "non-empty"),
    ("pick", {"versionMatch": "(unclosed"}, "not a valid regex"),
])
def test_schema_errors(tmp_path, field, value, message):
    mods = copy.deepcopy(MODS)
    mods[4][field] = value
    with pytest.raises(ManifestError, match=message):
        load_manifest(write_manifest(tmp_path, mods))


def test_schema_errors_in_overrides(tmp_path):
    mods = copy.deepcopy(MODS)
    mods[4]["whenSelected"] = {"mapfixes": {"pick": {"versionLabel": "x"}}}  # pick isn't selection-dependent
    with pytest.raises(ManifestError, match="unknown key"):
        load_manifest(write_manifest(tmp_path, mods))


def test_bundled_rules_are_valid(manifest):
    for m in manifest.mods.values():
        assert isinstance(m.require_members, tuple) and isinstance(m.reject_members, tuple)
        if m.pick:
            assert set(m.pick) <= {"versionLabel", "versionMatch"}


# ------------------------------------------------------------------------------------- gta5-mods versions
# Structure of gta5-mods' "All Versions" panel (hand-written; same elements and classes as the real page).
VERSIONS = """<div class="panel-body"><h3>All Versions</h3>
<div class="well pull-left file-version-container ">
  <div class="pull-left"><i class="fa fa-file"></i>&nbsp;21.8.2 Enhanced
    <p><span class="num-downloads">271 downloads <span class="file-size">, 530 MB</span></span></p></div>
  <div class="pull-right"><a target="_blank" href="https://www.virustotal.com/gui/file/abc"><i class="fa fa-shield"></i></a>
    <a target="_blank" href="/maps/map-fixes/download/204370"><i class="fa fa-download download-version"></i></a></div>
</div>
<div class="well pull-left file-version-container ">
  <div class="pull-left"><i class="fa fa-file"></i>&nbsp;21.8.2 Legacy <span>(current)</span>
    <p><span class="num-downloads">1,366 downloads</span></p></div>
  <div class="pull-right"><a target="_blank" href="/maps/map-fixes/download/204369"><i class="fa fa-download"></i></a></div>
</div>
<div class="well pull-left file-version-container "><div class="pull-left">20.0 Enhanced<p>old</p></div>
  <div class="pull-right"><a href="https://evil.example/download/1">x</a></div></div>
</div>
<div class="visible-xs"><div class="well pull-left file-version-container ">
  <div class="pull-left">21.8.2 Enhanced<p>x</p></div>
  <div class="pull-right"><a href="/maps/map-fixes/download/204370"><i></i></a></div></div></div>"""
PAGE = "https://www.gta5-mods.com/maps/map-fixes"


def test_gta5mods_versions():
    v = gta5mods_versions(PAGE, VERSIONS)
    assert v == [ModVersion("21.8.2 Enhanced", PAGE + "/download/204370", False),
                 ModVersion("21.8.2 Legacy", PAGE + "/download/204369", True)]  # evil link and duplicate dropped
    assert gta5mods_versions(PAGE, "") == [] and gta5mods_versions(PAGE, "<div class='file-version-container'>") == []


def test_pick_version():
    v = gta5mods_versions(PAGE, VERSIONS)
    assert pick_version(v, {"versionMatch": "(?i)\\benhanced\\b"}).url.endswith("/204370")
    assert pick_version(v, {"versionLabel": "21.8.2 legacy"}).current
    assert pick_version(v, {"versionLabel": "21.8.2"}) is None         # exact label only
    assert pick_version(v, {"versionMatch": "^9"}) is None and pick_version(v, None) is None
    assert pick_version(v, {"versionMatch": "(bad"}) is None


def test_pick_version_script():
    js = pick_version_script({"versionMatch": "(?i)\\benhanced\\b"})
    args = json.loads("[" + js[js.rindex("})(") + 3:-2] + "]")
    assert args == ["div.file-version-container", "div.pull-left", 'div.pull-right a[href*="/download/"]', "",
                    "(?i)\\benhanced\\b"]
    lab = json.loads("[" + pick_version_script({"versionLabel": "21.8.2 Enhanced"}).rsplit("})(", 1)[1][:-2] + "]")
    assert lab[3:] == ["21.8.2 Enhanced", None]
    assert ".click(" not in js and pick_version_script(None) is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_pick_version_script_is_valid_javascript(tmp_path):
    f = tmp_path / "p.js"
    f.write_text(pick_version_script({"versionMatch": "(?i)\"'</script>"}), encoding="utf-8")
    res = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr


def test_parse_pick_result():
    ok = json.dumps({"found": True, "label": "21.8.2 Enhanced", "href": PAGE + "/download/204370", "labels": ["a"]})
    assert parse_pick_result(ok) == {"found": True, "label": "21.8.2 Enhanced", "href": PAGE + "/download/204370",
                                     "labels": ["a"]}
    evil = json.dumps({"found": True, "label": "x", "href": "https://evil.example/download/1"})
    assert parse_pick_result(evil)["found"] is False and parse_pick_result(evil)["href"] is None
    for bad in (None, "", "nope", "[1]"):
        assert parse_pick_result(bad) == {"found": False, "label": "", "href": None, "labels": []}


# ---------------------------------------------------------------------------------------------------- CLI
def test_get_reports_wrong_edition(tmp_path, game, downloads, capsys):
    make_zip(downloads / "MapFixes_v21.8.2_NG.zip", MAPFIXES_LEGACY)
    rc = main(["--state-dir", str(tmp_path / "st"), "--manifest-dir", str(write_manifest(tmp_path)),
               "--download-dir", str(downloads), "--game-dir", str(game), "--game-build", "1.0.1013.20",
               "get", "--no-open"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "!! MapFixes_v21.8.2_NG.zip: wrong edition/version of Map Fixes: it contains Legacy/SPMapFixes/dlc.rpf" in out
    assert "download 'the version matching (?i)\\benhanced\\b' from the All Versions list" in out
