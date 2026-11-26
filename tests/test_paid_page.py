"""The modpack page's "Paid mods" tab (docs/PAID-MODS.md): buy on the author's page in the person's own browser,
"I've downloaded it", a refused (wrong) package, and Check and install through the test place."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

pytest.importorskip("PySide6")

from conftest import make_zip  # noqa: E402
from test_gui_launcher import labels  # noqa: E402
from test_gui_pages import dialogs, make_win, qapp, wait_idle, wait_until  # noqa: E402,F401  (fixtures)

from leonida.gui import paidpage as P  # noqa: E402


def _tab(win):
    win.open_pack(win.session.pack_choice().pack or win.session.base_manifest.default_pack)
    page = win.pack_page
    i = next(i for i in range(page.tabs.count()) if page.tabs.tabText(i) == "Paid mods")
    page.tabs.setCurrentIndex(i)
    return {c.row.id: c for c in getattr(page, "paid_cards", [])}


def test_every_paid_mod_has_a_card_and_buy_opens_the_authors_page_outside_leonida(make_win, dialogs,  # noqa: F811
                                                                                   monkeypatch):
    win = make_win()
    in_app, system = [], []
    monkeypatch.setattr(win, "open_page", lambda *a, **k: in_app.append(a))     # Leonida's own browser
    monkeypatch.setattr("leonida.gui.app._open", lambda url: system.append(url))  # the person's own browser
    cards = _tab(win)
    paid = [m.id for m in win.session.manifest.mods.values() if m.tier == "paid" and not m.free_since]
    assert set(cards) == set(paid) and paid
    nve = cards["nve"]
    texts = labels(nve)
    assert "Not bought" in texts and any(t.startswith("Price:") and "checked" in t for t in texts)
    assert any("paid by its creator" in t for t in texts) and P.NEVER in texts
    nve.buttons["Buy on the author's page"].click()
    assert in_app == [] and system == [nve.row.buy_url]                   # never the in-app browser
    assert "patreon.com" in nve.row.buy_url
    assert "page in your browser" in win.notifications.items[0].text


def test_a_downloaded_file_and_a_wrong_one(make_win, dialogs, downloads):  # noqa: F811
    make_zip(downloads / "NaturalVision Enhanced 1.0.zip", {"Main Package/x.dll": "x"})
    make_zip(downloads / "LWE fake.zip", {"x.txt": "x"})
    win = make_win()
    cards = _tab(win)
    nve = cards["nve"]
    assert "Downloaded: ready" in labels(nve) and "Check and install" in nve.buttons
    assert "Your file: NaturalVision Enhanced 1.0.zip" in labels(nve)
    lwe = cards["lwe"]                     # LWE's name with no content rules: named as its download
    assert lwe.row.status == "downloaded" and "LWE fake.zip" in lwe.row.file


def test_ive_downloaded_it_copies_a_file_from_elsewhere_and_assigns_it(make_win, dialogs, tmp_path,  # noqa: F811
                                                                         downloads, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    elsewhere = tmp_path / "Desktop" / "my renamed copy.zip"
    make_zip(elsewhere, {"Main Package/x.dll": "x"})
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(elsewhere), "")))
    win = make_win()
    cards = _tab(win)
    cards["nve"].buttons["I've downloaded it"].click()
    wait_until(lambda: win.session.config.assignments.get("my renamed copy.zip") == "nve")
    assert (downloads / "my renamed copy.zip").is_file() and elsewhere.is_file()        # copied, not moved
    wait_idle(win)
    assert _tab(win)["nve"].row.status == "downloaded"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    assert P.downloaded_it(win, cards["nve"].row, cards["nve"].mod) is None             # cancelled


class _FakeScan:
    def __init__(self, blocked):
        self.blocked = blocked

    def lines(self):
        return ["x.zip: flagged" if self.blocked else "x.zip: scanned OK"]


def test_check_and_install_scans_first_and_refuses_a_flagged_file(make_win, dialogs, downloads,  # noqa: F811
                                                                   monkeypatch):
    make_zip(downloads / "NaturalVision Enhanced 1.0.zip", {"Main Package/x.dll": "x"})
    win = make_win()
    s = win.session
    installed = []
    fake_inst = NS(plan=lambda mod, path: None, install=lambda mod, path: installed.append(mod.id) or NS(id=7))
    monkeypatch.setattr(s, "installer", lambda ui, dry_run=False: fake_inst)
    scans = []
    monkeypatch.setattr(s, "test_place", lambda: NS(scan=lambda *a, **k: scans.append(a[0]) or _FakeScan(True)))
    card = _tab(win)["nve"]
    assert P.check_and_install(win, card.row, card.mod) is True
    wait_until(lambda: not win.pages[5]._running)
    assert scans and installed == [] and any("refused" in t for t in dialogs.texts("warning"))
    monkeypatch.setattr(s, "test_place", lambda: NS(scan=lambda *a, **k: _FakeScan(False)))
    assert P.check_and_install(win, card.row, card.mod) is True
    wait_until(lambda: not win.pages[5]._running)
    assert installed == ["nve"] and "installed (step 7)" in win.notifications.items[0].text
    assert "nve" in {m.id for m in s.mods()}                     # its add-on (or the mod itself) is on now
    win.pages[5]._running = True
    assert P.check_and_install(win, card.row, card.mod) is False   # another install is running
    win.pages[5]._running = False


def test_a_repacked_file_is_refused_with_the_reason(make_win, dialogs, downloads):  # noqa: F811
    make_zip(downloads / "NaturalVision Enhanced reupload.zip", {"stuff/x.dll": "x"})   # no "Main Package"
    win = make_win()
    nve = _tab(win)["nve"]
    assert nve.row.status == "wrong file" and "main package" in nve.row.reason.lower()
    assert "Wrong file" in labels(nve) and {"Open Downloads", "Buy page"} <= set(nve.buttons)
    assert "Check and install" not in nve.buttons and P.NEVER in labels(nve)
