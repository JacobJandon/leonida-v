"""The per-user setup and uninstall (leonida/winsetup.py), its native dialogs (setupui) and the setup exe's entry.
Everything goes into temp folders and a throwaway HKCU\\Software\\LeonidaV-pytest-* key; never the real Start menu,
registry entries, %LOCALAPPDATA% or a game."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows setup (registry, shortcuts)")

ROOT = Path(__file__).resolve().parent.parent
if sys.platform == "win32":
    import winreg

    from leonida import paths, setupui, winsetup


@pytest.fixture
def reg_root(monkeypatch, tmp_path):
    root = f"Software\\LeonidaV-pytest-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("LEONIDA_REG_ROOT", root)
    monkeypatch.setenv("LEONIDA_NO_SHORTCUTS", "1")
    monkeypatch.setenv("LEONIDA_STARTMENU_DIR", str(tmp_path / "menu"))   # never the real Start menu / desktop
    monkeypatch.setenv("LEONIDA_DESKTOP_DIR", str(tmp_path / "desk"))
    monkeypatch.setattr(winsetup, "leonida_running", lambda d: [])
    yield root
    _delete_tree(root)


def _delete_tree(key: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            subs = []
            i = 0
            while True:
                try:
                    subs.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
        for s in subs:
            _delete_tree(f"{key}\\{s}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    except OSError:
        pass


def make_payload(tmp: Path, version: str = "1.0.0", marker: str = "") -> Path:
    z = tmp / f"LeonidaV-{version}-win64.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("LeonidaV/LeonidaV.exe", b"MZ gui " + version.encode())
        f.writestr("LeonidaV/leonida.exe", b"MZ cli")
        f.writestr("LeonidaV/_internal/base_library.zip", b"x" * 2048)
        if marker:
            f.writestr(f"LeonidaV/{marker}", b"m")
    return z


def places(tmp: Path) -> tuple[Path, Path]:
    return tmp / "Programs" / "Leonida V", tmp / "Leonida V"


# ------------------------------------------------------------------------------------------------- install
def test_install_registers_and_prepares_data(tmp_path, reg_root):
    install, data = places(tmp_path)
    res = winsetup.install(make_payload(tmp_path), install, data, version="1.0.0")
    assert (install / "LeonidaV.exe").read_bytes() == b"MZ gui 1.0.0" and (install / "_internal").is_dir()
    assert not res.upgraded and res.install_dir == install and res.data_dir == data
    reg = winsetup.registered()
    assert reg == {"InstallDir": str(install), "DataDir": str(data), "Version": "1.0.0"}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{reg_root}\\Uninstall\\LeonidaV") as k:
        assert winreg.QueryValueEx(k, "DisplayName")[0] == "Leonida V"
        assert winreg.QueryValueEx(k, "UninstallString")[0] == f'"{install / "LeonidaV.exe"}" --uninstall'
        assert winreg.QueryValueEx(k, "QuietUninstallString")[0].endswith("--uninstall --silent")
        assert winreg.QueryValueEx(k, "NoModify")[0] == 1 and winreg.QueryValueEx(k, "EstimatedSize")[0] >= 2
    cfg = json.loads((data / "State" / "config.json").read_text(encoding="utf-8"))
    assert cfg["download_dir"] == str(data / "Downloads") and (data / "Downloads").is_dir()
    assert not install.with_name("Leonida V.setup-new").exists() and not install.with_name("Leonida V.setup-old").exists()


def test_upgrade_keeps_data_and_replaces_the_program(tmp_path, reg_root):
    install, data = places(tmp_path)
    winsetup.install(make_payload(tmp_path, "1.0.0", marker="old-only.txt"), install, data, version="1.0.0")
    (data / "State" / "mine.txt").write_text("keep", encoding="utf-8")
    cfg = json.loads((data / "State" / "config.json").read_text(encoding="utf-8"))
    cfg["download_dir"] = "E:\\MyMods"
    (data / "State" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    new = tmp_path / "new"
    new.mkdir()
    res = winsetup.install(make_payload(new, "1.1.0"), install, version="1.1.0")  # data folder from the registry
    assert res.upgraded and res.data_dir == data and winsetup.registered()["Version"] == "1.1.0"
    assert (install / "LeonidaV.exe").read_bytes() == b"MZ gui 1.1.0" and not (install / "old-only.txt").exists()
    assert (data / "State" / "mine.txt").read_text(encoding="utf-8") == "keep"
    assert json.loads((data / "State" / "config.json").read_text(encoding="utf-8"))["download_dir"] == "E:\\MyMods"


def test_never_in_the_game_folder_or_over_other_files(tmp_path, reg_root):
    game = tmp_path / "Games" / "GTA V Enhanced"
    game.mkdir(parents=True)
    (game / "GTA5_Enhanced.exe").write_bytes(b"MZ")
    payload = make_payload(tmp_path)
    with pytest.raises(winsetup.SetupError, match="inside the game folder"):
        winsetup.install(payload, game / "Leonida", tmp_path / "data")
    with pytest.raises(winsetup.SetupError, match="inside the game folder"):
        winsetup.install(payload, tmp_path / "prog", game / "data")
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "notes.txt").write_text("someone's files")
    with pytest.raises(winsetup.SetupError, match="other files"):
        winsetup.install(payload, busy, tmp_path / "data")
    with pytest.raises(winsetup.SetupError, match="inside it"):
        winsetup.install(payload, tmp_path / "prog", tmp_path / "prog" / "data")
    assert winsetup.registered() is None and not (game / "Leonida").exists()


def test_a_broken_payload_changes_nothing(tmp_path, reg_root):
    install, data = places(tmp_path)
    winsetup.install(make_payload(tmp_path), install, data, version="1.0.0")
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as f:
        f.writestr("something/else.txt", "not leonida")
    with pytest.raises(winsetup.SetupError, match="not a Leonida V release"):
        winsetup.install(bad, install, data, version="9")
    assert (install / "LeonidaV.exe").read_bytes() == b"MZ gui 1.0.0" and winsetup.registered()["Version"] == "1.0.0"
    assert not install.with_name("Leonida V.setup-new").exists()


def test_leonida_running_blocks_the_install(tmp_path, reg_root, monkeypatch):
    monkeypatch.setattr(winsetup, "leonida_running", lambda d: ["LeonidaV.exe"])
    with pytest.raises(winsetup.SetupError, match="Close it"):
        winsetup.install(make_payload(tmp_path), *places(tmp_path))


def test_shortcuts_made_and_removed(tmp_path, reg_root, monkeypatch):
    monkeypatch.delenv("LEONIDA_NO_SHORTCUTS")
    install, data = places(tmp_path)
    res = winsetup.install(make_payload(tmp_path), install, data, version="1.0.0", desktop=False)
    assert [p.parent.name for p in res.shortcuts] == ["menu"] and not (tmp_path / "desk" / "Leonida V.lnk").exists()
    from leonida import shortcuts

    assert shortcuts.read(res.shortcuts[0])["target"].lower() == str(install / "LeonidaV.exe").lower()
    other = tmp_path / "desk" / "Leonida V.lnk"  # someone else's shortcut with the same name: left alone
    monkeypatch.setenv("LEONIDA_STARTMENU_DIR", str(tmp_path / "other-menu"))
    shortcuts.create(tmp_path / "elsewhere.exe", desktop=True)
    monkeypatch.setenv("LEONIDA_STARTMENU_DIR", str(tmp_path / "menu"))
    out = winsetup.uninstall(remove_program_now=True)
    assert not (tmp_path / "menu" / "Leonida V.lnk").exists() and other.exists()
    assert str(tmp_path / "menu" / "Leonida V.lnk") in out.removed


# ---------------------------------------------------------------------------------------------- uninstall
def test_uninstall_keeps_data_unless_asked(tmp_path, reg_root):
    install, data = places(tmp_path)
    winsetup.install(make_payload(tmp_path), install, data)
    (data / "Downloads" / "mod.zip").write_bytes(b"PK")
    res = winsetup.uninstall(remove_program_now=True)
    assert not install.exists() and winsetup.registered() is None
    assert (data / "State").is_dir() and (data / "Downloads" / "mod.zip").is_file()
    assert set(res.kept) == {str(data / "State"), str(data / "Downloads")}
    winsetup.install(make_payload(tmp_path), install, data)
    res = winsetup.uninstall(delete_state=True, delete_downloads=True, remove_program_now=True)
    assert not data.exists() and str(data / "State") in res.removed
    with pytest.raises(winsetup.SetupError, match="isn't installed"):
        winsetup.uninstall()


def test_uninstall_from_inside_waits_for_the_app_to_exit(tmp_path, reg_root, monkeypatch):
    install, data = places(tmp_path)
    winsetup.install(make_payload(tmp_path), install, data)
    started = []
    monkeypatch.setattr(winsetup.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "LeonidaV.exe"))
    monkeypatch.setenv("TEMP", str(tmp_path))
    res = winsetup.uninstall(pid=4242)
    assert res.later == install and install.exists()             # removed by the helper, after this process exits
    bat = Path(started[0][-1])
    text = bat.read_text(encoding="utf-8")
    assert f'set "DIR={install}"' in text and '"PID eq 4242"' in text and "rmdir /s /q" in text


# ------------------------------------------------------------------------------------- the installed exe
def test_installed_exe_uses_the_data_folder(tmp_path, reg_root, monkeypatch):
    install, data = places(tmp_path)
    winsetup.install(make_payload(tmp_path), install, data, version="0.9")
    monkeypatch.delenv("LEONIDA_STATE_DIR", raising=False)
    monkeypatch.delenv("LEONIDA_DOWNLOAD_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "LeonidaV.exe"))
    assert paths.state_dir() == data / "State" and paths.default_download_dir() == data / "Downloads"
    assert winsetup.sync_version() is True and winsetup.registered()["Version"] == winsetup.__version__
    assert winsetup.sync_version() is False
    # a portable copy elsewhere keeps the usual places
    monkeypatch.setattr(sys, "executable", str(tmp_path / "portable" / "LeonidaV.exe"))
    assert winsetup.data_dir_for_running_exe() is None and paths.state_dir() != data / "State"


def test_game_folder_near(tmp_path):
    game = tmp_path / "g"
    (game / "mods").mkdir(parents=True)
    (game / "PlayGTAV.exe").write_bytes(b"MZ")
    assert winsetup.game_folder_near(game / "mods" / "x") == game and winsetup.game_folder_near(tmp_path / "y") is None


# ------------------------------------------------------------------------------------------- the setup exe
def _entry():
    sys.path.insert(0, str(ROOT / "build"))
    import entry_setup

    return entry_setup


def _payload_dir(tmp: Path, zip_path: Path, version: str, sha: str | None = None) -> Path:
    d = tmp / "payload"
    d.mkdir()
    (d / zip_path.name).write_bytes(zip_path.read_bytes())
    digest = sha or hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (d / "payload.json").write_text(json.dumps({"file": zip_path.name, "sha256": digest, "version": version}))
    return d


def test_setup_exe_silent_install(tmp_path, reg_root, monkeypatch):
    es = _entry()
    d = _payload_dir(tmp_path, make_payload(tmp_path, "2.0.0"), "2.0.0")
    monkeypatch.setattr(es, "payload_dir", lambda: d)
    install, data = places(tmp_path)
    log = tmp_path / "setup.log"
    assert es.main(["/S", "--dir", str(install), "--data", str(data), "--log", str(log)]) == 0
    assert winsetup.registered()["Version"] == "2.0.0" and "is installed" in log.read_text(encoding="utf-8")
    assert json.loads((data / "State" / "setup-receipt.json").read_text())["version"] == "2.0.0"
    assert es.parse(["/VERYSILENT"]).silent and not es.parse([]).silent


def test_setup_exe_refuses_a_damaged_payload(tmp_path, reg_root, monkeypatch):
    es = _entry()
    d = _payload_dir(tmp_path, make_payload(tmp_path), "1.0.0", sha="0" * 64)
    monkeypatch.setattr(es, "payload_dir", lambda: d)
    log = tmp_path / "setup.log"
    assert es.main(["/S", "--dir", str(tmp_path / "p"), "--data", str(tmp_path / "d"), "--log", str(log)]) == 2
    assert "damaged" in log.read_text(encoding="utf-8") and winsetup.registered() is None


def test_setup_exe_dialog_flow(tmp_path, reg_root, monkeypatch):
    es = _entry()
    d = _payload_dir(tmp_path, make_payload(tmp_path, "3.0.0"), "3.0.0")
    monkeypatch.setattr(es, "payload_dir", lambda: d)
    install, data = places(tmp_path)
    monkeypatch.setattr(winsetup, "default_install_dir", lambda: install)
    monkeypatch.setattr(winsetup, "default_data_dir", lambda: data)
    answers = iter([("folder", True), ("install", False)])
    picked = tmp_path / "Big drive"
    picked.mkdir()
    monkeypatch.setattr(setupui, "ask_install", lambda *a: next(answers))
    monkeypatch.setattr(setupui, "pick_folder", lambda *a: picked)
    monkeypatch.setattr(setupui, "run_with_progress", lambda main, content, work: work(lambda a, b: None))
    launched = []
    monkeypatch.setattr(setupui, "finished", lambda text, main="": "3.0.0" in main)
    monkeypatch.setattr(es.subprocess, "Popen", lambda cmd, **k: launched.append(cmd))
    assert es.main([]) == 0
    assert winsetup.registered()["DataDir"] == str(picked / "Leonida V") and launched == [[str(install / "LeonidaV.exe")]]
    monkeypatch.setattr(setupui, "ask_install", lambda *a: ("cancel", True))
    assert es.main([]) == 1


def test_uninstall_main_asks_before_deleting_data(tmp_path, reg_root, monkeypatch):
    install, data = places(tmp_path)
    winsetup.install(make_payload(tmp_path), install, data)
    asked = []

    def answer(text, main="", **k):
        asked.append(main)
        return main != "Also delete your Leonida data (State)?"     # remove: yes; State: keep; Downloads: delete

    monkeypatch.setattr(setupui, "ask_yes_no", answer)
    monkeypatch.setattr(setupui, "message", lambda *a, **k: None)
    monkeypatch.setattr(winsetup, "uninstall", lambda s, d: asked.append(("uninstall", s, d)) or winsetup.UninstallResult())
    assert setupui.uninstall_main([]) == 0
    assert asked[:3] == ["Remove Leonida V from this PC?", "Also delete your Leonida data (State)?",
                         "Also delete the downloaded mod files?"] and asked[3] == ("uninstall", False, True)
    monkeypatch.setattr(setupui, "ask_yes_no", lambda *a, **k: False)
    assert setupui.uninstall_main([]) == 1                             # "No": nothing removed


# ----------------------------------------------------------------------------------------- native dialogs
@pytest.mark.skipif(sys.platform != "win32" or not os.environ.get("USERNAME"), reason="needs a Windows desktop")
def test_native_dialogs_with_autoclick(monkeypatch):
    monkeypatch.setenv("LEONIDA_SETUPUI_AUTOCLICK", str(setupui.BTN_INSTALL))
    assert setupui.ask_install("1.0", Path("C:/p"), Path("C:/d")) == ("install", True)
    monkeypatch.setenv("LEONIDA_SETUPUI_AUTOCLICK", str(-setupui.BTN_INSTALL))
    choice, desktop = setupui.ask_install("1.0", Path("C:/p"), Path("C:/d"))
    assert choice == "install" and (desktop is False or not setupui.available())
    monkeypatch.setenv("LEONIDA_SETUPUI_AUTOCLICK", str(setupui.IDYES))
    assert setupui.ask_yes_no("Remove?") is True
    monkeypatch.setenv("LEONIDA_SETUPUI_AUTOCLICK", str(setupui.BTN_START))
    assert setupui.finished("done") is True
    assert setupui.run_with_progress("x", "y", lambda progress: progress(1, 1) or "ok") == "ok"

    def boom(progress):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        setupui.run_with_progress("x", "y", boom)


def test_leonida_running_reads_process_paths(tmp_path, monkeypatch):
    import subprocess

    install = tmp_path / "Programs" / "Leonida V"
    install.mkdir(parents=True)
    out = f"{install / 'LeonidaV.exe'}\n{tmp_path / 'elsewhere' / 'leonida.exe'}\n\n"
    monkeypatch.setattr(winsetup.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
    assert winsetup.leonida_running(install) == ["LeonidaV.exe"]


def test_dialog_fallbacks_without_taskdialog(monkeypatch):
    def no_taskdialog(*a, **k):
        raise OSError("TaskDialog is not available")

    monkeypatch.setattr(setupui, "_show", no_taskdialog)
    monkeypatch.setattr(setupui, "_dpi_aware", lambda: None)
    monkeypatch.setenv("LEONIDA_SETUPUI_AUTOCLICK", str(setupui.IDYES))   # the MessageBox fallback answers at once
    assert setupui.ask_yes_no("q") is True and setupui.finished("x") is True
    assert setupui.ask_install("1", Path("C:/p"), Path("C:/d")) == ("install", True)
    setupui.message("m")
    monkeypatch.setenv("LEONIDA_SETUPUI_AUTOCLICK", str(setupui.IDNO))
    assert setupui.ask_yes_no("q") is False and setupui.ask_install("1", Path("C:/p"), Path("C:/d"))[0] == "folder"
    monkeypatch.setattr(setupui, "available", lambda: False)
    assert setupui.run_with_progress("a", "b", lambda progress: progress(1, 2) or 5) == 5
