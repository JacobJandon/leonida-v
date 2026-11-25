"""Leonida's test place (leonida/quarantine.py): Defender scan (a stub here), static inspection, trial install, the
install gate, `leonida scan`. No real malware and no test signature (EICAR) is ever written: the stub Defender
decides by the file's name."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from conftest import AutoUI, flush_deletes, make_zip

from leonida import quarantine as Q
from leonida.cli import main
from leonida.detect import find_7zip
from leonida.installer import InstallError
from leonida.session import Session

STUB = '''import sys
args = sys.argv[1:]
path = args[args.index("-File") + 1]
name = path.lower()
print("Scan starting...")
print("Scan finished.")
if "infected" in name:
    print(f"Scanning {path} found 1 threats.")
    print("<===========================LIST OF DETECTED THREATS==========================>")
    print("----------------------------- Threat information ------------------------------")
    print("Threat                  : Trojan:Win32/LeonidaStub")
    print("Resources               : 1 total")
    sys.exit(2)
if "broken" in name:
    print("CmdTool: Failed with hr = 0x80508023. Check MpCmdRun.log for more information")
    sys.exit(2)
print(f"Scanning {path} found no threats.")
'''


@pytest.fixture
def defender(tmp_path, monkeypatch):
    stub = tmp_path / "MpCmdRun.py"
    stub.write_text(STUB)
    monkeypatch.setenv(Q.DEFENDER_ENV, str(stub))
    return stub


def _mod(mid, method="copy", files=("Mod.asi",), **extra):
    install = {"method": method}
    if method in ("copy", "generic"):
        install["files"] = [{"match": f} for f in files] if method == "copy" else []
    if method == "run":
        install["run"] = extra.pop("run", "setup*.exe")
        install["steps"] = ["Finish its installer."]
    if method == "guided":
        install["steps"] = ["Do it."]
    return {"id": mid, "order": extra.pop("order", 1), "tier": "core", "layer": "t", "name": mid.title(),
            "version": "1", "source": "direct", "page": f"https://{mid}.example/", "archive": [f"{mid}*"],
            "install": install, **extra}


@pytest.fixture
def kit(tmp_path, game, downloads):
    d = tmp_path / "manifest"
    d.mkdir()
    mods = [_mod("good", order=1), _mod("withexe", order=2), _mod("installer", "run", order=3),
            _mod("escape", order=4), _mod("hidden", order=5), _mod("infected", order=6)]
    (d / "mods.json").write_text(json.dumps({"pack": "L", "version": "1", "mods": mods}))
    (d / "profiles.json").write_text(json.dumps({"default": "p", "profiles": [
        {"id": "p", "name": "P", "include": [m["id"] for m in mods]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    s = Session(tmp_path / "st", d, download_dir=str(downloads), game_dir=str(game))
    files = {
        "good": make_zip(downloads / "good-1.zip", {"Mod.asi": "asi", "readme.txt": "r", "extras/opt.dll": "dll",
                                                    "extras/more.zip": "PK"}),
        "withexe": make_zip(downloads / "withexe-1.zip", {"Mod.asi": "asi", "tools/helper.exe": "MZ"}),
        "installer": make_zip(downloads / "installer-1.zip", {"setup_v1.exe": "MZ", "readme.txt": "r"}),
        "escape": make_zip(downloads / "escape-1.zip", {"Mod.asi": "asi", "../../Windows/evil.dll": "x"}),
        "hidden": make_zip(downloads / "hidden-1.zip", {"Mod.asi": "asi", "readme.txt.exe": "MZ"}),
        "infected": make_zip(downloads / "infected-1.zip", {"Mod.asi": "asi"}),
    }
    return s, files


# ------------------------------------------------------------------------------------------------- Defender
def test_defender_verdicts(defender, tmp_path):
    clean, bad, broken = (tmp_path / n for n in ("clean.bin", "infected.bin", "broken.bin"))
    for p in (clean, bad, broken):
        p.write_bytes(b"harmless bytes")
    assert Q.defender_scan(clean) == ("clean", "")
    assert Q.defender_scan(bad) == ("threat", "Trojan:Win32/LeonidaStub")
    verdict, detail = Q.defender_scan(broken)               # exit 2 without a threat: an error, not malware
    assert verdict == "error" and "0x80508023" in detail


def test_no_defender_means_not_scanned(monkeypatch, tmp_path):
    monkeypatch.setenv(Q.DEFENDER_ENV, "off")
    assert Q.defender_exe() is None
    p = tmp_path / "x.bin"
    p.write_bytes(b"x")
    assert Q.defender_scan(p)[0] == "unavailable"
    monkeypatch.setenv(Q.DEFENDER_ENV, str(tmp_path / "missing" / "MpCmdRun.exe"))
    assert Q.defender_scan(p)[0] == "unavailable"


def test_defender_found_on_this_pc_when_not_overridden(monkeypatch, tmp_path):
    monkeypatch.delenv(Q.DEFENDER_ENV, raising=False)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "PF"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "PD"))
    assert Q.defender_exe() is None
    plat = tmp_path / "PD" / "Microsoft" / "Windows Defender" / "Platform"
    for v in ("4.18.1-0", "4.18.2-0"):
        (plat / v).mkdir(parents=True)
        (plat / v / "MpCmdRun.exe").write_bytes(b"MZ")
    assert Q.defender_exe() == plat / "4.18.2-0" / "MpCmdRun.exe"   # the newest platform
    pf = tmp_path / "PF" / "Windows Defender"
    pf.mkdir(parents=True)
    (pf / "MpCmdRun.exe").write_bytes(b"MZ")
    assert Q.defender_exe() == pf / "MpCmdRun.exe"


# ----------------------------------------------------------------------------------------------- inspection
def test_inspection_flags(kit):
    s, files = kit
    m = s.manifest.mods

    def check(mid):
        plan = s.installer(AutoUI()).plan(m[mid], files[mid])
        return Q.inspect(files[mid], m[mid], plan)

    flags, notes, outside = check("good")
    assert flags == [] and outside == []
    assert any("extras/opt.dll" in n for n in notes) and any("extras/more.zip" in n for n in notes)
    flags, _, _ = check("withexe")
    assert flags == ["tools/helper.exe: a program or script this mod's install doesn't use"]
    assert check("installer")[0] == []                     # its own installer, the manifest's `run`
    flags, _, outside = check("escape")
    assert outside == ["../../Windows/evil.dll"] and "outside the game folder" in flags[0]
    assert check("hidden")[0] == ["readme.txt.exe: a program hidden behind another extension"]


def test_inspection_of_names_programs_and_passwords(tmp_path):
    exe = tmp_path / "Cool Mod.zip.exe"
    exe.write_bytes(b"MZ")
    flags, _, _ = Q.inspect(exe)
    assert "hides a program" in flags[0] and "is a program" in flags[1]
    enc = tmp_path / "locked.zip"
    with zipfile.ZipFile(enc, "w") as z:
        z.writestr("Mod.asi", b"x")
    data = bytearray(enc.read_bytes())                        # mark it encrypted, as a password-protected zip is:
    central = data.index(b"PK\x01\x02")                       # bit 0 of the central directory's flags
    data[central + 8] |= 0x1
    enc.write_bytes(bytes(data))
    assert Q.inspect(enc)[0] == ["password-protected: Leonida can't see what's inside"]
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert "couldn't look inside" in Q.inspect(bad)[1][0]


def test_oiv_targets_outside_the_game(tmp_path):
    pkg = tmp_path / "pack.oiv"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("assembly.xml", '<package><content><add source="a.dll">..\\..\\Windows\\a.dll</add>'
                   '<archive path="update\\update.rpf"><add source="b">x64\\b.meta</add></archive></content></package>')
        z.writestr("content/a.dll", "x")
    _, _, outside = Q.inspect(pkg)
    assert outside == [".oiv -> ..\\..\\Windows\\a.dll"]


@pytest.mark.skipif(find_7zip() is None, reason="7-Zip not installed")
def test_7z_listing_and_a_password_protected_7z(tmp_path):
    import subprocess

    seven = find_7zip()
    src = tmp_path / "src"
    (src / "scripts").mkdir(parents=True)
    (src / "scripts" / "Mod.dll").write_text("x")
    (src / "run.bat").write_text("echo")
    plain, locked = tmp_path / "plain.7z", tmp_path / "locked.7z"
    subprocess.run([str(seven), "a", str(plain), "."], cwd=src, capture_output=True, check=True)
    subprocess.run([str(seven), "a", "-pSecret", "-mhe=on", str(locked), "."], cwd=src, capture_output=True,
                   check=True)
    names = sorted(m.name.replace("\\", "/") for m in Q.list_archive(plain, seven))
    assert names == ["run.bat", "scripts/Mod.dll"]
    assert "run.bat: a program or script" in Q.inspect(plain, seven_zip=seven)[0][0]
    assert Q.inspect(locked, seven_zip=seven)[0] == ["password-protected: Leonida can't see what's inside"]


# ----------------------------------------------------------------------------------------- scan, cache, move
def test_scan_caches_and_quarantines(kit, defender, downloads):
    s, files = kit
    tp = s.test_place()
    good = tp.scan(files["good"], s.manifest.mods["good"])
    assert good.status == Q.OK and good.label == "scanned OK" and len(good.sha256) == 64
    assert tp.cached(files["good"]).status == Q.OK
    files["good"].write_bytes(files["good"].read_bytes() + b" ")   # changed file: the old result doesn't count
    assert tp.cached(files["good"]) is None
    bad = tp.scan(files["infected"], s.manifest.mods["infected"])
    q = downloads / Q.QUARANTINE_DIR / "infected-1.zip"
    assert bad.status == Q.QUARANTINED and bad.threat == "Trojan:Win32/LeonidaStub" and Path(bad.path) == q
    assert not files["infected"].exists() and q.is_file()
    assert "Trojan:Win32/LeonidaStub" in (q.parent / "infected-1.zip.reason.txt").read_text()
    assert "infected" not in s.matches().matched                   # the quarantine folder isn't a download
    assert Q.TestPlace(s.state, downloads).cached(q).status == Q.QUARANTINED  # survives a restart


def test_scan_report_only_keeps_the_file(kit, defender, downloads):
    s, files = kit
    r = s.test_place().scan(files["infected"], move=False)
    assert r.status == Q.QUARANTINED and files["infected"].exists()


def test_trial_install(kit, game):
    s, files = kit
    changes, clean, why = Q.trial_install(s.manifest.mods["good"], files["good"], s.manifest, game)
    assert why == "" and clean is True and changes == ["add Mod.asi"]
    assert not (game / "Mod.asi").exists()                         # the real game folder is never touched
    assert Q.trial_install(s.manifest.mods["installer"], files["installer"], s.manifest, game)[2].startswith("a run")
    r = s.test_place().scan(files["good"], s.manifest.mods["good"], manifest=s.manifest, game_dir=game, trial=True)
    assert r.trial == ["add Mod.asi"] and r.trial_ok and any("trial install: rolled back cleanly" in x
                                                              for x in r.lines())


# ------------------------------------------------------------------------------------------------ the gate
def test_install_refuses_flagged_and_quarantined_files(kit, defender, game):
    s, files = kit
    inst = s.installer(AutoUI())
    m = s.manifest.mods
    assert inst.install(m["good"], files["good"]).status == "done"
    with pytest.raises(InstallError, match="flagged by Leonida's test place.*helper.exe"):
        inst.install(m["withexe"], files["withexe"])
    with pytest.raises(InstallError, match="quarantined"):
        inst.install(m["infected"], files["infected"])
    assert not (game / "tools").exists()
    s.allow_unsafe.add("withexe")                                  # leonida install --force-unsafe, confirmed
    assert inst.install(m["withexe"], files["withexe"]).status == "done"


def test_not_scanned_files_still_install(kit, monkeypatch):
    monkeypatch.setenv(Q.DEFENDER_ENV, "off")
    s, files = kit
    assert s.installer(AutoUI()).install(s.manifest.mods["good"], files["good"]).status == "done"
    assert s.test_place().cached(files["good"]).status == Q.NOT_SCANNED


# ---------------------------------------------------------------------------------------------------- CLI
def _base(s, downloads, game, tmp_path):
    return ["--state-dir", str(s.state), "--manifest-dir", str(tmp_path / "manifest"), "--game-dir", str(game),
            "--download-dir", str(downloads)]


def test_cli_scan_get_and_install(kit, defender, downloads, game, tmp_path, capsys, monkeypatch):
    s, files = kit
    base = _base(s, downloads, game, tmp_path)
    assert main(base + ["scan", str(files["good"])]) == 0
    out = capsys.readouterr().out
    assert "good-1.zip: scanned OK" in out and "trial install: rolled back cleanly, 1 change(s)" in out
    assert main(base + ["scan", "--all", "--report-only"]) == 1        # something was found
    out = capsys.readouterr().out
    assert "withexe-1.zip: flagged" in out and "infected-1.zip: quarantined (Defender: Trojan" in out
    assert files["infected"].exists()                                   # report only: not moved
    main(base + ["get"])
    out = capsys.readouterr().out
    assert "scanned OK" in out and "flagged" in out
    assert main(base + ["install", "--only", "withexe", "--yes", "--no-pause"]) == 1
    assert "flagged by Leonida's test place" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda prompt="": "nope")
    assert main(base + ["install", "--only", "withexe", "--yes", "--no-pause", "--force-unsafe"]) == 1
    monkeypatch.setattr("builtins.input", lambda prompt="": "withexe")
    assert main(base + ["install", "--only", "withexe", "--yes", "--no-pause", "--force-unsafe"]) == 0
    assert (game / "Mod.asi").exists()


def test_cli_scan_without_files(kit, downloads, game, tmp_path, capsys):
    s, _ = kit
    base = _base(s, downloads, game, tmp_path)
    assert main(base + ["scan"]) == 2
    assert main(base + ["scan", str(tmp_path / "missing.zip")]) == 2
    shutil.rmtree(downloads)
    downloads.mkdir()
    assert main(base + ["scan", "--all"]) == 0 and "No downloads to scan" in capsys.readouterr().out


def test_stub_never_contains_a_real_signature():
    assert "EICAR" not in STUB.upper() and "X5O!P%" not in STUB


def test_gui_get_page_shows_each_files_status(qt_app, kit, defender, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("LEONIDA_NO_OPEN", "1")
    import leonida.gui.app as A

    s, files = kit
    s.test_place().scan(files["good"], s.manifest.mods["good"])
    s.test_place().scan(files["withexe"], s.manifest.mods["withexe"])
    win = A.MainWindow(s)
    page = win.pages[3]
    page.refresh()
    col = page.FILE if hasattr(page, "FILE") else 4
    texts = {page.table.item(r, 1).text(): page.table.item(r, col).text() for r in range(page.table.rowCount())}
    assert texts["Good"].endswith("· ✓ checked") and texts["Withexe"].endswith("· ⚠ flagged")
    assert texts["Installer"].endswith("· not checked yet")
    win.close()
    win.deleteLater()
    flush_deletes()




def test_a_setup_program_the_manifest_names_is_expected(tmp_path):
    from leonida.manifest import load_manifest

    openiv = load_manifest(edition="legacy").mods["openiv"]
    exe = tmp_path / "OpenIV_Setup.exe"
    exe.write_bytes(b"MZ")
    if any(p.lower().endswith(".exe") for p in openiv.archive):
        assert Q.inspect(exe, openiv)[0] == []                 # its author's installer, as the manifest says
    other = tmp_path / "Free_Cheats.exe"
    other.write_bytes(b"MZ")
    assert "is a program" in Q.inspect(other, openiv)[0][0]   # a program the manifest doesn't name


def test_oiv_paths_with_a_leading_backslash_stay_inside(tmp_path):
    r"""OpenIV writes archive paths like "\common\data\handling.meta": relative to the game/archive, not absolute
    (the real Drive V and Immersive Combat packages showed hundreds of false 'outside' lines)."""
    pkg = tmp_path / "drive.oiv"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("assembly.xml", r'<package><content><archive path="update\update.rpf">'
                   r'<add source="h">\common\data\handling.meta</add></archive>'
                   r'<add source="x">C:\Windows\x.dll</add><add source="y">\\server\share\y.dll</add>'
                   r'</content></package>')
    assert Q.inspect(pkg)[2] == [r".oiv -> C:\Windows\x.dll", r".oiv -> \\server\share\y.dll"]


def test_trial_install_of_a_mod_with_its_own_folders(kit, game):
    """The installer makes a mod's createDirs (and logs them): the trial mustn't make them first, or rolling back
    removes folders that were 'there before' (Jason Duval House was flagged for that)."""
    import dataclasses

    s, files = kit
    mod = dataclasses.replace(s.manifest.mods["good"], create_dirs=(r"mods\update\x64\dlcpacks",))
    changes, clean, _ = Q.trial_install(mod, files["good"], s.manifest, game)
    assert clean and changes[0] == "mkdir mods/update/x64/dlcpacks"   # logged with "/", so all of it rolls back
