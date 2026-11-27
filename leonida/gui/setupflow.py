"""The first-run setup ("Initialize"): Welcome -> your game -> what Windows needs -> your modpack -> download ->
install -> play test -> done, then the library with Play.

Every step can be skipped; where the person is is saved in ``<state>/setup.json`` (leonida/firstrun.py), so closing
Leonida half-way opens the setup at that step next time. Settings > "Run setup again" starts it over. Long work
(finding the game, installing) runs on worker threads; downloads use the Get mods page's own machinery.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import PACK_NAME
from .. import firstrun as FR
from . import widgets as W


def suggestion(session, pack) -> tuple[str | None, str]:
    """The variant ``gamesettings.suggest_variant`` recommends for this PC, and why in one sentence ("" without a
    recommendation: the PC couldn't be read, or the pack's variants aren't sized by RAM or graphics card)."""
    from ..gamesettings import suggest_variant

    if pack is None or not getattr(pack, "variants", ()):
        return None, ""
    try:
        pc = session.pc_specs()
    except Exception:  # noqa: BLE001 - no recommendation rather than a broken page
        return None, ""
    vid = suggest_variant(pack, pc)
    v = pack.variant(vid) if vid else None
    if v is None:
        return None, ""
    card = pc.gpus[0] if pc.gpus else "your graphics card"
    if vid.startswith("ram") and pc.ram_gb is not None:
        why = f"{pc.ram_gb:.0f} GB of RAM"
    elif pc.vram_gb is not None:
        why = f"{card}, {pc.vram_gb:.0f} GB of video memory" + (", ray tracing" if vid == "ultra" else "")
    else:
        why = card
    return vid, f"Recommended for this PC ({why}): {v.name}."


TITLES = {
    "welcome": ("Welcome to Leonida V", "Six short steps to a GTA VI-style story mode. Skip any step and come back "
                                        "later: Settings > Run setup again."),
    "game": ("Find your GTA V", "Leonida looks in Steam, Epic, the Rockstar launcher and the usual folders."),
    "prereqs": ("What Windows needs", "Script mods need these. Missing ones come from their makers' own pages."),
    "pack": ("Choose your modpack", "The recommended pack is the set the owner plays and tests. You can change it "
                                    "any time on My modpack."),
    "download": ("Download the mods", "From each author's own page: automatic where they publish a direct file, "
                                      "otherwise in Leonida's browser."),
    "install": ("Install", "One mod after another, every file logged so it can be undone."),
    "playtest": ("Play test", "Start story mode once: Leonida waits for it and reads the mods' logs."),
    "done": ("You're set", "Your modpack is ready. Play starts story mode."),
}


def _box(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("card", True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)
    if title:
        lay.addWidget(W._label(title, "eyebrow"))
    return f, lay


class SetupFlow(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.step = 0
        self.launched: list[list[str]] = []      # winget commands started (tests read this)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.eyebrow = W._label("", "eyebrow")
        self.title = W._label("", "title", wrap=True)
        self.text = W._label("", "muted", wrap=True)
        for w in (self.eyebrow, self.title, self.text):
            lay.addWidget(w)
        self.dots_holder, self.dots = W.flow_box(6)
        lay.addWidget(self.dots_holder)
        self.body_holder = QWidget()
        self.body = QVBoxLayout(W.clear_background(self.body_holder))
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(12)
        sc = QScrollArea()
        sc.setWidget(self.body_holder)
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(sc, 1)
        row = QHBoxLayout()
        self.leave_btn = W.button("Finish setup later", "ghost", self.leave)
        self.back_btn = W.button("Back", "ghost", lambda: self.goto(self.step - 1))
        self.skip_btn = W.button("Skip this step", "secondary", self.skip)
        self.next_btn = W.button("Continue", "primary", self.next, glow=True)
        row.addWidget(self.leave_btn)
        row.addStretch()
        for b in (self.back_btn, self.skip_btn, self.next_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.installing = False
        self.auto_install = False                # a ready-made setup: install as soon as everything is downloaded

    # ---- flow
    @property
    def name(self) -> str:
        return FR.STEPS[self.step]

    def begin(self, step: int = 0, fresh: bool = False) -> None:
        s = self.win.session
        data = FR.start(s.state) if fresh or not FR.load(s.state) else FR.load(s.state)
        data["dismissed"] = False
        FR.save(s.state, data)
        self.win.stack.setCurrentWidget(self)
        for b in (self.win.back, self.win.fwd):
            b.hide()
        for nav in (self.win.nav, self.win.home_nav, self.win.foot_nav):  # no page of the sidebar is "current"
            nav.blockSignals(True)
            nav.clearSelection()
            nav.setCurrentRow(-1)
            nav.blockSignals(False)
            for r in range(nav.count()):
                nav.set_state(r, "todo")
        self.goto(step)

    def _save(self, **kw) -> None:
        state = self.win.session.state
        data = FR.load(state) or FR.start(state)
        data.update(step=self.step, **kw)
        FR.save(state, data)

    def goto(self, i: int) -> None:
        self.step = max(0, min(i, len(FR.STEPS) - 1))
        self._save()
        title, text = TITLES[self.name]
        self.eyebrow.setText(f"SETUP · STEP {self.step + 1} OF {len(FR.STEPS)}")
        self.title.setText(title)
        self.text.setText(text)
        self._dots()
        from .app import _clear

        _clear(self.body)
        getattr(self, f"_page_{self.name}")()
        self.body.addStretch()
        self.back_btn.setVisible(self.step > 0)
        self.skip_btn.setVisible(self.name not in ("welcome", "done"))
        self.next_btn.setText({"welcome": "Start", "done": "Go to my modpack"}.get(self.name, "Continue"))
        if self.name in ("download", "install"):
            self.timer.start()
        else:
            self.timer.stop()

    def _dots(self) -> None:
        from .app import _clear

        _clear(self.dots)
        skipped = set(FR.load(self.win.session.state).get("skipped", []))
        for i, n in enumerate(FR.STEPS[1:-1], 1):
            tone = "info" if i == self.step else ("warning" if n in skipped else ("success" if i < self.step else None))
            self.dots.addWidget(W.Badge(f"{i}. {TITLES[n][0]}", tone))

    def next(self) -> None:
        if self.name == "pack" and not self._apply_pack():
            return
        if self.name == "done":
            self.finish()
            return
        self.goto(self.step + 1)

    def skip(self) -> None:
        data = FR.load(self.win.session.state)
        skipped = list(dict.fromkeys([*data.get("skipped", []), self.name]))
        self._save(skipped=skipped)
        self.goto(self.step + 1)

    def leave(self) -> None:
        """Out of the setup for now; Settings > Run setup again comes back to this step."""
        self._save(dismissed=True)
        self.timer.stop()
        self.auto_install = False
        self.win.notify("Setup paused: Settings > Run setup again continues where you left off.", "info")
        self.win.show_home("pack" if self.win.returning() else "browse")

    def finish(self) -> None:
        self._save(finished=True)
        self.timer.stop()
        self.win.set_setup_open(False)
        self.win.show_home("pack")

    # ---- the steps
    def _page_welcome(self) -> None:
        f, lay = _box()
        for line in ("1. Find your GTA V and check its version.",
                     "2. Check what Windows needs for script mods.",
                     "3. Choose a modpack (the recommended one fits most PCs).",
                     "4. Download the mods from their authors.",
                     "5. Install them, one logged step at a time.",
                     "6. A short play test in story mode."):
            lay.addWidget(W._label(line, None, wrap=True))
        lay.addWidget(W._label("Story mode only: never use these mods in GTA Online.", "caption", "warning"))
        self.body.addWidget(f)

    # game
    def _page_game(self) -> None:
        f, lay = _box("YOUR GAME")
        self.game_now = W._label("", "subtitle", wrap=True)
        lay.addWidget(self.game_now)
        self.found_box = QVBoxLayout()
        lay.addLayout(self.found_box)
        row = QHBoxLayout()
        self.detect_btn = W.button("Look again", "secondary", lambda: self.detect(said=True), "game")
        row.addWidget(self.detect_btn)
        row.addWidget(W.button("Pick the folder…", "ghost", self.pick_folder))
        row.addStretch()
        lay.addLayout(row)
        self.body.addWidget(f)
        self._show_game()
        self.detect()

    def _show_game(self) -> None:
        s = self.win.session
        g = s.game_dir()
        if g and g.is_dir():
            ed = {"enhanced": "GTA V Enhanced", "legacy": "GTA V Legacy"}.get(s.game_edition or "", "GTA V")
            self.game_now.setText(f"Using: {g}  ·  {ed} {s.game_version() or '(build unknown)'}  ·  "
                                  f"{self._support(s.game_version(), s.base_manifest)}")
        else:
            self.game_now.setText("No game folder yet.")

    @staticmethod
    def _support(build: str | None, manifest) -> str:
        if not build:
            return "build unknown"
        return "tested build ✓" if build in manifest.tested_builds else "not a tested build (mods may still work)"

    def detect(self, said: bool = False) -> None:
        from ..detect import ALL_EXES, detect_games
        from .workers import start_worker

        self.detect_btn.setEnabled(False)
        self.detect_btn.setText("Looking…")
        self._said = said
        start_worker(self, lambda: detect_games(ALL_EXES), on_done=self._found,
                     on_fail=lambda msg: self._found([]))

    def _found(self, games) -> None:
        from shiboken6 import isValid

        if not isValid(self.detect_btn) or self.name != "game":
            return
        from .app import _clear

        self.detect_btn.setEnabled(True)
        self.detect_btn.setText("Look again")
        _clear(self.found_box)
        self.found = list(games)
        if not games:
            self.found_box.addWidget(W._label("Not found automatically: use Pick the folder…", "caption"))
        s = self.win.session
        for g in games:
            row = QHBoxLayout()
            ed = getattr(g, "edition_name", "GTA V")
            try:
                manifest = s.manifest_for(g.edition) if g.edition else s.base_manifest
            except Exception:  # noqa: BLE001
                manifest = s.base_manifest
            row.addWidget(W._label(f"{g.path}  ·  {ed} {g.version or ''}  ·  {self._support(g.version, manifest)}",
                                   None, wrap=True), 1)
            row.addWidget(W.button("Use this", "secondary", lambda _=False, d=str(g.path): self.use_dir(d)))
            self.found_box.addLayout(row)
        if getattr(self, "_said", False):  # "Look again": say what it found, even when it's the same
            self.win.notify(f"Looked again: {len(games)} GTA V folder(s) found.", "info")
        if games and not s.game_dir():
            self.use_dir(str(games[0].path))

    def pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "GTA V folder (Enhanced or Legacy)")
        if d:
            self.use_dir(d)

    def use_dir(self, d: str) -> None:
        self.win.pages[1].set_dir(d)       # the Game page checks the exe, saves it, switches edition
        self._show_game()
        self.win.statusBar().showMessage(f"Game folder: {self.win.session.config.game_dir or 'not set'}", 8000)

    # prerequisites
    def _page_prereqs(self) -> None:
        s = self.win.session
        f, lay = _box("THIS PC")
        have = dict(s.prerequisites())
        have["7zip"] = bool(s.seven_zip())
        winget = shutil.which("winget")
        self.prereq_rows: dict[str, bool | None] = {}
        for key, (name, page, wid) in FR.PREREQS.items():
            ok = have.get(key)
            self.prereq_rows[key] = ok
            row = QHBoxLayout()
            row.addWidget(W.StatusPill("ready" if ok else ("failed" if ok is False else "not-seen")))
            row.addWidget(W._label(name + ("" if ok else (" is missing" if ok is False else ": can't tell")), None),
                          1)
            if not ok:
                row.addWidget(W.button("Open its download page", "ghost", lambda _=False, u=page: self._open(u),
                                       "external"))
                if wid and winget:
                    row.addWidget(W.button("Install with winget", "secondary",
                                           lambda _=False, i=wid: self.winget(i)))
            lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(W.button("Check again", "secondary", self.recheck))
        row.addStretch()
        lay.addLayout(row)
        self.body.addWidget(f)

    def _open(self, url: str) -> None:
        from .app import _open

        _open(url)
        self.win.notify(f"Opened {url} in your browser.", "info")

    def winget(self, package: str) -> None:
        """winget in a console window the person can see (it asks there before it installs anything)."""
        cmd = ["winget", "install", "--id", package, "-e"]
        self.launched.append(cmd)
        if not os.environ.get("LEONIDA_NO_OPEN"):
            subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        self.win.notify(f"winget is installing {package} in its own window: Check again when it's done.", "info")

    def recheck(self) -> None:
        self.win.session.__dict__.pop("_pc_cache", None)
        self.goto(self.step)
        self.win.statusBar().showMessage("Checked this PC again.", 8000)

    # pack
    def _page_pack(self) -> None:
        from ..playinfo import gpu_note
        from .launcher import summary_of

        s = self.win.session
        base = s.base_manifest
        rec = FR.recommended_pack(base)
        current = s.pack_choice().pack if (s.state / "pack.json").is_file() else rec
        from . import setupspage

        sf, sl = _box("READY-MADE SETUPS · ONE CLICK")
        sl.addWidget(W._label("A pack with its variant and add-ons, tested together. Leonida downloads and installs it "
                              "next. Or pick a modpack yourself below.", "caption", wrap=True))
        self.setup_cards = setupspage.fill(self.win, sl, self._use_setup, compact=True)
        self.body.addWidget(sf)
        self.body.addWidget(W._label("OR CHOOSE A MODPACK", "eyebrow"))
        self.pack_group = QButtonGroup(self)
        self.pack_radios: dict[str, QRadioButton] = {}
        try:
            gpus = s.gpus()
        except Exception:  # noqa: BLE001
            gpus = []
        for pid, pack in base.packs.items():
            f, lay = _box()
            top = QHBoxLayout()
            rb = QRadioButton(pack.name)
            rb.setChecked(pid == current)
            self.pack_group.addButton(rb)
            self.pack_radios[pid] = rb
            top.addWidget(rb, 1)
            if pid == rec:
                top.addWidget(W.Badge("Recommended", "success"))
            note = gpu_note((pack.requires or {}).get("gpu"), gpus)
            if note:
                top.addWidget(W.Badge(note, "warning"))
                rb.setEnabled(pid == current)
            lay.addLayout(top)
            lay.addWidget(W._label(summary_of(pack.description, 220), "caption", wrap=True))
            rb.toggled.connect(lambda on, p=pid: on and self._variants_for(p))
            self.body.addWidget(f)
        vf, vl = _box("VARIANT")
        self.variant = QComboBox()
        self.variant_note = W._label("", "caption", wrap=True)
        vl.addWidget(self.variant)
        vl.addWidget(self.variant_note)
        self.body.addWidget(vf)
        self._variants_for(current)

    def _use_setup(self, setup_id: str) -> bool:
        """A setup card in the modpack step: choose it, then straight on to downloading (and installing)."""
        from . import setupspage

        if not setupspage.choose(self.win, setup_id):
            return False
        self.run_setup()
        return True

    def run_setup(self) -> None:
        """Download everything the chosen setup needs, then install it (Use this setup in Browse > Setups)."""
        self.auto_install = True
        self.begin(FR.STEPS.index("download"))
        ready, missing, _m = self._todo()
        if missing:
            self.download()
        else:
            self._auto_install()

    def _auto_install(self) -> None:
        self.auto_install = False
        self.goto(FR.STEPS.index("install"))
        if self._todo()[0]:
            self.install_all()

    def chosen_pack(self) -> str | None:
        return next((p for p, rb in self.pack_radios.items() if rb.isChecked()), None)

    def _variants_for(self, pid: str | None) -> None:
        s = self.win.session
        pack = s.base_manifest.packs.get(pid) if pid else None
        self.variant.clear()
        if pack is None or not pack.variants:
            self.variant.addItem("This pack has one setup")
            self.variant.setEnabled(False)
            self.variant_note.setText("")
            return
        pick, why = suggestion(s, pack)          # gamesettings.suggest_variant: RAM, video memory, RTX
        if pick is None:                          # the PC couldn't be read: the RAM alone, if it names RAM sizes
            ram = FR.total_ram_gb()
            pick = FR.variant_for_ram(pack.variants, ram)
            why = f"Picked for your {ram:.0f} GB of RAM." if pick and ram else ""
        saved = s.pack_choice().variant if s.pack_choice().pack == pid else None
        chosen = saved or pick or (pack.variant(None).id if pack.variant(None) else pack.variants[0].id)
        for v in pack.variants:
            self.variant.addItem(v.name, v.id)
        self.variant.setCurrentIndex(max(0, self.variant.findData(chosen)))
        self.variant.setEnabled(True)
        self.variant_note.setText(why if pick and chosen == pick and why
                                  else (pack.variant(chosen).description if pack.variant(chosen) else ""))

    def _apply_pack(self) -> bool:
        pid = self.chosen_pack()
        if pid is None:
            QMessageBox.information(self, PACK_NAME, "Choose a modpack first, or Skip this step.")
            return False
        variant = self.variant.currentData() if self.variant.isEnabled() else None
        s = self.win.session
        if s.pack_choice().pack == pid and (s.state / "pack.json").is_file():
            if variant and variant != s.pack_choice().variant:
                self.win.pages[2].pick_variant(variant)
            return True
        return bool(self.win.pages[2].switch(pid, None, variant))

    # download
    def _page_download(self) -> None:
        f, lay = _box("DOWNLOADS")
        self.dl_state = W._label("", "subtitle", wrap=True)
        self.dl_missing = W._label("", "caption", wrap=True)
        lay.addWidget(self.dl_state)
        lay.addWidget(self.dl_missing)
        row = QHBoxLayout()
        self.dl_btn = W.button("Download everything", "primary", self.download, "download")
        row.addWidget(self.dl_btn)
        row.addWidget(W.button("Open the Get mods page", "ghost", lambda: self.win.go(3)))
        row.addStretch()
        lay.addLayout(row)
        self.body.addWidget(f)
        self._tick()

    def download(self) -> None:
        get = self.win.pages[3]
        get.refresh(force=True)
        get.download_everything()
        self.win.notify("Downloading: Leonida's browser opens the authors' pages that need your click.", "info")
        self._tick()

    def _tick(self) -> None:
        from shiboken6 import isValid

        if self.name == "download" and isValid(getattr(self, "dl_state", None)):
            get = self.win.pages[3]
            if getattr(get, "result", None) is None or not get.isVisible():
                get.refresh()
            mods, res = getattr(get, "mods", []), getattr(get, "result", None)
            missing = res.missing(mods) if res is not None else []
            busy = getattr(get, "busy", {}) or {}
            self.dl_state.setText(f"{len(mods) - len(missing)} of {len(mods)} files ready"
                                  + (f" · downloading {len(busy)}" if busy else ""))
            self.dl_missing.setText("Still needed: " + ", ".join(m.name for m in missing[:8])
                                    + (f" and {len(missing) - 8} more" if len(missing) > 8 else "")
                                    if missing else "Everything is downloaded.")
            self.dl_btn.setEnabled(bool(missing) and not busy and getattr(get, "autodl", None) is None)
            if self.auto_install and not missing and not busy and getattr(get, "autodl", None) is None:
                self._auto_install()
        elif self.name == "install" and isValid(getattr(self, "inst_state", None)):
            self._install_state()

    # install
    def _page_install(self) -> None:
        f, lay = _box("INSTALL")
        self.inst_state = W._label("", "subtitle", wrap=True)
        lay.addWidget(self.inst_state)
        row = QHBoxLayout()
        self.inst_btn = W.button("Install everything downloaded", "primary", self.install_all, "install")
        row.addWidget(self.inst_btn)
        row.addStretch()
        lay.addLayout(row)
        self.inst_log = QPlainTextEdit()
        self.inst_log.setReadOnly(True)
        self.inst_log.setProperty("log", True)
        self.inst_log.setMinimumHeight(200)
        lay.addWidget(self.inst_log)
        self.body.addWidget(f)
        self._install_state()

    def _todo(self):
        s = self.win.session
        done = s.log.installed_mods()
        matched = s.matches().matched
        todo = [m for m in s.mods() if m.id not in done]
        return [m for m in todo if m.id in matched], [m for m in todo if m.id not in matched], matched

    def _install_state(self) -> None:
        if self.installing:
            return
        ready, missing, _m = self._todo()
        s = self.win.session
        n = len(s.log.installed_mods() & {m.id for m in s.mods()})
        self.inst_state.setText(f"{n} of {len(s.mods())} mods installed · {len(ready)} ready to install"
                                + (f" · {len(missing)} not downloaded" if missing else ""))
        self.inst_btn.setEnabled(bool(ready) and bool(s.game_dir()))

    def install_all(self) -> None:
        from .app import GuiUI
        from .workers import start_worker

        ready, _missing, matched = self._todo()
        if not ready:
            return
        s = self.win.session
        ui = GuiUI(self, self.inst_log, self.win.caller)
        inst = s.installer(ui)
        self.installing = True
        self.inst_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.win.pages[5]._running = True          # the bottom bar says "Installing…"

        def work(emit):
            done = []
            for i, m in enumerate(ready, 1):
                emit((i, len(ready), m.name))
                step = inst.install(m, matched[m.id])
                done.append((m.name, step.id if step else None))
            return done

        def progress(p) -> None:
            i, n, name = p
            self.inst_state.setText(f"Installing {i} of {n}: {name}…")

        def finished(done) -> None:
            self._installed_end()
            self.inst_log.appendPlainText(f"Installed {len(done)} mod(s).")
            self.win.notify(f"Setup installed {len(done)} mod(s).", "success")

        def failed(msg: str) -> None:
            self._installed_end()
            self.inst_log.appendPlainText(f"Stopped: {msg}")
            QMessageBox.warning(self, PACK_NAME, f"Installing stopped: {msg}\n\nThe mods before it stay installed.")

        start_worker(self, work, pass_progress=True, on_progress=progress, on_done=finished, on_fail=failed)

    def _installed_end(self) -> None:
        self.installing = False
        self.win.pages[5]._running = False
        self.next_btn.setEnabled(True)
        self._install_state()
        self.win.update_sidebar(force=True)

    # play test
    def _page_playtest(self) -> None:
        from .newpages import PlaytestView

        f, lay = _box("STORY MODE")
        lay.addWidget(W._label("Leonida starts GTA V, waits for story mode (about two minutes) and checks that every "
                               "mod loaded. Save your game first: it closes GTA V if it's open.", None, wrap=True))
        self.playtest = PlaytestView(self.win.session)
        lay.addWidget(self.playtest)
        self.body.addWidget(f)

    # done
    def _page_done(self) -> None:
        s = self.win.session
        f, lay = _box("YOUR SETUP")
        c = s.pack_choice()
        pack = s.base_manifest.packs.get(c.pack) if c.pack else None
        n = len(s.log.installed_mods() & {m.id for m in s.mods()}) if pack else 0
        g = s.game_dir()
        skipped = FR.load(s.state).get("skipped", [])
        for text in (f"Game: {g if g else 'not set yet'}",
                     f"Modpack: {pack.name if pack else 'not chosen yet'}"
                     + (f" ({pack.variant(c.variant).name})" if pack and pack.variant(c.variant) else ""),
                     f"Installed: {n} of {len(s.mods()) if pack else 0} mods",
                     "Skipped: " + (", ".join(TITLES[k][0] for k in skipped if k in TITLES) or "nothing")):
            lay.addWidget(W._label(text, None, wrap=True))
        self.body.addWidget(f)
        from .launcher import before_play_card

        card = before_play_card(self.win, s.mods()) if pack else None
        if card is not None:
            self.body.addWidget(card)


def show_setup_at_start(win) -> int | None:
    """Open the setup when this is a first start or it was left half-way (not when it was paused on purpose)."""
    if os.environ.get("LEONIDA_NO_SETUP"):
        return None
    state = win.session.state
    data = FR.load(state)
    if data.get("dismissed"):
        return None
    step = FR.should_run(state)
    if step is not None:
        win.setup_flow.begin(step)
    return step


__all__ = ["SetupFlow", "show_setup_at_start"]
