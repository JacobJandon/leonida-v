"""Render docs/design/theme-preview.png: a demo window in the Leonida V theme (leonida/gui/theme.py).

    QT_QPA_PLATFORM=offscreen python build/theme_preview.py [--out docs/design/theme-preview.png] [--show]

Shows the sidebar nav, the page header, mod cards (selected / normal / unsupported), the download queue with
per-mod progress, inputs, every button variant, badges and a toast. Not part of the app.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonida.gui import theme  # noqa: E402

LOGO = ROOT / "leonida" / "gui" / "assets" / "leonida.png"


def label(text: str, role: str | None = None, tone: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    if tone:
        lab.setProperty("tone", tone)
    lab.setWordWrap(wrap)
    return lab


def button(text: str, variant: str | None = None, enabled: bool = True) -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    b.setEnabled(enabled)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def art(colors: tuple[str, str], h: int = 96) -> QLabel:
    """Stand-in for a mod's preview image: a sunset gradient tile."""
    a = QLabel()
    a.setFixedHeight(h)
    a.setStyleSheet(
        "border-radius: 10px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 {colors[0]}, stop:1 {colors[1]});")
    return a


def card(name: str, author: str, badges: list[tuple[str, str | None]], *, checked: bool, selected: bool = False,
         unsupported: str | None = None, colors=("#FFC15E", "#FF4F8B")) -> QFrame:
    f = QFrame()
    f.setProperty("card", True)
    if selected:
        f.setProperty("selected", True)
    if unsupported:
        f.setProperty("disabled", True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)
    lay.addWidget(art(colors if not unsupported else ("#262634", "#1C1C27")))
    top = QHBoxLayout()
    cb = QCheckBox()
    cb.setChecked(checked)
    cb.setEnabled(not unsupported)
    top.addWidget(label(name, "subtitle"))
    top.addStretch()
    top.addWidget(cb)
    lay.addLayout(top)
    lay.addWidget(label(author, "caption"))
    row = QHBoxLayout()
    row.setSpacing(6)
    for text, tone in badges:
        row.addWidget(label(text, "badge", tone))
    row.addStretch()
    lay.addLayout(row)
    if unsupported:
        lay.addWidget(label(unsupported, "caption", "warning", wrap=True))
    lay.addStretch()
    return f


def queue_row(name: str, status: str, value: int, tone: str | None = None, sub: str = "") -> QWidget:
    w = QFrame()
    w.setProperty("card", True)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(14, 10, 14, 12)
    lay.setSpacing(6)
    top = QHBoxLayout()
    top.addWidget(label(name, "subtitle"))
    top.addStretch()
    top.addWidget(label(status, "caption", tone))
    lay.addLayout(top)
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(value)
    bar.setTextVisible(False)
    if tone in ("success", "error"):
        bar.setProperty("tone", tone)
    lay.addWidget(bar)
    if sub:
        lay.addWidget(label(sub, "caption"))
    return w


def sidebar(current: int) -> QWidget:
    side = QWidget()
    side.setObjectName("sidebar")
    side.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    side.setFixedWidth(232)
    sl = QVBoxLayout(side)
    sl.setContentsMargins(16, 20, 8, 16)
    sl.setSpacing(6)
    brand = QHBoxLayout()
    logo = QLabel()
    logo.setPixmap(QPixmap(str(LOGO)).scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
    brand.addWidget(logo)
    names = QVBoxLayout()
    names.setSpacing(0)
    names.addWidget(label("LEONIDA V", "eyebrow"))
    names.addWidget(label("1.0.0", "caption"))
    brand.addLayout(names)
    brand.addStretch()
    sl.addLayout(brand)
    sl.addSpacing(14)
    nav = QListWidget()
    nav.setObjectName("nav")
    steps = ["Welcome", "Game", "Choose mods", "Get mods", "Check", "Install", "Manage"]
    marks = ["✓" if i < current else str(i + 1) for i in range(len(steps))]
    nav.addItems([f"{m}   {s}" for m, s in zip(marks, steps, strict=True)])
    nav.setCurrentRow(current)
    sl.addWidget(nav, 1)
    status = QFrame()
    status.setProperty("card", True)
    st = QVBoxLayout(status)
    st.setContentsMargins(12, 10, 12, 10)
    st.setSpacing(2)
    st.addWidget(label("GTA V Enhanced", "caption"))
    st.addWidget(label("1.0.1013.20", "subtitle"))
    st.addWidget(label("● Mods on", "caption", "success"))
    sl.addWidget(status)
    return side


def build_window() -> QWidget:
    win = QWidget()
    win.setWindowTitle("Leonida V theme preview")
    win.resize(1280, 800)
    root = QHBoxLayout(win)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    root.addWidget(sidebar(current=2))

    # ---- page
    page = QWidget()
    pl = QVBoxLayout(page)
    pl.setContentsMargins(32, 24, 32, 20)
    pl.setSpacing(14)
    strip = QFrame()
    strip.setProperty("brand", True)
    head = QHBoxLayout()
    titles = QVBoxLayout()
    titles.setSpacing(2)
    titles.addWidget(label("STEP 3 OF 7", "eyebrow"))
    titles.addWidget(label("Choose your mods", "title"))
    titles.addWidget(label("Core profile picked for a GTX 1070. Tick what you want; cards that can't run on "
                           "your game build are greyed out with the reason.", "muted", wrap=True))
    head.addLayout(titles, 1)
    prof = QHBoxLayout()
    prof.setSpacing(6)
    for i, p in enumerate(("Core", "Max", "Custom")):
        b = button(p, "primary" if i == 0 else "secondary")
        prof.addWidget(b)
    head.addLayout(prof)
    pl.addLayout(head)
    pl.addWidget(strip)

    body = QHBoxLayout()
    body.setSpacing(20)
    grid = QGridLayout()
    grid.setSpacing(14)
    grid.addWidget(card("NaturalVision Enhanced", "Razed · Graphics",
                        [("Core", None), ("December 2025", "info")], checked=True, selected=True,
                        colors=("#FFC15E", "#FF4F8B")), 0, 0)
    grid.addWidget(card("Menyoo 2.0", "MAFINS, ItsJustCurtis · Tools",
                        [("Core", None), ("Auto download", "success")], checked=True,
                        colors=("#FF4F8B", "#8B3DFF")), 0, 1)
    grid.addWidget(card("Lively World Expansion", "LWE team · World",
                        [("Max", None), ("Needs 1.0.1158", "warning")], checked=False,
                        unsupported="Not on 1.0.1013.20: swap it for Enable All Interiors."), 1, 0)
    grid.addWidget(card("Script Hook V .NET", "Chiheb-Bacha · Framework",
                        [("Core", None), ("Installed", "success")], checked=True,
                        colors=("#8B3DFF", "#5CC8FF")), 1, 1)
    gw = QWidget()
    gw.setLayout(grid)
    body.addWidget(gw, 3)

    right = QVBoxLayout()
    right.setSpacing(10)
    right.addWidget(label("DOWNLOAD QUEUE", "eyebrow"))
    right.addWidget(queue_row("Script Hook V .NET", "Done · verified", 100, "success", "2.7 MB · SHA-256 ok"))
    right.addWidget(queue_row("Menyoo 2.0", "62% · 4.0 / 6.4 MB", 62, None, "github.com/itsjustcurtis"))
    right.addWidget(queue_row("Ultimate ASI Loader", "Failed", 35, "error", "Connection reset. Retry or get it in the browser."))
    folder = QHBoxLayout()
    edit = QLineEdit(r"D:\Games\Grand Theft Auto V Enhanced")
    edit.setCursorPosition(0)
    folder.addWidget(edit, 1)
    folder.addWidget(button("Browse…", "secondary"))
    right.addSpacing(6)
    right.addWidget(label("GAME FOLDER", "eyebrow"))
    right.addLayout(folder)
    bad = QLineEdit(r"C:\Program Files\Nothing here")
    bad.setProperty("invalid", True)
    right.addWidget(bad)
    right.addWidget(label("GTA5_Enhanced.exe not found in this folder.", "caption", "error"))
    right.addStretch()
    rw = QWidget()
    rw.setLayout(right)
    body.addWidget(rw, 2)
    pl.addLayout(body, 1)

    toast = QFrame()
    toast.setProperty("toast", True)
    tl = QHBoxLayout(toast)
    tl.setContentsMargins(14, 8, 8, 8)
    tl.addWidget(label("✓  MenyooSP.zip saved to Downloads and matched to Menyoo 2.0.", None, "success"))
    tl.addStretch()
    tl.addWidget(button("Undo", "ghost"))
    pl.addWidget(toast)

    actions = QHBoxLayout()
    actions.setSpacing(10)
    actions.addWidget(button("Uninstall everything", "danger"))
    actions.addWidget(button("Disabled", "secondary", enabled=False))
    actions.addStretch()
    actions.addWidget(button("Skip for now", "ghost"))
    actions.addWidget(button("Back", "secondary"))
    nxt = button("Next: get mods  →", "primary")
    theme.add_glow(nxt, radius=24, alpha=0.45)
    actions.addWidget(nxt)
    pl.addLayout(actions)
    root.addWidget(page, 1)
    return win


def feature(title: str, text: str, eyebrow: str) -> QFrame:
    f = QFrame()
    f.setProperty("card", True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(6)
    lay.addWidget(label(eyebrow, "eyebrow"))
    lay.addWidget(label(title, "subtitle"))
    lay.addWidget(label(text, "muted", wrap=True))
    lay.addStretch()
    return f


def build_welcome() -> QWidget:
    win = QWidget()
    win.resize(1280, 800)
    root = QHBoxLayout(win)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    root.addWidget(sidebar(current=0))
    page = QWidget()
    pl = QVBoxLayout(page)
    pl.setContentsMargins(48, 40, 48, 24)
    pl.setSpacing(18)

    hero = QFrame()
    hero.setObjectName("hero")
    hero.setStyleSheet(
        "QFrame#hero { border: 1px solid #2C2C3C; border-radius: 18px; background: qlineargradient(x1:0, y1:0, "
        "x2:1, y2:1, stop:0 #1A1222, stop:0.55 #15151D, stop:1 #120F1F); }")
    hl = QHBoxLayout(hero)
    hl.setContentsMargins(36, 28, 36, 28)
    hl.setSpacing(32)
    logo = QLabel()
    logo.setPixmap(QPixmap(str(LOGO)).scaled(210, 210, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
    theme.add_glow(logo, radius=60, alpha=0.5)
    hl.addWidget(logo)
    text = QVBoxLayout()
    text.setSpacing(10)
    text.addStretch()
    text.addWidget(label("STORY MODE · GTA V ENHANCED", "eyebrow"))
    name = theme.gradient_label("LEONIDA V")
    text.addWidget(name)
    text.addWidget(label("A GTA VI-style GTA V Enhanced, one safe step at a time. Curated, conflict-checked mods; "
                         "every file logged, every step undoable.", "muted", wrap=True))
    cta = QHBoxLayout()
    cta.setSpacing(10)
    start = button("Start: find my game  →", "primary")
    theme.add_glow(start, radius=26, alpha=0.45)
    cta.addWidget(start)
    cta.addWidget(button("Read the guide", "ghost"))
    cta.addStretch()
    text.addSpacing(6)
    text.addLayout(cta)
    text.addStretch()
    hl.addLayout(text, 1)
    pl.addWidget(hero)

    row = QHBoxLayout()
    row.setSpacing(14)
    row.addWidget(feature("Curated and conflict-checked",
                          "24 mods in profiles that fit your GPU and game build. Clashing keys and slots are caught before "
                          "anything is installed.", "PICK"))
    row.addWidget(feature("Every file logged",
                          "A snapshot before the first step. Undo one step or everything, and the folder is exactly as it was.",
                          "UNDO"))
    row.addWidget(feature("Online-safe switch",
                          "Story mode only. One click moves every mod out before you go online, and back afterwards.",
                          "SAFE"))
    pl.addLayout(row)

    before = QFrame()
    before.setProperty("card", True)
    bl = QVBoxLayout(before)
    bl.setContentsMargins(18, 14, 18, 14)
    bl.setSpacing(8)
    bl.addWidget(label("Before you start", "subtitle"))
    for text_, done in (("Back up your saves (Documents\\Rockstar Games\\GTA V Enhanced\\Profiles)", True),
                        ("Turn off automatic game updates in your launcher", True),
                        ("Turn off BattlEye in the Rockstar Games Launcher (story mode only)", False)):
        cb = QCheckBox(text_)
        cb.setChecked(done)
        bl.addWidget(cb)
    pl.addWidget(before)
    pl.addStretch()
    foot = QHBoxLayout()
    foot.addWidget(label("Leonida V never re-hosts mods: every file comes from its author's own page.", "caption"))
    foot.addStretch()
    foot.addWidget(label("Up to date · 1.0.0", "badge", "success"))
    pl.addLayout(foot)
    root.addWidget(page, 1)
    return win


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", choices=("choose", "welcome"), default="choose")
    ap.add_argument("--out", type=Path, help="default: docs/design/theme-preview[-welcome].png")
    ap.add_argument("--show", action="store_true", help="open the window instead of saving a picture")
    args = ap.parse_args()
    if args.out is None:
        suffix = "" if args.page == "choose" else f"-{args.page}"
        args.out = ROOT / "docs" / "design" / f"theme-preview{suffix}.png"
    app = QApplication.instance() or QApplication(sys.argv)
    info = theme.apply_theme(app)
    win = build_window() if args.page == "choose" else build_welcome()
    if args.show:
        win.show()
        return app.exec()
    win.show()
    app.processEvents()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ok = win.grab().save(str(args.out))
    print(f"{'Saved' if ok else 'Could not save'} {args.out}  (body font: {info.body}, display: {info.display}, "
          f"bundled: {', '.join(info.loaded) or 'none'})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
