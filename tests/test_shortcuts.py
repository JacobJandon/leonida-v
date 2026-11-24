"""Start menu / desktop shortcuts, Start-Leonida.bat's update swap, and the opt-in release dry run.

Shortcuts are only ever written into temp folders (LEONIDA_STARTMENU_DIR / LEONIDA_DESKTOP_DIR).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from leonida import cli
from leonida import shortcuts as SC

ROOT = Path(__file__).resolve().parent.parent
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    start, desk = tmp_path / "Start Menu" / "Programs", tmp_path / "Desktop"
    monkeypatch.setenv("LEONIDA_STARTMENU_DIR", str(start))
    monkeypatch.setenv("LEONIDA_DESKTOP_DIR", str(desk))
    monkeypatch.delenv("LEONIDA_NO_SHORTCUTS", raising=False)
    monkeypatch.delenv("LEONIDA_NO_DESKTOP_SHORTCUT", raising=False)
    return start, desk


# ------------------------------------------------------------------------------------------- folders / switches
def test_folders(monkeypatch, tmp_path):
    monkeypatch.delenv("LEONIDA_STARTMENU_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert SC.start_menu_dir() == tmp_path / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    monkeypatch.setenv("LEONIDA_STARTMENU_DIR", str(tmp_path / "s"))
    assert SC.start_menu_dir() == tmp_path / "s"
    monkeypatch.delenv("LEONIDA_DESKTOP_DIR", raising=False)
    monkeypatch.setattr(SC, "_powershell", lambda script, env: str(tmp_path / "OneDrive" / "Desktop"))
    assert SC.desktop_dir() == tmp_path / "OneDrive" / "Desktop"

    def fail(script, env):
        raise SC.ShortcutError("no powershell")

    monkeypatch.setattr(SC, "_powershell", fail)
    assert SC.desktop_dir() == Path.home() / "Desktop"
    monkeypatch.setattr(SC, "_powershell", lambda script, env: "")
    assert SC.desktop_dir() == Path.home() / "Desktop"
    monkeypatch.setenv("LEONIDA_DESKTOP_DIR", str(tmp_path / "d"))
    assert SC.desktop_dir() == tmp_path / "d"


def test_switched_off_and_not_windows(dirs, monkeypatch, tmp_path):
    monkeypatch.setenv("LEONIDA_NO_SHORTCUTS", "1")
    assert SC.create(tmp_path / "x.bat") == []
    monkeypatch.delenv("LEONIDA_NO_SHORTCUTS")
    monkeypatch.setattr(SC.sys, "platform", "linux")
    assert SC.create(tmp_path / "x.bat") == []
    assert not dirs[0].exists()


def test_create_passes_values_through_env(dirs, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(SC.sys, "platform", "win32")
    monkeypatch.setattr(SC, "_powershell", lambda script, env: seen.append(env) or "")
    monkeypatch.setenv("LEONIDA_NO_DESKTOP_SHORTCUT", "1")
    made = SC.create(tmp_path / "Start-Leonida.bat", icon="i.ico", workdir=tmp_path, minimized=True)
    assert made == [dirs[0] / "Leonida V.lnk"] and len(seen) == 1
    env = seen[0]
    assert env["LNK_TARGET"] == str((tmp_path / "Start-Leonida.bat").resolve()) and env["LNK_STYLE"] == "7"
    assert env["LNK_ICON"] == "i.ico" and env["LNK_WORKDIR"] == str(tmp_path.resolve())
    seen.clear()
    monkeypatch.delenv("LEONIDA_NO_DESKTOP_SHORTCUT")
    SC.create(tmp_path / "LeonidaV.exe")
    assert [e["LNK_STYLE"] for e in seen] == ["1", "1"] and seen[0]["LNK_ICON"] == ""
    assert seen[1]["LNK_WORKDIR"] == str(tmp_path.resolve())


def test_powershell_errors(monkeypatch):
    class P:
        returncode, stdout, stderr = 1, "", "boom"

    monkeypatch.setattr(SC.subprocess, "run", lambda *a, **k: P())
    with pytest.raises(SC.ShortcutError, match="boom"):
        SC._powershell("x", {})
    P.stderr = ""
    with pytest.raises(SC.ShortcutError, match="exit code 1"):
        SC._powershell("x", {})

    def missing(*a, **k):
        raise OSError("not found")

    monkeypatch.setattr(SC.subprocess, "run", missing)
    with pytest.raises(SC.ShortcutError, match="could not run"):
        SC._powershell("x", {})


def test_main_marker_and_errors(dirs, monkeypatch, tmp_path, capsys):
    made = []
    monkeypatch.setattr(SC, "create", lambda *a, **k: made.append((a, k)) or [tmp_path / "a.lnk"])
    marker = tmp_path / "State" / ".shortcuts-created"
    assert SC.main(["--target", "x.bat", "--minimized", "--no-desktop", "--marker", str(marker)]) == 0
    assert made[0][1]["minimized"] and made[0][1]["desktop"] is False and marker.read_text().strip().endswith("a.lnk")
    assert SC.main(["--target", "x.bat", "--marker", str(marker)]) == 0 and len(made) == 1  # once only
    assert "Shortcut:" in capsys.readouterr().out

    def broken(*a, **k):
        raise SC.ShortcutError("COM failed")

    monkeypatch.setattr(SC, "create", broken)
    assert SC.main(["--target", "x.bat"]) == 1
    assert "COM failed" in capsys.readouterr().err


@windows_only
def test_real_shortcuts_in_temp_folders(dirs, tmp_path):
    target = tmp_path / "kit" / "Start-Leonida.bat"
    target.parent.mkdir()
    target.write_text("@echo off\r\n")
    icon = ROOT / "leonida" / "gui" / "assets" / "leonida.ico"
    made = SC.create(target, icon=icon, workdir=target.parent, minimized=True)
    assert made == [dirs[0] / "Leonida V.lnk", dirs[1] / "Leonida V.lnk"] and all(p.is_file() for p in made)
    info = SC.read(made[0])
    assert info["target"].lower() == str(target).lower() and info["style"] == "7"
    assert info["workdir"].lower() == str(target.parent).lower() and info["icon"].lower().startswith(str(icon).lower())


# ------------------------------------------------------------------------------------------- leonida --create-shortcuts
def test_cli_create_shortcuts(dirs, monkeypatch, tmp_path, capsys):
    calls = []
    monkeypatch.setattr(SC, "create", lambda target, **k: calls.append((target, k)) or [dirs[0] / "Leonida V.lnk"])
    assert cli.main(["--state-dir", str(tmp_path / "st"), "--create-shortcuts", "--no-desktop"]) == 0
    target, kw = calls[0]
    assert target.name == "Start-Leonida.bat" and kw["minimized"] and kw["desktop"] is False
    assert kw["icon"].endswith("leonida.ico") and "Shortcut:" in capsys.readouterr().out
    monkeypatch.setattr(SC, "create", lambda target, **k: [])
    assert cli.main(["--state-dir", str(tmp_path / "st"), "shortcuts"]) == 0
    assert "No shortcuts made" in capsys.readouterr().out

    def broken(target, **k):
        raise SC.ShortcutError("denied")

    monkeypatch.setattr(SC, "create", broken)
    assert cli.main(["--state-dir", str(tmp_path / "st"), "shortcuts"]) == 1
    assert "denied" in capsys.readouterr().out


def test_cli_shortcut_target_frozen_and_missing(monkeypatch, tmp_path, capsys):
    exe = tmp_path / "LeonidaV" / "leonida.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    target, icon, minimized = cli.shortcut_target()
    assert target == exe.with_name("LeonidaV.exe") and icon == f"{target},0" and minimized is False
    assert cli.main(["--state-dir", str(tmp_path / "st"), "shortcuts"]) == 1  # LeonidaV.exe isn't there
    assert "doesn't exist" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------- Start-Leonida.bat swap
@windows_only
def test_start_leonida_applies_a_staged_update(tmp_path):
    kit = tmp_path / "Leonida"
    (kit / "leonida-v").mkdir(parents=True)
    (kit / "leonida-v" / "old.txt").write_text("old")
    new = kit / "leonida-v.new"
    new.mkdir()
    (new / "pyproject.toml").write_text("[project]")
    (new / ".leonida-update-ready").write_text("9.9.9")
    (kit / ".venv").mkdir()
    (kit / ".venv" / ".leonida-installed").write_text("ok")
    shutil.copy2(ROOT / "Start-Leonida.bat", kit / "Start-Leonida.bat")
    env = dict(os.environ, LEONIDA_SWAP_ONLY="1", LEONIDA_NO_SHORTCUTS="1")
    p = subprocess.run(["cmd", "/d", "/c", str(kit / "Start-Leonida.bat")], cwd=kit, env=env, capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Updated." in p.stdout
    assert (kit / "leonida-v" / "pyproject.toml").is_file() and not new.exists()
    assert (kit / "leonida-v.old" / "old.txt").is_file() and not (kit / "leonida-v" / ".leonida-update-ready").exists()
    assert not (kit / ".venv" / ".leonida-installed").exists() and (kit / "State").is_dir()


def test_start_leonida_keeps_crlf():
    data = (ROOT / "Start-Leonida.bat").read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n") and b"\x07" not in data
    assert b"LEONIDA_SWAP_ONLY" in data and b"-m leonida.shortcuts" in data


# ------------------------------------------------------------------------------------------- opt-in release dry run
@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get("LEONIDA_E2E_RELEASE") or sys.platform != "win32",
                    reason="set LEONIDA_E2E_RELEASE=1 after `python build/build_exe.py --release`")
def test_release_dry_run():
    spec = importlib.util.spec_from_file_location("e2e_update", ROOT / "build" / "e2e_update.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    rep = mod.run()
    assert rep.passed, "\n".join(rep.problems)
