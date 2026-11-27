"""leonida.rpf + the installer's "rpf" method, with tests/fake_rpf_helper.py standing in for LeonidaRpf.exe.

The fake keeps "archives" as zip files, so the whole install -> rollback -> uninstall cycle (mods\\ copies,
backups, logging, .oiv handling) is tested without CodeWalker or game keys. The real helper is covered by the
opt-in build/e2e_rpf.py run on real archives.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from conftest import AutoUI, make_zip

from leonida import log as L
from leonida import rpf as R
from leonida.installer import Installer, InstallError
from leonida.manifest import FileSpec, ManifestError, _mod_from
from leonida.snapshot import diff, take_snapshot

FAKE = Path(__file__).resolve().parent / "fake_rpf_helper.py"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fake_rpf(path: Path, members: dict[str, bytes | str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for n, d in members.items():  # zipfile turns "\" into "/" only on Windows: do it here for Linux CI too
            z.writestr(n.replace("\\", "/"), d.encode() if isinstance(d, str) else d)
    return path


def members_of(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:  # zip names use "/": show them as archive paths ("\\")
        return {n.replace("/", "\\"): z.read(n) for n in z.namelist()}


def entries_of(path: Path) -> dict[str, bytes]:
    """The archive's real entries (without the fake's "__open__" / "__xml__" bookkeeping)."""
    return {n: d for n, d in members_of(path).items() if not n.startswith("__")}


@pytest.fixture
def helper(monkeypatch):
    monkeypatch.setenv(R.HELPER_ENV, str(FAKE))
    return FAKE


@pytest.fixture
def rgame(game):
    """The conftest game plus the archives the tests edit (fake zips, as the fake helper reads them)."""
    fake_rpf(game / "update" / "update.rpf", {
        "common\\data\\dlclist.xml": "<SMandatoryPacksData><Paths/></SMandatoryPacksData>",
        "x64\\data\\tune\\physicstasks.ymt": "original tasks",
    })
    fake_rpf(game / "x64e.rpf", {"x64\\levels\\gta5\\paths.ymap": "orig"})
    return game


def rmod(manifest, rpf_ops, files=(), archive=("*.zip",)):
    return dataclasses.replace(manifest.mod("mapfixes"), method="rpf", rpf=tuple(rpf_ops), files=tuple(files),
                               archive=archive, require_members=(), reject_members=(), steps=())


def oiv_bytes(assembly: str, content: dict[str, str]) -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("assembly.xml", assembly)
        for n, d in content.items():
            z.writestr("content/" + n.replace("\\", "/"), d)
    return buf.getvalue()


ASSEMBLY = r"""<?xml version="1.0" encoding="UTF-8"?>
<package version="2.2" id="{1}" target="Five">
  <metadata><name>Test package</name></metadata>
  <content>
    <add source="scripts\Mod.dll">scripts\Mod.dll</add>
    <add source="packs\dlc.rpf">update\x64\dlcpacks\testpack\dlc.rpf</add>
    <delete>OldMod.asi</delete>
    <archive path="update\update.rpf" createIfNotExist="True" type="RPF7">
      <add source="handling.meta">\common\data\handling.meta</add>
      <archive path="x64\levels\gta5\paths.rpf" createIfNotExist="False" type="RPF7">
        <add source="nodes.ynd">nodes.ynd</add>
      </archive>
      <delete>x64\data\old.meta</delete>
      <xml path="common\data\dlclist.xml">
        <add xpath="/SMandatoryPacksData/Paths[not(Item[.='dlcpacks:/testpack/'])]" append="Last"><Item>dlcpacks:/testpack/</Item></add>
        <remove xpath="/SMandatoryPacksData/Junk" />
      </xml>
    </archive>
    <archive path="update\x64\dlcpacks\newpack\dlc.rpf" createIfNotExist="True" type="RPF7">
      <add source="content.xml">content.xml</add>
    </archive>
  </content>
</package>"""
CONTENT = {"scripts\\Mod.dll": "dll", "packs\\dlc.rpf": "packrpf", "handling.meta": "<handling/>",
           "nodes.ynd": "nodes", "content.xml": "<content/>"}


# ------------------------------------------------------------------------------------------- helpers / parsing
def test_paths():
    assert R.win("\\x64/data\\\\f.ymt ") == "x64\\data\\f.ymt"
    assert R.mods_rel("update\\update.rpf") == "mods/update/update.rpf"
    assert R.loose_dest("scripts\\a.dll") == "scripts/a.dll"
    assert R.loose_dest("ViPreload.asi") == "ViPreload.asi"
    assert R.loose_dest("update\\x64\\dlcpacks\\vihud\\dlc.rpf") == "mods/update/x64/dlcpacks/vihud/dlc.rpf"
    assert R.loose_dest("x64\\audio\\sfx\\a.awc") == "mods/x64/audio/sfx/a.awc"
    assert R.loose_dest("custom.rpf") == "mods/custom.rpf"
    with pytest.raises(R.RpfError, match="leaves the game folder"):
        R.win("..\\..\\Windows\\x.dll")
    with pytest.raises(R.RpfError, match="empty"):
        R.loose_dest("  ")


def test_dlclist_edit_is_idempotent_xpath():
    e = R.dlclist_edit("dlcpacks:/spMapFixes_Gen9/")
    assert e == {"type": "add", "append": "Last",
                 "xpath": "/SMandatoryPacksData/Paths[not(Item[.='dlcpacks:/spMapFixes_Gen9/'])]",
                 "xml": "<Item>dlcpacks:/spMapFixes_Gen9/</Item>"}
    with pytest.raises(R.RpfError):
        R.dlclist_edit("bad'quote")


@pytest.mark.parametrize(("ops", "msg"), [
    ([], "non-empty list"),
    ([{"archive": "update\\update.rpf"}], "exactly one of"),
    ([{"archive": "update\\update.rpf", "put": "a", "dlclist": "x"}], "exactly one of"),
    ([{"archive": "update\\update.rpf", "put": "a"}], "needs 'to'"),
    ([{"archive": "update.zip", "dlclist": "x"}], "game-relative .rpf"),
    ([{"oiv": "*.oiv", "archive": "update\\update.rpf"}], "takes only 'skip'"),
    ([{"oiv": "*.oiv", "skip": "gameconfig.xml"}], "'skip' must be a list"),
    ([{"archive": "update\\update.rpf", "dlclist": "x", "skip": ["a"]}], "only goes with 'oiv'"),
    ([{"archive": "update\\update.rpf", "putdir": "manual"}], "needs 'to'"),
    ([{"archive": "update\\update.rpf", "texture": "a.dds"}], "needs 'ytd'"),
    ([{"archive": "update\\update.rpf", "texture": "a.dds", "ytd": "a.ydr"}], "needs 'ytd'"),
    ([{"archive": "update\\update.rpf", "xml": "a.xml", "edits": [{"type": "nope", "xpath": "/a"}]}], "edits"),
    ([{"archive": "update\\update.rpf", "delete": "..\\x"}], "leaves the game folder"),
    ([{"archive": "update\\update.rpf", "dlclist": "x", "colour": 1}], "unknown keys"),
])
def test_check_ops_rejects(ops, msg):
    with pytest.raises(ValueError, match=msg):
        R.check_ops(ops, "Mod 'x'")


def test_manifest_accepts_the_rpf_method():
    raw = {"id": "t", "order": 1, "tier": "core", "layer": "Fixes", "name": "T", "page": "https://example.com",
           "archive": ["*.zip"], "install": {"method": "rpf", "rpf": [
               {"archive": "update\\update.rpf", "dlclist": "dlcpacks:/t/"}, {"oiv": "*.oiv"}]}}
    mod = _mod_from(raw)
    assert mod.method == "rpf" and mod.rpf[1] == {"oiv": "*.oiv"}
    raw["install"] = {"method": "rpf"}
    with pytest.raises(ManifestError, match="needs an 'rpf' list"):
        _mod_from(raw)
    raw["install"] = {"method": "rpf", "rpf": [{"archive": "x.rpf"}]}
    with pytest.raises(ManifestError, match="exactly one of"):
        _mod_from(raw)


def test_parse_oiv(tmp_path):
    pkg = tmp_path / "Test.oiv"
    pkg.write_bytes(oiv_bytes(ASSEMBLY, CONTENT))
    work = R.parse_oiv_file(pkg)
    assert [(a.path, a.create) for a in work.archives.values()] == [
        ("update\\update.rpf", True), ("update\\x64\\dlcpacks\\newpack\\dlc.rpf", True)]
    ops = work.archives["update\\update.rpf"].ops
    assert [(o["op"], o["entry"]) for o in ops] == [
        ("put", "common\\data\\handling.meta"),
        ("put", "x64\\levels\\gta5\\paths.rpf\\nodes.ynd"),
        ("delete", "x64\\data\\old.meta"),
        ("xml", "common\\data\\dlclist.xml")]
    assert ops[3]["edits"][0] == {"type": "add", "append": "Last",
                                  "xpath": "/SMandatoryPacksData/Paths[not(Item[.='dlcpacks:/testpack/'])]",
                                  "xml": "<Item>dlcpacks:/testpack/</Item>"}
    assert ops[3]["edits"][1]["type"] == "remove"
    assert Path(ops[0]["src"]).read_text() == "<handling/>"
    assert [d for _, d in work.loose_adds] == ["scripts/Mod.dll", "mods/update/x64/dlcpacks/testpack/dlc.rpf"]
    assert work.loose_deletes == ["OldMod.asi"]
    lines = "\n".join(work.describe())
    assert "mods/update/update.rpf: 1 delete, 2 put, 1 xml" in lines and "OldMod.asi" in lines
    assert R.parse_oiv_file(pkg).archives.keys() == work.archives.keys()  # unpacked once, reused


@pytest.mark.parametrize(("bad", "msg"), [
    ("<package><content><text path='a.txt'/></content></package>", None),
    ("<package><metadata/></package>", "no <content>"),
    ("<package><content><archive path='a.rpf' type='RPF8'/></content></package>", "not supported"),
    ("<package><content><add source='missing.dll'>a.dll</add></content></package>", "missing from the package"),
    ("<package><content><xml path='a.xml'/></content></package>", "outside an <archive>"),
    ("<package><content><archive path='a.rpf'><xml path='a.xml'><insert xpath='/a'/></xml></archive>"
     "</content></package>", "unsupported xml edit"),
    ("<package><content><archive path='a.rpf'><text path='a.txt'/></archive></content></package>", "not supported yet"),
    ("not xml", "can't be read"),
])
def test_parse_oiv_errors(tmp_path, bad, msg):
    (tmp_path / "assembly.xml").write_text(bad)
    if msg is None:  # a loose <text> is ignored (nothing OpenIV does outside archives that we support)
        assert R.parse_oiv(tmp_path).archives == {}
        return
    with pytest.raises(R.RpfError, match=msg):
        R.parse_oiv(tmp_path)


def test_parse_oiv_needs_assembly_and_a_zip(tmp_path):
    with pytest.raises(R.RpfError, match="No assembly.xml"):
        R.parse_oiv(tmp_path)
    bad = tmp_path / "bad.oiv"
    bad.write_bytes(b"not a zip")
    with pytest.raises(R.RpfError, match="not a valid .oiv"):
        R.parse_oiv_file(bad)
    evil = tmp_path / "evil.oiv"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../../escape.txt", "x")
    with pytest.raises(R.RpfError, match="unsafe path"):
        R.parse_oiv_file(evil)


def test_manifest_work(tmp_path):
    root = tmp_path / "dl"
    (root / "Mod Files").mkdir(parents=True)
    (root / "Mod Files" / "cameras.ymt").write_text("cam")
    (root / "Legacy").mkdir()
    (root / "Legacy" / "cameras.ymt").write_text("legacy cam")
    (root / "pkg").mkdir()
    (root / "pkg" / "Install.oiv").write_bytes(oiv_bytes(ASSEMBLY, CONTENT))
    members = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    work = R.manifest_work([
        {"archive": "update\\update.rpf", "put": "cameras.ymt", "to": "x64\\data\\metadata\\"},
        {"archive": "update\\update.rpf", "put": "cameras.ymt", "to": "x64/data/metadata/cameras.ymt"},
        {"archive": "update\\update.rpf", "dlclist": "dlcpacks:/a/"},
        {"archive": "update\\update.rpf", "xml": "common\\data\\gameconfig.xml",
         "edits": [{"type": "remove", "xpath": "/a/b"}]},
        {"archive": "x64e.rpf", "delete": "x64\\old.meta"},
        {"oiv": "install.oiv"},
    ], root, members)
    up = work.archives["update\\update.rpf"].ops
    assert up[0]["entry"] == up[1]["entry"] == "x64\\data\\metadata\\cameras.ymt"
    assert Path(up[0]["src"]).read_text() == "cam"  # the non-Legacy file wins
    assert up[2]["entry"] == R.DLCLIST and up[3]["op"] == "xml" and len(up) == 4 + 4
    assert work.archives["x64e.rpf"].ops == [{"op": "delete", "entry": "x64\\old.meta"}]
    with pytest.raises(R.RpfError, match="not in the download"):
        R.manifest_work([{"archive": "a.rpf", "put": "nope.ymt", "to": "x\\"}], root, members)
    with pytest.raises(R.RpfError, match="No .oiv package"):
        R.manifest_work([{"oiv": "missing*.oiv"}], root, members)


def test_find_helper_order(tmp_path, monkeypatch):
    monkeypatch.delenv(R.HELPER_ENV, raising=False)
    built = Path(R.__file__).resolve().parent.parent / "build" / "codewalker" / "bin" / R.HELPER_NAME
    assert R.find_helper(tmp_path) == ([str(built)] if built.is_file() else None)
    tools = tmp_path / "tools" / "LeonidaRpf" / R.HELPER_NAME
    tools.parent.mkdir(parents=True)
    tools.write_bytes(b"MZ")
    assert R.find_helper(tmp_path) == [str(tools)]
    monkeypatch.setenv(R.HELPER_ENV, str(FAKE))
    assert R.find_helper(tmp_path)[1:] == [str(FAKE)]


def test_run_helper_reports_errors(rgame, helper, monkeypatch, tmp_path):
    cmd = R.find_helper()
    res = R.run_helper(cmd, rgame, [{"op": "keys"}])
    assert res == [{"op": "keys", "ok": True}]
    monkeypatch.setenv("FAKE_RPF_FAIL_AT", "1")
    with pytest.raises(R.RpfError, match=r"operation 2 of 2: put x\\a\): RuntimeError: simulated failure"):
        R.run_helper(cmd, rgame, [{"op": "keys"}, {"op": "put", "entry": "x\\a", "rpf": "r", "src": "s"}])
    with pytest.raises(R.RpfError, match="GTA5_Enhanced.exe not found"):
        R.run_helper(cmd, tmp_path, [{"op": "keys"}])
    with pytest.raises(R.RpfError, match="could not run"):
        R.run_helper([str(tmp_path / "missing.exe")], rgame, [])
    bad = tmp_path / "bad.py"
    bad.write_text("import sys; sys.stderr.write('boom'); sys.exit(3)")
    with pytest.raises(R.RpfError, match="boom"):
        R.run_helper(["python", str(bad)], rgame, [])


# ------------------------------------------------------------------------------------------- installer
def _inst(manifest, game, state, log, ui=None):
    return Installer(manifest, game, state, log, ui or AutoUI())


def test_rpf_install_rollback_uninstall_equals_baseline(manifest, rgame, state, log, downloads, helper):
    game = rgame
    before = take_snapshot(game)
    orig_update = sha(game / "update" / "update.rpf")
    (game / "OldMod.asi").write_bytes(b"old asi")  # the .oiv deletes it: must come back on rollback
    before = take_snapshot(game)
    z = make_zip(downloads / "mapfix.zip", {
        "spMapFixes_Gen9/dlc.rpf": "mapfix pack",
        "Enhanced/MP Map Fixes.oiv": oiv_bytes(ASSEMBLY, CONTENT),
        "physicstasks.ymt": "new tasks",
    })
    mod = rmod(manifest, [
        {"archive": "update\\update.rpf", "dlclist": "dlcpacks:/spMapFixes_Gen9/"},
        {"archive": "update\\update.rpf", "put": "physicstasks.ymt", "to": "x64\\data\\tune\\physicstasks.ymt"},
        {"oiv": "MP Map Fixes.oiv"},
    ], files=[FileSpec("spMapFixes_Gen9", "mods/update/x64/dlcpacks", "dir")])
    inst = _inst(manifest, game, state, log)
    plan = inst.plan(mod, z)
    assert plan.problems == []
    text = "\n".join(plan.describe())
    assert "rpf mods\\update\\update.rpf: dlclist dlcpacks:/spMapFixes_Gen9/" in text and "apply .oiv" in text
    step = inst.install(mod, z)
    assert step.status == "done"
    mods_update = game / "mods" / "update" / "update.rpf"
    m = members_of(mods_update)
    assert m["x64\\data\\tune\\physicstasks.ymt"] == b"new tasks"
    assert m["common\\data\\handling.meta"] == b"<handling/>"
    assert m["x64\\levels\\gta5\\paths.rpf\\nodes.ynd"] == b"nodes"
    edits = json.loads(m["__xml__\\common\\data\\dlclist.xml.json"])
    assert [e["xml"] for e in edits if e["type"] == "add"] == ["<Item>dlcpacks:/spMapFixes_Gen9/</Item>",
                                                               "<Item>dlcpacks:/testpack/</Item>"]
    assert members_of(game / "mods/update/x64/dlcpacks/newpack/dlc.rpf")["content.xml"] == b"<content/>"
    assert "created empty: mods/update/x64/dlcpacks/newpack/dlc.rpf" in step.notes  # the in-game probe reads it
    assert (game / "mods/update/x64/dlcpacks/spMapFixes_Gen9/dlc.rpf").read_text() == "mapfix pack"
    assert (game / "scripts/Mod.dll").read_text() == "dll"
    assert (game / "mods/update/x64/dlcpacks/testpack/dlc.rpf").read_text() == "packrpf"
    assert not (game / "OldMod.asi").exists()
    assert sha(game / "update" / "update.rpf") == orig_update  # the game's own archive is never written
    ops = {(a.op, a.path) for a in step.actions}
    assert (L.ADD, "mods/update/update.rpf") in ops and (L.EXT_REMOVE, "OldMod.asi") in ops
    rpf_action = next(a for a in step.actions if a.path == "mods/update/update.rpf")
    assert rpf_action.sha256 == sha(mods_update)

    # a second step on the same mods\ archive: entry-level backup (only what it changes), so rolling it back puts
    # step 1's entries back exactly, and step 1 can still delete its copy cleanly afterwards
    after_first = entries_of(mods_update)
    z2 = make_zip(downloads / "cam.zip", {"Mod Files/cameras.ymt": "cam"})
    cam = rmod(manifest, [{"archive": "update\\update.rpf", "put": "cameras.ymt", "to": "x64\\data\\metadata\\"}])
    cam = dataclasses.replace(cam, id="combatcamera")
    step2 = inst.install(cam, z2)
    a2 = step2.actions[0]
    assert (a2.op, a2.path) == (L.RPF_EDIT, "mods/update/update.rpf") and a2.backup
    assert json.loads((state / a2.backup / R.ENTRY_MANIFEST).read_text())["entries"][0]["entry"] == \
        "x64\\data\\metadata\\cameras.ymt"
    assert members_of(mods_update)["x64\\data\\metadata\\cameras.ymt"] == b"cam"
    assert inst.rollback(step2.id) == []
    assert entries_of(mods_update) == after_first
    assert rpf_action.sha256 == sha(mods_update)  # step 1's record follows the archive's new layout
    warnings, residual = inst.uninstall()
    assert warnings == [] and residual.empty, residual.summary()
    assert diff(before, take_snapshot(game)).empty
    assert (game / "OldMod.asi").read_bytes() == b"old asi"
    assert not (game / "mods").exists()


def test_rpf_existing_mods_copy_is_backed_up(manifest, rgame, state, log, downloads, helper):
    game = rgame
    pre = fake_rpf(game / "mods" / "update" / "update.rpf", {"common\\data\\dlclist.xml": "<x/>", "mine.meta": "user"})
    pre_sha = sha(pre)
    before = take_snapshot(game)
    z = make_zip(downloads / "e.zip", {"physicstasks.ymt": "tasks"})
    mod = rmod(manifest, [{"archive": "update\\update.rpf", "put": "physicstasks.ymt", "to": "x64\\data\\tune\\"}])
    inst = _inst(manifest, game, state, log)
    pre_members = entries_of(pre)
    step = inst.install(mod, z)
    a = step.actions[0]
    assert a.op == L.RPF_EDIT and (state / a.backup / R.ENTRY_MANIFEST).is_file()
    assert not any(p.suffix == ".bin" for p in (state / a.backup).iterdir())  # a new entry: nothing to back up
    assert entries_of(pre)["mine.meta"] == b"user"  # the earlier mods\ copy is edited, not replaced
    assert inst.rollback(step.id) == []
    # the archive the user had comes back entry for entry (its bytes may differ: entries move inside an archive)
    assert entries_of(pre) == pre_members
    d = diff(before, take_snapshot(game))
    assert set(d.changed) <= {"mods/update/update.rpf"} and not d.added and not d.removed
    del pre_sha


def test_rpf_helper_failure_is_rolled_back(manifest, rgame, state, log, downloads, helper, monkeypatch):
    game = rgame
    before = take_snapshot(game)
    z = make_zip(downloads / "e.zip", {"physicstasks.ymt": "tasks"})
    mod = rmod(manifest, [{"archive": "update\\update.rpf", "put": "physicstasks.ymt", "to": "x64\\data\\tune\\"},
                          {"archive": "x64e.rpf", "delete": "x64\\levels\\gta5\\paths.ymap"}])
    monkeypatch.setenv("FAKE_RPF_FAIL_AT", "1")
    inst = _inst(manifest, game, state, log)
    with pytest.raises(InstallError, match="simulated failure"):
        inst.install(mod, z)
    step = log.steps[-1]
    assert step.status == "failed"
    assert {a.path for a in step.actions} == {"mods/update/update.rpf", "mods/x64e.rpf"}
    assert inst.rollback(step.id) == []
    assert diff(before, take_snapshot(game)).empty


def test_rpf_one_helper_batch_per_step(manifest, rgame, state, log, downloads, helper, monkeypatch, tmp_path):
    batches = tmp_path / "batches.jsonl"
    monkeypatch.setenv("FAKE_RPF_LOG", str(batches))
    z = make_zip(downloads / "e.zip", {"physicstasks.ymt": "tasks", "Install.oiv": oiv_bytes(ASSEMBLY, CONTENT)})
    mod = rmod(manifest, [{"archive": "update\\update.rpf", "put": "physicstasks.ymt", "to": "x64\\data\\tune\\"},
                          {"archive": "x64e.rpf", "delete": "x64\\levels\\gta5\\paths.ymap"}, {"oiv": "*.oiv"}])
    _inst(manifest, rgame, state, log).install(mod, z)
    lines = batches.read_text().splitlines()
    assert len(lines) == 1  # keys are derived once per step
    ops = json.loads(lines[0])
    newpack = [o["op"] for o in ops if Path(o["rpf"]).parts[-2:] == ("newpack", "dlc.rpf")]
    assert newpack == ["create", "put"]  # createIfNotExist and the game has no such archive: made empty first


def test_rpf_oiv_download_itself(manifest, rgame, state, log, downloads, helper):
    pkg = downloads / "GTA-VI-HUD-Enhanced.oiv"
    pkg.write_bytes(oiv_bytes(ASSEMBLY, CONTENT))
    mod = rmod(manifest, [{"oiv": "*.oiv", "skip": ["x64\\data\\old.meta"]}], archive=("*.oiv",))
    mod = dataclasses.replace(mod, steps=("Set the screen to Windowed Borderless.",))
    ui = AutoUI()
    inst = _inst(manifest, rgame, state, log, ui)
    plan = inst.plan(mod, pkg)
    assert plan.problems == []
    text = "\n".join(plan.describe())
    assert "(leaving out x64\\data\\old.meta)" in text and "by hand afterwards: Set the screen" in text
    step = inst.install(mod, pkg)
    assert step.status == "done" and (rgame / "scripts/Mod.dll").is_file()
    assert "By hand, after this step: Set the screen to Windowed Borderless." in ui.lines
    assert any("left out of GTA-VI-HUD-Enhanced.oiv: delete x64\\data\\old.meta" in line for line in ui.lines)


def test_rpf_plan_problems(manifest, rgame, state, log, downloads, monkeypatch, tmp_path):
    monkeypatch.setenv(R.HELPER_ENV, str(tmp_path / "missing.exe"))
    monkeypatch.setattr(R, "__file__", str(tmp_path / "leonida" / "rpf.py"))  # no build/codewalker/bin either
    z = make_zip(downloads / "e.zip", {"other.ymt": "x"})
    mod = rmod(manifest, [{"archive": "update\\update.rpf", "put": "physicstasks.ymt", "to": "x\\"}, {"oiv": "*.oiv"}])
    inst = _inst(manifest, rgame, state, log)
    plan = inst.plan(mod, z)
    assert any("RPF helper" in p for p in plan.problems)
    assert "physicstasks.ymt not found in e.zip." in plan.problems
    assert any("No .oiv matching" in p for p in plan.problems)
    with pytest.raises(InstallError, match="RPF helper"):
        inst.install(mod, z)
    txt = downloads / "notes.txt"
    txt.write_text("x")
    assert "is not a .zip/.7z/.rar archive or an .oiv" in inst.plan(mod, txt).problems[0]


def test_rpf_missing_game_archive_and_disk_space(manifest, rgame, state, log, downloads, helper, monkeypatch):
    z = make_zip(downloads / "e.zip", {"physicstasks.ymt": "tasks"})
    inst = _inst(manifest, rgame, state, log)
    mod = rmod(manifest, [{"archive": "update\\update2.rpf", "put": "physicstasks.ymt", "to": "x\\"}])
    with pytest.raises(InstallError, match="has no update\\\\update2.rpf"):
        inst.install(mod, z)
    inst.rollback(log.steps[-1].id)
    mod = rmod(manifest, [{"archive": "update\\update.rpf", "put": "physicstasks.ymt", "to": "x\\"}])
    import shutil

    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 10, 0))
    with pytest.raises(InstallError, match=r"needs about .* only 0 MB is free there .*nothing was changed"):
        inst.install(mod, z)
    assert not (rgame / "mods").exists()


def test_rpf_bad_manifest_ops_at_install(manifest, rgame, state, log, downloads, helper):
    z = make_zip(downloads / "e.zip", {"a.oiv": b"not a zip"})
    mod = rmod(manifest, [{"oiv": "a.oiv"}])
    with pytest.raises(InstallError, match="not a valid .oiv"):
        _inst(manifest, rgame, state, log).install(mod, z)


def test_space_needed(rgame):
    work = R.Work()
    work.archive("update\\update.rpf")
    work.archive("update\\nothere.rpf", create=True)
    assert R.space_needed(rgame, work) == (rgame / "update/update.rpf").stat().st_size
    assert R.space_needed(rgame, R.Work()) == 0


# ------------------------------------------------------------------------------------------- entry-level backups
def _two_steps(manifest, rgame, state, log, downloads):
    """Step 1 makes the mods\\ copy of update.rpf; step 2 edits it: replaces, adds, deletes, an xml edit, a new
    nested archive and a texture."""
    inst = _inst(manifest, rgame, state, log)
    z1 = make_zip(downloads / "base.zip", {"physicstasks.ymt": "tasks v1", "cameras.ymt": "cam v1",
                                            "phone.ytd": "<icons>", "old.meta": "old"})
    first = rmod(manifest, [{"archive": "update\\update.rpf", "put": "physicstasks.ymt", "to": "x64\\data\\tune\\"},
                            {"archive": "update\\update.rpf", "put": "cameras.ymt", "to": "x64\\data\\metadata\\"},
                            {"archive": "update\\update.rpf", "put": "phone.ytd", "to": "x64\\cdimages\\sf.rpf\\"},
                            {"archive": "update\\update.rpf", "put": "old.meta", "to": "x64\\data\\"}])
    s1 = inst.install(first, z1)
    z2 = make_zip(downloads / "edit.zip", {"cameras.ymt": "cam v2", "new.meta": "new", "icons.dds": "DDS",
                                            "manual/mods/update.rpf/common/data/w_clear.xml": "<w/>",
                                            "manual/mods/update.rpf/x64/movies/m.bik": "bik"})
    second = rmod(manifest, [
        {"archive": "update\\update.rpf", "put": "cameras.ymt", "to": "x64\\data\\metadata\\"},
        {"archive": "update\\update.rpf", "put": "new.meta", "to": "x64\\new\\pack.rpf\\new.meta"},
        {"archive": "update\\update.rpf", "delete": "x64\\data\\old.meta"},
        {"archive": "update\\update.rpf", "dlclist": "dlcpacks:/x/"},
        {"archive": "update\\update.rpf", "texture": "icons.dds", "ytd": "x64\\cdimages\\sf.rpf\\phone.ytd"},
        {"archive": "update\\update.rpf", "putdir": "manual/mods/update.rpf", "to": ""}])
    second = dataclasses.replace(second, id="visualv")
    return inst, s1, second, z2


def test_rpf_entry_backups_and_exact_rollback(manifest, rgame, state, log, downloads, helper):
    mods_update = rgame / "mods" / "update" / "update.rpf"
    inst, s1, second, z2 = _two_steps(manifest, rgame, state, log, downloads)
    before = entries_of(mods_update)
    s2 = inst.install(second, z2)
    a = s2.actions[0]
    assert a.op == L.RPF_EDIT
    man = json.loads((state / a.backup / R.ENTRY_MANIFEST).read_text())
    recs = {r["entry"]: r for r in man["entries"]}
    assert recs["x64\\data\\metadata\\cameras.ymt"]["backup"] and recs["x64\\data\\old.meta"]["backup"]
    assert recs["x64\\new\\pack.rpf\\new.meta"]["before"] is None
    assert recs["x64\\new\\pack.rpf\\new.meta"]["created"] == "x64\\new"
    assert recs["common\\data\\w_clear.xml"]["before"] is None and recs["x64\\movies\\m.bik"]["after"]
    assert all(r["after"] != r["before"] for r in recs.values() if r["entry"] != "x64\\data\\old.meta")
    assert recs["x64\\data\\old.meta"]["after"] is None  # deleted
    now = members_of(mods_update)
    assert now["x64\\data\\metadata\\cameras.ymt"] == b"cam v2" and "x64\\data\\old.meta" not in now
    assert now["x64\\cdimages\\sf.rpf\\phone.ytd"].startswith(b"<icons>|icons=")
    assert now["common\\data\\w_clear.xml"] == b"<w/>" and now["x64\\movies\\m.bik"] == b"bik"
    # backups hold only the entries it replaced, edited or deleted (not the 3 GB archive)
    bins = sorted(p.read_bytes() for p in (state / a.backup).glob("*.bin"))
    assert bins == [b"<SMandatoryPacksData><Paths/></SMandatoryPacksData>", b"<icons>", b"cam v1", b"old"]
    assert inst.rollback(s2.id) == []
    assert entries_of(mods_update) == before
    assert next(x for x in s1.actions if x.path == "mods/update/update.rpf").sha256 == sha(mods_update)
    warnings, residual = inst.uninstall()
    assert warnings == [] and residual.empty


def test_rpf_entry_rollback_reports_later_changes_and_problems(manifest, rgame, state, log, downloads, helper,
                                                              monkeypatch):
    mods_update = rgame / "mods" / "update" / "update.rpf"
    inst, _s1, second, z2 = _two_steps(manifest, rgame, state, log, downloads)
    before = entries_of(mods_update)
    s2 = inst.install(second, z2)
    a = s2.actions[0]
    m = members_of(mods_update)  # someone changes an entry after the install
    m["x64/data/metadata/cameras.ymt".replace("/", "\\")] = b"edited by hand"
    fake_rpf(mods_update, m)
    warns = inst.rollback(s2.id)
    assert len(warns) == 1 and "was changed after the install" in warns[0]
    assert entries_of(mods_update) == before
    # what's left when things are missing
    assert "entry backups are missing" in inst._undo_rpf_edit(s2, L.Action(L.RPF_EDIT, a.path, None, "nope"))[0]
    gone = L.Action(L.RPF_EDIT, "mods/update/gone.rpf", None, a.backup)
    assert "is gone" in inst._undo_rpf_edit(s2, gone)[0]
    monkeypatch.setenv(R.HELPER_ENV, str(mods_update.parent / "missing.exe"))
    monkeypatch.setattr(R, "__file__", str(mods_update.parent / "leonida" / "rpf.py"))
    assert "helper isn't installed" in inst._undo_rpf_edit(s2, a)[0]


def test_rpf_entry_backup_failures(manifest, rgame, state, log, downloads, helper, monkeypatch):
    inst, _s1, second, z2 = _two_steps(manifest, rgame, state, log, downloads)
    monkeypatch.setenv("FAKE_RPF_FAIL_AT", "0")  # the backup run fails: nothing is changed
    with pytest.raises(InstallError, match="couldn't back up the archive entries"):
        inst.install(second, z2)
    monkeypatch.setenv("FAKE_RPF_FAIL_AT", "-1")
    assert inst.rollback(log.steps[-1].id) == []
    # the edit run fails half-way: the step is logged with its entry backups, and rollback puts them back
    mods_update = rgame / "mods" / "update" / "update.rpf"
    before = entries_of(mods_update)
    monkeypatch.setenv("FAKE_RPF_FAIL_ON", "delete:1")  # after two puts went in
    with pytest.raises(InstallError, match="simulated failure"):
        inst.install(second, z2)
    monkeypatch.delenv("FAKE_RPF_FAIL_ON")
    step = log.steps[-1]
    assert step.status == "failed" and step.actions[0].op == L.RPF_EDIT
    assert inst.rollback(step.id) == []
    assert entries_of(mods_update) == before
    # the helper fails while putting entries back: reported, not raised
    s = inst.install(second, z2)
    monkeypatch.setenv("FAKE_RPF_FAIL_AT", "1")
    assert "couldn't put its entries back" in inst.rollback(s.id)[0]


def test_rpf_manifest_ops_putdir_texture_skip(tmp_path):
    root = tmp_path / "dl"
    files = {"VisualV/manual installation/mods/update.rpf/common/data/w_clear.xml": "w",
             "VisualV/manual installation/mods/update.rpf/x64/movies/m.bik": "m",
             "VisualV/original files/mods/update/update.rpf/common/data/w_clear.xml": "orig",
             "iOS/icons_spritesheet_ifruit.dds": "dds",
             "Enhanced/Pkg.oiv": oiv_bytes(ASSEMBLY, CONTENT), "Legacy/Pkg.oiv": b"not even a zip"}
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data if isinstance(data, bytes) else data.encode())
    members = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    work = R.manifest_work([
        {"archive": "update\\update.rpf", "putdir": "manual installation/mods/update.rpf", "to": ""},
        {"archive": "update\\update.rpf", "putdir": "mods\\update.rpf", "to": "x64\\extra"},
        {"archive": "update\\update.rpf", "texture": "icons_spritesheet_ifruit.dds",
         "ytd": "x64\\data\\cdimages\\scaleform_generic.rpf\\cellphone_ifruit.ytd"},
        {"oiv": "Enhanced/Pkg.oiv", "skip": ["common\\data\\dlclist.xml", "x64\\data\\old.meta"]},
    ], root, members)
    ops = work.archives["update\\update.rpf"].ops
    assert [(o["op"], o["entry"]) for o in ops[:5]] == [
        ("put", "common\\data\\w_clear.xml"), ("put", "x64\\movies\\m.bik"),
        ("put", "x64\\extra\\common\\data\\w_clear.xml"), ("put", "x64\\extra\\x64\\movies\\m.bik"),
        ("ytd", "x64\\data\\cdimages\\scaleform_generic.rpf\\cellphone_ifruit.ytd")]
    assert ops[4]["texture"] == "icons_spritesheet_ifruit"
    assert Path(ops[0]["src"]).read_text() == "w"  # the 'manual installation' copy, not 'original files'
    entries = [o["entry"] for o in ops[5:]]
    assert "common\\data\\dlclist.xml" not in entries and "x64\\data\\old.meta" not in entries
    assert "common\\data\\handling.meta" in entries
    assert any("left out of Pkg.oiv: xml common\\data\\dlclist.xml" in n for n in work.notes)
    assert R.touched_entries(ops + ops) == [o["entry"] for o in ops]
    with pytest.raises(R.RpfError, match="No folder"):
        R.find_folder(root, members, "nope/update.rpf")
    with pytest.raises(R.RpfError, match="needs a folder"):
        R.find_folder(root, members, "/")
    assert [p.parent.name for p in R.find_oivs(root, "*.oiv")] == ["Enhanced", "Legacy"]
    assert [p.parent.name for p in R.find_oivs(root, "enhanced\\*.oiv")] == ["Enhanced"]


def test_space_items_and_message(rgame, state, log, manifest, tmp_path, monkeypatch):
    src = tmp_path / "big.bin"
    src.write_bytes(b"x" * 3000)
    work = R.Work()
    work.archive("update\\update.rpf").ops.append({"op": "put", "entry": "a", "src": str(src)})
    work.archive("update\\update.rpf").ops.append({"op": "xml", "entry": "b", "edits": []})
    items = R.space_items(rgame, work)
    size = (rgame / "update/update.rpf").stat().st_size
    assert ("copy of update\\update.rpf in mods", size, "game") in items
    assert ("new data inside mods\\update\\update.rpf", 3000 + 64 * 1024, "game") in items
    fake_rpf(rgame / "mods" / "update" / "update.rpf", {"a": "1"})
    work.loose_adds.append((src, "scripts/x.dll"))
    items = dict((w, n) for w, n, _ in R.space_items(rgame, work))
    assert items["backups of the entries it changes in mods\\update\\update.rpf"] == 3000 + 64 * 1024
    assert items["loose files from the .oiv"] == 3000
    import shutil

    inst = _inst(manifest, rgame, state, log)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 10, 100 * 2**20))
    big = tmp_path / "big.bin"  # small on purpose: tests must never fill the disk (a 1 GB file here once did)
    big.write_bytes(b"x" * (4 * 2**20))
    with pytest.raises(InstallError, match=r"Map Fixes needs about \d+ MB .*files it copies into the game folder: "
                                           r"4 MB.*only 100 MB is free"):
        inst._check_space(work, [big], "Map Fixes")
    inst._check_space(R.Work(), [], "Nothing")  # nothing to write: no error


def test_modupdate_paths_of_rpf_edits(manifest, rgame, state, log, downloads, helper):
    from leonida import modupdate

    inst, s1, second, z2 = _two_steps(manifest, rgame, state, log, downloads)
    s2 = inst.install(second, z2)
    paths = modupdate._paths(s2, state)
    assert "mods/update/update.rpf/x64/data/metadata/cameras.ymt" in paths
    assert "mods/update/update.rpf" not in paths
    assert modupdate._paths(s2) == {"mods/update/update.rpf"}  # no state folder: the whole archive
    # the step that made the copy depends... the editing step is a later one that shares the copy
    assert [s.id for s in modupdate.dependents(log, s1)] == [s2.id]


def test_burger_shot_on_1013_loses_only_its_empty_lod_stub(manifest, rgame, state, log, downloads, helper):
    """The 0xBCC6AD fix (mods.json burgershot, gameBuilds <= 1.0.1013.x): the user's own copy of the pack in mods\
    loses the 146-byte LOD stub, so the game uses its own; everything else in the pack stays, the game's archives are
    never written, and rolling the step back gives the folder before the install."""
    from leonida.manifest import load_manifest

    game = rgame
    before = take_snapshot(game)
    orig_update = sha(game / "update" / "update.rpf")
    stub = r"x64\levels\gta5\basev.rpf\vb_03_bld2_e_slod_children.ydd"
    building = r"x64\levels\gta5\basev.rpf\vb_03_bld2.ydr"
    mlo = r"x64\levels\gta5\meta.rpf\vespucci_burgershot_milo_.ymap"
    pack = io.BytesIO()
    with zipfile.ZipFile(pack, "w") as zz:
        for n, d in {stub: b"stub", building: b"building", mlo: b"mlo"}.items():
            zz.writestr(n.replace("\\", "/"), d)
    z = make_zip(downloads / "66ab92-Burgershot_new.rar.zip", {"SP/burgershot/dlc.rpf": pack.getvalue()})
    real = load_manifest().for_build("1.0.1013.20").mod("burgershot")
    mod = rmod(manifest, real.rpf, files=real.files)
    step = _inst(manifest, game, state, log).install(mod, z)
    assert step.status == "done"
    copy = entries_of(game / "mods/update/x64/dlcpacks/burgershot/dlc.rpf")
    assert stub not in copy and copy[building] == b"building" and mlo in copy
    edits = json.loads(members_of(game / "mods/update/update.rpf")[r"__xml__\common\data\dlclist.xml.json"])
    assert [e["xml"] for e in edits if e["type"] == "add"] == ["<Item>dlcpacks:/burgershot/</Item>"]
    assert sha(game / "update" / "update.rpf") == orig_update            # the game's own archive: never written
    warnings = _inst(manifest, game, state, log).rollback(step.id)
    assert not warnings and diff(before, take_snapshot(game)).empty
