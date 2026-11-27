"""Ready-made setups in the launcher (leonida/gui/setupspage.py): Browse > Setups cards (best for this PC, needs,
tested on), one click = choose + download + install through the setup flow, Export / Import, and the setup cards in
the first-run setup's modpack step. Downloads and installs are fakes."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from test_gui_pages import SB, dialogs, make_win, qapp, wait_idle, wait_until  # noqa: E402,F401  (fixtures)

from leonida import firstrun as FR  # noqa: E402
from leonida import gamesettings as G  # noqa: E402
from leonida import setups as SU  # noqa: E402
from leonida.gui import setupspage as SP  # noqa: E402

GTX1070 = G.PC(15.8, 8.0, ("NVIDIA GeForce GTX 1070",))


def texts(w) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [lab.text() for lab in w.findChildren(QLabel)]


@pytest.fixture
def win(dialogs, make_win, monkeypatch):  # noqa: F811
    w = make_win()
    monkeypatch.setattr(w.session, "pc_specs", lambda: GTX1070)
    yield w
    wait_idle(w, *w.pages)


def _setups_tab(win):
    win.show_home("browse")
    b = win.browse
    i = next(i for i in range(b.tabs.count()) if b.tabs.tabText(i) == "Setups")
    b.tabs.setCurrentIndex(i)
    b.setups.refresh(force=True)
    return {c.setup.id: c for c in b.setups.cards}


def test_browse_setups_shows_every_setup_with_needs_tests_and_the_best_marked(win):
    cards = _setups_tab(win)
    assert set(cards) == {s.id for s in SU.load("enhanced")}
    best = SU.best_for(GTX1070, "enhanced")
    assert best is not None and "Best for this PC" in texts(cards[best.id])
    assert all("Best for this PC" not in texts(c) for sid, c in cards.items() if sid != best.id)
    o16 = texts(cards["owner-16gb"])
    assert "Owner's pick · 16 GB" in o16 and "Tested on 1.0.1013.20" in o16
    assert any(t.startswith("Needs 12 GB RAM, 6 GB video memory") for t in o16)
    assert any(" mods · Leonida (owner's pick) · 16 GB of RAM · 1 add-on" in t for t in o16)
    rtx = texts(cards["showcase-rtx"])
    assert "Too much for this PC" in rtx and "Not play-tested yet" in rtx
    assert cards["owner-16gb"].use_btn.text() == "Use this setup" and cards["owner-16gb"].use_btn.isEnabled()


def test_use_this_setup_chooses_it_then_downloads_and_installs(win, dialogs, monkeypatch):  # noqa: F811
    s = win.session
    downloads = []
    monkeypatch.setattr(win.pages[3], "download_everything", lambda: downloads.append(1))
    dialogs.answer = SB.No
    assert SP.use_setup(win, "owner-16gb") is False and SU.chosen(s) is None
    dialogs.answer = SB.Yes
    assert SP.use_setup(win, "owner-16gb") is True
    c = s.pack_choice()
    assert (c.pack, c.variant, sorted(c.addons)) == ("owner-pick", "ram16", ["owner-gun-sounds"])
    assert SU.chosen(s) == "owner-16gb"
    flow = win.setup_flow
    assert win.stack.currentWidget() is flow and flow.name == "download" and flow.auto_install
    assert downloads == [1]
    assert "Use the setup “Owner's pick · 16 GB”?" in [t for k, t in dialogs.calls if k == "question"][-1]
    # everything downloaded: on to installing it
    installs = []
    monkeypatch.setattr(flow, "install_all", lambda: installs.append(1))
    monkeypatch.setattr(flow, "_todo", lambda: ([s.mods()[0]], [], {}))
    flow._auto_install()
    assert flow.name == "install" and installs == [1] and not flow.auto_install
    cards = _setups_tab(win)
    assert "Your setup" in texts(cards["owner-16gb"]) and not cards["owner-16gb"].use_btn.isEnabled()


def test_a_setup_already_downloaded_goes_straight_to_installing(win, dialogs, monkeypatch):  # noqa: F811
    flow = win.setup_flow
    installs = []
    monkeypatch.setattr(flow, "install_all", lambda: installs.append(1))
    monkeypatch.setattr(flow, "_todo", lambda: ([object()], [], {}))
    monkeypatch.setattr(win.pages[3], "download_everything", lambda: pytest.fail("nothing to download"))
    assert SP.use_setup(win, "core-laptop") is True
    assert flow.name == "install" and installs == [1]
    flow.leave()
    assert not flow.auto_install


def test_export_and_import_a_setup_file(win, dialogs, tmp_path, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QFileDialog

    s = win.session
    out = tmp_path / "shared.json"
    answer = [("", "")]
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: answer[0]))
    SP.choose(win, "core-laptop")
    assert SP.export_file(win) is None and not out.exists()            # cancelled
    answer[0] = (str(out), "")
    assert SP.export_file(win) == out
    data = json.loads(out.read_text())
    assert data["kind"] == SU.EXPORT_KIND and data["pack"] == "core" and "state" not in json.dumps(data).lower()
    # someone else's file: the owner's pick
    other = tmp_path / "friend.json"
    other.write_text(json.dumps({**data, "name": "Friend's setup", "pack": "owner-pick", "variant": "ram16",
                                 "addons": []}), encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(other), "")))
    assert SP.import_file(win) is True
    assert s.pack_choice().pack == "owner-pick" and "Setup imported: Friend's setup" in win.notifications.items[0].text
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**data, "pack": "no-such-pack"}), encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    assert SP.import_file(win) is False
    assert any("doesn't fit your mod list" in t for k, t in dialogs.calls if k == "warning")
    assert s.pack_choice().pack == "owner-pick"


def test_the_first_run_setup_offers_the_setups_first(win, dialogs, monkeypatch):  # noqa: F811
    flow = win.setup_flow
    flow.begin(FR.STEPS.index("pack"))
    cards = {c.setup.id: c for c in flow.setup_cards}
    assert set(cards) == {x.id for x in SU.load("enhanced")}
    assert "READY-MADE SETUPS · ONE CLICK" in texts(flow.body_holder)
    downloads = []
    monkeypatch.setattr(win.pages[3], "download_everything", lambda: downloads.append(1))
    cards["owner-16gb"].use_btn.click()                      # no extra question: the step itself is the choice
    assert SU.chosen(win.session) == "owner-16gb" and flow.name == "download" and downloads == [1]
