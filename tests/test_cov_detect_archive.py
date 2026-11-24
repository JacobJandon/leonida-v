"""Coverage for detect.py (stores, registry, exe version, GPU, prerequisites, 7-Zip) and archive.py (zip / 7z / rar).

Registry, PowerShell and subprocess calls are monkeypatched; the Windows-only tests also make real read-only calls
(HKLM keys, the version resource of C:\\Windows\\System32\\kernel32.dll, a real 7z.exe if installed).
The real game folder is never looked at: every store lookup inside detect_games is replaced.
"""

from __future__ import annotations

import ctypes
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import make_zip

from leonida import archive, detect
from leonida.archive import ArchiveError, extract, is_archive, list_members

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
EXE = ("GTA5_Enhanced.exe",)
KERNEL32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "kernel32.dll"
SEVEN_ZIP = Path(r"C:\Program Files\7-Zip\7z.exe")


@pytest.fixture
def not_windows(monkeypatch):
    """Make detect.py take its non-Windows branches without touching the real sys.platform."""
    monkeypatch.setattr(detect, "sys", SimpleNamespace(platform="linux"))


@pytest.fixture
def no_fake_version(monkeypatch):
    monkeypatch.delenv("LEONIDA_FAKE_GAME_VERSION", raising=False)


# ============================================================================================ detect: basics
def test_find_exe_and_is_game_dir(tmp_path):
    assert detect.find_exe(tmp_path / "missing", EXE) is None
    (tmp_path / "readme.txt").write_text("x")
    (tmp_path / "GTA5_Enhanced.exe").mkdir()  # a folder with the exe's name is not the exe
    assert detect.find_exe(tmp_path, EXE) is None and not detect.is_game_dir(tmp_path, EXE)
    other = tmp_path / "g"
    other.mkdir()
    (other / "gta5_enhanced.EXE").write_bytes(b"MZ")
    assert detect.find_exe(other, EXE) == other / "gta5_enhanced.EXE"  # case-insensitive
    assert detect.is_game_dir(other, EXE)


def test_parse_version_edge_cases():
    assert detect.parse_version(None) is None
    assert detect.parse_version("") is None
    assert detect.parse_version("no digits") is None
    assert detect.parse_version("v1.0.1158.13-beta") == (1, 0, 1158, 13)
    assert detect.compare_versions("1.0", "1.0.0.0") == 0  # padded with zeros
    assert detect.compare_versions("1.0.1", "garbage") is None


def test_python_bits():
    assert detect.python_bits() == struct.calcsize("P") * 8 in (32, 64)


# ============================================================================================ detect: version
def test_exe_version_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.9999.1")
    assert detect.exe_version(tmp_path / "does-not-matter.exe") == "1.0.9999.1"


def test_exe_version_and_description_off_windows(not_windows, no_fake_version, tmp_path):
    assert detect.exe_version(tmp_path / "x.exe") is None
    assert detect.file_description(tmp_path / "x.dll") is None


@windows_only
def test_exe_version_real_dll(no_fake_version):
    ver = detect.exe_version(KERNEL32)
    assert ver and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ver)
    assert detect.parse_version(ver)[0] >= 6  # Windows 7+ system DLLs


@windows_only
def test_exe_version_without_version_resource(no_fake_version, tmp_path):
    f = tmp_path / "fake.exe"
    f.write_bytes(b"MZ not a real exe")
    assert detect.exe_version(f) is None
    assert detect.file_description(f) is None


@windows_only
def test_file_description_real_dll():
    desc = detect.file_description(KERNEL32)
    assert desc and "Microsoft" in desc and len(desc) <= 120


class _FakeVersionDLL:
    """Stand-in for version.dll: size / GetFileVersionInfoW / VerQueryValueW results are configurable."""

    def __init__(self, size=64, info=1, query=0, raise_on=None):
        self.size, self.info, self.query, self.raise_on = size, info, query, raise_on
        self.queries: list[str] = []

    def GetFileVersionInfoSizeW(self, path, _):  # noqa: N802 - Win32 name
        if self.raise_on == "size":
            raise OSError("boom")
        return self.size

    def GetFileVersionInfoW(self, path, _zero, size, buf):  # noqa: N802
        return self.info

    def VerQueryValueW(self, buf, sub, ptr, length):  # noqa: N802
        self.queries.append(sub)
        return self.query


@pytest.fixture
def fake_version_dll(monkeypatch):
    def install(**kw):
        dll = _FakeVersionDLL(**kw)
        monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error=False: dll, raising=False)
        return dll
    return install


@windows_only
def test_exe_version_get_info_fails(no_fake_version, fake_version_dll, tmp_path):
    fake_version_dll(info=0)
    assert detect.exe_version(tmp_path / "a.exe") is None


@windows_only
def test_exe_version_query_fails(no_fake_version, fake_version_dll, tmp_path):
    dll = fake_version_dll(info=1, query=0)
    assert detect.exe_version(tmp_path / "a.exe") is None
    assert dll.queries == ["\\"]


@windows_only
def test_exe_version_and_description_swallow_errors(no_fake_version, fake_version_dll, tmp_path):
    fake_version_dll(raise_on="size")
    assert detect.exe_version(tmp_path / "a.exe") is None
    assert detect.file_description(tmp_path / "a.dll") is None


@windows_only
def test_file_description_get_info_fails(fake_version_dll, tmp_path):
    fake_version_dll(info=0)
    assert detect.file_description(tmp_path / "a.dll") is None


@windows_only
def test_file_description_without_strings(fake_version_dll, tmp_path):
    dll = fake_version_dll(info=1, query=0)  # no translation table, no string values
    assert detect.file_description(tmp_path / "a.dll") is None
    # falls back to the two default code pages for each name it looks up
    assert "\\StringFileInfo\\040904b0\\FileDescription" in dll.queries
    assert "\\StringFileInfo\\040904e4\\CompanyName" in dll.queries


# ============================================================================================ detect: registry
def test_registry_readers_off_windows(not_windows):
    assert detect._winreg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\x", "y") is None
    assert detect._winreg_subkeys("HKEY_LOCAL_MACHINE", r"SOFTWARE\x") == []


def test_registry_readers_without_winreg(monkeypatch):
    monkeypatch.setattr(detect, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setitem(sys.modules, "winreg", None)  # `import winreg` -> ImportError
    assert detect._winreg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\x", "y") is None
    assert detect._winreg_subkeys("HKEY_LOCAL_MACHINE", r"SOFTWARE\x") == []


@windows_only
def test_registry_views_are_64_and_32_bit():
    import winreg

    views = detect._registry_views()
    assert views == (winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ | winreg.KEY_WOW64_32KEY)


@windows_only
def test_winreg_value_missing_key_and_value():
    assert detect._winreg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\LeonidaV-does-not-exist", "x") is None
    assert detect._winreg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows\CurrentVersion",
                                "LeonidaV-no-such-value") is None


@windows_only
def test_winreg_subkeys_real_and_missing():
    names = detect._winreg_subkeys("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft")
    assert "Windows" in names
    assert len(names) == len(set(names))  # both registry views are merged without duplicates
    assert detect._winreg_subkeys("HKEY_LOCAL_MACHINE", r"SOFTWARE\LeonidaV-does-not-exist") == []


# ============================================================================================ detect: stores
def test_steam_candidates_from_libraryfolders(monkeypatch, tmp_path):
    steam = tmp_path / "Steam"
    lib = tmp_path / "SteamLibrary"
    (steam / "steamapps").mkdir(parents=True)
    escaped = str(lib).replace("\\", "\\\\")
    vdf = '"libraryfolders"\n{\n "1"\n {\n  "path"  "' + escaped + '"\n }\n}'
    (steam / "steamapps" / "libraryfolders.vdf").write_text(vdf, encoding="utf-8")
    calls = []

    def fake_value(root, key, value):
        calls.append((root, key, value))
        return str(steam)

    monkeypatch.setattr(detect, "_winreg_value", fake_value)
    out = detect._steam_candidates()
    assert calls == [("HKEY_CURRENT_USER", r"Software\Valve\Steam", "SteamPath")]
    expected = [root / "steamapps" / "common" / n for root in (steam, lib) for n in detect.GAME_DIR_NAMES]
    assert out == expected


def test_steam_candidates_without_vdf_or_steam(monkeypatch, tmp_path):
    monkeypatch.setattr(detect, "_winreg_value", lambda *a: str(tmp_path))
    assert detect._steam_candidates() == [tmp_path / "steamapps" / "common" / n for n in detect.GAME_DIR_NAMES]
    monkeypatch.setattr(detect, "_winreg_value", lambda *a: None)
    assert detect._steam_candidates() == []


def test_epic_candidates_default_dir_and_bad_items(monkeypatch, tmp_path):
    base = tmp_path / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    base.mkdir(parents=True)
    (base / "broken.item").write_text("{not json", encoding="utf-8")
    (base / "nameless.item").write_text(json.dumps({"InstallLocation": "E:/x"}), encoding="utf-8")
    (base / "noloc.item").write_text(json.dumps({"DisplayName": "GTA V"}), encoding="utf-8")
    (base / "gta.item").write_text(json.dumps({"DisplayName": "GTA V Enhanced", "InstallLocation": "E:/Epic/GTAV"}),
                                   encoding="utf-8")
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    assert detect._epic_candidates() == [Path("E:/Epic/GTAV")]
    assert detect._epic_candidates(tmp_path / "nowhere") == []


def test_rockstar_and_common_off_windows(not_windows):
    assert detect._rockstar_candidates() == []
    assert detect._common_candidates() == []


@windows_only
def test_rockstar_candidates_from_registry(monkeypatch):
    values = {r"SOFTWARE\Rockstar Games\GTAV Enhanced": r"D:\R\GTAV Enhanced",
              r"SOFTWARE\Rockstar Games\Launcher": None,
              r"SOFTWARE\Rockstar Games\GTAV Enhanced (dup)": r"D:\R\GTAV Enhanced"}
    seen = []
    monkeypatch.setattr(detect, "_winreg_subkeys", lambda root, key: seen.append((root, key)) or [
        "GTAV Enhanced", "Launcher", "GTAV Enhanced (dup)"])
    monkeypatch.setattr(detect, "_winreg_value", lambda root, key, value: values[key] if value == "InstallFolder" else None)
    assert detect._rockstar_candidates() == [Path(r"D:\R\GTAV Enhanced")]
    assert seen == [("HKEY_LOCAL_MACHINE", r"SOFTWARE\Rockstar Games")]


@windows_only
def test_common_candidates_cover_existing_drives():
    out = detect._common_candidates()
    assert out and all(p.name in detect.GAME_DIR_NAMES for p in out)
    drives = {p.drive.upper() for p in out}
    assert "C:" in drives and drives <= {f"{c}:" for c in "CDEFGH"}
    assert Path(r"C:\Games\Grand Theft Auto V Enhanced") in out


def test_detect_games_order_dedupe_and_errors(monkeypatch, tmp_path):
    def make_game(name):
        g = tmp_path / name
        g.mkdir()
        (g / "GTA5_Enhanced.exe").write_bytes(b"MZ")
        return g

    manual, steam, epic = make_game("manual"), make_game("steam"), make_game("epic")
    bad = make_game("bad")
    monkeypatch.setattr(detect, "_steam_candidates", lambda: [steam, manual, tmp_path / "empty"])
    monkeypatch.setattr(detect, "_epic_candidates", lambda: [epic, bad])
    monkeypatch.setattr(detect, "_rockstar_candidates", lambda: [str(steam)])  # same folder as text
    monkeypatch.setattr(detect, "_common_candidates", lambda: [])
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1158.13")
    real_resolve = pathlib.Path.resolve

    def resolve(self, strict=False):
        if self.name == "bad":
            raise OSError("unreadable")
        return real_resolve(self, strict)

    monkeypatch.setattr(pathlib.Path, "resolve", resolve)
    found = detect.detect_games(EXE, extra=[manual, manual])
    assert [(g.source, g.path.name) for g in found] == [("manual", "manual"), ("steam", "steam"), ("epic", "epic")]
    assert all(g.version == "1.0.1158.13" and g.exe.name == "GTA5_Enhanced.exe" for g in found)


def test_detect_games_nothing(monkeypatch):
    for fn in ("_steam_candidates", "_epic_candidates", "_rockstar_candidates", "_common_candidates"):
        monkeypatch.setattr(detect, fn, lambda: [])
    assert detect.detect_games(EXE) == []


# ============================================================================================ detect: GPU
def test_detect_gpus_override(monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GPU", "NVIDIA GeForce RTX 5090;;AMD Radeon RX 9070;")
    assert detect.detect_gpus() == ["NVIDIA GeForce RTX 5090", "AMD Radeon RX 9070"]
    monkeypatch.setenv("LEONIDA_FAKE_GPU", "")
    assert detect.detect_gpus() == []


def test_detect_gpus_off_windows(monkeypatch, not_windows):
    monkeypatch.delenv("LEONIDA_FAKE_GPU", raising=False)
    monkeypatch.setattr(detect.subprocess, "run", lambda *a, **k: pytest.fail("no PowerShell off Windows"))
    assert detect.detect_gpus() == []


def test_detect_gpus_parses_powershell(monkeypatch):
    monkeypatch.setattr(detect, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.delenv("LEONIDA_FAKE_GPU", raising=False)
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return SimpleNamespace(stdout="NVIDIA GeForce RTX 5080\r\n\r\n   Intel(R) UHD Graphics 770  \n", returncode=0)

    monkeypatch.setattr(detect.subprocess, "run", fake_run)
    gpus = detect.detect_gpus()
    assert gpus == ["NVIDIA GeForce RTX 5080", "Intel(R) UHD Graphics 770"] and detect.is_rtx50(gpus)
    cmd, kw = calls[0]
    assert cmd[0] == "powershell" and "Win32_VideoController" in cmd[-1]
    assert kw["timeout"] == 20 and kw["check"] is False


@pytest.mark.parametrize("exc", [OSError("no powershell"), subprocess.TimeoutExpired("powershell", 20)])
def test_detect_gpus_failure(monkeypatch, exc):
    monkeypatch.setattr(detect, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.delenv("LEONIDA_FAKE_GPU", raising=False)

    def fail(*a, **k):
        raise exc

    monkeypatch.setattr(detect.subprocess, "run", fail)
    assert detect.detect_gpus() == []


# ============================================================================================ detect: prerequisites
def test_prerequisites_off_windows(not_windows):
    assert detect.check_prerequisites() == {"dotnet48": None, "vcredist": None}


@pytest.mark.parametrize("values, expected", [
    ({"Release": "528372", ("Installed", 0): "1"}, {"dotnet48": True, "vcredist": True}),
    ({"Release": "461808", ("Installed", 1): "0"}, {"dotnet48": False, "vcredist": False}),
    ({"Release": "528040", ("Installed", 1): "1"}, {"dotnet48": True, "vcredist": True}),  # only WOW6432Node key
    ({"Release": "not-a-number"}, {"dotnet48": False, "vcredist": False}),
    ({}, {"dotnet48": False, "vcredist": False}),
])
def test_prerequisites_from_registry(monkeypatch, values, expected):
    monkeypatch.setattr(detect, "sys", SimpleNamespace(platform="win32"))
    vc_keys = [r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
               r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"]

    def fake_value(root, key, value):
        assert root == "HKEY_LOCAL_MACHINE"
        if value == "Release":
            assert key.endswith(r"NDP\v4\Full")
            return values.get("Release")
        return values.get((value, vc_keys.index(key)))

    monkeypatch.setattr(detect, "_winreg_value", fake_value)
    assert detect.check_prerequisites() == expected


@windows_only
def test_prerequisites_real_registry():
    res = detect.check_prerequisites()
    assert set(res) == {"dotnet48", "vcredist"} and all(isinstance(v, bool) for v in res.values())


# ============================================================================================ detect: 7-Zip
def test_find_7zip_on_path(monkeypatch, tmp_path):
    exe = tmp_path / "7z.exe"
    monkeypatch.setattr(detect.shutil, "which", lambda name: str(exe) if name == "7z" else None)
    assert detect.find_7zip() == exe
    monkeypatch.setattr(detect.shutil, "which", lambda name: str(exe) if name == "7za" else None)
    assert detect.find_7zip() == exe


def test_find_7zip_off_windows_not_found(monkeypatch, not_windows):
    monkeypatch.setattr(detect.shutil, "which", lambda name: None)
    assert detect.find_7zip() is None


@windows_only
def test_find_7zip_from_registry_path64(monkeypatch, tmp_path):
    seven = tmp_path / "Seven"
    seven.mkdir()
    (seven / "7z.exe").write_bytes(b"MZ")
    monkeypatch.setattr(detect.shutil, "which", lambda name: None)
    monkeypatch.setattr(detect, "_winreg_value", lambda root, key, value: str(seven) if value == "Path64" else None)
    assert detect.find_7zip() == seven / "7z.exe"


@windows_only
def test_find_7zip_skips_folders_without_exe(monkeypatch, tmp_path):
    empty = tmp_path / "Empty7z"
    empty.mkdir()
    pf = tmp_path / "PF"
    (pf / "7-Zip").mkdir(parents=True)
    (pf / "7-Zip" / "7z.exe").write_bytes(b"MZ")
    monkeypatch.setattr(detect.shutil, "which", lambda name: None)
    monkeypatch.setattr(detect, "_winreg_value", lambda root, key, value: str(empty) if value == "Path" else None)
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.setenv("ProgramFiles", str(pf))
    assert detect.find_7zip() == pf / "7-Zip" / "7z.exe"


# ============================================================================================ archive
def test_is_archive():
    assert is_archive(Path("a.ZIP")) and is_archive(Path("b.7z")) and is_archive(Path("c.Rar"))
    assert not is_archive(Path("d.oiv")) and not is_archive(Path("e.exe"))


def test_bad_zip(tmp_path):
    p = tmp_path / "broken.zip"
    p.write_bytes(b"PK\x03\x04 definitely not a zip")
    with pytest.raises(ArchiveError, match="broken.zip is not a valid zip"):
        list_members(p)


def test_not_an_archive(tmp_path):
    p = tmp_path / "readme.txt"
    p.write_text("x")
    with pytest.raises(ArchiveError, match="is not an archive"):
        list_members(p)
    with pytest.raises(ArchiveError, match="is not an archive"):
        extract(p, tmp_path / "out")


def test_zip_extract_normal_and_absolute(tmp_path):
    z = make_zip(tmp_path / "ok.zip", {"a/b.txt": "b", "c.txt": "c"})
    assert sorted(list_members(z)) == ["a/b.txt", "c.txt"]
    out = extract(z, tmp_path / "out")
    assert (out / "a" / "b.txt").read_text() == "b" and (out / "c.txt").read_text() == "c"
    evil = make_zip(tmp_path / "abs.zip", {"C:/Windows/evil.dll": "x"})
    with pytest.raises(ArchiveError, match="unsafe path"):
        extract(evil, tmp_path / "out2")


@windows_only
def test_zip_drive_relative_member_rejected(tmp_path):
    # "Q:evil.txt" (another drive, drive-relative) passes the name check but resolves outside the destination.
    other = "Q" if not str(tmp_path).upper().startswith("Q") else "R"
    z = make_zip(tmp_path / "drive.zip", {f"{other}:evil.txt": "x"})
    with pytest.raises(ArchiveError, match="unsafe path"):
        extract(z, tmp_path / "out")
    assert not any((tmp_path / "out").iterdir())


SLT = """Path = Mod
Size = 0
Attributes = D
CRC =

Path = Mod\\bin\\Mod.asi
Size = 3
Attributes = A
CRC = ED6F7A7A

Path = Mod\\empty
Folder = +
Size = 0

Path = Mod\\readme.txt
Folder = -
Size = 5
Attributes = A"""


class _Fake7z:
    def __init__(self, listing=SLT, list_rc=0, extract_rc=0, stderr="ERROR: Data Error"):
        self.listing, self.list_rc, self.extract_rc, self.stderr = listing, list_rc, extract_rc, stderr
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        assert kw.get("capture_output") and kw.get("check") is False
        if cmd[1] == "l":
            return SimpleNamespace(returncode=self.list_rc, stdout=self.listing, stderr=self.stderr)
        return SimpleNamespace(returncode=self.extract_rc, stdout="", stderr=self.stderr)


@pytest.fixture
def fake7z(monkeypatch):
    def install(**kw):
        fake = _Fake7z(**kw)
        monkeypatch.setattr(archive.subprocess, "run", fake)
        return fake
    return install


@pytest.mark.parametrize("ext", [".7z", ".rar"])
def test_7z_listing_parses_slt(tmp_path, fake7z, ext):
    fake = fake7z()
    p = tmp_path / f"mod{ext}"
    p.write_bytes(b"x")
    assert list_members(p, Path("7z.exe")) == ["Mod/bin/Mod.asi", "Mod/readme.txt"]
    assert fake.calls == [["7z.exe", "l", "-slt", "-ba", str(p)]]


def test_7z_listing_error(tmp_path, fake7z):
    fake7z(list_rc=2, stderr="  ERROR: Can not open the file as archive  ")
    p = tmp_path / "bad.7z"
    p.write_bytes(b"x")
    with pytest.raises(ArchiveError, match="7-Zip could not list bad.7z: ERROR: Can not open the file as archive$"):
        list_members(p, Path("7z.exe"))


def test_7z_extract_success(tmp_path, fake7z):
    fake = fake7z()
    p = tmp_path / "mod.7z"
    p.write_bytes(b"x")
    dest = tmp_path / "out"
    assert extract(p, dest, Path("7z.exe")) == dest and dest.is_dir()
    assert fake.calls[-1] == ["7z.exe", "x", "-y", f"-o{dest}", str(p)]


def test_7z_extract_refuses_unsafe_member(tmp_path, fake7z):
    fake = fake7z(listing="Path = ..\\..\\evil.dll\nSize = 1\nAttributes = A\n")
    p = tmp_path / "evil.rar"
    p.write_bytes(b"x")
    with pytest.raises(ArchiveError, match="unsafe path in archive: '../../evil.dll'"):
        extract(p, tmp_path / "out", Path("7z.exe"))
    assert [c[1] for c in fake.calls] == ["l"]  # never extracted


def test_7z_extract_error(tmp_path, fake7z):
    fake7z(extract_rc=2, stderr="ERROR: CRC Failed : Mod.asi")
    p = tmp_path / "mod.7z"
    p.write_bytes(b"x")
    with pytest.raises(ArchiveError, match="7-Zip could not extract mod.7z: ERROR: CRC Failed"):
        extract(p, tmp_path / "out", Path("7z.exe"))


def test_7z_extract_without_7zip(tmp_path):
    p = tmp_path / "mod.rar"
    p.write_bytes(b"x")
    with pytest.raises(ArchiveError, match="install 7-Zip"):
        extract(p, tmp_path / "out", None)


@pytest.mark.skipif(not SEVEN_ZIP.exists(), reason="needs 7-Zip at C:\\Program Files\\7-Zip")
def test_real_7z_round_trip(tmp_path):
    src = tmp_path / "src"
    (src / "Mod" / "bin").mkdir(parents=True)
    (src / "Mod" / "empty").mkdir()
    (src / "Mod" / "bin" / "Mod.asi").write_bytes(b"asi bytes")
    (src / "Mod" / "Mod.ini").write_text("[x]\n")
    arc = tmp_path / "Real Mod (v1).7z"
    subprocess.run([str(SEVEN_ZIP), "a", str(arc), "Mod"], cwd=src, check=True, capture_output=True)
    assert sorted(list_members(arc, SEVEN_ZIP)) == ["Mod/Mod.ini", "Mod/bin/Mod.asi"]
    out = extract(arc, tmp_path / "out dir", SEVEN_ZIP)
    assert (out / "Mod" / "bin" / "Mod.asi").read_bytes() == b"asi bytes"
    assert (out / "Mod" / "Mod.ini").read_text() == "[x]\n"


@pytest.mark.skipif(not (SEVEN_ZIP.exists() or shutil.which("7z")), reason="needs 7-Zip")
def test_real_7z_rejects_garbage(tmp_path):
    seven = SEVEN_ZIP if SEVEN_ZIP.exists() else Path(shutil.which("7z"))
    p = tmp_path / "garbage.7z"
    p.write_bytes(b"this is not a 7z archive" * 10)
    with pytest.raises(ArchiveError, match="7-Zip could not list garbage.7z"):
        list_members(p, seven)
