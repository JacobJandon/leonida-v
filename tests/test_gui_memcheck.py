"""The low-memory step before Play / Play test: the dialog, the user's choices, and that nothing is closed without
their click. Fake memory and a fake closer only (never real apps)."""

from __future__ import annotations

import types

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox  # noqa: E402

from leonida import memwatch as M  # noqa: E402
from leonida.gui import memcheck  # noqa: E402
from leonida.gui import newpages as NP  # noqa: E402
from leonida.session import Session  # noqa: E402

GB = 1024.0


@pytest.fixture(scope="module")
def app(qt_app):
    return qt_app


class Mem(M.NullMemory):
    def __init__(self, free=4.6 * GB, commit_free=9.8 * GB):
        self.free, self.commit_free = free, commit_free

    def system(self):
        return {"sys_free_mb": self.free, "commit_limit_mb": 32 * GB, "commit_used_mb": 32 * GB - self.commit_free}

    def top_users(self, n=8):
        return [("firefox.exe", 1500.0), ("svchost.exe", 1300.0), ("Discord.exe", 900.0), ("LeonidaV.exe", 200.0)]


def never_close(names):
    raise AssertionError(f"closed {names} without the user's click")


def test_low_memory_dialog_offers_only_closeable_apps_unticked(app):
    seen = []

    def look(dlg):
        seen.append(dlg)
        labels = [b.text() for b in dlg.boxes]
        assert labels == ["firefox.exe  (1.5 GB)", "Discord.exe  (0.9 GB)"]        # never svchost or Leonida
        assert not any(b.isChecked() for b in dlg.boxes) and not dlg.close_btn.isEnabled()
        dlg.boxes[1].setChecked(True)
        assert dlg.close_btn.isEnabled()
        dlg.boxes[1].setChecked(False)
        dlg.anyway_btn.click()

    assert memcheck.confirm(None, Mem(), run_dialog=look, close_apps=never_close) is True
    text = " ".join(lab.text() for lab in seen[0].findChildren(QLabel))
    assert "GTA may crash while loading: free memory is low" in text
    assert "4.6 GB of RAM free (under 6.0 GB); 9.8 GB of commit free (under 12.0 GB)" in text
    assert "svchost.exe (1.3 GB)" in text and "not offered" in text


def test_close_them_and_play_closes_only_the_ticked_ones(app):
    closed = []

    def pick(dlg):
        dlg.boxes[0].setChecked(True)       # firefox only
        dlg.close_btn.click()

    def fake_close(names):
        closed.append(list(names))
        return names, []

    assert memcheck.confirm(None, Mem(), run_dialog=pick, close_apps=fake_close) is True
    assert closed == [["firefox.exe"]]


def test_cancel_and_fine_memory(app):
    assert memcheck.confirm(None, Mem(), run_dialog=lambda d: d.reject(), close_apps=never_close) is False
    shown = []
    assert memcheck.confirm(None, Mem(free=8 * GB, commit_free=20 * GB), run_dialog=shown.append,
                            close_apps=never_close) is True
    assert shown == []                                                            # no dialog when there's room


def test_offscreen_without_a_memory_source_never_blocks(app, monkeypatch):
    assert QApplication.platformName() == "offscreen"
    monkeypatch.setattr(M, "default_ops", lambda: pytest.fail("no real measuring offscreen"))
    assert memcheck.confirm(None) is True


def test_play_button_stops_when_the_user_cancels(app, tmp_path, game, monkeypatch):
    from leonida.gui import launcher

    (game / "PlayGTAV.exe").write_bytes(b"MZ")
    s = Session(tmp_path / "st", game_dir=str(game), game_build="1.0.1013.20")
    win = types.SimpleNamespace(session=s)
    monkeypatch.delenv("LEONIDA_NO_OPEN", raising=False)
    monkeypatch.setattr(memcheck, "confirm", lambda w: False)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("the game must not start"))
    assert launcher.play_game(win) == "Not started."


def test_play_test_stops_when_the_user_cancels(app, tmp_path, game, monkeypatch):
    import leonida.playtest as P

    s = Session(tmp_path / "st", game_dir=str(game), game_build="1.0.1013.20")
    monkeypatch.setattr(P, "playtest", lambda *a, **k: pytest.fail("must not start"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(memcheck, "confirm", lambda w: False)
    view = NP.PlaytestView(s)
    assert view.start() is False and view.thread is None
