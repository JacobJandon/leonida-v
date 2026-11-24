"""leonida/gui/widgets.py: the redesign's building blocks (offscreen), plus the design preview renderer."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QLabel, QPushButton, QWidget  # noqa: E402

from leonida.gui import theme  # noqa: E402
from leonida.gui import widgets as W  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "leonida" / "gui" / "assets" / "leonida.png"
BUILD = "1.0.1013.20"


@pytest.fixture(scope="module")
def app(qt_app):
    return qt_app


@pytest.fixture
def mods(manifest):
    return manifest.for_build(BUILD)


def colored_pixels(pm: QPixmap) -> int:
    img = pm.toImage()
    return sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 0)


# ------------------------------------------------------------------------------------------- icons / labels
@pytest.mark.parametrize("name", W.ICONS)
def test_every_icon_draws(app, name):
    pm = W.icon_pixmap(name, "#FF4F8B", 20)
    assert pm.devicePixelRatio() == 2.0 and colored_pixels(pm) > 10
    assert not W.icon(name).isNull()


def test_unknown_icon(app):
    with pytest.raises(KeyError):
        W.icon_pixmap("nope")


def test_button_variants(app):
    b = W.button("Go", "primary", icon_name="play", glow=True)
    assert b.property("variant") == "primary" and not b.icon().isNull() and b.graphicsEffect() is not None
    hits = []
    d = W.button("Delete", "danger", lambda: hits.append(1), icon_name="cross")
    d.click()
    assert hits == [1] and d.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert W.button("x", "ghost", icon_name="info").property("variant") == "ghost"


def test_badge(app):
    b = W.Badge("Core", "info", "Tier: core")
    assert b.property("role") == "badge" and b.property("tone") == "info" and b.toolTip() == "Tier: core"
    b.set_tone(None)
    assert b.property("tone") == ""


def test_status_pill(app):
    p = W.StatusPill("downloading", percent=142)
    assert p.text.text() == "Downloading 100%" and p.kind == "downloading"
    p.set_status("failed", "log line")
    assert p.text.text() == "Failed · log line" and W.TONE_COLORS["error"] in p.text.styleSheet()
    p.set_status("downloading", percent=-5)
    assert p.text.text() == "Downloading 0%"
    for kind in W.STATUS:
        p.set_status(kind)
        assert p.toolTip() == W.STATUS[kind][0]
    with pytest.raises(KeyError):
        p.set_status("exploded")


def test_flow_layout_wraps(app):
    holder, flow = W.flow_box(6)
    for i in range(6):
        lab = QLabel(f"badge {i}")
        lab.setFixedSize(80, 20)
        flow.addWidget(lab)
    assert flow.count() == 6 and flow.itemAt(9) is None and flow.takeAt(9) is None
    assert flow.hasHeightForWidth() and flow.expandingDirections() == Qt.Orientation(0)
    assert flow.heightForWidth(1000) == 20          # one line
    assert flow.heightForWidth(180) == 20 * 3 + 6 * 2  # two per line -> three lines
    flow.setGeometry(QRect(0, 0, 180, 100))
    assert flow.itemAt(2).geometry().y() == 26
    assert flow.minimumSize().width() == 80 and flow.sizeHint() == flow.minimumSize()
    taken = flow.takeAt(0)
    assert taken is not None and flow.count() == 5
    assert "transparent" in holder.styleSheet()


def test_art_placeholder_picture_and_dim(app):
    a = W.Art("menyoo", "Tools", height=100)
    a.resize(280, 100)
    img = a.grab().toImage()
    top_left, bottom = img.pixelColor(20, 10), img.pixelColor(140, 95)
    assert top_left.saturation() > 60  # sunset gradient, not the page colour
    assert bottom.lightness() < top_left.lightness()  # darker horizon for the label
    a.label = "Unknown layer"  # hue from the seed instead
    assert a._colors()[0].isValid()
    pm = QPixmap(400, 200)
    pm.fill(QColor("#00FF00"))
    a.set_pixmap(pm)
    assert a.grab().toImage().pixelColor(140, 50).green() > 200
    a.dim = True
    assert a.grab().toImage().pixelColor(140, 50).green() < 150
    a.set_pixmap(QPixmap())
    assert a.pixmap is None


# ------------------------------------------------------------------------------------------- mod card
def test_mod_badges_cover_every_route(mods):
    texts = lambda m: [t for t, _tone, _tip in W.mod_badges(m, BUILD)]  # noqa: E731
    assert texts(mods.mod("menyoo")) == ["Core", "Free", "Works on your build", "Auto download"]
    assert texts(mods.mod("mapfixes"))[-1] == "In-app browser"
    assert texts(mods.mod("hud-fbicat"))[-1] == "Discord"
    lwe = texts(mods.mod("lwe"))
    assert lwe[:2] == ["Paid tier", "Paid"] and lwe[-1] == "Patreon"
    assert texts(mods.mod("nve"))[2] == "Older version"
    bad = dataclasses.replace(mods.mod("menyoo"), unsupported="Needs 1.0.1158.")
    assert (f"Not on {BUILD}", "error", "Needs 1.0.1158.") in W.mod_badges(bad, BUILD)
    assert W.mod_badges(bad)[2][0] == "Not on this build"
    odd = dataclasses.replace(mods.mod("menyoo"), tier="weird")
    assert W.mod_badges(odd)[0][0] == "Weird"


def test_mod_card_toggle_page_status(app, mods):
    card = W.ModCard(mods.mod("menyoo"), build=BUILD, status="ready")
    assert card.is_selected() and card.property("selected") is True
    assert [card.badges.itemAt(i).widget().text() for i in range(card.badges.count())][0] == "Core"
    assert card.status.kind == "ready" and card.notes.toolTip().startswith("Menyoo")
    got = []
    card.toggled.connect(lambda mid, on: got.append((mid, on)))
    card.page_requested.connect(lambda mid: got.append(("page", mid)))
    card.selector.click()
    assert got == [("menyoo", False)] and card.property("selected") is False
    card.page_btn.click()
    assert got[-1] == ("page", "menyoo") and card.page_btn.toolTip() == mods.mod("menyoo").page
    card.set_status("downloading", percent=50)
    assert card.status.text.text() == "Downloading 50%"
    pm = QPixmap(10, 10)
    card.set_picture(pm)
    assert card.art.pixmap is not None
    card.set_selected(True)
    assert card.is_selected()


def test_mod_card_radio_and_unsupported(app, mods):
    radio = W.ModCard(mods.mod("hud-geckomacabre"), mode="radio")
    assert type(radio.selector).__name__ == "QRadioButton"
    bad = dataclasses.replace(mods.mod("menyoo"), unsupported="Needs game build 1.0.1158.13.")
    card = W.ModCard(bad, build=BUILD)
    assert not card.selector.isEnabled() and not card.is_selected()
    assert card.property("disabled") is True and card.art.dim
    assert card.status.kind == "unsupported" and card.notes.property("tone") == "warning"
    plain = dataclasses.replace(mods.mod("menyoo"), notes="", author="")
    card = W.ModCard(plain)
    assert not card.notes.isVisibleTo(card) and card.meta.text() == plain.layer


# ------------------------------------------------------------------------------------------- headers / stepper
def test_hero_and_page_header(app):
    go = W.button("Start", "primary")
    hero = W.HeroHeader(LOGO, pitch="Pitch", actions=[go])
    assert not hero.logo.pixmap().isNull() and hero.title.text() == "LEONIDA V"
    assert hero.pitch.text() == "Pitch" and go.parent() is not None
    assert W.HeroHeader(None).logo.pixmap().isNull()
    right = QWidget()
    h = W.PageHeader(3, 7, "Choose", "Text", right)
    texts = [lab.text() for lab in h.findChildren(QLabel)]
    assert "STEP 3 OF 7" in texts and "Choose" in texts and right.parent() is h
    h2 = W.PageHeader(None, 7, "No step")
    assert not any(lab.text().startswith("STEP") for lab in h2.findChildren(QLabel))
    assert not h2.text.isVisibleTo(h2)


def test_stepper_states_and_paint(app):
    s = W.Stepper([("A", "copy", "done", "ok"), ("B", "", "current", None), ("C", "x", "failed", "failed"),
                   ("D", "y", "skipped", None), ("E", "z", "pending", "not-seen")])
    assert len(s.rows) == 5 and s.current() == 1
    assert s.rows[0].result.kind == "ok" and s.rows[1].result is None and s.rows[4].result.kind == "not-seen"
    assert not s.rows[1].detail.isVisibleTo(s.rows[1])
    s.resize(400, 400)
    s.show()
    img = s.grab().toImage()
    assert img.width() == 400
    dot = s.rows[0].dot
    assert dot.first and not dot.last and s.rows[4].dot.last
    s.close()
    assert W.Stepper([("A", "", "pending", None)]).current() is None
    with pytest.raises(KeyError):
        W.Stepper([("A", "", "flying", None)])
    with pytest.raises(KeyError):
        W.Stepper([("A", "", "done", "great")])


# ------------------------------------------------------------------------------------------- queue / toast / empty
def test_queue_row(app):
    acted = []
    r = W.QueueRow("Menyoo", "downloading", 40, "2 of 6 MB", [W.button("Cancel", "ghost", lambda: acted.append(1))])
    assert r.bar.value() == 40 and r.status.text.text() == "Downloading 40%" and r.detail.text() == "2 of 6 MB"
    r.set_progress("ready", detail="")
    assert r.bar.value() == 100 and r.bar.property("tone") == "success" and not r.detail.isVisibleTo(r)
    r.set_progress("failed", 30, "Connection reset")
    assert r.bar.property("tone") == "error" and r.status.kind == "failed" and r.detail.text() == "Connection reset"
    r.set_progress("manual")
    assert not r.bar.isVisibleTo(r) and r.detail.text() == "Connection reset"  # detail None keeps the text
    r.findChildren(QPushButton)[0].click()
    assert acted == [1]


def test_toast(app):
    t = W.Toast()
    assert not t.isVisible()
    t.show_message("Saved", "success", "Show", timeout_ms=5000)
    assert t.isVisible() and t.text.text() == "Saved" and t.action.text() == "Show" and t.timer.isActive()
    got = []
    t.action_clicked.connect(lambda: got.append(1))
    t.action.click()
    assert got == [1]
    t.timer.timeout.emit()
    assert not t.isVisible()
    t.show_message("Broken", "error", timeout_ms=5000)  # errors stay until closed
    assert t.isVisible() and not t.timer.isActive() and not t.action.isVisibleTo(t)
    t.close_btn.click()
    assert not t.isVisible()
    t.show_message("FYI", "info", timeout_ms=0)
    assert not t.timer.isActive() and W.TONE_COLORS["info"] in t.styleSheet()


def test_empty_state(app):
    go = W.button("Go", "primary")
    e = W.EmptyState("install", "Nothing yet", "Pick mods.", go)
    texts = [lab.text() for lab in e.findChildren(QLabel)]
    assert "Nothing yet" in texts and "Pick mods." in texts and go.parent() is e
    assert W.EmptyState("info", "T", "x").property("card") is True


# ------------------------------------------------------------------------------------------- sidebar
def test_nav_list_states(app):
    nav = W.NavList()
    nav.add_step("Welcome", state="done")
    nav.add_step("Game", state="current")
    nav.add_step("Install", state="locked", reason="Run the checks first")
    nav.add_step("Custom", icon_name="play", state="busy")
    assert nav.objectName() == "nav" and nav.currentRow() == 1
    assert [nav.state(i) for i in range(4)] == ["done", "current", "locked", "busy"]
    locked = nav.item(2)
    assert not locked.flags() & Qt.ItemFlag.ItemIsEnabled and locked.toolTip() == "Run the checks first"
    assert nav.item(3).data(Qt.ItemDataRole.UserRole) == "play"
    nav.set_state(2, "todo")
    assert nav.item(2).flags() & Qt.ItemFlag.ItemIsEnabled and nav.item(2).toolTip() == ""
    assert nav.add_step("Unknown page").data(Qt.ItemDataRole.UserRole) == "dot"
    with pytest.raises(KeyError):
        nav.set_state(0, "sleepy")


def test_sidebar_and_action_bar(app):
    side = W.Sidebar(LOGO, "1.0.0")
    assert side.objectName() == "sidebar" and not side.logo.pixmap().isNull()
    assert side.mods_state.kind == "mods-off" and side.build.text() == "Game not found"
    side.set_game(BUILD, "mods-on", "14 mods")
    assert side.build.text() == BUILD and side.mods_state.text.text() == "Mods on · 14 mods"
    side.set_game(None, "online-safe")
    assert side.build.text() == "Game not found" and side.mods_state.kind == "online-safe"
    assert W.Sidebar(None, "x").logo.pixmap().isNull()
    a, b, c = QPushButton("a"), QPushButton("b"), QPushButton("c")
    bar = W.ActionBar([a], [b, c])
    lay = bar.layout()
    assert lay.itemAt(0).widget() is a and lay.itemAt(2).widget() is b and lay.itemAt(3).widget() is c


# ------------------------------------------------------------------------------------------- preview renderer
def test_design_preview_renders_every_page(app, tmp_path):
    spec = importlib.util.spec_from_file_location("design_preview", ROOT / "build" / "design_preview.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    old_sheet, old_font, old_palette = app.styleSheet(), app.font(), app.palette()
    try:
        saved = mod.render(list(mod.RENDER), tmp_path)
    finally:
        app.setStyleSheet(old_sheet)
        app.setFont(old_font)
        app.setPalette(old_palette)
    assert [p.name for p in saved] == ["components.png"] + [f"page-{n}.png" for n in list(mod.RENDER)[1:]]
    for p in saved:
        pm = QPixmap(str(p))
        assert pm.width() >= 1280 and pm.height() >= 800
        assert pm.toImage().pixelColor(5, 5) in (QColor(theme.COLORS["bg"]), QColor(theme.COLORS["surface"]))
