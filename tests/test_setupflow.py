"""The first-run setup (leonida/firstrun.py, leonida/gui/setupflow.py), moving Leonida's folders
(leonida/relocate.py) and the Settings controls that go with them. The real game is never looked for or started."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from leonida import firstrun as FR
from leonida import relocate as R
from leonida.paths import CONFIG_NAME


# ------------------------------------------------------------------------------------------------ engine
def test_when_the_setup_runs(tmp_path):
    assert FR.should_run(tmp_path) == 0                        # a first start: no config.json
    (tmp_path / CONFIG_NAME).write_text("{}")
    assert FR.should_run(tmp_path) is None                     # used before, never set up: not forced on anyone
    FR.save(tmp_path, {"step": 4, "finished": False})
    assert FR.should_run(tmp_path) == 4                        # left half-way
    FR.save(tmp_path, {"step": 99, "finished": False})
    assert FR.should_run(tmp_path) == len(FR.STEPS) - 1
    FR.save(tmp_path, {"step": 2, "finished": True})
    assert FR.should_run(tmp_path) is None
    (tmp_path / FR.SETUP_NAME).write_text("garbage")
    assert FR.load(tmp_path) == {}


def test_the_variant_follows_the_ram():
    vs = [NS(id="ram16"), NS(id="ram32"), NS(id="other")]
    assert FR.variant_for_ram(vs, 31.9) == "ram32" and FR.variant_for_ram(vs, 64) == "ram32"
    assert FR.variant_for_ram(vs, 16) == "ram16" and FR.variant_for_ram(vs, 23.7) == "ram16"
    assert FR.variant_for_ram(vs, 8) == "ram16"                # the smallest when even that is more
    assert FR.variant_for_ram(vs, None) is None and FR.variant_for_ram([NS(id="balanced")], 32) is None
    ram = FR.total_ram_gb()
    assert ram is None or ram > 1


def test_the_recommended_pack():
    assert FR.recommended_pack(NS(packs={"core": 1, "owner-pick": 2}, default_pack="core")) == "owner-pick"
    assert FR.recommended_pack(NS(packs={"core": 1}, default_pack="core")) == "core"


def test_moving_the_state_folder_leaves_a_pointer(tmp_path, monkeypatch):
    from leonida import paths

    home = tmp_path / "LocalAppData" / "LeonidaV"
    (home / "backups" / "step-1").mkdir(parents=True)
    (home / "install-log.json").write_text('{"steps": []}')
    (home / "backups" / "step-1" / "a.bin").write_bytes(b"x" * 100)
    monkeypatch.delenv("LEONIDA_STATE_DIR")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setattr(paths.sys, "platform", "win32")
    assert paths.state_dir() == home
    new = tmp_path / "D" / "Leonida"
    rep = R.move_state(home, new, home)
    assert rep.copied == 2 and rep.left == [] and "Copied 2 file(s)" in rep.lines()[0]
    assert (new / "backups" / "step-1" / "a.bin").read_bytes() == b"x" * 100
    assert not (home / "install-log.json").exists() and (home / R.POINTER).is_file()
    assert paths.state_dir() == new                            # Leonida follows the pointer
    monkeypatch.setenv("LEONIDA_STATE_DIR", str(tmp_path / "env"))
    assert paths.state_dir() == tmp_path / "env"               # the override still wins
    with pytest.raises(R.MoveError, match="already"):
        R.move_state(new, new, home)
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x").write_text("x")
    with pytest.raises(R.MoveError, match="isn't empty"):
        R.move_state(new, tmp_path / "full", home)
    with pytest.raises(R.MoveError, match="outside"):
        R.move_state(new, new / "inside", home)


def test_a_failed_copy_moves_nothing(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("a")

    def boom(a, b):
        raise OSError(13, "Access is denied", str(a))

    monkeypatch.setattr(R.shutil, "copy2", boom)
    with pytest.raises(R.MoveError, match="Nothing was moved"):
        R.move_downloads(src, tmp_path / "dst")
    assert (src / "a.txt").exists() and not (tmp_path / "dst").exists()


def test_moving_the_downloads(tmp_path):
    src, dst = tmp_path / "dl", tmp_path / "new"
    src.mkdir()
    (src / "mod-1.zip").write_bytes(b"zip")
    rep = R.move_downloads(src, dst)
    assert rep.copied == 1 and (dst / "mod-1.zip").read_bytes() == b"zip" and not (src / "mod-1.zip").exists()
    assert R.move_downloads(tmp_path / "nothing-here", tmp_path / "new2").copied == 0


# ------------------------------------------------------------------------------------------------ the GUI
pytest.importorskip("PySide6")

from conftest import AutoUI  # noqa: E402,F401
from test_gui_pages import dialogs, make_win, qapp, wait_idle, wait_until  # noqa: E402,F401  (fixtures)


def _first_start(qapp, tmp_path, downloads, monkeypatch, game=None):  # noqa: F811
    import leonida.gui.app as A
    from leonida.session import Session

    monkeypatch.delenv("LEONIDA_NO_SETUP", raising=False)
    s = Session(state=tmp_path / "fresh-state", download_dir=str(downloads),
                game_dir=str(game) if game else None)
    return A.MainWindow(s)


def test_a_first_start_walks_through_the_setup(qapp, tmp_path, downloads, game, dialogs, monkeypatch):  # noqa: F811
    from leonida import detect
    from leonida.detect import GameInstall

    monkeypatch.setattr(detect, "detect_games", lambda names=None, extra=None: [
        GameInstall(game, "steam", game / "GTA5_Enhanced.exe", "1.0.1013.20", "enhanced")])
    monkeypatch.setattr(FR, "total_ram_gb", lambda: 31.9)
    win = _first_start(qapp, tmp_path, downloads, monkeypatch)
    flow = win.setup_flow
    try:
        assert win.stack.currentWidget() is flow and flow.name == "welcome"
        assert not flow.back_btn.isVisibleTo(flow) and flow.next_btn.text() == "Start"
        flow.next_btn.click()
        assert flow.name == "game"
        wait_until(lambda: win.session.config.game_dir == str(game))   # found, and used
        assert "Using:" in flow.game_now.text() and "GTA V Enhanced" in flow.game_now.text()
        flow.next_btn.click()
        assert flow.name == "prereqs"
        monkeypatch.setattr(type(win.session), "prerequisites", lambda self: {"dotnet48": True, "vcredist": False})
        monkeypatch.setattr(type(win.session), "seven_zip", lambda self: None)
        monkeypatch.setattr("leonida.gui.setupflow.shutil.which", lambda name: "C:/winget.exe")
        flow.recheck()
        texts = [b.text() for b in flow.findChildren(type(flow.next_btn)) if b.isVisibleTo(flow)]
        assert texts.count("Install with winget") == 2 and texts.count("Open its download page") == 2
        next(b for b in flow.findChildren(type(flow.next_btn)) if b.text() == "Install with winget").click()
        assert flow.launched == [["winget", "install", "--id", "Microsoft.VCRedist.2015+.x64", "-e"]]
        flow.skip()                                            # the prerequisites step: skipped
        assert flow.name == "pack"
        rec = FR.recommended_pack(win.session.base_manifest)
        assert flow.chosen_pack() == rec
        if rec == "owner-pick":
            assert flow.variant.currentData() == "ram32" and "32 GB" in flow.variant_note.text()
        flow.next_btn.click()                                  # the choice is saved
        assert flow.name == "download" and win.session.pack_choice().pack == rec
        assert "files ready" in flow.dl_state.text()
        assert FR.load(win.session.state)["step"] == FR.STEPS.index("download")
        assert "prereqs" in FR.load(win.session.state)["skipped"]
    finally:
        wait_idle(win, *win.pages, flow)
        win.close()
        win.deleteLater()
    again = _first_start(qapp, tmp_path, downloads, monkeypatch)   # closed half-way: it opens where it was
    try:
        assert again.stack.currentWidget() is again.setup_flow and again.setup_flow.name == "download"
        again.setup_flow.leave()                               # paused on purpose: not on every start
        assert FR.load(again.session.state)["dismissed"] is True
        assert again.stack.currentWidget() is not again.setup_flow
    finally:
        again.close()
        again.deleteLater()
    third = _first_start(qapp, tmp_path, downloads, monkeypatch)
    try:
        assert third.stack.currentWidget() is not third.setup_flow
        third.settings_page.refresh()
        assert third.settings_page.setup_btn.text() == "Continue setup"
        third.settings_page.setup_btn.click()
        assert third.setup_flow.name == "download"
        third.setup_flow.goto(len(FR.STEPS) - 1)
        assert third.setup_flow.name == "done" and third.setup_flow.next_btn.text() == "Go to my modpack"
        third.setup_flow.next_btn.click()
        assert FR.load(third.session.state)["finished"] is True and third.stack.currentWidget() is third.pack_page
        third.settings_page.refresh()
        assert third.settings_page.setup_btn.text() == "Run setup again"
    finally:
        third.close()
        third.deleteLater()


def test_the_setup_installs_everything_downloaded(kit, game, qapp, dialogs, monkeypatch):  # noqa: F811
    import leonida.gui.app as A

    win = A.MainWindow(kit)
    flow = win.setup_flow
    try:
        flow.begin(FR.STEPS.index("install"), fresh=True)
        assert flow.inst_btn.isEnabled() and "ready to install" in flow.inst_state.text()
        flow.inst_btn.click()
        wait_until(lambda: not flow.installing)
        assert kit.log.installed_mods() == {m.id for m in kit.mods()}
        assert "Installed" in flow.inst_log.toPlainText() and not flow.inst_btn.isEnabled()
        assert "installed" in win.notifications.items[0].text
        flow.goto(FR.STEPS.index("playtest"))
        assert flow.playtest.start_btn.text() == "Play test"
    finally:
        wait_idle(win, *win.pages, flow)
        win.close()
        win.deleteLater()


from test_settings import kit  # noqa: E402,F401  (fixture)


def test_settings_move_channel_and_report(make_win, tmp_path, monkeypatch, dialogs):  # noqa: F811
    win = make_win()
    page = win.settings_page
    page.refresh()
    s = win.session
    page.channel.setCurrentIndex(page.channel.findData("beta"))
    assert s.config.update_channel == "beta"
    assert json.loads((s.state / CONFIG_NAME).read_text())["update_channel"] == "beta"
    old = s.config.downloads()
    (old / "a.zip").write_bytes(b"a")
    dialogs.directory = str(tmp_path / "Moved downloads")
    page.move_folder("downloads")
    wait_until(lambda: s.config.download_dir == str(tmp_path / "Moved downloads"))
    assert (tmp_path / "Moved downloads" / "a.zip").exists() and not (old / "a.zip").exists()
    page.move_folder("state")                                  # LEONIDA_STATE_DIR is set in tests: refused
    assert "LEONIDA_STATE_DIR" in dialogs.calls[-1][1]
    win.pages[5]._running = True
    page.move_folder("downloads")
    assert dialogs.calls[-1][1].startswith("Not now: an install is running")
    win.pages[5]._running = False
    reports = []
    monkeypatch.setattr(win.about_page, "report", lambda: reports.append(1))
    page.debug_report()
    assert reports == [1] and s.config.debug is True
    assert page.restart() is False                             # LEONIDA_NO_OPEN: no restart in tests
