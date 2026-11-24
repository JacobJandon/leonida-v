"""Windows-specific behaviour found on the first real-PC run (32-bit Python, awkward paths)."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from leonida import cli, detect
from leonida.installer import windows_launch_command

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_launch_command_double_quotes_the_path(tmp_path):
    p = tmp_path / "Mod (v2) & more" / "Install_GTA6Hud.bat"
    assert windows_launch_command(p) == f'cmd /d /c ""{p}""'


@windows_only
@pytest.mark.parametrize("folder", ["GTA 6 HUD (v2.1)", "HUD & Radar (Enhanced)"])
def test_launch_runs_bat_in_awkward_folder(tmp_path, folder):
    d = tmp_path / folder
    d.mkdir()
    bat = d / "Install Me.bat"
    bat.write_text("@echo off\r\necho ok> ran.txt\r\n", encoding="ascii")
    subprocess.run(windows_launch_command(bat), cwd=str(d), check=False, timeout=30)
    assert (d / "ran.txt").exists()


@windows_only
def test_find_7zip_sees_64bit_program_files(tmp_path, monkeypatch):
    seven = tmp_path / "Program Files" / "7-Zip"
    seven.mkdir(parents=True)
    (seven / "7z.exe").write_bytes(b"MZ")
    monkeypatch.setattr(detect.shutil, "which", lambda name: None)
    monkeypatch.setattr(detect, "_winreg_value", lambda *a: None)
    monkeypatch.setenv("ProgramW6432", str(tmp_path / "Program Files"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files (x86)"))  # what a 32-bit Python sees
    assert detect.find_7zip() == seven / "7z.exe"


@windows_only
@pytest.mark.skipif(not os.environ.get("ProgramW6432"), reason="needs 64-bit Windows")
def test_registry_reads_64bit_view():
    # 32-bit processes are redirected to WOW6432Node, where this value is "Program Files (x86)".
    val = detect._winreg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows\CurrentVersion", "ProgramFilesDir")
    assert val and val.lower() == os.environ["ProgramW6432"].lower()


def test_doctor_reports_python_bits(capsys, tmp_path):
    assert cli.main(["--state-dir", str(tmp_path), "doctor"]) == 0
    out = capsys.readouterr().out
    assert f"({detect.python_bits()}-bit)" in out
