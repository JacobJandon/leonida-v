"""leonida.gui.theme: tokens meet WCAG AA, the stylesheet parses, the bundled fonts load, helpers work."""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QtMsgType, qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QColor, QFontDatabase, QPalette  # noqa: E402
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget  # noqa: E402

from leonida.gui import theme  # noqa: E402


@pytest.fixture(scope="module")
def app(qt_app):
    return qt_app


# ------------------------------------------------------------------ tokens / contrast
def test_contrast_math():
    assert theme.contrast("#FFFFFF", "#000000") == pytest.approx(21.0)
    assert theme.contrast("#777777", "#777777") == pytest.approx(1.0)
    assert theme.luminance("#FFFFFF") == pytest.approx(1.0)
    assert theme.luminance("#000000") == 0.0
    assert theme.rgba("#FF4F8B", 0.5) == "rgba(255, 79, 139, 0.50)"


@pytest.mark.parametrize(("fg", "bg", "ratio", "need"), theme.contrast_report(), ids=lambda v: str(v))
def test_text_colors_meet_wcag_aa(fg, bg, ratio, need):
    assert ratio >= need, f"{fg} on {bg}: {ratio}:1 < {need}:1"


def test_every_text_token_is_checked_on_the_main_surfaces():
    checked = {(fg, bg) for fg, bg, _ in theme.CONTRAST_PAIRS}
    for fg in ("text", "text_muted", "text_subtle", "violet_text", "success", "warning", "error", "info"):
        for bg in ("bg", "surface", "surface_2"):
            assert (fg, bg) in checked
    assert all(("text_on_accent", stop) in checked for stop in theme.GRADIENT)


def test_white_on_the_accent_gradient_would_fail():
    """Why primary buttons use dark text: white on coral is below AA."""
    assert theme.contrast("#FFFFFF", theme.COLORS["coral"]) < 4.5


def test_scales_are_ordered():
    assert list(theme.SPACE.values()) == sorted(theme.SPACE.values())
    assert theme.RADIUS["sm"] < theme.RADIUS["md"] < theme.RADIUS["lg"] < theme.RADIUS["pill"]
    assert theme.TYPE["display"] > theme.TYPE["title"] > theme.TYPE["subtitle"] > theme.TYPE["body"] > theme.TYPE["small"]


# ------------------------------------------------------------------ fonts
def test_bundled_fonts_and_licences_exist():
    d = theme.fonts_dir()
    names = {p.name for p in d.iterdir()}
    assert {"Inter-Regular.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf", "Montserrat-Bold.ttf",
            "Montserrat-ExtraBold.ttf"} <= names
    assert {"Inter-LICENSE.txt", "Montserrat-OFL.txt"} <= names
    for lic in ("Inter-LICENSE.txt", "Montserrat-OFL.txt"):
        assert "SIL Open Font License" in (d / lic).read_text(encoding="utf-8")


def test_fonts_load_and_are_picked(app):
    loaded = theme.load_fonts()
    assert {"Inter", "Montserrat"} <= set(loaded)
    assert theme.pick_family(theme.BODY_FAMILIES) == "Inter"
    assert theme.pick_family(theme.DISPLAY_FAMILIES) == "Montserrat"
    assert "Bold" in QFontDatabase.styles("Montserrat") or "ExtraBold" in QFontDatabase.styles("Montserrat")


def test_load_fonts_skips_missing_folder_and_bad_files(app, tmp_path):
    assert theme.load_fonts(tmp_path / "nope") == []
    (tmp_path / "broken.ttf").write_bytes(b"not a font")
    (tmp_path / "readme.txt").write_text("x")
    assert theme.load_fonts(tmp_path) == []


def test_pick_family_falls_back_to_last(app):
    assert theme.pick_family(("No Such Font 1", "No Such Font 2")) == "No Such Font 2"


def test_fonts_dir_in_frozen_build(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert theme.fonts_dir() == tmp_path / "leonida" / "gui" / "assets" / "fonts"
    assert theme.icons_dir() == tmp_path / "leonida" / "gui" / "assets" / "icons"


def test_icons_exist():
    for name in ("check.svg", "chevron-down.svg"):
        assert (theme.icons_dir() / name).read_text(encoding="utf-8").startswith("<svg")


# ------------------------------------------------------------------ stylesheet / palette
def test_qss_uses_tokens_and_covers_components():
    qss = theme.build_qss("Inter", "Montserrat")
    assert qss.count("{") == qss.count("}")
    for hexv in ("#0D0D12", "#15151D", "#F4F1FA", "#FF4F8B", "#B08CFF"):
        assert hexv in qss
    for selector in ('QPushButton[variant="primary"]', 'QPushButton[variant="ghost"]', 'QPushButton[variant="danger"]',
                     'QFrame[card="true"][selected="true"]', 'QFrame[card="true"][disabled="true"]',
                     "QProgressBar::chunk", "QListWidget#nav::item:selected", "QLineEdit:focus",
                     'QLineEdit[invalid="true"]', "QCheckBox::indicator:checked", 'QLabel[role="badge"][tone="error"]',
                     "QToolTip", "QStatusBar", "QScrollBar", "QMessageBox", 'QFrame[toast="true"]'):
        assert selector in qss, selector
    assert '"Inter"' in qss and '"Montserrat"' in qss
    assert "check.svg" in qss and "chevron-down.svg" in qss


def test_qss_parses_without_qt_warnings(app):
    warnings: list[str] = []

    def handler(mode, _ctx, msg):
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg):
            warnings.append(msg)

    old = qInstallMessageHandler(handler)
    try:
        w = QWidget()
        w.setStyleSheet(theme.build_qss("Inter", "Montserrat"))
        for cls in (QPushButton, QLabel, QFrame):
            cls(w)
        w.ensurePolished()
        for child in w.findChildren(QWidget):
            child.ensurePolished()
        app.processEvents()
    finally:
        qInstallMessageHandler(old)
    assert not [m for m in warnings if "style" in m.lower() or "parse" in m.lower()], warnings


def test_palette_is_dark():
    p = theme.palette()
    assert p.color(QPalette.ColorRole.Window) == QColor(theme.COLORS["bg"])
    assert p.color(QPalette.ColorRole.Text) == QColor(theme.COLORS["text"])
    assert p.color(QPalette.ColorRole.Highlight) == QColor(theme.COLORS["violet"])
    assert p.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text) == QColor(theme.COLORS["text_disabled"])
    assert theme.luminance(theme.COLORS["bg"]) < 0.01


# ------------------------------------------------------------------ apply + helpers
def test_apply_theme(app, monkeypatch):
    old_sheet, old_style = app.styleSheet(), app.style().name() or "fusion"
    old_font, old_palette = app.font(), app.palette()
    styles: list[str] = []
    real_set_style = app.setStyle
    monkeypatch.setattr(app, "setStyle", lambda s: (styles.append(s), real_set_style(s))[1])
    try:
        info = theme.apply_theme(app)
        assert (info.body, info.display) == ("Inter", "Montserrat")
        assert {"Inter", "Montserrat"} <= set(info.loaded)
        assert app.font().family() == "Inter"
        assert styles == ["Fusion"]  # the native Windows style ignores parts of QSS
        assert app.palette().color(QPalette.ColorRole.Window) == QColor(theme.COLORS["bg"])
        assert 'QPushButton[variant="primary"]' in app.styleSheet()
        # a primary button really picks up the dark-on-gradient rule
        b = QPushButton("Next")
        b.setProperty("variant", "primary")
        b.ensurePolished()
        assert b.palette().color(QPalette.ColorRole.ButtonText) == QColor(theme.COLORS["text_on_accent"])
    finally:
        app.setStyleSheet(old_sheet)
        real_set_style(old_style)
        app.setFont(old_font)
        app.setPalette(old_palette)


def test_add_glow_and_repolish(app):
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    b = QPushButton("Go")
    theme.add_glow(b, radius=20, alpha=0.4)
    fx = b.graphicsEffect()
    assert isinstance(fx, QGraphicsDropShadowEffect)
    assert fx.blurRadius() == 20 and fx.offset().x() == 0
    assert fx.color().alphaF() == pytest.approx(0.4, abs=0.01)
    b.setProperty("variant", "danger")
    theme.repolish(b)  # must not raise; the property is kept
    assert b.property("variant") == "danger"


def test_gradient_label_paints_gradient(app):
    lab = theme.gradient_label("LEONIDA V")
    assert lab.property("role") == "display"
    f = lab.font()
    f.setPointSize(30)
    f.setBold(True)
    lab.setFont(f)
    lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    lab.resize(400, 60)
    lab.setStyleSheet("background: #0D0D12;")
    img = lab.grab().toImage()
    # the left of the text is warm (gold), the right cool (violet): sample the brightest pixel per third
    def brightest(x0, x1):
        best = QColor(0, 0, 0)
        for x in range(x0, x1):
            for y in range(img.height()):
                c = img.pixelColor(x, y)
                if c.lightness() > best.lightness():
                    best = c
        return best
    width = lab.fontMetrics().horizontalAdvance("LEONIDA V")
    left, right = brightest(0, width // 4), brightest(3 * width // 4, width)
    assert left.red() > left.blue()       # gold
    assert right.blue() > right.green()   # violet
