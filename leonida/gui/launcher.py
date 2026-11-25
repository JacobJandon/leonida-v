"""The launcher views: Browse (modpack tiles and every mod, with a details drawer), the Modpack page (hero banner, the
main action, Overview / Mods / Variants & settings / Screenshots / Files & logs) and the bottom bar (game, pack,
mods state, progress, Play).

The structure follows a mod-manager launcher (a library of modpack tiles; a pack page with a banner and tabs; a
persistent Play bar), see docs/DESIGN.md section "Launcher". The look is Leonida's own: theme.py tokens, the sunset
logo and gradient, our widgets. Every mod shows its picture (``Pictures``: the image cache, else the author's page).
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme
from . import widgets as W
from .chooser import how_text

C = theme.COLORS


# --------------------------------------------------------------------------------------------- pictures
def _alive(obj) -> bool:
    try:
        import shiboken6

        return shiboken6.isValid(obj)
    except Exception:  # noqa: BLE001
        return True


class Pictures(QObject):
    """Puts a mod's (or pack's) picture into every ``W.Art`` that shows it, from the cache at once or when the
    loader brings it from the author's page."""

    def __init__(self, loader, parent: QObject | None = None):
        super().__init__(parent)
        self.loader = loader
        self.arts: dict[str, list] = {}
        self._pixmaps: dict[str, QPixmap] = {}
        loader.loaded.connect(self._loaded)

    def bind(self, art, key: str, image: str | None, page: str | None) -> None:
        self.arts.setdefault(key, []).append(art)
        self.loader.request(key, image, page)

    def bind_mod(self, art, mod) -> None:
        self.bind(art, mod.id, getattr(mod, "image", None), mod.page)

    def pixmap(self, path: str) -> QPixmap | None:
        if path not in self._pixmaps:
            pm = QPixmap(path)
            if pm.isNull():
                return None
            self._pixmaps[path] = pm
        return self._pixmaps[path]

    def _loaded(self, key: str, path: str) -> None:
        if not path:
            return
        pm = self.pixmap(path)
        keep = []
        for art in self.arts.get(key, []):
            if _alive(art):
                art.set_pixmap(pm)
                keep.append(art)
        self.arts[key] = keep


def thumb(width: int, height: int, seed: str, label: str = "") -> W.Art:
    art = W.Art(seed, label, height)
    art.setFixedWidth(width)
    return art


class Banner(W.Art):
    """A cover picture with a dark fade on the left and the bottom, so text on it reads well."""

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        r = self.rect()
        side = QLinearGradient(0, 0, r.width(), 0)
        side.setColorAt(0.0, QColor(13, 13, 18, 235))
        side.setColorAt(0.55, QColor(13, 13, 18, 170))
        side.setColorAt(1.0, QColor(13, 13, 18, 40))
        p.fillRect(r, side)
        bottom = QLinearGradient(0, r.height() * 0.5, 0, r.height())
        bottom.setColorAt(0, QColor(13, 13, 18, 0))
        bottom.setColorAt(1, QColor(13, 13, 18, 200))
        p.fillRect(r, bottom)


# --------------------------------------------------------------------------------------------- pack facts
@dataclass
class PackInfo:
    pack: object
    mods: list
    installed: int
    ready: int
    size: int
    paid: bool
    gpu_ok: bool
    chosen: bool
    edition: str

    @property
    def missing(self) -> int:
        return len(self.mods) - self.ready

    @property
    def to_install(self) -> int:
        return len([m for m in self.mods if not getattr(m, "unsupported", None)]) - self.installed


def summary_of(text: str, limit: int = 150) -> str:
    """The first sentence of a description (for tiles and the banner)."""
    first = re.split(r"(?<=[.!?])\s", " ".join((text or "").split()), maxsplit=1)[0]
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


def size_text(n: int) -> str:
    if n <= 0:
        return "not downloaded"
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.0f} MB"
    return f"{max(1, n // 1024)} KB"


def pack_info(win, pack_id: str, edition: str | None = None) -> PackInfo:
    from .newpages import _is_rtx50

    s = win.session
    edition = edition or s.edition
    base = s.manifest_for(edition) if edition != s.edition else s.base_manifest
    pack = base.packs[pack_id]
    c = s.pack_choice()
    chosen = edition == s.edition and c.pack == pack_id
    if chosen:
        mods = s.mods()
    elif edition == s.edition:
        mods = s.manifest.resolve_pack(pack_id)
    else:
        mods = base.resolve_pack(pack_id)
    done = s.log.installed_mods() if edition == s.edition else set()
    matched = s.matches(mods).matched if edition == s.edition else {}
    size = 0
    for f in matched.values():
        with contextlib.suppress(OSError):
            size += f.stat().st_size
    need = (pack.requires or {}).get("gpu")
    gpu_ok = need != "rtx50" or _is_rtx50(getattr(win.pages[2], "gpus", None) or s.gpus())
    return PackInfo(pack, mods, sum(1 for m in mods if m.id in done), len(matched), size,
                    any(getattr(m, "is_paid", False) for m in mods), gpu_ok, chosen, edition)


def notice_for(pack_name: str) -> list[str]:
    """"What you'll notice in game" for a pack, from docs/GTA6-EXPERIENCE.md (section 3), following its
    "(everything in X, and)" chain. [] when the document isn't there (e.g. a build without docs)."""
    roots = [Path(__file__).resolve().parents[2] / "docs"]
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(getattr(sys, "_MEIPASS", "")) / "docs")
    doc = next((r / "GTA6-EXPERIENCE.md" for r in roots if (r / "GTA6-EXPERIENCE.md").is_file()), None)
    if doc is None:
        return []
    text = doc.read_text(encoding="utf-8")
    m = re.search(r"^## 3\..*?$(.*?)^(?:---|## )", text, re.M | re.S)
    if not m:
        return []
    blocks: dict[str, tuple[str | None, list[str]]] = {}
    for b in re.finditer(r"^\*\*(.+?)\*\*(.*?)$\n((?:- .*\n?)+)", m.group(1), re.M):
        parent = re.search(r"everything in ([^,)]+)", b.group(2))
        blocks[b.group(1).strip()] = (parent.group(1).strip() if parent else None,
                                      [ln[2:].strip() for ln in b.group(3).splitlines() if ln.startswith("- ")])
    out, name, seen = [], pack_name, set()
    while name and name not in seen:
        seen.add(name)
        key = next((k for k in blocks if k == name or k.endswith(name) or name.endswith(k)), None)
        if key is None:
            break
        parent, items = blocks[key]
        out = items + out
        name = f"Leonida {parent}" if parent and not parent.startswith("Leonida") else parent
    return [re.sub(r"\*\*(.+?)\*\*|\*(.+?)\*", lambda x: x.group(1) or x.group(2), i) for i in out]


def _title(text: str) -> QLabel:
    return W._label(text, "title", wrap=True)


def _scroll(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # rows shorten their text instead
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(W.clear_background(widget))
    return area


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


class _Clickable(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


def _version(mod) -> str:
    v = (getattr(mod, "version", "") or "").strip()
    return v if v and v != "-" else "—"


def _status_of(win, mod, installed: set[str], matched: dict) -> str:
    if getattr(mod, "unsupported", None):
        return "unsupported"
    if mod.id in installed:
        return "installed"
    if mod.id in matched:
        return "ready"
    if getattr(mod, "is_paid", False):
        return "paid"
    return "missing"


# ------------------------------------------------------------------------------------------- browse: packs
class PackTile(_Clickable):
    """A modpack in the library: cover, name, one line, counts and its state; click opens its page."""

    play = Signal(str)

    def __init__(self, info: PackInfo, pictures: Pictures, parent: QWidget | None = None):
        super().__init__(parent)
        self.info = info
        pack = info.pack
        self.setProperty("card", True)
        self.setProperty("selected", info.chosen)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(330)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 14)
        lay.setSpacing(6)
        self.cover = thumb(330, 176, pack.id)
        cover_mod = next((m for m in info.mods if getattr(m, "image", None)), None)
        if pack.picture:
            pictures.bind(self.cover, f"pack:{pack.id}", pack.picture, None)
        elif cover_mod is not None:
            pictures.bind_mod(self.cover, cover_mod)
        lay.addWidget(self.cover)
        body = QVBoxLayout()
        body.setContentsMargins(14, 4, 14, 0)
        body.setSpacing(6)
        body.addWidget(W._label(pack.name, "subtitle", wrap=True))
        self.summary = W._label(summary_of(pack.description, 140), "caption", wrap=True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.summary.setFixedHeight(self.summary.fontMetrics().lineSpacing() * 3 + 4)  # every tile the same height
        self.summary.setToolTip(pack.description)
        body.addWidget(self.summary)
        chips, flow = W.flow_box(6)
        flow.addWidget(W.Badge(f"{len(info.mods)} mods", "info"))
        if info.size:
            flow.addWidget(W.Badge(size_text(info.size)))
        flow.addWidget(W.Badge("Has paid mods", "warning") if info.paid else W.Badge("Free", "success"))
        if not info.gpu_ok:
            flow.addWidget(W.Badge("RTX 50 only", "warning", "Needs an NVIDIA RTX 50-series GPU"))
        body.addWidget(chips)
        row = QHBoxLayout()
        if info.chosen:
            done = info.installed and info.to_install <= 0
            row.addWidget(W.Badge("Installed" if done else f"In use · {info.installed}/{len(info.mods)} installed",
                                  "success" if done else "info"))
        else:
            row.addWidget(W._label("Not installed", "caption"))
        row.addStretch()
        if info.chosen and info.installed:
            btn = W.button("Play", "primary", lambda: self.play.emit(pack.id), "play")
        else:
            btn = W.button("Open", "secondary", self.clicked.emit)
        self.action = btn
        row.addWidget(btn)
        body.addLayout(row)
        lay.addLayout(body)
        if info.edition and not info.gpu_ok:
            self.setToolTip("This pack needs an NVIDIA RTX 50-series graphics card.")


class ModRow(_Clickable):
    """One mod in a list: picture, name and author, what it is, the version for this build, its state."""

    def __init__(self, mod, pictures: Pictures, *, status: str, in_pack: bool, build: str | None,
                 size: int = 0, toggle: QWidget | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.mod = mod
        self.setProperty("card", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 14, 8)
        lay.setSpacing(14)
        self.art = thumb(96, 54, mod.id, mod.layer)
        pictures.bind_mod(self.art, mod)
        lay.addWidget(self.art)
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(W.ElidedLabel(mod.name, "subtitle"), 1)  # shortens instead of widening the list
        if in_pack:
            top.addWidget(W.Badge("In this pack", "success"))
        col.addLayout(top)
        by = f"by {mod.author}" if getattr(mod, "author", "") else ""
        col.addWidget(W.ElidedLabel(" · ".join(x for x in (by, mod.layer, how_text(mod)) if x)))
        version = _version(mod)
        meta = [f"Version for build {build}: {version}" if build else version, size_text(size) if size else ""]
        col.addWidget(W.ElidedLabel(" · ".join(x for x in meta if x)))
        lay.addLayout(col, 1)
        lay.addWidget(W.StatusPill(status), 0, Qt.AlignmentFlag.AlignVCenter)
        if toggle is not None:
            lay.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)


class ModDrawer(QFrame):
    """The details of one mod beside the list: a big picture, what it is, build support, conflicts, its page."""

    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        self.setProperty("card", True)
        self.setFixedWidth(400)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 16, 16, 16)
        self.lay.setSpacing(10)
        self.mod = None
        self.hide()

    def show_mod(self, mod) -> None:
        self.mod = mod
        _clear(self.lay)
        s = self.win.session
        top = QHBoxLayout()
        top.addWidget(W._label("MOD DETAILS", "eyebrow"))
        top.addStretch()
        top.addWidget(W.button("Close", "ghost", self.hide))
        self.lay.addLayout(top)
        art = thumb(368, 184, mod.id, mod.layer)
        self.win.pictures.bind_mod(art, mod)
        self.lay.addWidget(art)
        self.lay.addWidget(W._label(mod.name, "title", wrap=True))
        self.lay.addWidget(W._label(f"by {mod.author}" if getattr(mod, "author", "") else mod.layer, "caption",
                                    wrap=True))
        chips, flow = W.flow_box(6)
        for text, tone, tip in W.mod_badges(mod, s.game_version()):
            flow.addWidget(W.Badge(text, tone, tip))
        self.lay.addWidget(chips)
        body = QWidget()
        bl = QVBoxLayout(W.clear_background(body))
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        build = s.game_version()
        rows = [("Version for your build", f"{_version(mod)} (game build {build})" if build else _version(mod)),
                ("Get it", how_text(mod)), ("Kind", mod.layer)]
        if getattr(mod, "unsupported", None):
            rows.append(("Not on this build", mod.unsupported))
        conflicts = [s.base_manifest.mods[c].name if c in s.base_manifest.mods else c
                     for c in (getattr(mod, "conflicts", ()) or ())]
        if conflicts:
            rows.append(("Doesn't go with", ", ".join(conflicts)))
        for k, v in rows:
            bl.addWidget(W._label(k.upper(), "eyebrow"))
            bl.addWidget(W._label(v, None, wrap=True))
        if getattr(mod, "notes", ""):
            bl.addWidget(W._label("ABOUT", "eyebrow"))
            bl.addWidget(W._label(mod.notes, "caption", wrap=True))
        bl.addStretch()
        self.lay.addWidget(_scroll(body), 1)
        self.lay.addWidget(W.button("Open the author's page", "secondary", lambda: self.win.open_page(mod), "external"))
        self.show()


class BrowsePage(QWidget):
    """Browse: the modpacks as big tiles (filters: edition, fits my GPU, free only) and every mod (search,
    category chips, a details drawer)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(W._label("LIBRARY", "eyebrow"))
        col.addWidget(_title("Browse"))
        head.addLayout(col, 1)
        lay.addLayout(head)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        # -- modpacks
        packs = QWidget()
        pl = QVBoxLayout(packs)
        pl.setContentsMargins(0, 12, 0, 0)
        pl.setSpacing(12)
        filters = QHBoxLayout()
        filters.setSpacing(10)
        self.edition = QComboBox()
        for key, name in (("enhanced", "GTA V Enhanced"), ("legacy", "GTA V Legacy")):
            self.edition.addItem(name, key)
        self.edition.currentIndexChanged.connect(lambda _i: self.refresh_packs())
        filters.addWidget(W._label("Edition", "caption"))
        filters.addWidget(self.edition)
        self.gpu_only = QCheckBox("Fits my GPU")
        self.free_only = QCheckBox("Free only")
        for cb in (self.gpu_only, self.free_only):
            cb.toggled.connect(lambda _on: self.refresh_packs())
            filters.addWidget(cb)
        filters.addStretch()
        self.pack_count = W._label("", "caption")
        filters.addWidget(self.pack_count)
        pl.addLayout(filters)
        self.pack_holder, self.pack_flow = W.flow_box(18)
        pl.addWidget(_scroll(self.pack_holder), 1)
        self.tabs.addTab(packs, "Modpacks")
        # -- mods
        mods = QWidget()
        ml = QVBoxLayout(mods)
        ml.setContentsMargins(0, 12, 0, 0)
        ml.setSpacing(10)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods, authors, kinds…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.refresh_mods())
        bar.addWidget(self.search, 1)
        self.mine_only = QCheckBox("In my pack only")
        self.mine_only.toggled.connect(lambda _on: self.refresh_mods())
        bar.addWidget(self.mine_only)
        ml.addLayout(bar)
        self.cat_holder, self.cat_flow = W.flow_box(6)
        ml.addWidget(self.cat_holder)
        self.cats = QButtonGroup(self)
        self.cats.setExclusive(True)
        self.cats.buttonClicked.connect(lambda _b: self.refresh_mods())
        body = QHBoxLayout()
        body.setSpacing(14)
        self.mod_list = QWidget()
        self.mod_box = QVBoxLayout(W.clear_background(self.mod_list))
        self.mod_box.setContentsMargins(0, 0, 6, 0)
        self.mod_box.setSpacing(8)
        body.addWidget(_scroll(self.mod_list), 1)
        self.drawer = ModDrawer(win)
        body.addWidget(self.drawer)
        ml.addLayout(body, 1)
        self.tabs.addTab(mods, "Mods")
        self.mod_count = 0

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)

    def refresh(self) -> None:
        s = self.win.session
        i = self.edition.findData(s.edition)
        if i >= 0 and self.edition.currentIndex() != i and not getattr(self, "_edition_set", False):
            self.edition.blockSignals(True)
            self.edition.setCurrentIndex(i)
            self.edition.blockSignals(False)
        self._edition_set = True
        self.refresh_packs()
        self._build_categories()
        self.refresh_mods()

    def refresh_packs(self) -> None:
        s = self.win.session
        edition = self.edition.currentData() or s.edition
        try:
            base = s.base_manifest if edition == s.edition else s.manifest_for(edition)
        except Exception:  # noqa: BLE001 - an edition without data shows no packs
            base = None
        _clear(self.pack_flow)
        self.tiles: list[PackTile] = []
        shown = 0
        for pid in (base.packs if base is not None else {}):
            info = pack_info(self.win, pid, edition)
            if (self.gpu_only.isChecked() and not info.gpu_ok) or (self.free_only.isChecked() and info.paid):
                continue
            tile = PackTile(info, self.win.pictures)
            tile.clicked.connect(lambda p=pid, e=edition: self.win.open_pack(p, e))
            tile.play.connect(lambda _p: self.win.play())
            if edition != s.edition:
                tile.setToolTip(f"For {self.edition.currentText()}: your game is "
                                f"{'GTA V Enhanced' if s.edition == 'enhanced' else 'GTA V Legacy'}.")
            self.pack_flow.addWidget(tile)
            self.tiles.append(tile)
            shown += 1
        total = len(base.packs) if base is not None else 0
        self.pack_count.setText(f"{shown} of {total} modpacks")

    def _build_categories(self) -> None:
        s = self.win.session
        layers = sorted({m.layer for m in s.manifest.mods.values() if m.tier != "custom"})
        current = self.cats.checkedButton().text() if self.cats.checkedButton() else "All"
        for b in self.cats.buttons():
            self.cats.removeButton(b)
        _clear(self.cat_flow)
        for name in ["All", *layers]:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setProperty("variant", "chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(name == current)
            self.cats.addButton(b)
            self.cat_flow.addWidget(b)

    def refresh_mods(self) -> None:
        s = self.win.session
        q = self.search.text().strip().lower()
        cat = self.cats.checkedButton().text() if self.cats.checkedButton() else "All"
        mine = {m.id for m in s.mods()}
        installed = s.log.installed_mods()
        mods = sorted((m for m in s.manifest.mods.values() if m.tier != "custom"), key=lambda m: (m.layer, m.name))
        matched = s.matches(list(s.manifest.mods.values())).matched
        _clear(self.mod_box)
        self.rows: list[ModRow] = []
        build = s.game_version()
        for m in mods:
            if cat != "All" and m.layer != cat:
                continue
            if self.mine_only.isChecked() and m.id not in mine:
                continue
            hay = " ".join((m.name, getattr(m, "author", "") or "", m.layer)).lower()  # not the notes: too noisy
            if q and q not in hay:
                continue
            f = matched.get(m.id)
            row = ModRow(m, self.win.pictures, status=_status_of(self.win, m, installed, matched),
                         in_pack=m.id in mine, build=build, size=f.stat().st_size if f and f.exists() else 0)
            row.clicked.connect(lambda mod=m: self.drawer.show_mod(mod))
            self.mod_box.addWidget(row)
            self.rows.append(row)
        if not self.rows:
            self.mod_box.addWidget(W.EmptyState("mods", "No mods match", "Try another word or category."))
        self.mod_box.addStretch()
        self.mod_count = len(self.rows)


# ------------------------------------------------------------------------------------------- the pack page
class PackPage(QWidget):
    """One modpack: the banner with the main action, then Overview / Mods / Variants & settings / Screenshots /
    Files & logs."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.pack_id: str | None = None
        self.edition: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        # hero: the cover with the text and actions on it
        self.hero = QWidget()
        grid = QGridLayout(self.hero)
        grid.setContentsMargins(0, 0, 0, 0)
        self.banner = Banner("pack", "", 236)
        grid.addWidget(self.banner, 0, 0)
        over = QWidget()
        over.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        ol = QHBoxLayout(W.clear_background(over))
        ol.setContentsMargins(28, 22, 28, 22)
        text = QVBoxLayout()
        text.setSpacing(6)
        self.back = W.button("←  Browse", "ghost", lambda: win.show_home("browse"))
        text.addWidget(self.back, 0, Qt.AlignmentFlag.AlignLeft)
        text.addStretch()
        text.addWidget(W._label("MODPACK", "eyebrow"))
        self.name = W._label("", "title", wrap=True)
        f = self.name.font()
        f.setPointSize(22)
        self.name.setFont(f)
        text.addWidget(self.name)
        self.summary = W._label("", None, wrap=True)
        self.summary.setMaximumWidth(720)
        text.addWidget(self.summary)
        self.chips_holder, self.chips = W.flow_box(6)
        text.addWidget(self.chips_holder)
        ol.addLayout(text, 1)
        act = QVBoxLayout()
        act.addStretch()
        self.main_btn = W.button("Play", "primary", self._main_action, "play", glow=True)
        self.main_btn.setMinimumWidth(190)
        act.addWidget(self.main_btn)
        self.main_hint = W._label("", "caption", wrap=True)
        self.main_hint.setMaximumWidth(220)
        self.main_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        act.addWidget(self.main_hint)
        ol.addLayout(act)
        grid.addWidget(over, 0, 0)
        lay.addWidget(self.hero)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.overview, self.mods_tab, self.variants_tab, self.shots_tab, self.files_tab = (QWidget() for _ in range(5))
        for w, name in ((self.overview, "Overview"), (self.mods_tab, "Mods"),
                        (self.variants_tab, "Variants && settings"),  # "&&": a plain "&" (not a shortcut key)
                        (self.shots_tab, "Screenshots"), (self.files_tab, "Files && logs")):
            QVBoxLayout(W.clear_background(w)).setContentsMargins(0, 12, 0, 0)
            self.tabs.addTab(_scroll(w), name)
        self.mod_rows: list[ModRow] = []
        self.toggles: dict[str, QCheckBox] = {}
        self.shots: list[W.Art] = []

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)

    def resizeEvent(self, e) -> None:  # noqa: N802
        self.banner.setFixedHeight(176 if self.height() < 620 else 236)  # leave the tabs room on small screens
        super().resizeEvent(e)

    def set_pack(self, pack_id: str | None, edition: str | None = None) -> None:
        self.pack_id, self.edition = pack_id, edition
        self.refresh()

    def current_id(self) -> str | None:
        s = self.win.session
        base = s.base_manifest
        pid = self.pack_id or s.pack_choice().pack or base.default_pack
        return pid if pid in base.packs or (self.edition and self.edition != s.edition) else next(iter(base.packs), None)

    def refresh(self) -> None:
        pid = self.current_id()
        if pid is None:
            return
        s = self.win.session
        edition = self.edition or s.edition
        info = pack_info(self.win, pid, edition)
        self.info = info
        pack = info.pack
        self.name.setText(pack.name)
        self.summary.setText(summary_of(pack.description, 220))
        cover_mod = next((m for m in info.mods if getattr(m, "image", None)), None)
        if pack.picture:
            self.win.pictures.bind(self.banner, f"pack:{pack.id}", pack.picture, None)
        elif cover_mod is not None:
            self.win.pictures.bind_mod(self.banner, cover_mod)
        _clear(self.chips)
        variant = pack.variant(s.pack_choice().variant if info.chosen else None)
        for text, tone in ((f"{len(info.mods)} mods", "info"), (size_text(info.size) if info.size else "", None),
                           (f"Variant: {variant.name}" if variant else "", None),
                           ("Free" if not info.paid else "Has paid mods", "success" if not info.paid else "warning"),
                           (f"Game build {s.game_version()}" if s.game_version() else "", None)):
            if text:
                self.chips.addWidget(W.Badge(text, tone))
        self._set_action(info)
        self._overview(info)
        self._mods(info)
        self._variants(info)
        self._screenshots(info)
        self._files(info)

    # ---- the main action
    def _set_action(self, info: PackInfo) -> None:
        s = self.win.session
        if info.edition != s.edition:
            kind, text, hint = "none", "Not for your game", "This pack is for the other edition of GTA V."
        elif not info.chosen:
            kind, text, hint = "use", "Use this pack", "Switches your modpack; Leonida asks before removing mods."
        elif info.missing > 0:
            kind, text, hint = "get", f"Get the files ({info.missing})", "Downloads from the authors' own pages."
        elif info.to_install > 0:
            kind, text, hint = "install", f"Install ({info.to_install} left)", "One step at a time, every file logged."
        else:
            kind, text, hint = "play", "Play", "Starts GTA V story mode."
        if not info.gpu_ok and kind == "use":
            kind, text, hint = "none", "Needs an RTX 50", "This pack needs an NVIDIA RTX 50-series graphics card."
        self.action_kind = kind
        self.main_btn.setText(text)
        self.main_btn.setEnabled(kind != "none")
        self.main_hint.setText(hint)

    def _main_action(self) -> None:
        kind = getattr(self, "action_kind", "none")
        if kind == "use":
            if self.win.pages[2].switch(self.info.pack.id):
                self.pack_id = None
                self.refresh()
                self.win.bottom.refresh()
        elif kind == "get":
            self.win.go(3)
        elif kind == "install":
            self.win.go(5)
        elif kind == "play":
            self.win.play()

    # ---- tabs
    def _tab(self, w: QWidget):
        lay = w.layout()
        _clear(lay)
        return lay

    def _overview(self, info: PackInfo) -> None:
        lay = self._tab(self.overview)
        lay.addWidget(W._label("ABOUT THIS PACK", "eyebrow"))
        lay.addWidget(W._label(info.pack.description, None, wrap=True))
        notice = notice_for(info.pack.name)
        if notice:
            lay.addSpacing(8)
            lay.addWidget(W._label("WHAT YOU'LL NOTICE IN GAME", "eyebrow"))
            box, bl = W.flow_box(10)
            for item in notice:
                card = QFrame()
                card.setProperty("card", True)
                card.setFixedWidth(300)
                cl = QHBoxLayout(card)
                cl.setContentsMargins(12, 10, 12, 10)
                icon = QLabel()
                icon.setPixmap(W.icon_pixmap("check", C["success"], 16))
                cl.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
                cl.addWidget(W._label(item, None, wrap=True), 1)
                bl.addWidget(card)
            lay.addWidget(box)
        lay.addStretch()

    def _mods(self, info: PackInfo) -> None:
        lay = self._tab(self.mods_tab)
        s = self.win.session
        base = s.base_manifest
        installed = s.log.installed_mods() if info.edition == s.edition else set()
        matched = s.matches(info.mods).matched if info.edition == s.edition else {}
        in_base = base.pack_mod_ids(info.pack.id, (), s.pack_choice().variant if info.chosen else None) \
            if info.edition == s.edition else {m.id for m in info.mods}
        addon_of = {mid: a for a in base.addons.values() for mid in a.mods} if info.edition == s.edition else {}
        chosen_addons = set(s.chosen_addons()) if info.chosen else set()
        self.mod_rows, self.toggles = [], {}
        head = QHBoxLayout()
        head.addWidget(W._label(f"{len(info.mods)} MODS · {info.installed} INSTALLED · {info.ready} DOWNLOADED", "eyebrow"))
        head.addStretch()
        if info.chosen:
            head.addWidget(W.button("All add-ons…", "ghost", lambda: self.win.go(2)))
        lay.addLayout(head)
        build = s.game_version()
        for m in info.mods:
            toggle = None
            addon = addon_of.get(m.id)
            if info.chosen and addon is not None and m.id not in in_base:
                toggle = QCheckBox()
                toggle.setToolTip(f"Add-on: {addon.name}")
                toggle.setChecked(addon.id in chosen_addons)
                toggle.toggled.connect(lambda on, a=addon.id: self._toggle_addon(a, on))
                self.toggles[m.id] = toggle
            f = matched.get(m.id)
            row = ModRow(m, self.win.pictures, status=_status_of(self.win, m, installed, matched), in_pack=False,
                         build=build, size=f.stat().st_size if f and f.exists() else 0, toggle=toggle)
            row.clicked.connect(lambda mod=m: self._details(mod))
            lay.addWidget(row)
            self.mod_rows.append(row)
        lay.addStretch()

    def _toggle_addon(self, addon_id: str, on: bool) -> None:
        self.win.pages[2].toggle_addon(addon_id, on)
        QTimer.singleShot(0, self.refresh)

    def _details(self, mod) -> None:
        self.win.show_home("browse")
        browse = self.win.browse
        browse.tabs.setCurrentIndex(1)
        browse.drawer.show_mod(mod)

    def _variants(self, info: PackInfo) -> None:
        lay = self._tab(self.variants_tab)
        s = self.win.session
        pack = info.pack
        lay.addWidget(W._label("VARIANT", "eyebrow"))
        if not pack.variants:
            lay.addWidget(W._label("This pack has one setup: no variants to choose.", "caption"))
        current = pack.variant(s.pack_choice().variant if info.chosen else None)
        box, flow = W.flow_box(12)
        self.variant_buttons: dict[str, QRadioButton] = {}
        group = QButtonGroup(self.variants_tab)
        for v in pack.variants:
            card = QFrame()
            card.setProperty("card", True)
            card.setProperty("selected", current is not None and v.id == current.id)
            card.setFixedWidth(300)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            rb = QRadioButton(v.name)
            rb.setChecked(current is not None and v.id == current.id)
            rb.setEnabled(info.chosen)
            group.addButton(rb)
            rb.toggled.connect(lambda on, vid=v.id: on and self._pick_variant(vid))
            self.variant_buttons[v.id] = rb
            cl.addWidget(rb)
            cl.addWidget(W._label(v.description or "", "caption", wrap=True))
            flow.addWidget(card)
        lay.addWidget(box)
        lay.addSpacing(8)
        lay.addWidget(W._label("LOCKED SETTINGS", "eyebrow"))
        lay.addWidget(W._label("Values Leonida writes into the mods' own settings files for this pack and variant, "
                               "so keys and features don't clash.", "caption", wrap=True))
        count = 0
        if info.edition == s.edition:
            for m in info.mods:
                wanted = s.settings_for(m) if info.chosen else []
                if not wanted:
                    continue
                card = QFrame()  # one card per mod: its picture and name, then each value it locks
                card.setProperty("card", True)
                cl = QHBoxLayout(card)
                cl.setContentsMargins(12, 10, 14, 10)
                cl.setSpacing(14)
                art = thumb(96, 54, m.id, m.layer)
                self.win.pictures.bind_mod(art, m)
                cl.addWidget(art, 0, Qt.AlignmentFlag.AlignTop)
                col = QVBoxLayout()
                col.setSpacing(4)
                col.addWidget(W._label(m.name, "subtitle"))
                for w in wanted:
                    line = QHBoxLayout()
                    line.setSpacing(12)
                    key = W._label(f"{w.file} · {w.key} = {w.value}", None)
                    key.setMinimumWidth(360)
                    line.addWidget(key, 0)
                    line.addWidget(W._label(w.why or "", "caption", wrap=True), 1)
                    col.addLayout(line)
                    count += 1
                cl.addLayout(col, 1)
                lay.addWidget(card)
        if not count:
            lay.addWidget(W._label("Use this pack to see the values it locks." if not info.chosen else
                                   "No locked settings.", "caption"))
        lay.addStretch()

    def _pick_variant(self, variant_id: str) -> None:
        self.win.pages[2].pick_variant(variant_id)
        QTimer.singleShot(0, self.refresh)

    def _screenshots(self, info: PackInfo) -> None:
        lay = self._tab(self.shots_tab)
        box, flow = W.flow_box(14)
        self.shots = []
        for m in info.mods:
            if not (getattr(m, "image", None) or m.page):
                continue
            card = QFrame()
            card.setProperty("card", True)
            card.setFixedWidth(292)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(8, 8, 8, 10)
            cl.setSpacing(6)
            art = thumb(276, 155, m.id, m.layer)
            self.win.pictures.bind_mod(art, m)
            cl.addWidget(art)
            cl.addWidget(W._label(m.name, "caption"))
            flow.addWidget(card)
            self.shots.append(art)
        lay.addWidget(box)
        lay.addStretch()

    def _files(self, info: PackInfo) -> None:
        lay = self._tab(self.files_tab)
        s = self.win.session
        if info.edition != s.edition:
            lay.addWidget(W._label("This pack is for the other edition of GTA V.", "caption"))
            lay.addStretch()
            return
        tp = s.test_place()
        matched = s.matches(info.mods).matched
        lay.addWidget(W._label("DOWNLOADS", "eyebrow"))
        row = QHBoxLayout()
        row.addWidget(W._label(f"Folder: {s.config.downloads()}", "caption"), 1)
        row.addWidget(W.button("Get mods page", "ghost", lambda: self.win.go(3)))
        lay.addLayout(row)
        for m in info.mods:
            f = matched.get(m.id)
            r = tp.cached(f) if f else None
            text = (f"{f.name} · {size_text(f.stat().st_size) if f.exists() else ''} · "
                    f"{r.label if r else 'not scanned yet'}") if f else "not downloaded"
            line = QHBoxLayout()
            line.addWidget(W._label(m.name, "subtitle"), 0)
            line.addWidget(W._label(text, "caption"), 1)
            lay.addLayout(line)
        lay.addSpacing(10)
        lay.addWidget(W._label("INSTALL LOG", "eyebrow"))
        steps = [st for st in s.log.steps if st.status == "done"]
        if not steps:
            lay.addWidget(W._label("Nothing installed yet.", "caption"))
        names = {m.id: m.name for m in s.manifest.mods.values()}
        for st in steps:
            settings_of = st.mod.split(":", 1)[1] if st.mod.startswith("settings:") else None
            name = f"Locked settings: {names.get(settings_of, settings_of)}" if settings_of else names.get(st.mod, st.mod)
            lay.addWidget(W._label(f"Step {st.id} · {name} · {st.method} · {len(st.actions)} change(s)", "caption"))
        lay.addSpacing(10)
        lay.addWidget(W.button("Check the game's logs", "secondary", self._logs, "shield"), 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()

    def _logs(self) -> None:
        self.win.go(6)
        self.win.pages[6].check_logs()


# ------------------------------------------------------------------------------------------------ bottom bar
class BottomBar(QFrame):
    """Always there, like a launcher: the game and its build, the pack, the mods' state, what's running, Play."""

    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        self.setObjectName("bottombar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#bottombar {{ background: {C['surface']}; border-top: 1px solid {C['border']}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 10, 20, 10)
        lay.setSpacing(18)
        self.game = W._label("", "subtitle")
        self.pack = W._label("", "caption")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.game)
        col.addWidget(self.pack)
        lay.addLayout(col)
        self.state = W.StatusPill("mods-off")
        lay.addWidget(self.state)
        lay.addStretch()
        self.work = W._label("", "caption")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(260)
        self.bar.setRange(0, 0)
        lay.addWidget(self.work)
        lay.addWidget(self.bar)
        self.play_btn = W.button("Play", "primary", win.play, "play", glow=True)
        self.play_btn.setMinimumWidth(150)
        lay.addWidget(self.play_btn)
        self.timer = QTimer(self)
        self.timer.setInterval(800)
        self.timer.timeout.connect(self.refresh_work)
        self.timer.start()
        self.refresh()

    def refresh(self) -> None:
        from ..detect import EDITION_NAMES
        from ..onlinesafe import status as online_status

        s = self.win.session
        g = s.game_dir()
        build = s.game_version() if g else None
        edition = EDITION_NAMES.get(s.game_edition or s.edition, "GTA V")
        self.game.setText(f"{edition} · {build}" if build else f"{edition} · game not found")
        c = s.pack_choice()
        pack = s.base_manifest.packs.get(c.pack) if c.pack else None
        variant = pack.variant(c.variant) if pack else None
        self.pack.setText(" · ".join(x for x in (pack.name if pack else "No modpack chosen",
                                                 variant.name if variant else "") if x))
        n = len(s.log.installed_mods())
        try:
            st = online_status(g, s.manifest.online_safe_items) if g and g.is_dir() else ""
        except Exception:  # noqa: BLE001
            st = ""
        kind = "online-safe" if st == "online-safe" else ("mods-on" if n else "mods-off")
        self.state.set_status(kind, f"{n} mods" if n and kind == "mods-on" else "")
        self.play_btn.setEnabled(bool(g and g.is_dir()))
        self.play_btn.setToolTip("Starts GTA V story mode (PlayGTAV.exe)" if g else "Find your game first")
        self.refresh_work()

    def refresh_work(self) -> None:
        pages = self.win.pages
        get, install = pages[3], pages[5]
        busy = getattr(get, "busy", {}) or {}
        text = ""
        if getattr(install, "_running", False):
            text = "Installing…"
        elif busy or getattr(get, "autodl", None) is not None:
            text = f"Downloading {len(busy)} mod{'s' if len(busy) != 1 else ''}…" if busy else "Downloading…"
        self.work.setText(text)
        self.work.setVisible(bool(text))
        self.bar.setVisible(bool(text))


def play_game(win) -> str:
    """Start GTA V story mode through PlayGTAV.exe (the Rockstar launcher's entry point). Returns what happened.
    Mods moved out by Online-safe are offered back first."""
    from PySide6.QtWidgets import QMessageBox

    from .. import PACK_NAME
    from ..installer import windows_launch_command
    from ..onlinesafe import restore_mods
    from ..onlinesafe import status as online_status

    s = win.session
    g = s.game_dir()
    if not g or not g.is_dir():
        return "Find your game first (Game page)."
    try:
        st = online_status(g, s.manifest.online_safe_items)
    except Exception:  # noqa: BLE001
        st = ""
    if st in ("online-safe", "mixed") and QMessageBox.question(
            win, PACK_NAME, "Your mods are moved out (Online-safe). Bring them back before playing story mode?") \
            == QMessageBox.StandardButton.Yes:
        restore_mods(g)
    exe = g / "PlayGTAV.exe"
    if not exe.is_file():
        from ..detect import find_exe

        exe = find_exe(g, s.base_manifest.exe_names) or exe
    if not exe.is_file():
        return f"No PlayGTAV.exe in {g}."
    if os.environ.get("LEONIDA_NO_OPEN"):
        return f"Would start {exe.name} (opening is off)."
    import subprocess

    subprocess.Popen(windows_launch_command(exe), cwd=str(g))
    return f"Starting {exe.name}: story mode loads in a minute."


__all__ = ["BottomBar", "BrowsePage", "ModDrawer", "ModRow", "PackPage", "PackTile", "Pictures", "notice_for",
           "pack_info", "play_game", "size_text", "summary_of"]
