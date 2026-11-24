"""leonida/gui/newpages.py: Choose your modpack, editions, the play-test view (offscreen, playtest faked)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from leonida.detect import GameInstall  # noqa: E402
from leonida.gui import newpages as NP  # noqa: E402
from leonida.gui import widgets as W  # noqa: E402
from leonida.session import Session  # noqa: E402


@pytest.fixture(scope="module")
def app(qt_app):
    return qt_app


@pytest.fixture
def session(tmp_path, game):
    return Session(state=tmp_path / "state", game_dir=str(game), game_build="1.0.1013.20")


def wait_until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.01)
    assert cond(), "timed out"


# ------------------------------------------------------------------------------------------- modpacks
def test_modpack_page_cards_and_choice(app, session):
    page = NP.ModpackPage(session, gpus=["NVIDIA GeForce GTX 1070"])
    profiles = session.manifest.profiles
    assert list(page.cards) == list(profiles)
    default = session.manifest.default_profile
    assert page.selected == default and page.cards[default].property("selected") is True
    rtx = next(pid for pid, p in profiles.items() if (p.requires or {}).get("gpu") == "rtx50")
    assert not page.cards[rtx].isEnabled() and page.cards[rtx].toolTip().startswith("Needs an NVIDIA RTX 50")
    got = []
    page.pack_chosen.connect(got.append)
    page.select(rtx)  # locked: ignored
    assert page.selected == default and got == []
    other = next(pid for pid in profiles if pid not in (default, rtx))
    page.cards[other].choose.click()
    assert page.selected == other and got == [other] and page.cards[default].property("selected") is False
    page.select("no-such-pack")
    assert page.selected == other
    assert page.choose() == other
    assert Session(state=session.state).config.profile == other  # saved
    own, nxt = [], []
    page.add_own_mod.connect(lambda: own.append(1))
    page.next_requested.connect(lambda: nxt.append(1))
    page.add_btn.click()
    page.next_btn.click()
    assert own == [1] and nxt == [1]
    counts = {pid: len(session.manifest.resolve(pid, [], [], {})) for pid in profiles}
    texts = [lab.text() for lab in page.cards[default].findChildren(W.Badge)]
    assert f"{counts[default]} mods" in texts


def test_modpack_page_rtx50_unlocked_and_saved_profile(app, session):
    session.config.profile = "core-plus"
    page = NP.ModpackPage(session, gpus=["NVIDIA GeForce RTX 5080"])
    assert page.selected == "core-plus"
    assert all(c.isEnabled() for c in page.cards.values())
    session.config.profile = "gone-profile"
    assert NP.ModpackPage(session).selected == next(iter(session.manifest.profiles))
    empty = NP.ModpackPage.__new__(NP.ModpackPage)
    empty.selected = None
    assert NP.ModpackPage.choose(empty) is None


# ------------------------------------------------------------------------------------------- editions
def test_editions_from_installs():
    gi = [GameInstall(Path("D:/A"), "common", Path("D:/A/GTA5_Enhanced.exe"), "1.0.1013.20"),
          GameInstall(Path("D:/B"), "steam", Path("D:/B/GTA5_Enhanced.exe"), "1.0.1158.13"),
          GameInstall(Path("D:/L"), "steam", Path("D:/L/GTA5.exe"), "1.0.3586.0"),
          GameInstall(Path("D:/X"), "manual", Path("D:/X/other.exe"), None)]
    assert NP.editions_from(gi) == [("Enhanced", str(Path("D:/A")), "1.0.1013.20"),
                                    ("Legacy", str(Path("D:/L")), "1.0.3586.0")]
    assert NP.editions_from([]) == [("Enhanced", None, None), ("Legacy", None, None)]
    picker = W.EditionPicker(NP.editions_from(gi[:1]))
    assert picker.current() == "Enhanced" and not picker.buttons["Legacy"].isEnabled()


# ------------------------------------------------------------------------------------------- play test
class _Report:
    def __init__(self, status="passed", message="Story mode loaded in 60 s; every mod OK."):
        self.status, self.message = status, message
        self.results, self.notes, self.evidence = [], [], []

    @property
    def ok(self):
        return self.status == "passed"


def test_playtest_view_asks_first(app, session, monkeypatch):
    import leonida.playtest as P

    monkeypatch.setattr(P, "playtest", lambda *a, **k: pytest.fail("must not start without a yes"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    view = NP.PlaytestView(session)
    assert view.start() is False and view.thread is None and view.start_btn.isEnabled()


def test_playtest_view_runs_and_reports(app, session, monkeypatch):
    import leonida.playtest as P

    calls = []

    def fake(sess, keep_running=False, progress=None):
        calls.append((sess, keep_running))
        for msg in ("Started PlayGTAV.exe", "GTA5_Enhanced.exe is running", "Script Hook V loaded (ScriptHookV.log)"):
            progress(msg)
        return _Report()

    monkeypatch.setattr(P, "playtest", fake)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    view = NP.PlaytestView(session)
    done = []
    view.finished.connect(done.append)
    view.keep.setChecked(True)
    assert view.start() is True and not view.start_btn.isEnabled()
    assert view.start() is False  # already running
    wait_until(lambda: done)
    assert calls == [(session, True)] and done[0].ok
    assert view.panel.pill.kind == "ok" and view.panel.states()[4] == "done"
    assert view.toast.isVisibleTo(view) and view.toast.timer.isActive() and view.start_btn.isEnabled()
    assert view.thread is None


def test_playtest_view_bad_result_and_crash(app, session, monkeypatch):
    import leonida.playtest as P

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(P, "playtest", lambda *a, **k: _Report("crashed", "The game closed before story mode."))
    view = NP.PlaytestView(session)
    done, failed = [], []
    view.finished.connect(done.append)
    view.failed.connect(failed.append)
    view.start()
    wait_until(lambda: done)
    assert view.panel.pill.kind == "failed" and not view.toast.timer.isActive()  # errors stay

    def boom(*a, **k):
        raise RuntimeError("tasklist missing")

    monkeypatch.setattr(P, "playtest", boom)
    view.start()
    wait_until(lambda: failed)
    assert failed == ["tasklist missing"] and "couldn't run" in view.toast.text.text()
    assert view.panel.pill.kind == "failed" and view.start_btn.isEnabled() and view.thread is None
