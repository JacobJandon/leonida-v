"""Leonida V look: "Sunset Emblem" dark theme (see docs/DESIGN.md).

    from leonida.gui.theme import apply_theme
    apply_theme(app)            # after QApplication exists, before windows are built

Self-contained: tokens -> Qt stylesheet (QSS) + dark QPalette + bundled fonts from leonida/gui/assets/fonts/.
Widgets opt into variants with dynamic properties, e.g.::

    button.setProperty("variant", "primary")      # primary | secondary | ghost | danger
    frame.setProperty("card", True)               # a card; add "selected"/"disabled" True for those states
    label.setProperty("role", "title")            # display | title | subtitle | muted | caption | badge | eyebrow
    label.setProperty("tone", "success")          # success | warning | error | info (status text / badges)
    nav.setObjectName("nav")                       # the wizard sidebar (QListWidget)

Change a property at runtime -> call ``repolish(widget)`` so Qt re-applies the stylesheet.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# ------------------------------------------------------------------------------------------- tokens
COLORS: dict[str, str] = {
    # surfaces (near-black, a hint of violet)
    "bg": "#0D0D12",
    "surface": "#15151D",
    "surface_2": "#1C1C27",
    "surface_3": "#262634",
    "overlay": "#0D0D12E6",      # dialogs' scrim (90%)
    "border": "#2C2C3C",
    "border_strong": "#3E3E55",
    # text (AA-checked against bg, surface and surface_2 in CONTRAST_PAIRS)
    "text": "#F4F1FA",
    "text_muted": "#BDB7CC",
    "text_subtle": "#9690A8",
    "text_disabled": "#5E596E",
    "text_on_accent": "#0D0D12",  # on the gold -> coral primary gradient
    # sunset brand
    "gold": "#FFC15E",
    "coral": "#FF4F8B",
    "violet": "#8B3DFF",
    "violet_text": "#B08CFF",     # violet light enough for text/links on dark
    "focus": "#B08CFF",
    # status
    "success": "#3DDC97",
    "warning": "#FFC15E",
    "error": "#FF6B81",
    "info": "#5CC8FF",
}
GRADIENT = ("#FFC15E", "#FF7A6B", "#FF4F8B")           # primary buttons, progress chunks (gold -> coral)
GRADIENT_FULL = ("#FFC15E", "#FF4F8B", "#8B3DFF")      # brand strip, hero, selected nav marker
SPACE = {"xxs": 2, "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32, "xxxl": 48}
RADIUS = {"sm": 6, "md": 10, "lg": 14, "pill": 999}
# point sizes (Qt pt; 10pt is ~13px at 96 dpi)
TYPE = {"display": 26, "title": 17, "subtitle": 12, "body": 10, "small": 9, "caption": 8}
BODY_FAMILIES = ("Inter", "Segoe UI Variable Text", "Segoe UI", "Roboto", "Helvetica Neue", "Arial")
DISPLAY_FAMILIES = ("Montserrat", "Inter", "Segoe UI Variable Display", "Segoe UI", "Arial")

# (foreground, background, minimum WCAG ratio): checked by tests/test_theme.py
CONTRAST_PAIRS: list[tuple[str, str, float]] = [
    *[(fg, bg, 4.5) for fg in ("text", "text_muted", "text_subtle", "violet_text", "gold", "coral",
                               "success", "warning", "error", "info")
      for bg in ("bg", "surface", "surface_2")],
    ("text", "surface_3", 4.5),
    ("text_muted", "surface_3", 4.5),
    *[("text_on_accent", c, 4.5) for c in GRADIENT],
    ("text_disabled", "surface_2", 2.0),  # disabled text is exempt from AA; just keep it visible
]


# ------------------------------------------------------------------------------------------- contrast
def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")[:6]
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(hex_color: str) -> float:
    """WCAG 2.x relative luminance."""
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def contrast_report(colors: dict[str, str] | None = None) -> list[tuple[str, str, float, float]]:
    """[(fg, bg, ratio, required)] for every pair in CONTRAST_PAIRS (a name is a token, or a literal #hex)."""
    c = colors or COLORS
    return [(fg, bg, round(contrast(c.get(fg, fg), c.get(bg, bg)), 2), need) for fg, bg, need in CONTRAST_PAIRS]


def rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (round(x * 255) for x in _rgb(hex_color))
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


# ------------------------------------------------------------------------------------------- fonts
def fonts_dir() -> Path:
    """leonida/gui/assets/fonts, also inside the frozen build (sys._MEIPASS/leonida/gui/assets/fonts)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "leonida" / "gui" / "assets" / "fonts"
    return Path(__file__).resolve().parent / "assets" / "fonts"


def icons_dir() -> Path:
    """leonida/gui/assets/icons (small SVGs the stylesheet uses: checkbox tick, combo chevron)."""
    return fonts_dir().parent / "icons"


def _url(path: Path) -> str:
    return path.resolve().as_posix()


def load_fonts(folder: Path | None = None) -> list[str]:
    """Register every .ttf/.otf in the fonts folder with Qt; returns the family names that loaded."""
    from PySide6.QtGui import QFontDatabase

    folder = folder or fonts_dir()
    families: list[str] = []
    if not folder.is_dir():
        return families
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in (".ttf", ".otf"):
            fid = QFontDatabase.addApplicationFont(str(f))
            if fid >= 0:
                families += [n for n in QFontDatabase.applicationFontFamilies(fid) if n not in families]
    return families


def pick_family(preferred: tuple[str, ...]) -> str:
    from PySide6.QtGui import QFontDatabase

    have = {f.lower(): f for f in QFontDatabase.families()}
    for name in preferred:
        if name.lower() in have:
            return have[name.lower()]
    return preferred[-1]


# ------------------------------------------------------------------------------------------- QSS
def _grad(stops: tuple[str, ...], horizontal: bool = True) -> str:
    end = "x2:1, y2:0" if horizontal else "x2:0, y2:1"
    n = len(stops) - 1
    parts = ", ".join(f"stop:{i / n:.2f} {c}" for i, c in enumerate(stops))
    return f"qlineargradient(x1:0, y1:0, {end}, {parts})"


def build_qss(body: str = "Segoe UI", display: str = "Segoe UI", colors: dict[str, str] | None = None) -> str:
    c = colors or COLORS
    r, s, t = RADIUS, SPACE, TYPE
    accent = _grad(GRADIENT)
    accent_hover = _grad(("#FFD27F", "#FF8C7C", "#FF6AA0"))
    accent_pressed = _grad(("#E8A94A", "#E86A5D", "#E3417A"))
    brand = _grad(GRADIENT_FULL)
    check = _url(icons_dir() / "check.svg")
    check_muted = _url(icons_dir() / "check-muted.svg")
    chevron = _url(icons_dir() / "chevron-down.svg")
    return f"""
/* ---- base ---- */
QWidget {{
    background: {c['bg']}; color: {c['text']};
    font-family: "{body}"; font-size: {t['body']}pt;
    selection-background-color: {rgba(c['violet'], 0.55)}; selection-color: {c['text']};
}}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QToolTip {{
    background: {c['surface_3']}; color: {c['text']}; border: 1px solid {c['border_strong']};
    border-radius: {r['sm']}px; padding: {s['xs']}px {s['sm']}px;
}}
QLabel {{ background: transparent; }}
QLabel[role="display"] {{
    font-family: "{display}"; font-size: {t['display']}pt; font-weight: 800; letter-spacing: 1px;
}}
QLabel[role="title"] {{ font-family: "{display}"; font-size: {t['title']}pt; font-weight: 700; }}
QLabel[role="subtitle"] {{ font-size: {t['subtitle']}pt; font-weight: 600; color: {c['text']}; }}
QLabel[role="muted"] {{ color: {c['text_muted']}; }}
QLabel[role="caption"] {{ color: {c['text_subtle']}; font-size: {t['small']}pt; }}
QLabel[role="eyebrow"] {{
    color: {c['coral']}; font-family: "{display}"; font-size: {t['caption']}pt; font-weight: 700;
    letter-spacing: 2px;
}}
QLabel[role="badge"] {{
    background: {c['surface_3']}; color: {c['text_muted']}; border: 1px solid {c['border_strong']};
    border-radius: 9px; padding: 1px {s['sm']}px; font-size: {t['caption']}pt; font-weight: 600;
    min-height: 16px; max-height: 18px;
}}
QLabel[tone="success"] {{ color: {c['success']}; }}
QLabel[tone="warning"] {{ color: {c['warning']}; }}
QLabel[tone="error"] {{ color: {c['error']}; }}
QLabel[tone="info"] {{ color: {c['info']}; }}
QLabel[role="badge"][tone="success"] {{ background: {rgba(c['success'], 0.12)}; border-color: {rgba(c['success'], 0.45)}; }}
QLabel[role="badge"][tone="warning"] {{ background: {rgba(c['warning'], 0.12)}; border-color: {rgba(c['warning'], 0.45)}; }}
QLabel[role="badge"][tone="error"] {{ background: {rgba(c['error'], 0.12)}; border-color: {rgba(c['error'], 0.45)}; }}
QLabel[role="badge"][tone="info"] {{ background: {rgba(c['info'], 0.12)}; border-color: {rgba(c['info'], 0.45)}; }}
QLabel a, QTextBrowser a {{ color: {c['violet_text']}; }}
QFrame[brand="true"] {{ background: {brand}; border: none; max-height: 3px; min-height: 3px; }}
QFrame[divider="true"] {{ background: {c['border']}; border: none; max-height: 1px; min-height: 1px; }}

/* ---- buttons ---- */
QPushButton, QToolButton {{
    background: {c['surface_2']}; color: {c['text']}; border: 1px solid {c['border_strong']};
    border-radius: {r['md']}px; padding: {s['sm']}px {s['lg']}px; font-weight: 600; min-height: 20px;
}}
QPushButton:hover, QToolButton:hover {{ background: {c['surface_3']}; border-color: {c['violet_text']}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {c['surface']}; }}
QPushButton:focus, QToolButton:focus {{ border: 1px solid {c['focus']}; outline: none; }}
QPushButton:disabled, QToolButton:disabled {{
    background: {c['surface']}; color: {c['text_disabled']}; border-color: {c['border']};
}}
QPushButton[variant="primary"] {{
    background: {accent}; color: {c['text_on_accent']}; border: 1px solid transparent; font-weight: 700;
}}
QPushButton[variant="primary"]:hover {{ background: {accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {accent_pressed}; }}
QPushButton[variant="primary"]:focus {{ border: 1px solid {c['text']}; }}
QPushButton[variant="primary"]:disabled {{ background: {c['surface_3']}; color: {c['text_disabled']}; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; color: {c['text_muted']}; }}
QPushButton[variant="ghost"]:hover {{ background: {c['surface_2']}; color: {c['text']}; }}
QPushButton[variant="danger"] {{ color: {c['error']}; border-color: {rgba(c['error'], 0.55)}; background: {rgba(c['error'], 0.08)}; }}
QPushButton[variant="danger"]:hover {{ background: {rgba(c['error'], 0.18)}; border-color: {c['error']}; }}

/* ---- inputs ---- */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit, QTextBrowser {{
    background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border_strong']};
    border-radius: {r['sm']}px; padding: {s['sm'] - 2}px {s['sm']}px;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {c['text_subtle']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {c['focus']}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {c['text_disabled']}; border-color: {c['border']}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {c['error']}; }}
QPlainTextEdit[log="true"] {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: {t['small']}pt; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {c['surface_2']}; border: 1px solid {c['border_strong']}; selection-background-color: {c['surface_3']};
}}
QCheckBox, QRadioButton {{ spacing: {s['sm']}px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {c['border_strong']}; background: {c['surface']};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c['violet_text']}; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {accent}; border-color: {c['coral']}; }}
QCheckBox::indicator:checked {{ image: url("{check}"); }}
QCheckBox::indicator:checked:disabled {{
    background: {c['surface_3']}; border-color: {c['border_strong']}; image: url("{check_muted}");
}}
QCheckBox::indicator:disabled {{ background: {c['surface_2']}; border-color: {c['border']}; }}

/* ---- cards ---- */
QFrame[card="true"] {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['lg']}px;
}}
QFrame[card="true"]:hover {{ border-color: {c['border_strong']}; background: {c['surface_2']}; }}
QFrame[card="true"][selected="true"] {{ border: 1px solid {c['coral']}; background: {c['surface_2']}; }}
QFrame[card="true"][disabled="true"] {{ background: {c['bg']}; border: 1px dashed {c['border']}; }}
QFrame[card="true"][tone="error"] {{ border-color: {rgba(c['error'], 0.6)}; }}
QFrame[card="true"][tone="warning"] {{ border-color: {rgba(c['warning'], 0.6)}; }}
QFrame[card="true"][tone="success"] {{ border-color: {rgba(c['success'], 0.5)}; }}
QFrame[card="true"] QLabel {{ background: transparent; }}
QFrame[toast="true"] {{
    background: {c['surface_3']}; border: 1px solid {c['border_strong']}; border-radius: {r['md']}px;
}}

/* ---- progress ---- */
QProgressBar {{
    background: {c['surface_3']}; border: none; border-radius: 4px; color: {c['text_muted']};
    text-align: center; min-height: 8px; max-height: 8px; font-size: {t['caption']}pt;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
QProgressBar[tone="success"]::chunk {{ background: {c['success']}; }}
QProgressBar[tone="error"]::chunk {{ background: {c['error']}; }}
QProgressBar[thick="true"] {{ min-height: 18px; max-height: 18px; border-radius: 9px; color: {c['text']}; }}
QProgressBar[thick="true"]::chunk {{ border-radius: 9px; }}

/* ---- lists / tables ---- */
QListWidget, QListView, QTreeView, QTableWidget, QTableView {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['md']}px;
    alternate-background-color: {c['surface_2']}; outline: none; gridline-color: {c['border']};
}}
QListWidget::item, QListView::item, QTreeView::item {{ padding: {s['sm']}px {s['md']}px; border-radius: {r['sm']}px; }}
QListWidget::item:hover, QListView::item:hover, QTreeView::item:hover, QTableView::item:hover {{ background: {c['surface_2']}; }}
QListWidget::item:selected, QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {{
    background: {c['surface_3']}; color: {c['text']};
}}
QListWidget::item:disabled {{ color: {c['text_disabled']}; }}
QHeaderView::section {{
    background: {c['surface_2']}; color: {c['text_muted']}; border: none; border-bottom: 1px solid {c['border']};
    padding: {s['sm']}px {s['md']}px; font-weight: 600;
}}

/* ---- nav sidebar (QListWidget#nav) ---- */
QWidget#sidebar {{ background: {c['surface']}; border-right: 1px solid {c['border']}; }}
QListWidget#nav {{ background: transparent; border: none; padding: {s['sm']}px 0; }}
QListWidget#nav::item {{
    color: {c['text_muted']}; padding: {s['md'] - 2}px {s['lg']}px; margin: 2px {s['sm']}px;
    border-radius: {r['md']}px; border-left: 3px solid transparent;
}}
QListWidget#nav[compact="true"]::item {{ padding: {s['sm'] - 1}px {s['lg']}px; margin: 1px {s['sm']}px; }}
QListWidget#nav::item:hover {{ background: {c['surface_2']}; color: {c['text']}; }}
QListWidget#nav::item:selected {{
    background: {rgba(c['coral'], 0.12)}; color: {c['text']}; border-left: 3px solid {c['coral']}; font-weight: 700;
}}
QListWidget#nav::item:disabled {{ color: {c['text_disabled']}; }}

/* ---- scroll bars ---- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {c['border_strong']}; border-radius: 4px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {c['text_subtle']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0;
}}

/* ---- tabs, status bar, menus, dialogs ---- */
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: {r['md']}px; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {c['text_muted']}; padding: {s['sm']}px {s['lg']}px; border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['coral']}; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QStatusBar {{ background: {c['surface']}; color: {c['text_muted']}; border-top: 1px solid {c['border']}; }}
QStatusBar QLabel {{ color: {c['text_muted']}; }}
QMenu {{ background: {c['surface_2']}; border: 1px solid {c['border_strong']}; border-radius: {r['sm']}px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['surface_3']}; }}
QMessageBox, QInputDialog, QFileDialog {{ background: {c['surface']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
QDialogButtonBox QPushButton {{ min-width: 84px; }}
"""


def palette(colors: dict[str, str] | None = None):
    """A dark QPalette matching the tokens (native dialogs and widgets that ignore QSS use it)."""
    from PySide6.QtGui import QColor, QPalette

    c = colors or COLORS
    p = QPalette()
    role, grp = QPalette.ColorRole, QPalette.ColorGroup
    pairs = {
        role.Window: c["bg"], role.WindowText: c["text"], role.Base: c["surface"], role.AlternateBase: c["surface_2"],
        role.ToolTipBase: c["surface_3"], role.ToolTipText: c["text"], role.PlaceholderText: c["text_subtle"],
        role.Text: c["text"], role.Button: c["surface_2"], role.ButtonText: c["text"], role.BrightText: c["coral"],
        role.Highlight: c["violet"], role.HighlightedText: c["text"], role.Link: c["violet_text"],
        role.LinkVisited: c["coral"], role.Light: c["surface_3"], role.Midlight: c["border_strong"],
        role.Mid: c["border"], role.Dark: c["surface"], role.Shadow: "#000000",
    }
    for r_, hexv in pairs.items():
        p.setColor(r_, QColor(hexv))
    for r_ in (role.WindowText, role.Text, role.ButtonText):
        p.setColor(grp.Disabled, r_, QColor(c["text_disabled"]))
    return p


def add_glow(widget, color: str = COLORS["coral"], radius: int = 28, alpha: float = 0.55) -> None:
    """Neon glow under a widget (hero logo, primary call to action)."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    fx = QGraphicsDropShadowEffect(widget)
    q = QColor(color)
    q.setAlphaF(alpha)
    fx.setColor(q)
    fx.setBlurRadius(radius)
    fx.setOffset(0, 0)
    widget.setGraphicsEffect(fx)


def glow_pixmap(pm, color: str = COLORS["coral"], radius: int = 60, alpha: float = 0.5, pad: int | None = None):
    """``pm`` with the same glow as add_glow, drawn once into a bigger pixmap (``pad`` px around it). A drop-shadow
    effect on a widget is blurred again on every repaint; a big static picture (the hero logo) doesn't need that."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsPixmapItem, QGraphicsScene

    pad = radius // 2 if pad is None else pad
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pm)
    fx = QGraphicsDropShadowEffect()
    q = QColor(color)
    q.setAlphaF(alpha)
    fx.setColor(q)
    fx.setBlurRadius(radius)
    fx.setOffset(0, 0)
    item.setGraphicsEffect(fx)
    scene.addItem(item)
    w, h = pm.width() + 2 * pad, pm.height() + 2 * pad
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(p, QRectF(0, 0, w, h), QRectF(-pad, -pad, w, h))
    p.end()
    return QPixmap.fromImage(img)


def gradient_label(text: str, stops: tuple[str, ...] = ("#FFC15E", "#FF4F8B", "#A66BFF"), role: str = "display"):
    """A QLabel whose text is painted with the sunset gradient (QSS can't gradient text). Used for the hero title."""
    from PySide6.QtGui import QLinearGradient, QPainter, QPen
    from PySide6.QtWidgets import QLabel

    class GradientLabel(QLabel):
        def paintEvent(self, _event):  # noqa: N802 - Qt naming
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            rect = self.contentsRect()
            width = self.fontMetrics().horizontalAdvance(self.text()) or rect.width()
            g = QLinearGradient(rect.left(), 0, rect.left() + width, 0)
            for i, col in enumerate(stops):
                g.setColorAt(i / max(1, len(stops) - 1), col)
            p.setPen(QPen(g, 1))
            p.setFont(self.font())
            p.drawText(rect, int(self.alignment()), self.text())
            p.end()

    lab = GradientLabel(text)
    lab.setProperty("role", role)
    return lab


def repolish(widget) -> None:
    """Re-apply the stylesheet after changing a dynamic property (variant, selected, tone, ...)."""
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


@dataclass
class ThemeInfo:
    body: str
    display: str
    loaded: list[str] = field(default_factory=list)  # families loaded from the bundled fonts


def apply_theme(app) -> ThemeInfo:
    """Load the bundled fonts, then set the Fusion style, the dark palette, the app font and the stylesheet."""
    from PySide6.QtGui import QFont

    loaded = load_fonts()
    body, display = pick_family(BODY_FAMILIES), pick_family(DISPLAY_FAMILIES)
    app.setStyle("Fusion")  # the native Windows style ignores parts of QSS and the palette
    app.setPalette(palette())
    font = QFont(body, TYPE["body"])
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    app.setStyleSheet(build_qss(body, display))
    return ThemeInfo(body, display, loaded)
