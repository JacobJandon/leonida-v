"""Styled building blocks for the redesigned Leonida V pages (docs/DESIGN.md, theme from leonida/gui/theme.py).

Self-contained; nothing in app.py uses it yet. Every widget only sets dynamic properties the theme's stylesheet
understands (variant, card, role, tone, ...), so it looks right as soon as ``theme.apply_theme(app)`` ran.

    icon(name, color, size)       small vector icons drawn with QPainter (no icon font needed)
    Badge, StatusPill             tone-coloured labels; StatusPill.set_status("downloading", percent=42)
    FlowLayout                    wrapping row (badges)
    Art                           a mod's picture, or a sunset placeholder when there is none
    ModCard                       picture, name, author, badges, notes (tooltip), include toggle / slot radio, page
    HeroHeader, PageHeader        Welcome hero with the logo; the per-page "STEP n OF 7" header with the brand strip
    Stepper                       Install steps with state and the play-test result
    QueueRow                      one mod in the download queue with its progress bar
    Toast, EmptyState             result message with an action; a friendly empty page
    NavList, Sidebar, ActionBar   the wizard sidebar (icons + states) and the bottom action row
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from . import theme

C = theme.COLORS
TONE_COLORS = {"success": C["success"], "warning": C["warning"], "error": C["error"], "info": C["info"],
               "accent": C["coral"], None: C["text_muted"], "muted": C["text_subtle"]}


# ------------------------------------------------------------------------------------------- icons
def _path_for(name: str, s: float) -> tuple[QPainterPath, bool]:
    """Icon outline in an s x s box. Returns (path, filled)."""
    p = QPainterPath()
    u = s / 24.0  # icons are designed on a 24-unit grid

    def pt(x, y):
        return QPointF(x * u, y * u)

    if name == "home":
        p.moveTo(pt(3, 11)); p.lineTo(pt(12, 3.5)); p.lineTo(pt(21, 11))  # noqa: E702
        p.moveTo(pt(5.5, 9.5)); p.lineTo(pt(5.5, 20)); p.lineTo(pt(18.5, 20)); p.lineTo(pt(18.5, 9.5))  # noqa: E702
        p.moveTo(pt(10, 20)); p.lineTo(pt(10, 14)); p.lineTo(pt(14, 14)); p.lineTo(pt(14, 20))  # noqa: E702
    elif name == "game":
        p.addRoundedRect(QRectF(pt(2.5, 7), pt(21.5, 18)), 4.5 * u, 4.5 * u)
        p.moveTo(pt(7, 10.5)); p.lineTo(pt(7, 14.5)); p.moveTo(pt(5, 12.5)); p.lineTo(pt(9, 12.5))  # noqa: E702
        p.addEllipse(pt(16, 11.2), 1.1 * u, 1.1 * u)
        p.addEllipse(pt(18, 13.8), 1.1 * u, 1.1 * u)
    elif name == "mods":
        for x, y in ((3.5, 3.5), (13, 3.5), (3.5, 13), (13, 13)):
            p.addRoundedRect(QRectF(pt(x, y), pt(x + 7.5, y + 7.5)), 2 * u, 2 * u)
    elif name == "download":
        p.moveTo(pt(12, 3.5)); p.lineTo(pt(12, 15))  # noqa: E702
        p.moveTo(pt(7.5, 10.5)); p.lineTo(pt(12, 15)); p.lineTo(pt(16.5, 10.5))  # noqa: E702
        p.moveTo(pt(4, 15.5)); p.lineTo(pt(4, 20)); p.lineTo(pt(20, 20)); p.lineTo(pt(20, 15.5))  # noqa: E702
    elif name == "shield":
        p.moveTo(pt(12, 3)); p.lineTo(pt(19.5, 6)); p.lineTo(pt(19.5, 11.5))  # noqa: E702
        p.quadTo(pt(19.5, 18), pt(12, 21)); p.quadTo(pt(4.5, 18), pt(4.5, 11.5))  # noqa: E702
        p.lineTo(pt(4.5, 6)); p.closeSubpath()  # noqa: E702
        p.moveTo(pt(8.5, 12)); p.lineTo(pt(11, 14.5)); p.lineTo(pt(15.5, 9.5))  # noqa: E702
    elif name == "install":
        p.moveTo(pt(3.5, 8)); p.lineTo(pt(12, 3.5)); p.lineTo(pt(20.5, 8)); p.lineTo(pt(20.5, 16.5))  # noqa: E702
        p.lineTo(pt(12, 21)); p.lineTo(pt(3.5, 16.5)); p.closeSubpath()  # noqa: E702
        p.moveTo(pt(3.5, 8)); p.lineTo(pt(12, 12.5)); p.lineTo(pt(20.5, 8)); p.moveTo(pt(12, 12.5)); p.lineTo(pt(12, 21))  # noqa: E702
    elif name == "manage":
        for y, x in ((6, 15), (12, 8), (18, 13)):
            p.moveTo(pt(3.5, y)); p.lineTo(pt(20.5, y))  # noqa: E702
            p.addEllipse(pt(x, y), 2.2 * u, 2.2 * u)
    elif name == "check":
        p.moveTo(pt(5, 12.5)); p.lineTo(pt(10, 17.5)); p.lineTo(pt(19.5, 7))  # noqa: E702
    elif name == "cross":
        p.moveTo(pt(6.5, 6.5)); p.lineTo(pt(17.5, 17.5)); p.moveTo(pt(17.5, 6.5)); p.lineTo(pt(6.5, 17.5))  # noqa: E702
    elif name == "warning":
        p.moveTo(pt(12, 3.5)); p.lineTo(pt(21.5, 20)); p.lineTo(pt(2.5, 20)); p.closeSubpath()  # noqa: E702
        p.moveTo(pt(12, 9.5)); p.lineTo(pt(12, 14)); p.moveTo(pt(12, 16.8)); p.lineTo(pt(12, 17))  # noqa: E702
    elif name == "info":
        p.addEllipse(pt(12, 12), 9 * u, 9 * u)
        p.moveTo(pt(12, 11)); p.lineTo(pt(12, 16.5)); p.moveTo(pt(12, 7.8)); p.lineTo(pt(12, 8))  # noqa: E702
    elif name == "play":
        p.moveTo(pt(8, 5)); p.lineTo(pt(19, 12)); p.lineTo(pt(8, 19)); p.closeSubpath()  # noqa: E702
        return p, True
    elif name == "dot":
        p.addEllipse(pt(12, 12), 4.5 * u, 4.5 * u)
        return p, True
    elif name == "external":
        p.moveTo(pt(13.5, 4)); p.lineTo(pt(20, 4)); p.lineTo(pt(20, 10.5))  # noqa: E702
        p.moveTo(pt(20, 4)); p.lineTo(pt(11, 13))  # noqa: E702
        p.moveTo(pt(17.5, 14)); p.lineTo(pt(17.5, 20)); p.lineTo(pt(4, 20)); p.lineTo(pt(4, 6.5)); p.lineTo(pt(10, 6.5))  # noqa: E702
    elif name == "lock":
        p.addRoundedRect(QRectF(pt(5, 10.5), pt(19, 20.5)), 2 * u, 2 * u)
        p.moveTo(pt(8, 10.5)); p.lineTo(pt(8, 7.5)); p.arcTo(QRectF(pt(8, 3.5), pt(16, 11.5)), 180, -180)  # noqa: E702
        p.lineTo(pt(16, 10.5))
    elif name == "spinner":
        p.arcMoveTo(QRectF(pt(4, 4), pt(20, 20)), 90)
        p.arcTo(QRectF(pt(4, 4), pt(20, 20)), 90, 270)
    else:
        raise KeyError(f"no icon {name!r}")
    return p, False


ICONS = ("home", "game", "mods", "download", "shield", "install", "manage", "check", "cross", "warning", "info",
         "play", "dot", "external", "lock", "spinner")


_ICON_CACHE: dict[tuple, QPixmap] = {}


def icon_pixmap(name: str, color: str = C["text_muted"], size: int = 18, stroke: float = 1.8) -> QPixmap:
    key = (name, color, size, stroke)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return QPixmap(cached)  # implicitly shared: a cheap copy
    pm = QPixmap(QSize(size, size) * 2)  # drawn at 2x, so it stays crisp on high-DPI screens
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    path, filled = _path_for(name, size)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), stroke * size / 18.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QBrush(QColor(color)) if filled else Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.end()
    _ICON_CACHE[key] = pm
    return QPixmap(pm)


def icon(name: str, color: str = C["text_muted"], size: int = 18) -> QIcon:
    return QIcon(icon_pixmap(name, color, size))


def _icon_label(name: str, color: str, size: int = 16) -> QLabel:
    lab = QLabel()
    lab.setPixmap(icon_pixmap(name, color, size))
    lab.setFixedSize(size, size)
    lab.setProperty("iconName", name)
    return lab


def _label(text: str, role: str | None = None, tone: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    if tone:
        lab.setProperty("tone", tone)
    lab.setWordWrap(wrap)
    return lab


def button(text: str, variant: str = "secondary", on_click: Callable | None = None, icon_name: str | None = None,
           glow: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("variant", variant)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        col = C["text_on_accent"] if variant == "primary" else (C["error"] if variant == "danger" else C["text_muted"])
        b.setIcon(icon(icon_name, col, 16))
        b.setIconSize(QSize(16, 16))
    if on_click:
        b.clicked.connect(on_click)
    if glow:
        theme.add_glow(b, radius=24, alpha=0.4)
    return b


# ------------------------------------------------------------------------------------------- labels
class Badge(QLabel):
    """Small rounded label; tone None/success/warning/error/info."""

    def __init__(self, text: str, tone: str | None = None, tooltip: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setProperty("role", "badge")
        self.setProperty("tone", tone or "")  # not polished yet: no repolish needed
        if tooltip:
            self.setToolTip(tooltip)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_tone(self, tone: str | None) -> None:
        self.setProperty("tone", tone or "")
        theme.repolish(self)


# kind -> (text, tone, icon)
STATUS = {
    "ready": ("Ready", "success", "check"),
    "missing": ("Not downloaded", None, "download"),
    "wrong": ("Wrong edition", "error", "warning"),
    "downloading": ("Downloading", "info", "spinner"),
    "queued": ("Queued", None, "dot"),
    "installed": ("Installed", "success", "install"),
    "ok": ("OK in game", "success", "shield"),
    "failed": ("Failed", "error", "cross"),
    "not-seen": ("Not seen yet", "warning", "info"),
    "manual": ("Get it yourself", "warning", "external"),
    "paid": ("Paid", "warning", "lock"),
    "unsupported": ("Not on this build", "warning", "warning"),
    "mods-on": ("Mods on", "success", "check"),
    "mods-off": ("No mods yet", None, "dot"),
    "online-safe": ("Online-safe", "info", "shield"),
    "up-to-date": ("Up to date", "success", "check"),
    "update-ready": ("Update ready", "info", "download"),
}


class StatusPill(QFrame):
    """Icon + text in a rounded pill. ``set_status("downloading", percent=42)`` -> 'Downloading 42%'."""

    def __init__(self, kind: str = "missing", detail: str = "", percent: int | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pill")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 10, 2)
        lay.setSpacing(5)
        self.icon = QLabel()
        self.icon.setFixedSize(12, 12)
        self.text = QLabel()
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.kind = ""
        self.set_status(kind, detail, percent)

    def set_status(self, kind: str, detail: str = "", percent: int | None = None) -> None:
        if kind not in STATUS:
            raise KeyError(f"unknown status {kind!r}")
        text, tone, icon_name = STATUS[kind]
        if percent is not None:
            text = f"{text} {max(0, min(100, int(percent)))}%"
        if detail:
            text = f"{text} · {detail}"
        self.kind = kind
        col = TONE_COLORS[tone]
        self.icon.setPixmap(icon_pixmap(icon_name, col, 12))
        self.text.setText(text)
        self.text.setStyleSheet(f"color: {col}; font-size: {theme.TYPE['caption']}pt; font-weight: 600;"
                                "background: transparent;")
        self.setStyleSheet(f"QFrame#pill {{ background: {theme.rgba(col, 0.12)}; border: 1px solid "
                           f"{theme.rgba(col, 0.40)}; border-radius: 10px; }}")
        self.setToolTip(text)


# ------------------------------------------------------------------------------------------- layout
class FlowLayout(QLayout):
    """Lays children out left to right and wraps (Qt's classic flow layout)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802 - Qt naming
        self._items.append(item)

    def addWidget(self, w: QWidget) -> None:  # noqa: N802
        self.addChildWidget(w)
        self.addItem(QWidgetItem(w))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _do_layout(self, rect: QRect, test: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            height = hint.height()
            if it.hasHeightForWidth():  # wrapped text: the real height at this width, not the bare size hint
                height = max(height, it.heightForWidth(hint.width()))
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if not test:
                it.setGeometry(QRect(x, y, hint.width(), height))
            x += hint.width() + self._spacing
            line = max(line, height)
        return y + line - rect.y()


def clear_background(w: QWidget) -> QWidget:
    """Let the card/page behind show through a plain container. The theme paints plain QWidgets with the page colour;
    the rule is scoped by object name because a selector-less widget stylesheet would also strip the background of
    every child (buttons, badges, cards)."""
    w.setObjectName("clearbg")
    w.setStyleSheet("QWidget#clearbg { background: transparent; }")
    return w


def flow_box(spacing: int = 6) -> tuple[QWidget, FlowLayout]:
    """A transparent container with a FlowLayout (badge / pill rows inside cards)."""
    holder = clear_background(QWidget())
    return holder, FlowLayout(holder, spacing=spacing)


# ------------------------------------------------------------------------------------------- art
LAYER_HUES = {"Framework": 265, "Graphics": 20, "Fixes": 190, "Traffic": 330, "Driving": 5, "Physics": 280,
              "Camera": 300, "HUD": 345, "Tools": 210, "World": 150, "Interiors": 35, "Vehicles": 15,
              "Gameplay": 320, "Combat": 0, "Characters": 290}


class Art(QWidget):
    """A mod's picture (rounded, cropped to fill), or a sunset placeholder with the layer name."""

    def __init__(self, seed: str = "", label: str = "", height: int = 118, parent: QWidget | None = None):
        super().__init__(parent)
        self.seed, self.label = seed, label
        self.pixmap: QPixmap | None = None
        self.dim = False
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_pixmap(self, pm: QPixmap | None) -> None:
        self.pixmap = pm if pm is not None and not pm.isNull() else None
        self.update()

    def _colors(self) -> tuple[QColor, QColor]:
        hue = LAYER_HUES.get(self.label)
        if hue is None:
            hue = int(hashlib.sha1(self.seed.encode()).hexdigest()[:4], 16) % 360
        a = QColor.fromHsv(hue % 360, 150, 255)
        b = QColor.fromHsv((hue + 300) % 360, 200, 150)
        return a, b

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 10, 10)
        p.setClipPath(clip)
        if self.pixmap is not None:
            pm = self.pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int((self.width() - pm.width()) / 2), int((self.height() - pm.height()) / 2), pm)
        else:
            a, b = self._colors()
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, a)
            g.setColorAt(1, b)
            p.fillRect(r, g)
            # retro sun with horizontal cuts, like the logo
            sun = r.height() * 0.95
            cx, cy = r.width() * 0.72, r.height() * 0.88
            sg = QLinearGradient(0, cy - sun / 2, 0, cy + sun / 2)
            sg.setColorAt(0, QColor(255, 220, 140, 220))
            sg.setColorAt(1, QColor(255, 79, 139, 120))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sg)
            p.drawEllipse(QPointF(cx, cy), sun / 2, sun / 2)
            p.setBrush(b)
            for i in range(5):
                y = cy - sun * 0.05 + i * sun * 0.07
                p.drawRect(QRectF(cx - sun / 2, y, sun, 1.6 + i * 0.9))
            # horizon glow
            hg = QLinearGradient(0, r.height() * 0.6, 0, r.height())
            hg.setColorAt(0, QColor(13, 13, 18, 0))
            hg.setColorAt(1, QColor(13, 13, 18, 170))
            p.fillRect(r, hg)
            if self.label:
                p.setPen(QColor(255, 255, 255, 215))
                f = self.font()
                f.setPointSize(8)
                f.setBold(True)
                f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 1.5)
                p.setFont(f)
                p.drawText(QRectF(12, 0, r.width() - 24, r.height() - 10),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom), self.label.upper())
        if self.dim:
            p.fillRect(r, QColor(13, 13, 18, 170))
        p.end()


# ------------------------------------------------------------------------------------------- mod card
def mod_badges(mod, build: str | None = None) -> list[tuple[str, str | None, str]]:
    """(text, tone, tooltip) badges for a mod: tier, free/paid, build support, download route."""
    tier = {"core": ("Core", "info"), "optional": ("Optional", None), "alternative": ("Alternative", None),
            "paid": ("Paid tier", "warning")}.get(mod.tier, (mod.tier.title(), None))
    out = [(tier[0], tier[1], f"Tier: {mod.tier}")]
    out.append(("Paid", "warning", "Costs money right now") if getattr(mod, "is_paid", False)
               else ("Free", "success", "Free download from the author"))
    if getattr(mod, "unsupported", None):
        out.append((f"Not on {build}" if build else "Not on this build", "error", mod.unsupported))
    elif getattr(mod, "variant", None) is not None:
        out.append(("Older version", "info", f"Uses {mod.version} for your game build"))
    else:
        out.append(("Works on your build", "success", f"Version {mod.version}"))
    if getattr(mod, "download", None):
        out.append(("Auto download", "success", "Leonida downloads it from the author's release"))
    elif getattr(mod, "manual_download", False):
        where = {"patreon": "Patreon", "discord": "Discord", "shop": "Shop", "nexus-login": "Nexus login"}
        out.append((where.get(mod.source, "Manual"), "warning", "You download it yourself from the author's page"))
    else:
        out.append(("In-app browser", None, "Click Download on the author's page inside Leonida"))
    return out


class ModCard(QFrame):
    """A mod in the chooser grid. ``mode`` "toggle" (checkbox) or "radio" (one per slot; group it yourself)."""

    toggled = Signal(str, bool)
    page_requested = Signal(str)

    def __init__(self, mod, *, build: str | None = None, selected: bool = True, mode: str = "toggle",
                 status: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.mod = mod
        self.setProperty("card", True)
        self.setFixedWidth(292)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)  # never squeezed below its content
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        self.art = Art(mod.id, mod.layer)
        lay.addWidget(self.art)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.name = _label(mod.name, "subtitle", wrap=True)
        top.addWidget(self.name, 1)
        self.selector: QAbstractButton = QRadioButton() if mode == "radio" else QCheckBox()
        self.selector.setCursor(Qt.CursorShape.PointingHandCursor)
        self.selector.setToolTip("Use this one for its slot" if mode == "radio" else "Include this mod")
        top.addWidget(self.selector, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)
        meta = f"{mod.author} · {mod.layer}" if mod.author else mod.layer
        self.meta = _label(meta, "caption", wrap=True)
        lay.addWidget(self.meta)
        holder, self.badges = flow_box(6)
        for text, tone, tip in mod_badges(mod, build):
            self.badges.addWidget(Badge(text, tone, tip))
        lay.addWidget(holder)
        notes = (mod.unsupported or mod.notes or "").strip()
        self.notes = _label(self._elide(notes, 2), "caption", "warning" if mod.unsupported else None, wrap=True)
        self.notes.setToolTip(notes)
        self.notes.setVisible(bool(notes))
        lay.addWidget(self.notes)
        lay.addStretch()
        bottom = QHBoxLayout()
        self.status = StatusPill(status or ("unsupported" if mod.unsupported else "missing"))
        bottom.addWidget(self.status)
        bottom.addStretch()
        self.page_btn = button("Page", "ghost", lambda: self.page_requested.emit(self.mod.id), "external")
        self.page_btn.setToolTip(mod.page)
        bottom.addWidget(self.page_btn)
        lay.addLayout(bottom)
        self.selector.toggled.connect(self._on_toggle)
        self.set_selected(selected and not mod.unsupported)
        if mod.unsupported:
            self.selector.setEnabled(False)
            self.setProperty("disabled", True)
            self.art.dim = True

    def _elide(self, text: str, lines: int) -> str:
        fm = self.fontMetrics()
        width = (self.width() - 24) * lines
        return fm.elidedText(" ".join(text.split()), Qt.TextElideMode.ElideRight, max(80, width))

    def _on_toggle(self, on: bool) -> None:
        self.setProperty("selected", bool(on))
        theme.repolish(self)
        self.toggled.emit(self.mod.id, bool(on))

    def set_selected(self, on: bool) -> None:
        self.selector.setChecked(on)
        self.setProperty("selected", bool(on))
        theme.repolish(self)

    def is_selected(self) -> bool:
        return self.selector.isChecked()

    def set_status(self, kind: str, detail: str = "", percent: int | None = None) -> None:
        self.status.set_status(kind, detail, percent)

    def set_picture(self, pm: QPixmap | None) -> None:
        self.art.set_pixmap(pm)


# ------------------------------------------------------------------------------------------- headers
class HeroHeader(QFrame):
    """Welcome hero: the logo with a coral glow, an eyebrow, the gradient wordmark, a pitch, call-to-action buttons."""

    def __init__(self, logo: Path | str | None, title: str = "LEONIDA V", eyebrow: str = "STORY MODE · GTA V ENHANCED",
                 pitch: str = "", actions: list[QWidget] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("hero")
        self.setStyleSheet(
            f"QFrame#hero {{ border: 1px solid {C['border']}; border-radius: 18px; background: qlineargradient("
            f"x1:0, y1:0, x2:1, y2:1, stop:0 #1E1226, stop:0.5 {C['surface']}, stop:1 #120F1F); }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(36, 28, 36, 28)
        lay.setSpacing(32)
        self.logo = QLabel()
        if logo and Path(logo).is_file():
            self.logo.setPixmap(QPixmap(str(logo)).scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation))
            theme.add_glow(self.logo, radius=60, alpha=0.5)
        lay.addWidget(self.logo)
        col = QVBoxLayout()
        col.setSpacing(10)
        col.addStretch()
        col.addWidget(_label(eyebrow, "eyebrow"))
        self.title = theme.gradient_label(title)
        col.addWidget(self.title)
        self.pitch = _label(pitch, "muted", wrap=True)
        col.addWidget(self.pitch)
        row = QHBoxLayout()
        row.setSpacing(10)
        for a in actions or []:
            row.addWidget(a)
        row.addStretch()
        col.addSpacing(6)
        col.addLayout(row)
        col.addStretch()
        lay.addLayout(col, 1)


class PageHeader(QWidget):
    """'STEP 3 OF 7' + title + one sentence, an optional widget on the right, and the sunset brand strip."""

    def __init__(self, step: int | None, total: int, title: str, text: str = "", right: QWidget | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(3)
        if step:
            col.addWidget(_label(f"STEP {step} OF {total}", "eyebrow"))
        self.title = _label(title, "title")
        col.addWidget(self.title)
        self.text = _label(text, "muted", wrap=True)
        self.text.setVisible(bool(text))
        col.addWidget(self.text)
        row.addLayout(col, 1)
        if right is not None:
            row.addWidget(right, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(row)
        strip = QFrame()
        strip.setProperty("brand", True)
        lay.addWidget(strip)


# ------------------------------------------------------------------------------------------- stepper
STEP_STATES = ("pending", "current", "done", "failed", "skipped")
TEST_RESULTS = {"ok": "ok", "failed": "failed", "not-seen": "not-seen"}


class StepDot(QWidget):
    """The circle of one stepper row: number, check, cross; with the connector line above/below."""

    def __init__(self, number: int, state: str, first: bool, last: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.number, self.state, self.first, self.last = number, state, first, last
        self.setFixedWidth(34)
        self.setMinimumHeight(46)  # a row never collapses below its dot, however tight the column

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = self.width() / 2, 22.0, 12.0
        line = QColor(C["border_strong"])
        p.setPen(QPen(line, 2))
        if not self.first:
            p.drawLine(QPointF(cx, 0), QPointF(cx, cy - r - 2))
        if not self.last:
            p.drawLine(QPointF(cx, cy + r + 2), QPointF(cx, self.height()))
        fill, text_col, mark = {
            "done": (QColor(C["success"]), QColor(C["bg"]), "check"),
            "failed": (QColor(C["error"]), QColor(C["bg"]), "cross"),
            "current": (None, QColor(C["text_on_accent"]), None),
            "skipped": (QColor(C["surface_3"]), QColor(C["text_subtle"]), None),
        }.get(self.state, (QColor(C["surface_2"]), QColor(C["text_muted"]), None))
        if self.state == "current":
            glow = QColor(C["coral"])
            glow.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), r + 5, r + 5)
            g = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
            g.setColorAt(0, QColor(theme.GRADIENT[0]))
            g.setColorAt(1, QColor(theme.GRADIENT[-1]))
            p.setBrush(g)
        else:
            p.setPen(QPen(QColor(C["border_strong"]), 1) if self.state == "pending" else Qt.PenStyle.NoPen)
            p.setBrush(fill)
        p.drawEllipse(QPointF(cx, cy), r, r)
        if mark:
            pm = icon_pixmap(mark, text_col.name(), 14)
            p.drawPixmap(int(cx - 7), int(cy - 7), pm)
        else:
            p.setPen(text_col)
            f = self.font()
            f.setBold(True)
            f.setPointSize(9)
            p.setFont(f)
            p.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r), int(Qt.AlignmentFlag.AlignCenter), str(self.number))
        p.end()


class StepRow(QWidget):
    def __init__(self, number: int, title: str, detail: str, state: str, test: str | None, first: bool, last: bool,
                 parent: QWidget | None = None):
        super().__init__(parent)
        if state not in STEP_STATES:
            raise KeyError(f"unknown step state {state!r}")
        self.state, self.test = state, test
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.dot = StepDot(number, state, first, last)
        lay.addWidget(self.dot)
        col = QVBoxLayout()
        col.setContentsMargins(0, 10, 0, 12)
        col.setSpacing(2)
        self.title = _label(title, "subtitle", wrap=True)
        if state in ("pending", "skipped"):
            self.title.setStyleSheet(f"color: {C['text_muted']};")
        col.addWidget(self.title)
        self.detail = _label(detail, "caption", wrap=True)
        self.detail.setVisible(bool(detail))
        col.addWidget(self.detail)
        lay.addLayout(col, 1)
        self.result: StatusPill | None = None
        if test:
            if test not in TEST_RESULTS:
                raise KeyError(f"unknown play-test result {test!r}")
            self.result = StatusPill(TEST_RESULTS[test], "play test")
            lay.addWidget(self.result, 0, Qt.AlignmentFlag.AlignVCenter)


class Stepper(QWidget):
    """Install steps: ``Stepper([("Script Hook V", "copy · 3 files", "done", "ok"), ...])``."""

    def __init__(self, steps: list[tuple[str, str, str, str | None]], parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.rows: list[StepRow] = []
        for i, (title, detail, state, test) in enumerate(steps):
            row = StepRow(i + 1, title, detail, state, test, i == 0, i == len(steps) - 1)
            self.rows.append(row)
            lay.addWidget(row)

    def current(self) -> int | None:
        return next((i for i, r in enumerate(self.rows) if r.state == "current"), None)


# ------------------------------------------------------------------------------------------- queue / toast / empty
class QueueRow(QFrame):
    """One mod in the download queue: name, status pill, progress, caption, actions."""

    def __init__(self, name: str, kind: str = "queued", percent: int | None = None, detail: str = "",
                 actions: list[QWidget] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.name = _label(name, "subtitle")
        top.addWidget(self.name, 1)
        self.status = StatusPill(kind)
        top.addWidget(self.status)
        lay.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        bottom = QHBoxLayout()
        self.detail = _label(detail, "caption", wrap=True)
        bottom.addWidget(self.detail, 1)
        for a in actions or []:
            bottom.addWidget(a)
        lay.addLayout(bottom)
        self.set_progress(kind, percent, detail)

    def set_progress(self, kind: str, percent: int | None = None, detail: str | None = None) -> None:
        self.status.set_status(kind, percent=percent if kind == "downloading" else None)
        value = 100 if kind in ("ready", "installed", "ok") else (percent or 0)
        self.bar.setValue(max(0, min(100, int(value))))
        tone = {"ready": "success", "installed": "success", "ok": "success", "failed": "error", "wrong": "error"}.get(kind, "")
        self.bar.setProperty("tone", tone)
        self.bar.setVisible(kind not in ("manual", "paid"))
        theme.repolish(self.bar)
        if detail is not None:
            self.detail.setText(detail)
            self.detail.setVisible(bool(detail))


class Toast(QFrame):
    """A result line above the action bar: icon + message (+ action). Auto-hides after ``timeout_ms`` unless 0."""

    action_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("toast", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        lay.addWidget(self.icon)
        self.text = QLabel()
        self.text.setWordWrap(True)
        lay.addWidget(self.text, 1)
        self.action = button("", "ghost", self.action_clicked.emit)
        lay.addWidget(self.action)
        self.close_btn = button("", "ghost", self.hide, "cross")
        self.close_btn.setToolTip("Close")
        lay.addWidget(self.close_btn)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text: str, tone: str = "success", action: str = "", timeout_ms: int = 6000) -> None:
        name = {"success": "check", "error": "cross", "warning": "warning"}.get(tone, "info")
        col = TONE_COLORS.get(tone, C["text"])
        self.icon.setPixmap(icon_pixmap(name, col, 16))
        self.text.setText(text)
        self.text.setStyleSheet(f"color: {C['text']}; background: transparent;")
        self.setStyleSheet(f"QFrame[toast=\"true\"] {{ border-left: 3px solid {col}; }}")
        self.action.setText(action)
        self.action.setVisible(bool(action))
        self.show()
        self.timer.stop()
        if timeout_ms and tone != "error":
            self.timer.start(timeout_ms)


class EmptyState(QFrame):
    """Centered icon, title, one sentence and the one button that fixes it."""

    def __init__(self, icon_name: str, title: str, text: str, action: QWidget | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 36, 32, 36)
        lay.setSpacing(10)
        lay.addStretch()
        ring = QLabel()
        ring.setFixedSize(64, 64)
        ring.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ring.setPixmap(icon_pixmap(icon_name, C["coral"], 30))
        ring.setStyleSheet(f"background: {theme.rgba(C['coral'], 0.10)}; border: 1px solid "
                           f"{theme.rgba(C['coral'], 0.35)}; border-radius: 32px;")
        lay.addWidget(ring, 0, Qt.AlignmentFlag.AlignHCenter)
        t = _label(title, "subtitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        s = _label(text, "muted", wrap=True)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(s)
        if action is not None:
            lay.addSpacing(6)
            lay.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch()


# ------------------------------------------------------------------------------------------- sidebar
NAV_ICONS = {"Welcome": "home", "Game": "game", "Choose mods": "mods", "Get mods": "download", "Check": "shield",
             "Install": "install", "Manage": "manage"}
NAV_STATES = ("todo", "current", "done", "locked", "busy")


class NavList(QListWidget):
    """The wizard steps with icons. States: todo, current, done (green check icon), locked (disabled + reason), busy."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("nav")
        self.setIconSize(QSize(18, 18))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def add_step(self, title: str, icon_name: str | None = None, state: str = "todo", reason: str = "") -> QListWidgetItem:
        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, icon_name or NAV_ICONS.get(title, "dot"))
        self.addItem(item)
        self.set_state(self.count() - 1, state, reason)
        return item

    def set_state(self, row: int, state: str, reason: str = "") -> None:
        if state not in NAV_STATES:
            raise KeyError(f"unknown nav state {state!r}")
        item = self.item(row)
        name = item.data(Qt.ItemDataRole.UserRole)
        col = {"current": C["coral"], "done": C["success"], "locked": C["text_disabled"], "busy": C["info"]}.get(
            state, C["text_muted"])
        item.setIcon(icon("check" if state == "done" else ("lock" if state == "locked" else name), col, 18))
        flags = item.flags()
        if state == "locked":
            item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
        else:
            item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setToolTip(reason if state == "locked" else "")
        item.setData(Qt.ItemDataRole.UserRole + 1, state)
        if state == "current":
            self.setCurrentRow(row)

    def state(self, row: int) -> str:
        return self.item(row).data(Qt.ItemDataRole.UserRole + 1)


class Sidebar(QWidget):
    """Logo + name + version on top, the NavList, and the game card (build + mods state) at the bottom."""

    def __init__(self, logo: Path | str | None, version: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(236)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 20, 10, 16)
        lay.setSpacing(6)
        brand = QHBoxLayout()
        self.logo = QLabel()
        if logo and Path(logo).is_file():
            self.logo.setPixmap(QPixmap(str(logo)).scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation))
        brand.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(_label("LEONIDA V", "eyebrow"))
        names.addWidget(_label(version, "caption"))
        brand.addLayout(names)
        brand.addStretch()
        lay.addLayout(brand)
        lay.addSpacing(12)
        self.nav = NavList()
        lay.addWidget(self.nav, 1)
        self.game = QFrame()
        self.game.setProperty("card", True)
        g = QVBoxLayout(self.game)
        g.setContentsMargins(12, 10, 12, 10)
        g.setSpacing(3)
        g.addWidget(_label("GTA V Enhanced", "caption"))
        self.build = _label("Game not found", "subtitle")
        g.addWidget(self.build)
        self.mods_state = StatusPill("mods-off")
        g.addWidget(self.mods_state)
        lay.addWidget(self.game)

    def set_game(self, build: str | None, mods_kind: str = "mods-on", detail: str = "") -> None:
        self.build.setText(build or "Game not found")
        self.mods_state.set_status(mods_kind, detail)


class ActionBar(QWidget):
    """Bottom row: danger/secondary on the left, the rest and the one primary on the right."""

    def __init__(self, left: list[QWidget] | None = None, right: list[QWidget] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        for w in left or []:
            lay.addWidget(w)
        lay.addStretch()
        for w in right or []:
            lay.addWidget(w)



# ------------------------------------------------------------------------------------------- play test (leonida.playtest)
# (phase key, label, progress-message prefixes from leonida.playtest.playtest(progress=...))
PLAYTEST_PHASES = (
    ("close", "Close the game if it's open", ("Closing ",)),
    ("logs", "Move the mods' old logs aside", ("Moved the old logs",)),
    ("start", "Start the game (PlayGTAV.exe)", ("Started ",)),
    ("game", "Game running", ("GTA5_Enhanced.exe is running",)),
    ("shv", "Script Hook V loaded", ("Script Hook V loaded",)),
    ("shvdn", "Script Hook V .NET started", ("Script Hook V .NET started",)),
    ("story", "Story mode loaded", ("Story mode loaded", "Waited long enough for story mode")),
    ("read", "Read the mods' logs and close the game", ("Closed the game", "Left the game running")),
)
# playtest status -> (pill kind, pill detail)
PLAYTEST_STATUS = {"passed": ("ok", "play test passed"), "failed": ("failed", "a mod failed"),
                   "crashed": ("failed", "the game crashed"), "hang": ("not-seen", "no story mode in time"),
                   "blocked": ("manual", "can't start")}
# verify.VerifyResult.status -> pill kind
VERIFY_PILL = {"ok": "ok", "failed": "failed", "warning": "not-seen", "not-seen": "not-seen", "no-log": "queued"}


class PlaytestPanel(QFrame):
    """Live view of ``leonida.playtest.playtest``: ``start()``, feed ``on_progress(msg)`` (on the UI thread, e.g.
    from start_worker's on_progress), then ``show_report(report)``."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("card", True)
        self.done: set[str] = set()
        self.failed_at: int | None = None
        self.timeline: list[str] = []
        self.seconds = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(_label("PLAY TEST", "eyebrow"))
        top.addStretch()
        self.clock = _label("0:00", "caption")
        top.addWidget(self.clock)
        self.pill = StatusPill("queued", "not started")
        top.addWidget(self.pill)
        lay.addLayout(top)
        self.title = _label("Start story mode once and let Leonida read the logs", "subtitle", wrap=True)
        lay.addWidget(self.title)
        self.steps_box = QVBoxLayout()
        lay.addLayout(self.steps_box)
        self.stepper: Stepper | None = None
        self.results_box = QVBoxLayout()
        self.results_box.setSpacing(6)
        lay.addLayout(self.results_box)
        self.log = _label("", "caption", wrap=True)
        self.log.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.log)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self._render()

    def start(self) -> None:
        self.done.clear()
        self.failed_at = None
        self.timeline.clear()
        self.seconds = 0
        self.clock.setText("0:00")
        self._clear_results()
        self.pill.set_status("downloading")
        self.pill.text.setText("Running")
        self.title.setText("Starting the game. Leave it alone until story mode has loaded.")
        self.log.setText("")
        self.timer.start()
        self._render()

    def _tick(self) -> None:
        self.seconds += 1
        self.clock.setText(f"{self.seconds // 60}:{self.seconds % 60:02d}")

    def on_progress(self, msg: str) -> None:
        self.timeline.append(msg)
        for i, (_key, _text, prefixes) in enumerate(PLAYTEST_PHASES):
            if any(msg.startswith(p) for p in prefixes):
                # reaching a phase means the earlier ones are behind it (e.g. no "Closing" when the game wasn't open)
                self.done.update(k for k, _t, _p in PLAYTEST_PHASES[:i + 1])
        self.log.setText("\n".join(self.timeline[-6:]))
        self._render()

    def states(self) -> list[str]:
        out, current_given = [], False
        for i, (key, _text, _p) in enumerate(PLAYTEST_PHASES):
            if key in self.done:
                out.append("done")
            elif self.failed_at == i:
                out.append("failed")
            elif self.timer.isActive() and not current_given:
                out.append("current")
                current_given = True
            else:
                out.append("pending")
        return out

    def _render(self) -> None:
        if self.stepper is not None:  # detach the old one now: deleteLater alone leaves it painted until the loop runs
            self.steps_box.removeWidget(self.stepper)
            self.stepper.hide()
            self.stepper.setParent(None)
            self.stepper.deleteLater()
        rows = [(text, "", state, None) for (_k, text, _p), state in zip(PLAYTEST_PHASES, self.states(), strict=True)]
        self.stepper = Stepper(rows)
        self.steps_box.addWidget(self.stepper)

    def _clear_results(self) -> None:
        while self.results_box.count():
            w = self.results_box.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def show_report(self, report) -> None:
        """``report``: a leonida.playtest.PlaytestReport (status, message, results, evidence, notes)."""
        self.timer.stop()
        kind, detail = PLAYTEST_STATUS.get(report.status, ("failed", report.status))
        self.pill.set_status(kind, detail)
        self.title.setText(report.message)
        if report.status in ("crashed", "hang", "blocked"):
            self.failed_at = next((i for i, (k, _t, _p) in enumerate(PLAYTEST_PHASES) if k not in self.done), None)
        self._render()
        self._clear_results()
        for r in getattr(report, "results", None) or []:
            if r.mod is None:
                continue
            w = clear_background(QWidget())
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            text = _label(r.message, "caption", wrap=True)
            if r.line:
                text.setToolTip(r.line)
            row.addWidget(text, 1)
            row.addWidget(StatusPill(VERIFY_PILL.get(r.status, "queued")))
            self.results_box.addWidget(w)
        extra = [*(f"Note: {n}" for n in getattr(report, "notes", None) or []),
                 *(f"Evidence: {e}" for e in getattr(report, "evidence", None) or [])]
        self.log.setText("\n".join(extra or self.timeline[-6:]))


# ------------------------------------------------------------------------------------------- edition / packs / drift
class EditionPicker(QWidget):
    """Enhanced / Legacy cards. ``editions``: [(name, folder or None, build or None)]; missing ones are disabled."""

    chosen = Signal(str)

    def __init__(self, editions: list[tuple[str, str | None, str | None]], current: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self.cards: dict[str, QFrame] = {}
        self.buttons: dict[str, QRadioButton] = {}
        installed = [e[0] for e in editions if e[1]]
        current = current if current in installed else (installed[0] if installed else None)
        for name, folder, build in editions:
            card = QFrame()
            card.setProperty("card", True)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 14, 16, 14)
            cl.setSpacing(4)
            top = QHBoxLayout()
            rb = QRadioButton()
            rb.setEnabled(bool(folder))
            rb.toggled.connect(lambda on, n=name: self._pick(n) if on else None)
            top.addWidget(rb)
            top.addWidget(_label(f"GTA V {name}", "subtitle"), 1)
            top.addWidget(Badge("Installed" if folder else "Not installed", "success" if folder else None))
            cl.addLayout(top)
            cl.addWidget(_label(folder or "Not found on this PC", "caption", wrap=True))
            if build:
                cl.addWidget(_label(f"Game build {build}", "caption"))
            if not folder:
                card.setProperty("disabled", True)
            self.cards[name], self.buttons[name] = card, rb
            lay.addWidget(card, 1)
        if current:
            self.buttons[current].setChecked(True)

    def _pick(self, name: str) -> None:
        for n, card in self.cards.items():
            card.setProperty("selected", n == name)
            theme.repolish(card)
        self.chosen.emit(name)

    def current(self) -> str | None:
        return next((n for n, b in self.buttons.items() if b.isChecked()), None)


class PackCard(QFrame):
    """A big 'Choose your modpack' card: picture, name, tagline, counts, badges; the whole card is clickable."""

    clicked = Signal(str)

    def __init__(self, pack_id: str, name: str, tagline: str, *, picture: QPixmap | None = None, mods: int = 0,
                 addons: int = 0, badges: list[tuple[str, str | None]] | None = None, recommended: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.pack_id = pack_id
        self.setProperty("card", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 16)
        lay.setSpacing(8)
        self.art = Art(pack_id, name, height=160)
        self.art.set_pixmap(picture)
        lay.addWidget(self.art)
        top = QHBoxLayout()
        top.addWidget(_label(name, "title"), 1)
        if recommended:
            top.addWidget(Badge("Recommended", "success", "Fits your PC"))
        lay.addLayout(top)
        lay.addWidget(_label(tagline, "muted", wrap=True))
        holder, flow = flow_box(6)
        flow.addWidget(Badge(f"{mods} mods", "info"))
        if addons:
            flow.addWidget(Badge(f"{addons} add-ons"))
        for text, tone in badges or []:
            flow.addWidget(Badge(text, tone))
        lay.addWidget(holder)
        lay.addStretch()
        self.choose = button("Choose this pack", "secondary", lambda: self.clicked.emit(self.pack_id))
        lay.addWidget(self.choose)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.choose.setText("Selected" if on else "Choose this pack")
        self.choose.setProperty("variant", "primary" if on else "secondary")
        theme.repolish(self.choose)
        theme.repolish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.clicked.emit(self.pack_id)
        super().mousePressEvent(event)


class DriftWarning(QFrame):
    """F5: locked settings that changed. ``items``: [(file, key, locked value, current value, why it matters)]."""

    restore = Signal()
    unlock = Signal(str, str)  # file, key

    def __init__(self, items: list[tuple[str, str, str, str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("tone", "warning")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(_icon_label("warning", C["warning"], 18))
        n = len(items)
        top.addWidget(_label(f"{n} locked setting{'s' if n != 1 else ''} changed since install", "subtitle"), 1)
        self.restore_btn = button("Restore all", "secondary", self.restore.emit)
        top.addWidget(self.restore_btn)
        lay.addLayout(top)
        self.rows: list[QWidget] = []
        for file, key, locked, current, why in items:
            w = clear_background(QWidget())
            row = QHBoxLayout(w)
            row.setContentsMargins(28, 0, 0, 0)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(_label(f"{file}: {key} is {current}, locked at {locked}", "caption", "warning"))
            if why:
                col.addWidget(_label(why, "caption", wrap=True))
            row.addLayout(col, 1)
            row.addWidget(button("Keep mine", "ghost", lambda _=False, f=file, k=key: self.unlock.emit(f, k)))
            self.rows.append(w)
            lay.addWidget(w)
