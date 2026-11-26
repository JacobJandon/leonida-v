"""The modpack page's "Paid mods" tab (docs/PAID-MODS.md): buy from the author, save the file in Downloads, then
Leonida checks it in its test place and installs it, logged and undoable like every mod.

The author's page always opens in the person's own default browser, never in Leonida's browser: Leonida never sees
the purchase or the account, never clicks on Patreon or a shop, never keeps a session, and never uses re-uploads.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QMessageBox, QVBoxLayout

from .. import PACK_NAME
from . import widgets as W

STATUS_BADGE = {"not bought": ("Not bought", None), "downloaded": ("Downloaded: ready", "info"),
                "wrong file": ("Wrong file", "error"), "installed": ("Installed", "success")}
NEVER = "Leonida never buys, signs in or uses re-uploads."


class PaidCard(QFrame):
    """One paid mod: its picture, what it is, the price, what changes in the pack, and the next step."""

    def __init__(self, win, row, mod, checked: str = ""):
        super().__init__()
        from .launcher import first_sentence, onoff_button, thumb

        self.win, self.row, self.mod = win, row, mod
        self.setProperty("card", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 14, 12)
        lay.setSpacing(14)
        art = thumb(176, 99, mod.id, mod.layer)
        win.pictures.bind_mod(art, mod)
        lay.addWidget(art, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(W._label(row.name, "subtitle"), 1)
        text, tone = STATUS_BADGE.get(row.status, (row.status, None))
        self.badge = W.Badge(text, tone, row.reason)
        top.addWidget(self.badge)
        col.addLayout(top)
        if row.author:
            col.addWidget(W._label(f"by {row.author} · paid by its creator", "caption"))
        if getattr(mod, "notes", ""):
            col.addWidget(W._label(first_sentence(mod.notes)[0], None, wrap=True))
        if row.gets:
            col.addWidget(W._label(f"You download: {row.gets}", "caption", wrap=True))
        price = " · ".join(x for x in (row.price, f"{row.tier} tier" if row.tier and row.tier not in row.price
                                       else "") if x)
        if price:
            col.addWidget(W._label(f"Price: {price}" + (f"  (checked {checked})" if checked else ""), "caption",
                                   wrap=True))
        change = []
        if row.addons:
            change.append(f"turns on with the add-on '{row.addons[0]}'")
        if row.replaces:
            change.append(f"takes the place of {', '.join(row.replaces)}")
        if change:
            col.addWidget(W._label("In your pack: " + "; ".join(change) + ".", "caption", wrap=True))
        col.addWidget(W._label(f"Game builds: {row.builds}", "caption", wrap=True))
        unsupported = getattr(mod, "unsupported", None)
        if unsupported:
            col.addWidget(W._label(f"Not for your game build: {unsupported}", "caption", "warning", wrap=True))
        if row.status == "wrong file":
            col.addWidget(W._label(f"{row.file}: not the author's package ({row.reason}). Download it again from "
                                   "the author's page.", "caption", "error", wrap=True))
        elif row.status == "downloaded":
            col.addWidget(W._label(f"Your file: {row.file}", "caption"))
        # the next step
        buttons = QHBoxLayout()
        self.buttons: dict[str, object] = {}

        def add(text, fn, variant="secondary", icon=None):
            b = W.button(text, variant, fn, icon)
            buttons.addWidget(b)
            self.buttons[text] = b
            return b

        if row.status == "not bought":
            add("Buy on the author's page", lambda: buy(win, row), "primary", "external")
            add("I've downloaded it", lambda: downloaded_it(win, row, mod), "secondary")
        elif row.status == "downloaded":
            b = add("Check and install", lambda: check_and_install(win, row, mod), "primary", "install")
            if unsupported:
                b.setEnabled(False)
                b.setToolTip(unsupported)
            add("Buy page", lambda: buy(win, row), "ghost", "external")
        elif row.status == "wrong file":
            add("Open Downloads", lambda: _open_downloads(win), "secondary", "external")
            add("Buy page", lambda: buy(win, row), "ghost", "external")
            add("I've downloaded it", lambda: downloaded_it(win, row, mod), "ghost")
        elif row.status == "installed" or mod.id in win.session.config.disabled:
            toggle = onoff_button(win, mod, "disabled" if mod.id in win.session.config.disabled else "installed")
            if toggle is not None:
                buttons.addWidget(toggle)
        buttons.addStretch()
        col.addLayout(buttons)
        if row.status in ("not bought", "wrong file"):
            col.addWidget(W._label(NEVER, "caption"))
        lay.addLayout(col, 1)


def fill(win, lay) -> list[PaidCard]:
    """The tab's contents into ``lay``: a line on how it works, then one card per paid mod."""
    from ..paid import buy_info, paid_list

    s = win.session
    lay.addWidget(W._label("PAID MODS", "eyebrow"))
    lay.addWidget(W._label("Some of the best mods are paid by their creators. Buy one on the author's own page, save "
                           "the file in your Downloads folder, and Leonida checks it in its test place and installs "
                           f"it like every other mod. {NEVER}", "caption", wrap=True))
    try:
        rows = paid_list(s)
    except Exception as exc:  # noqa: BLE001 - a broken entry must not empty the whole page
        lay.addWidget(W._label(f"Couldn't list the paid mods: {exc}", "caption", "warning"))
        return []
    if not rows:
        lay.addWidget(W.EmptyState("mods", "No paid mods for this game", "Every mod in the list is free."))
        return []
    cards = []
    for row in rows:
        mod = s.manifest.mods.get(row.id)
        if mod is None:
            continue
        card = PaidCard(win, row, mod, buy_info(row.id, s.manifest.edition).get("checked", ""))
        lay.addWidget(card)
        cards.append(card)
    return cards


# ---- the buttons
def buy(win, row) -> None:
    """The author's page in the person's own browser (never Leonida's: no purchase or sign-in passes through it)."""
    from .app import _open

    _open(row.buy_url)
    win.notify(f"Opened {row.name}'s page in your browser. Save the file in {win.session.config.downloads()}.",
               "info")


def _open_downloads(win) -> None:
    from .launcher import open_folder

    open_folder(win, "downloads")


def _refresh(win) -> None:
    win.pack_page.refresh(force=True)
    win.update_sidebar(force=True)


def downloaded_it(win, row, mod) -> str | None:
    """Pick the file you downloaded: it's copied into Downloads when it's elsewhere (on a worker: paid mods can be
    gigabytes) and assigned to the mod, so a renamed file is recognised too. Returns the file's name."""
    from .workers import start_worker

    s = win.session
    downloads = s.config.downloads()
    path, _f = QFileDialog.getOpenFileName(win, f"Your {row.name} download", str(downloads),
                                           "Mod files (*.zip *.7z *.rar *.oiv);;All files (*)")
    if not path:
        return None
    src = Path(path)

    def assign() -> None:
        s.config.assignments[src.name] = mod.id
        s.save()
        _refresh(win)
        row_now = next((r for r in _rows(win) if r.id == mod.id), None)
        state = row_now.status if row_now else "?"
        win.notify(f"{src.name}: {STATUS_BADGE.get(state, (state,))[0]} for {row.name}.",
                   "success" if state == "downloaded" else "warning")

    if src.parent.resolve() == Path(downloads).resolve():
        assign()
        return src.name
    target = Path(downloads) / src.name
    if target.exists():
        QMessageBox.warning(win, PACK_NAME, f"{target} exists already: rename one of them first.")
        return None
    win.notify(f"Copying {src.name} into {downloads}…", "info")

    def failed(msg: str) -> None:
        QMessageBox.warning(win, PACK_NAME, f"Couldn't copy {src.name} into Downloads: {msg}")

    start_worker(win, lambda: (Path(downloads).mkdir(parents=True, exist_ok=True), shutil.copy2(src, target)),
                 on_done=lambda _r: assign(), on_fail=failed)
    return src.name


def _rows(win):
    from ..paid import paid_list

    return paid_list(win.session)


def check_and_install(win, row, mod) -> bool:
    """Turn the pack's add-on on (the Choose page's switch asks before anything leaves), scan the file in the test
    place, and install it: the scan and the install on a worker, the install's dialogs on the UI thread."""
    from .app import GuiUI
    from .workers import start_worker

    s = win.session
    if getattr(win.pages[5], "_running", False):
        QMessageBox.information(win, PACK_NAME, "An install is running: wait until it's done.")
        return False
    c = s.pack_choice()
    pid = s.profile_id
    base = s.base_manifest
    addon = next((a for lst in base.addons_for(pid).values() for a in lst if mod.id in a.mods), None) \
        if pid in base.packs else None
    if addon is not None and addon.id not in s.chosen_addons():
        if not win.pages[2].switch(pid, [*s.chosen_addons(), addon.id], c.variant):
            return False
    elif mod.id not in {m.id for m in s.mods()}:
        win.pages[2].toggle(mod.id, True)
    path = s.matches([mod]).matched.get(mod.id)
    if path is None:
        QMessageBox.warning(win, PACK_NAME, f"{row.name}'s file isn't in {s.config.downloads()} any more.")
        return False
    log = win.pages[6].view
    ui = GuiUI(win, log, win.caller)
    inst = s.installer(ui)
    tp = s.test_place()
    game = s.game_dir()
    win.pages[5]._running = True          # the bottom bar says "Installing…"; other installs wait

    def work():
        plan = None
        try:
            plan = inst.plan(mod, path)
        except Exception:  # noqa: BLE001 - the scan works without a plan (it just can't try the install)
            plan = None
        result = tp.scan(path, mod, plan, manifest=s.manifest, game_dir=game, trial=True, move=True)
        if result.blocked:
            return result, None
        return result, inst.install(mod, path)

    def done(out) -> None:
        win.pages[5]._running = False
        result, step = out
        for line in result.lines():
            log.appendPlainText(line)
        if step is None and result.blocked:
            QMessageBox.warning(win, PACK_NAME, f"{row.name}: Leonida's test place refused {path.name}.\n\n"
                                + "\n".join(result.lines()[:6]))
        elif step is not None:
            win.notify(f"{row.name} is installed (step {step.id}), checked in the test place first.", "success")
        _refresh(win)

    def failed(msg: str) -> None:
        win.pages[5]._running = False
        QMessageBox.warning(win, PACK_NAME, f"{row.name} couldn't be installed: {msg}")
        _refresh(win)

    win.notify(f"Checking {path.name} in the test place, then installing {row.name}…", "info")
    start_worker(win, work, on_done=done, on_fail=failed)
    return True


__all__ = ["NEVER", "PaidCard", "buy", "check_and_install", "downloaded_it", "fill"]
