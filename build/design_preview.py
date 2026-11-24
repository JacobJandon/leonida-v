"""Render the redesign previews: every component and a mock of each wizard page, into docs/design/*.png.

    QT_QPA_PLATFORM=offscreen python build/design_preview.py [--out docs/design] [--only choose,install]

Uses the real manifest (Core mods resolved for game build 1.0.1013.20), the real logo and leonida/gui/widgets.py on
the theme from leonida/gui/theme.py. Mod pictures are the sunset placeholders (real ones are fetched at runtime from
the authors' pages). Mock data only: nothing here touches a game folder, the state folder or the network.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from leonida import __version__  # noqa: E402
from leonida.gui import theme  # noqa: E402
from leonida.gui import widgets as W  # noqa: E402
from leonida.manifest import load_manifest  # noqa: E402

BUILD = "1.0.1013.20"
LOGO = ROOT / "leonida" / "gui" / "assets" / "leonida.png"
PAGES = ["Welcome", "Game", "Choose mods", "Get mods", "Check", "Install", "Manage"]
SIZE = (1280, 800)


def lab(text: str, role: str | None = None, tone: str | None = None, wrap: bool = False) -> QLabel:
    return W._label(text, role, tone, wrap)


def card(margins=(16, 14, 16, 14), spacing=8) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("card", True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


def shell(current: int, header: QWidget, body: QWidget, actions: QWidget | None, toast: W.Toast | None = None) -> QWidget:
    win = QWidget()
    win.resize(*SIZE)
    root = QHBoxLayout(win)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    side = W.Sidebar(LOGO, __version__)
    for i, name in enumerate(PAGES):
        state = "done" if i < current else ("current" if i == current else "todo")
        if i == 5 and current < 4:
            state = "locked"
        side.nav.add_step(name, state=state, reason="Run the checks first")
    side.set_game(BUILD, "mods-on" if current >= 5 else "mods-off", "14 mods" if current >= 5 else "")
    root.addWidget(side)
    page = QWidget()
    pl = QVBoxLayout(page)
    pl.setContentsMargins(32, 24, 32, 20)
    pl.setSpacing(16)
    pl.addWidget(header)
    pl.addWidget(body, 1)
    if toast is not None:
        pl.addWidget(toast)
    if actions is not None:
        pl.addWidget(actions)
    root.addWidget(page, 1)
    return win


# ------------------------------------------------------------------------------------------- pages
def page_welcome(m) -> QWidget:
    win = QWidget()
    win.resize(*SIZE)
    root = QHBoxLayout(win)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    side = W.Sidebar(LOGO, __version__)
    for i, name in enumerate(PAGES):
        side.nav.add_step(name, state="current" if i == 0 else ("locked" if i >= 4 else "todo"),
                          reason="Pick your game first")
    side.set_game(BUILD, "mods-off")
    root.addWidget(side)
    page = QWidget()
    pl = QVBoxLayout(page)
    pl.setContentsMargins(44, 36, 44, 24)
    pl.setSpacing(18)
    core = [x for x in m.mods.values() if x.tier == "core"]
    pl.addWidget(W.HeroHeader(LOGO, pitch=f"A GTA VI-style GTA V Enhanced, one safe step at a time: {len(core)} "
                              "curated, conflict-checked mods, every file logged, every step undoable.",
                              actions=[W.button("Start: find my game", "primary", icon_name="play", glow=True),
                                       W.button("Read the guide", "ghost")]))
    row = QHBoxLayout()
    row.setSpacing(14)
    for eyebrow, title, text in (
            ("PICK", "Curated and conflict-checked", f"{len(m.mods)} mods in profiles that fit your GPU and game build; "
                                                     "key clashes and slots are caught before install."),
            ("UNDO", "Every file logged", "A snapshot before the first step. Undo one step or everything, and the "
                                          "folder is exactly as it was."),
            ("SAFE", "Online-safe switch", "Story mode only. One click moves every mod out before you go online.")):
        f, lay = card()
        lay.addWidget(lab(eyebrow, "eyebrow"))
        lay.addWidget(lab(title, "subtitle"))
        lay.addWidget(lab(text, "muted", wrap=True))
        lay.addStretch()
        row.addWidget(f)
    pl.addLayout(row)
    f, lay = card((18, 14, 18, 14))
    lay.addWidget(lab("Before you start", "subtitle"))
    for text, done in (("Back up your saves (Documents\\Rockstar Games\\GTA V Enhanced\\Profiles)", True),
                       ("Turn off automatic game updates in your launcher", True),
                       ("Turn off BattlEye in the Rockstar Games Launcher (story mode only)", False)):
        cb = QCheckBox(text)
        cb.setChecked(done)
        lay.addWidget(cb)
    pl.addWidget(f)
    pl.addStretch()
    foot = QHBoxLayout()
    foot.addWidget(lab("Leonida V never re-hosts mods: every file comes from its author's own page.", "caption"))
    foot.addStretch()
    foot.addWidget(W.StatusPill("up-to-date", f"Leonida {__version__}"))
    pl.addLayout(foot)
    root.addWidget(page, 1)
    return win


def page_game(m) -> QWidget:
    header = W.PageHeader(2, 7, "Find GTA V Enhanced", "Leonida found your game. Pick it, or browse to the folder "
                          "that holds GTA5_Enhanced.exe.")
    body = QWidget()
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(14)
    bl.addWidget(W.EditionPicker([("Enhanced", r"D:\Games\Grand Theft Auto V Enhanced", BUILD),
                                  ("Legacy", None, None)]))
    group = QButtonGroup(body)
    for path, store, chosen in ((r"D:\Games\Grand Theft Auto V Enhanced", "Common folder", True),
                                (r"C:\Program Files\Rockstar Games\Grand Theft Auto V Enhanced", "Rockstar", False)):
        f, lay = card((16, 12, 16, 12), 4)
        if chosen:
            f.setProperty("selected", True)
        top = QHBoxLayout()
        rb = QRadioButton()
        rb.setChecked(chosen)
        group.addButton(rb)
        top.addWidget(rb)
        top.addWidget(lab(path, "subtitle"), 1)
        top.addWidget(W.Badge(store))
        lay.addLayout(top)
        info = QHBoxLayout()
        info.addSpacing(26)
        if chosen:
            info.addWidget(lab(f"GTA5_Enhanced.exe {BUILD}", "caption"))
            info.addWidget(W.Badge("Not a tested build", "warning", "Tested: 1.0.1158.13"))
            info.addWidget(W.Badge("Older versions picked for 3 mods", "info"))
        else:
            info.addWidget(lab("GTA5_Enhanced.exe not found here (old install?)", "caption", "error"))
        info.addStretch()
        lay.addLayout(info)
        bl.addWidget(f)
    row = QHBoxLayout()
    edit = QLineEdit(r"D:\Games\Grand Theft Auto V Enhanced")
    edit.setCursorPosition(0)
    row.addWidget(edit, 1)
    row.addWidget(W.button("Browse…", "secondary"))
    row.addWidget(W.button("Detect again", "ghost"))
    bl.addLayout(row)
    f, lay = card((16, 12, 16, 14))
    lay.addWidget(lab("THIS PC", "eyebrow"))
    pills, flow = W.flow_box(8)
    for text, kind in ((".NET Framework 4.8", "ready"), ("VC++ x64", "ready"), ("7-Zip", "ready"),
                       ("GPU: GTX 1070 → Core profile", "ready"), ("BattlEye on", "manual")):
        p = W.StatusPill(kind)
        p.text.setText(text)
        flow.addWidget(p)
    lay.addWidget(pills)
    bl.addWidget(f)
    bl.addStretch()
    actions = W.ActionBar(right=[W.button("Back", "secondary"), W.button("Use this folder  →", "primary", glow=True)])
    return shell(1, header, body, actions)


def core_mods(m):
    sel = m.resolve("core", [], [], {})
    return sel


def page_choose(m) -> QWidget:
    prof = QWidget()
    pr = QHBoxLayout(prof)
    pr.setContentsMargins(0, 0, 0, 0)
    pr.setSpacing(6)
    for i, p in enumerate(("Core", "Core + Extras", "Max (RTX 50)", "GTA VI Showcase")):
        b = W.button(p, "primary" if i == 0 else "secondary")
        if i == 2:
            b.setEnabled(False)
            b.setToolTip("Needs an NVIDIA RTX 50-series GPU")
        pr.addWidget(b)
    header = W.PageHeader(3, 7, "Choose your mods", "Core is picked for your GTX 1070. Tick what you want; cards "
                          "that can't run on your game build are greyed out with the reason.", prof)
    body = QWidget()
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(12)
    chips = QHBoxLayout()
    chips.setSpacing(6)
    for i, c in enumerate(("All", "Framework", "Fixes", "Driving", "HUD", "Tools", "World")):
        b = W.button(c, "secondary" if i == 0 else "ghost")
        chips.addWidget(b)
    chips.addStretch()
    search = QLineEdit()
    search.setPlaceholderText("Search mods")
    search.setFixedWidth(220)
    chips.addWidget(search)
    bl.addLayout(chips)
    grid = QGridLayout()
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(14)
    ids = ["hud-geckomacabre", "mapfixes", "menyoo", "hud-fbicat", "drivev", "lwe"]
    statuses = {"menyoo": "ready", "hud-geckomacabre": "ready", "mapfixes": "missing", "drivev": "downloading",
                "hud-fbicat": "manual", "lwe": "paid"}
    slot_group = QButtonGroup(body)
    for i, mid in enumerate(ids):
        mod = m.mod(mid)
        mode = "radio" if mod.slot == "hud" else "toggle"
        c = W.ModCard(mod, build=BUILD, selected=mid not in ("hud-fbicat", "lwe"), mode=mode,
                      status=statuses.get(mid))
        if mid == "drivev":
            c.set_status("downloading", percent=62)
        if mode == "radio":
            slot_group.addButton(c.selector)
        grid.addWidget(c, i // 3, i % 3)
    gw = W.clear_background(QWidget())
    gw.setLayout(grid)
    scroll = QScrollArea()
    scroll.setWidget(gw)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    bl.addWidget(scroll, 1)
    sel = core_mods(m)
    summary = lab(f"{len(sel)} mods selected · 4 download automatically · 6 open in Leonida's browser · "
                  "HUD slot: GTA VI-Inspired HUD", "caption")
    actions = W.ActionBar(left=[summary], right=[W.button("Back", "secondary"),
                                                 W.button("Next: get mods  →", "primary", glow=True)])
    return shell(2, header, body, actions)


def page_get(m) -> QWidget:
    overall = QWidget()
    ol = QVBoxLayout(overall)
    ol.setContentsMargins(0, 0, 0, 0)
    ol.setSpacing(4)
    ol.addWidget(lab("9 of 15 ready", "caption"), 0, Qt.AlignmentFlag.AlignRight)
    bar = QProgressBar()
    bar.setRange(0, 15)
    bar.setValue(9)
    bar.setTextVisible(False)
    bar.setFixedWidth(260)
    ol.addWidget(bar)
    header = W.PageHeader(4, 7, "Get the mods", "Leonida downloads what it can from the authors' releases. The rest "
                          "open one by one in its browser: click Download there and the file lands here.", overall)
    body = QWidget()
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(10)
    rows = [
        ("shvdne", "ready", None, "ScriptHookVDotNetEnhanced-v1.1.0.6.zip · 2.6 MB · SHA-256 ok", []),
        ("menyoo", "downloading", 62, "MenyooSP.zip · 4.0 of 6.4 MB · github.com/itsjustcurtis", [W.button("Cancel", "ghost")]),
        ("mapfixes", "missing", None, "Open its page in Leonida's browser and pick '21.8.2 Enhanced' under All Versions.",
         [W.button("Open page", "secondary", icon_name="external")]),
        ("nextgeneuphoria", "manual", None, "Needs a free Nexus Mods account: sign in inside Leonida's browser.",
         [W.button("Open page", "secondary", icon_name="external")]),
        ("allmpvehicles", "wrong", None, "That file is the Legacy edition. Get the one marked Enhanced.",
         [W.button("Retry", "secondary"), W.button("Assign file…", "ghost")]),
    ]
    for mid, kind, pct, detail, acts in rows:
        bl.addWidget(W.QueueRow(m.mod(mid).name, kind, pct, detail, acts))
    bl.addStretch()
    toast = W.Toast()
    toast.show_message("ScriptHookVDotNetEnhanced-v1.1.0.6.zip saved and matched to Script Hook V .NET Enhanced.",
                       "success", "Show", timeout_ms=0)
    actions = W.ActionBar(left=[W.button("Open downloads folder", "ghost", icon_name="external")],
                          right=[W.button("Get the rest in Leonida's browser", "secondary"),
                                 W.button("Download everything", "primary", icon_name="download", glow=True)])
    return shell(3, header, body, actions, toast)


def finding(tone: str, title: str, text: str, fix: str | None) -> QFrame:
    f, lay = card((16, 12, 16, 12), 4)
    f.setProperty("tone", tone)
    top = QHBoxLayout()
    top.setSpacing(10)
    top.addWidget(W._icon_label({"error": "cross", "warning": "warning", "success": "check"}.get(tone, "info"),
                                W.TONE_COLORS[tone], 18))
    top.addWidget(lab(title, "subtitle"), 1)
    if fix:
        top.addWidget(W.button(fix, "secondary"))
    lay.addLayout(top)
    t = lab(text, "caption", wrap=True)
    t.setContentsMargins(28, 0, 0, 0)
    lay.addWidget(t)
    return f


def page_check(m) -> QWidget:
    counts = QWidget()
    cl = QHBoxLayout(counts)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(6)
    for text, tone in (("18 passed", "success"), ("3 warnings", "warning"), ("1 to fix", "error")):
        cl.addWidget(W.Badge(text, tone))
    header = W.PageHeader(5, 7, "Check before installing", "Leonida checked your game, your PC and the mods against "
                          "each other. Fix the red one; the yellow ones are worth a look.", counts)
    body = QWidget()
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(10)
    bl.addWidget(finding("error", "Map Fixes (Enhanced package) isn't downloaded yet",
                         "Bugstar Fixes needs it. Get the file marked '21.8.2 Enhanced' on its page.", "Get it"))
    bl.addWidget(finding("warning", "F8 opens both Menyoo and the HUD settings",
                         "Menyoo and GTA VI-Inspired HUD use the same key. Give Menyoo F10 (menyooConfig.ini).",
                         "Change key…"))
    bl.addWidget(finding("warning", "Game build 1.0.1013.20 isn't a tested build",
                         "Tested: 1.0.1158.13. Older versions are picked for NaturalVision Enhanced, OpenRPF and "
                         "Script Hook V .NET; after installing, Check my mods reads their logs.", None))
    bl.addWidget(finding("warning", "Resource Extensions with a changed gameconfig.xml",
                         "The HUD raises five pool limits in gameconfig.xml. Test story mode right after the HUD step.",
                         None))
    bl.addWidget(finding("success", "18 more checks passed",
                         "Prerequisites, free disk space, slots, conflicts, archive editions, story-mode only.", "Show"))
    bl.addStretch()
    actions = W.ActionBar(left=[W.button("Re-run checks", "ghost", icon_name="shield")],
                          right=[W.button("Back", "secondary"), W.button("Next: install  →", "primary", glow=True)])
    return shell(4, header, body, actions)


def page_install(m) -> QWidget:
    header = W.PageHeader(6, 7, "Install, one step at a time", "Each step is logged and can be undone. After the "
                          "big ones, start story mode once and tell Leonida if it worked.")
    body = QWidget()
    bl = QHBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(24)
    steps = [
        (m.mod("scripthookv").name, "copy · 3 files", "done", "ok"),
        (m.mod("shvdne").name, "copy · 5 files · scripts folder", "done", "ok"),
        (m.mod("openrpf").name, "copy · OpenRPF.asi", "done", None),
        (m.mod("resourceextensions").name, "copy · 2 files", "done", "not-seen"),
        (m.mod("mapfixes").name, "pack + dlclist.xml + MP Map Fixes.oiv into mods\\", "current", None),
        (m.mod("bugstarfixes").name, "pack + Enhanced Update RPF Content.oiv", "pending", None),
        (m.mod("menyoo").name, "copy · Menyoo.asi + menyooStuff", "pending", None),
        (m.mod("hud-geckomacabre").name, ".oiv · scripts, packs, update.rpf", "pending", None),
    ]
    st, sl = card((16, 8, 16, 8), 0)
    sl.addWidget(W.Stepper(steps))
    sl.addStretch()
    st.setFixedWidth(430)
    bl.addWidget(st)
    right = QVBoxLayout()
    right.setSpacing(14)
    cur, cl = card((18, 16, 18, 16), 8)
    cur.setProperty("selected", True)
    cl.addWidget(lab("STEP 5 · IN PROGRESS", "eyebrow"))
    cl.addWidget(lab(m.mod("mapfixes").name, "title"))
    cl.addWidget(lab("Copying update\\x64\\dlcpacks\\mpHeist\\dlc.rpf into mods (2.3 GB) · archive 6 of 14",
                     "caption", wrap=True))
    bar = QProgressBar()
    bar.setProperty("thick", True)
    bar.setRange(0, 100)
    bar.setValue(43)
    bar.setFormat("43%")
    cl.addWidget(bar)
    cl.addWidget(lab("Every archive is a copy in mods\\: your game's own files are never changed.", "caption"))
    right.addWidget(cur)
    test, tl = card((18, 16, 18, 16), 8)
    test.setProperty("tone", "success")
    top = QHBoxLayout()
    top.addWidget(W._icon_label("play", C_SUCCESS, 18))
    top.addWidget(lab("Play test after Resource Extensions", "subtitle"), 1)
    top.addWidget(W.StatusPill("not-seen", "log"))
    tl.addLayout(top)
    tl.addWidget(lab("Start story mode once, drive around for a minute, quit. Leonida then reads the mods' logs.",
                     "muted", wrap=True))
    row = QHBoxLayout()
    row.addWidget(W.button("Launch game", "secondary", icon_name="play"))
    row.addWidget(W.button("It works", "secondary", icon_name="check"))
    row.addWidget(W.button("Undo this step", "danger"))
    row.addStretch()
    tl.addLayout(row)
    right.addWidget(test)
    right.addStretch()
    rw = QWidget()
    rw.setLayout(right)
    bl.addWidget(rw, 1)
    actions = W.ActionBar(left=[W.button("Pause", "ghost")],
                          right=[W.button("Back", "secondary"), W.button("Install step 6  →", "primary", glow=True)])
    return shell(5, header, body, actions)


def installed_row(name: str, version: str, step: int, kind: str, detail: str = "") -> QFrame:
    f = QFrame()
    f.setProperty("card", True)
    lay = QHBoxLayout(f)
    lay.setContentsMargins(14, 8, 10, 8)
    lay.setSpacing(12)
    lay.addWidget(lab(f"{step:>2}", "caption"))
    col = QVBoxLayout()
    col.setSpacing(0)
    col.addWidget(lab(name, "subtitle"))
    col.addWidget(lab(version, "caption"))
    lay.addLayout(col, 1)
    lay.addWidget(W.StatusPill(kind, detail))
    lay.addWidget(W.button("Undo", "ghost"))
    return f


def page_manage(m) -> QWidget:
    header = W.PageHeader(7, 7, "Manage", "Everything Leonida installed, what the game's logs say about it, updates, "
                          "and the Online-safe switch.")
    body = QWidget()
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(14)
    cards = QHBoxLayout()
    cards.setSpacing(14)
    a, al = card()
    al.addWidget(lab("STATUS", "eyebrow"))
    al.addWidget(lab("14 mods installed", "subtitle"))
    al.addWidget(W.StatusPill("ok", "12 of 14"))
    al.addWidget(lab(f"Game {BUILD} · last check 10 min ago", "caption"))
    b, blay = card()
    blay.addWidget(lab("ONLINE-SAFE", "eyebrow"))
    blay.addWidget(lab("Mods are on", "subtitle"))
    blay.addWidget(lab("Before GTA Online: move every mod out (23 files).", "caption", wrap=True))
    blay.addWidget(W.button("Go online-safe", "secondary", icon_name="shield"))
    c, clay = card()
    clay.addWidget(lab("LEONIDA", "eyebrow"))
    clay.addWidget(lab(f"{__version__} · update ready", "subtitle"))
    clay.addWidget(lab("1.0.1 fixes the Get mods progress for big files.", "caption", wrap=True))
    rr = QHBoxLayout()
    rr.addWidget(W.button("Update", "primary", glow=True))
    rr.addWidget(W.button("Force update", "ghost"))
    clay.addLayout(rr)
    for x in (a, b, c):
        cards.addWidget(x, 1)
    bl.addLayout(cards)
    tabs = QTabWidget()
    inst = QWidget()
    il = QVBoxLayout(inst)
    il.setContentsMargins(12, 12, 12, 12)
    il.setSpacing(8)
    for i, (mid, kind, detail) in enumerate((("scripthookv", "ok", "1.0.1013.20"), ("shvdne", "ok", ""),
                                             ("resourceextensions", "not-seen", ""), ("menyoo", "failed", "log line"),
                                             ("hud-geckomacabre", "installed", ""))):
        mod = m.mod(mid)
        il.addWidget(installed_row(mod.name, mod.version, i + 1, kind, detail))
    il.addStretch()
    tabs.addTab(inst, "Installed")
    tabs.addTab(QWidget(), "Log check")
    tabs.addTab(QWidget(), "Mod updates (2)")
    tabs.addTab(QWidget(), "History")
    bl.addWidget(tabs, 1)
    actions = W.ActionBar(left=[W.button("Uninstall everything", "danger")],
                          right=[W.button("Check my mods", "primary", icon_name="shield", glow=True)])
    return shell(6, header, body, actions)


C_SUCCESS = theme.COLORS["success"]


# ------------------------------------------------------------------------------------------- components sheet
def components(m) -> QWidget:
    win = QWidget()
    win.resize(1280, 860)
    lay = QVBoxLayout(win)
    lay.setContentsMargins(32, 24, 32, 24)
    lay.setSpacing(16)
    lay.addWidget(W.PageHeader(None, 7, "Leonida V components", "leonida/gui/widgets.py on the Sunset Emblem theme"))
    row = QHBoxLayout()
    row.setSpacing(16)
    side = W.Sidebar(LOGO, __version__)
    for i, (name, state) in enumerate(zip(PAGES, ("done", "done", "current", "busy", "todo", "locked", "todo"),
                                          strict=True)):
        side.nav.add_step(name, state=state, reason="Run the checks first" if i == 5 else "")
    side.set_game(BUILD, "mods-on", "14 mods")
    side.setFixedHeight(560)
    row.addWidget(side, 0, Qt.AlignmentFlag.AlignTop)
    mid = QVBoxLayout()
    mid.setSpacing(12)
    cards = QHBoxLayout()
    cards.setSpacing(14)
    c1 = W.ModCard(m.mod("hud-geckomacabre"), build=BUILD, mode="radio", status="ready")
    c2 = W.ModCard(m.mod("drivev"), build=BUILD, status="downloading")
    c2.set_status("downloading", percent=62)
    c3 = W.ModCard(m.mod("lwe"), build=BUILD, selected=False, status="paid")
    for c in (c1, c2, c3):
        cards.addWidget(c, 0, Qt.AlignmentFlag.AlignTop)
    cards.addStretch()
    mid.addLayout(cards)
    pills, flow = W.flow_box(8)
    for kind in W.STATUS:
        flow.addWidget(W.StatusPill(kind, percent=42 if kind == "downloading" else None))
    mid.addWidget(pills)
    btns = QHBoxLayout()
    for text, var in (("Primary", "primary"), ("Secondary", "secondary"), ("Ghost", "ghost"), ("Danger", "danger")):
        btns.addWidget(W.button(text, var, glow=var == "primary"))
    dis = W.button("Disabled", "secondary")
    dis.setEnabled(False)
    btns.addWidget(dis)
    btns.addStretch()
    icons = QHBoxLayout()
    icons.setSpacing(10)
    for name in W.ICONS:
        icons.addWidget(W._icon_label(name, theme.COLORS["text_muted"], 20))
    btns.addLayout(icons)
    mid.addLayout(btns)
    row.addLayout(mid, 1)
    lay.addLayout(row)
    low = QHBoxLayout()
    low.setSpacing(16)
    st, sl = card((14, 6, 14, 6), 0)
    sl.addWidget(W.Stepper([("Script Hook V", "copy · 3 files", "done", "ok"),
                            ("Map Fixes", "pack + .oiv into mods", "current", None),
                            ("Menyoo 2.0", "copy", "failed", "failed"),
                            ("GTA VI-Inspired HUD", ".oiv", "pending", None)]))
    st.setFixedWidth(400)
    low.addWidget(st, 0, Qt.AlignmentFlag.AlignTop)
    q = QVBoxLayout()
    q.addWidget(W.QueueRow("Menyoo 2.0", "downloading", 62, "4.0 of 6.4 MB", [W.button("Cancel", "ghost")]))
    toast = W.Toast()
    toast.show_message("MenyooSP.zip saved and matched to Menyoo 2.0.", "success", "Show", timeout_ms=0)
    q.addWidget(toast)
    q.addStretch()
    low.addLayout(q, 1)
    empty = W.EmptyState("install", "Nothing installed yet", "Pick your mods and install them step by step.",
                         W.button("Go to Install  →", "primary"))
    empty.setFixedWidth(300)
    low.addWidget(empty)
    lay.addLayout(low)
    return win


RENDER = {"components": components, "welcome": page_welcome, "game": page_game, "choose": page_choose,
          "get": page_get, "check": page_check, "install": page_install, "manage": page_manage}


# ------------------------------------------------------------------------------------------- task 3: new features
PACK_TEXT = {
    "core": ("Leonida Core", "The GTA VI look and feel: one free mod per job, stable, minimal."),
    "core-plus": ("Leonida Plus", "Core plus world life: interiors, combat, Jason Duval's house."),
    "video-setup": ("Leonida Showcase", "The full video-style setup with remastered world and shops. Strong PCs."),
}


def page_modpack(m) -> QWidget:
    header = W.PageHeader(None, 7, "Choose your modpack", "Pick a starting point. You can add or remove add-ons on "
                          "the next page, and switch packs later: Leonida rolls back what isn't in the new one.")
    body = QWidget()
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(16)
    row = QHBoxLayout()
    row.setSpacing(16)
    for pid, (name, tagline) in PACK_TEXT.items():
        mods = m.resolve(pid, [], [], {})
        free = all(not x.is_paid for x in mods)
        card = W.PackCard(pid, name, tagline, mods=len(mods), addons=12 if pid == "core" else 8,
                          badges=[("Free", "success") if free else ("Paid add-ons", "warning"),
                                  ("Strong PC", "warning") if pid == "video-setup" else ("Any GPU", None)],
                          recommended=pid == "core")
        card.set_selected(pid == "core")
        row.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
    row.addStretch()
    bl.addLayout(row)
    own, ol = card_frame()
    top = QHBoxLayout()
    top.addWidget(W._icon_label("mods", theme.COLORS["coral"], 20))
    col = QVBoxLayout()
    col.setSpacing(0)
    col.addWidget(lab("Your own mods", "subtitle"))
    col.addWidget(lab("Add any mod from a file or a page link: it gets the same logged install, rollback and "
                      "online-safe handling.", "caption", wrap=True))
    top.addLayout(col, 1)
    top.addWidget(W.button("Add a mod", "secondary", icon_name="download"))
    ol.addLayout(top)
    bl.addWidget(own)
    bl.addStretch()
    actions = W.ActionBar(right=[W.button("Next: add-ons  →", "primary", glow=True)])
    return shell(2, header, body, actions)


def card_frame() -> tuple[QFrame, QVBoxLayout]:
    return card((16, 12, 16, 12), 6)


class _Result:
    def __init__(self, mod, status, message, line=None):
        self.mod, self.status, self.message, self.line = mod, status, message, line


class _Report:
    status = "failed"
    message = "Story mode loaded in 74 s. One mod failed: Menyoo 2.0."
    notes = ["Straight To Story Mode is installed: the game went straight into story mode."]
    evidence: list = []
    results = [_Result("scripthookv", "ok", "Script Hook V works on this game build: 1.0.1013.20 (Enhanced)."),
               _Result("shvdne", "ok", "Script Hook V .NET Enhanced 1.1.0.6 started."),
               _Result("menyoo", "failed", "Menyoo 2.0 logged an error.", "ERROR - Pattern not found: 48 8B 05"),
               _Result("resourceextensions", "warning", "Resource Extensions: 2 feature groups not fully active.")]


def page_playtest(m) -> QWidget:
    header = W.PageHeader(7, 7, "Play test", "Leonida starts the game the way you do, waits for story mode, reads "
                          "every mod's log and closes the game again.")
    body = QWidget()
    bl = QHBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(18)
    running = W.PlaytestPanel()
    running.start()
    for msg in ("Moved the old logs aside: ScriptHookV.log", "Started PlayGTAV.exe", "GTA5_Enhanced.exe is running",
                "Script Hook V loaded (ScriptHookV.log)"):
        running.on_progress(msg)
    running.timer.stop()
    running.seconds = 41
    running._tick()
    running.timer.start()
    running._render()
    running.timer.stop()
    left = QVBoxLayout()
    left.addWidget(running)
    left.addStretch()
    bl.addLayout(left, 1)
    done = W.PlaytestPanel()
    done.start()
    for msg in ("Started PlayGTAV.exe", "GTA5_Enhanced.exe is running", "Script Hook V loaded (ScriptHookV.log)",
                "Script Hook V .NET started (ScriptHookVDotNet.log)",
                "Story mode loaded ('Loading scripts from' in ScriptHookVDotNet.log)", "Closed the game"):
        done.on_progress(msg)
    done.done.add("close")
    done.done.add("logs")
    done.show_report(_Report())
    right = QVBoxLayout()
    right.setSpacing(14)
    right.addWidget(done)
    right.addWidget(W.DriftWarning([
        ("menyooStuff\\menyooConfig.ini", "open_key", "F10", "F8", "F8 also opens the HUD settings."),
        ("ResourceExtensions.ini", "PedDensity", "1.50", "3.00", "Above 2.00 the game can run out of memory.")]))
    right.addStretch()
    bl.addLayout(right, 1)
    actions = W.ActionBar(left=[W.button("Undo the last step", "danger")],
                          right=[W.button("Play test again", "primary", icon_name="play", glow=True)])
    return shell(6, header, body, actions)


RENDER.update({"modpack": page_modpack, "playtest": page_playtest})


# ------------------------------------------------------------------------------------------- real pages (newpages.py)
def frame(current: int, page: QWidget) -> QWidget:
    """Sidebar + a ready-made page widget (which brings its own header and actions)."""
    win = QWidget()
    win.resize(*SIZE)
    root = QHBoxLayout(win)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    side = W.Sidebar(LOGO, __version__)
    for i, name in enumerate(PAGES):
        side.nav.add_step(name, state="done" if i < current else ("current" if i == current else "todo"))
    side.set_game(BUILD, "mods-off")
    root.addWidget(side)
    holder = QWidget()
    hl = QVBoxLayout(holder)
    hl.setContentsMargins(32, 24, 32, 20)
    hl.addWidget(page)
    root.addWidget(holder, 1)
    return win


def _temp_session():
    import tempfile

    from leonida.session import Session

    return Session(state=Path(tempfile.mkdtemp(prefix="leonida-preview-")), game_build=BUILD)


def live_modpack(m) -> QWidget:
    from leonida.gui.newpages import ModpackPage

    return frame(2, ModpackPage(_temp_session(), gpus=["NVIDIA GeForce GTX 1070"]))


def live_playtest(m) -> QWidget:
    from leonida.gui.newpages import PlaytestView

    view = PlaytestView(_temp_session())
    view.panel.start()
    for msg in ("Started PlayGTAV.exe", "GTA5_Enhanced.exe is running", "Script Hook V loaded (ScriptHookV.log)",
                "Script Hook V .NET started (ScriptHookVDotNet.log)"):
        view.panel.on_progress(msg)
    view.panel.timer.stop()
    view.panel.seconds = 63
    view.panel._tick()
    view.panel.timer.start()
    view.panel._render()
    view.panel.timer.stop()
    page = QWidget()
    pl = QVBoxLayout(page)
    pl.setContentsMargins(0, 0, 0, 0)
    pl.setSpacing(16)
    pl.addWidget(W.PageHeader(7, 7, "Play test", "Leonida starts the game the way you do, waits for story mode, "
                              "reads every mod's log and closes the game again."))
    pl.addWidget(view)
    pl.addStretch()
    return frame(6, page)


RENDER.update({"live-modpack": live_modpack, "live-playtest": live_playtest})


# ------------------------------------------------------------------------------------------- the real app (after)
def render_after(out: Path) -> list[Path]:
    """Screens of the real MainWindow (temp state + a stub game folder; no network, nothing installed)."""
    import os
    import tempfile

    from leonida.gui import app as A
    from leonida.session import Session

    os.environ.setdefault("LEONIDA_NO_NET", "1")
    os.environ.setdefault("LEONIDA_NO_OPEN", "1")
    os.environ.setdefault("LEONIDA_NO_UPDATE_CHECK", "1")
    qapp = QApplication.instance() or QApplication(sys.argv)
    theme.apply_theme(qapp)
    tmp = Path(tempfile.mkdtemp(prefix="leonida-after-"))
    game = tmp / "Grand Theft Auto V Enhanced"
    game.mkdir()
    (game / "GTA5_Enhanced.exe").write_bytes(b"MZ stub")
    (game / "PlayGTAV.exe").write_bytes(b"MZ stub")
    session = Session(state=tmp / "State", download_dir=str(tmp / "Downloads"), game_dir=str(game),
                      game_build=BUILD)
    win = A.MainWindow(session)
    win.resize(*SIZE)
    win.show()
    qapp.processEvents()
    out.mkdir(parents=True, exist_ok=True)
    shots = [("welcome", 0, None), ("game", 1, None), ("choose-packs", 2, 0), ("choose", 2, 1), ("get", 3, None),
             ("check", 4, None), ("install", 5, None), ("manage", 6, None)]
    saved = []
    for name, index, view in shots:
        win.go(index)
        if view is not None:
            win.pages[2].views.setCurrentIndex(view)
        for _ in range(3):
            qapp.processEvents()
        path = out / f"after-{name}.png"
        win.grab().save(str(path))
        saved.append(path)
    win.close()
    win.deleteLater()
    return saved


def render(names: list[str], out: Path) -> list[Path]:
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply_theme(app)
    m = load_manifest().for_build(BUILD)
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    for name in names:
        win = RENDER[name](m)
        win.show()
        app.processEvents()
        path = out / (f"{name}.png" if name == "components" else f"page-{name}.png")
        win.grab().save(str(path))
        win.close()
        win.deleteLater()
        saved.append(path)
    return saved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "design")
    ap.add_argument("--only", help="comma-separated: " + ",".join(RENDER))
    ap.add_argument("--after", action="store_true", help="screens of the real app: docs/design/after-*.png")
    args = ap.parse_args()
    if args.after:
        for p in render_after(args.out):
            print("saved", p)
        return 0
    names = args.only.split(",") if args.only else list(RENDER)
    for p in render(names, args.out):
        print("saved", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
