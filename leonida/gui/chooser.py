"""'Choose mods': the modpack picker, then the pack's add-ons by category, its variant, your own mods and a picture
card per mod, grouped by layer, with alternatives side by side."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import PACK_NAME
from ..detect import is_rtx50
from ..manifest import Mod
from ..playinfo import gpu_note
from . import theme
from . import widgets as W

THUMB_W, THUMB_H = 256, 144
COLUMNS = 3
NOTE_CHARS = 140
LOCKED_LAYERS = ("Framework",)  # other mods depend on these, so they can't be unticked
SOURCE_TEXT = {
    "discord": "manual download (Discord)",
    "patreon": "manual download (Patreon)",
    "shop": "manual download (paid shop)",
    "nexus-login": "in-app download (Nexus, free login)",
}


def _note(text: str) -> QLabel:
    lab = QLabel(f"<small style='color:{theme.COLORS['error']}'>{text}</small>")
    lab.setWordWrap(True)
    return lab


def _thumb_style(layer: str) -> str:
    """A sunset gradient per layer for cards without a picture (same hues as widgets.Art)."""
    hue = W.LAYER_HUES.get(layer, 300)
    a = QColor.fromHsv(hue % 360, 150, 255).name()
    b = QColor.fromHsv((hue + 300) % 360, 200, 150).name()
    return (f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a}, stop:1 {b}); color: white; "
            "border-radius: 10px; padding: 0 0 10px 12px;")


def how_text(mod: Mod) -> str:
    if mod.download:
        return "automatic download"
    return SOURCE_TEXT.get(mod.source, "in-app download (author's page)")


class _Thumb(QLabel):
    def __init__(self, card: ModCard):
        super().__init__()
        self.card = card
        self.setFixedSize(THUMB_W, THUMB_H)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.setStyleSheet(_thumb_style(card.mod.layer))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSize(8)
        f.setCapitalization(QFont.Capitalization.AllUppercase)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self.setFont(f)
        self.setText(card.mod.layer)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.full: QPixmap | None = None

    def set_image(self, path: str, pix: QPixmap | None = None) -> None:
        if getattr(self, "_path", None) == path:
            return  # already showing it
        pix = pix if pix is not None else QPixmap(path)
        if pix.isNull():
            return
        self._path = path
        self.full = pix
        self.setStyleSheet("border-radius: 10px;")
        self.setPixmap(pix.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation).copy(0, 0, THUMB_W, THUMB_H))

    def mousePressEvent(self, e) -> None:  # noqa: N802 - Qt naming
        if self.full is not None:
            dlg = QDialog(self)
            dlg.setWindowTitle(self.card.mod.name)
            lay = QVBoxLayout(dlg)
            big = QLabel()
            big.setPixmap(self.full.scaled(1100, 700, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
            lay.addWidget(big)
            dlg.exec()
        super().mousePressEvent(e)


class ModCard(QFrame):
    def __init__(self, page: ChoosePage, mod: Mod, control: QCheckBox | QRadioButton):
        super().__init__()
        self.mod = mod
        self.control = control
        self.setProperty("card", True)
        self.setFixedWidth(THUMB_W + 26)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(7)
        self.thumb = _Thumb(self)
        lay.addWidget(self.thumb)
        lay.addWidget(W._label(mod.name, "subtitle", wrap=True))
        if mod.author:
            lay.addWidget(W._label(mod.author, "caption", wrap=True))
        holder, flow = W.flow_box(6)
        build = page.win.session.game_version()
        for text, tone, tip in W.mod_badges(mod, build)[1:]:  # the tier is clear from the pack / section
            flow.addWidget(W.Badge(text, tone, tip))
        if mod.version:
            holder.setToolTip(f"Version used for your game build: {mod.version}")
        lay.addWidget(holder)
        if mod.notes:
            short = mod.notes.split(" Game builds:")[0].strip()  # research citations stay in the tooltip
            if len(short) > NOTE_CHARS:
                short = short[:NOTE_CHARS].rsplit(" ", 1)[0] + " ..."
            notes = QLabel(f"<small>{short}</small>")
            notes.setProperty("role", "caption")
            notes.setWordWrap(True)
            notes.setToolTip(f"<p style='max-width:480px'>{mod.notes}</p>")
            lay.addWidget(notes)
        lay.addStretch()
        row = QHBoxLayout()
        row.addWidget(control)
        row.addStretch()
        link = W.button("Page", "ghost", lambda: page.win.open_page(mod), "external")
        link.setToolTip(mod.page)
        row.addWidget(link)
        lay.addLayout(row)
        control.toggled.connect(self._mark)
        self._mark(control.isChecked())

    def _mark(self, on: bool) -> None:
        self.setProperty("selected", bool(on))
        theme.repolish(self)


class AddonCard(QFrame):
    """One add-on of the chosen pack: a tick, its name, what it adds. An add-on whose mods the pack already has
    (its base or its variant) shows ticked and locked: it's part of the pack either way."""

    def __init__(self, addon, mods: list[Mod], checked: bool, on_toggle, included: bool = False, pictures=None,
                 blocked: str = ""):
        super().__init__()
        self.addon = addon
        self.blocked = blocked
        self.setProperty("card", True)
        self.setFixedWidth(THUMB_W + 26)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        self.included = included
        self.control = QCheckBox(addon.name)
        self.control.setChecked(checked or included)
        self.control.setEnabled(not included and (not blocked or checked))  # ticked anyway: it can be unticked
        lay.addWidget(self.control)
        if blocked:  # this PC can't run it (its mods' "requires")
            self.control.setToolTip(blocked)
            lay.addWidget(W.Badge(blocked, "warning", blocked))
        if included:
            self.control.setToolTip("Already part of this pack")
            lay.addWidget(W.Badge("In this pack", "success", "The pack already has these mods"))
        if pictures is not None and mods:  # the add-on's mods, as pictures
            strip = QHBoxLayout()
            strip.setSpacing(6)
            for m in mods[:3]:
                art = W.Art(m.id, m.layer, 52)
                art.setFixedWidth(86 if len(mods) > 1 else 266)
                pictures.bind_mod(art, m)
                strip.addWidget(art)
            strip.addStretch()
            lay.addLayout(strip)
        if addon.description:
            lay.addWidget(W._label(addon.description, "caption", wrap=True))
        names = ", ".join(m.name for m in mods[:3]) + (" ..." if len(mods) > 3 else "")
        lay.addWidget(W._label(f"{len(mods)} mod{'s' if len(mods) != 1 else ''}: {names}" if mods else "no mods",
                               "caption", wrap=True))
        self._mark(checked or included)
        self.control.toggled.connect(self._mark)
        self.control.toggled.connect(lambda on: on_toggle(addon.id, on))

    def _mark(self, on: bool) -> None:
        self.setProperty("selected", bool(on))
        theme.repolish(self)


class ChoosePage(QWidget):
    """'Choose your modpack' (view 0) and 'Choose your mods' (view 1): the pack's add-ons by category, the variant,
    your own mods and every mod. Saves the pack choice (pack.json) and add / remove / swaps (config)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cards: dict[str, ModCard] = {}
        self.addon_cards: dict[str, AddonCard] = {}
        self.variant_buttons: dict[str, QRadioButton] = {}
        self._building = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.views = QStackedWidget()
        root.addWidget(self.views)
        s = win.session
        gpus = s.gpus()
        self.gpus = gpus
        from .newpages import ModpackPage

        # 1) "Choose your modpack": big picture cards (first run), 2) add-ons, variant, your own mods, every mod
        self.packs = ModpackPage(s, gpus, win.images)
        self.packs.next_requested.connect(self._packs_done)
        self.packs.add_own_mod.connect(self.add_own_mod)
        self.views.addWidget(self.packs)
        addons = QWidget()
        outer = QVBoxLayout(addons)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        change = W.button("Change pack", "secondary", self.show_packs, "mods")
        outer.addWidget(W.PageHeader(3, 7, "Choose your mods",
                                     "Your pack is ticked below. Turn add-ons on or off, pick a variant, bring your "
                                     "own mods; cards that can't run on your game build are greyed out with the "
                                     "reason.", change))
        outer.addWidget(W._label(f"GPU: {', '.join(gpus) or 'unknown'}.  Click a picture to enlarge it.", "caption"))
        prow = QHBoxLayout()
        prow.addWidget(W._label("Pack:", "caption"))
        self.group = QButtonGroup(self)
        self.pack_row = QHBoxLayout()
        prow.addLayout(self.pack_row)
        prow.addStretch()
        outer.addLayout(prow)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setProperty("role", "muted")
        outer.addWidget(self.desc)
        self.variant_box = W.clear_background(QWidget())
        vrow = QHBoxLayout(self.variant_box)
        vrow.setContentsMargins(0, 0, 0, 0)
        vrow.addWidget(W._label("Variant:", "caption"))
        self.variant_group = QButtonGroup(self)
        self.variant_row = QHBoxLayout()
        vrow.addLayout(self.variant_row)
        self.variant_desc = W._label("", "caption", wrap=True)
        vrow.addWidget(self.variant_desc, 1)
        outer.addWidget(self.variant_box)
        self.build_label = QLabel()
        self.build_label.setWordWrap(True)
        self.build_label.setProperty("role", "caption")
        outer.addWidget(self.build_label)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll, 1)
        self.summary = QLabel()
        self.summary.setProperty("role", "muted")
        self.views.addWidget(addons)
        self.group.buttonClicked.connect(self.pick_profile)
        self.variant_group.buttonClicked.connect(lambda b: self.pick_variant(b.property("vid")))
        win.images.loaded.connect(self._image_loaded)
        self._build_pack_radios()
        self.rebuild()
        outer.addWidget(W.ActionBar([self.summary], [W.button("Next: get mods  →", "primary",
                                                               lambda: win.go(3), glow=True)]))
        self.views.setCurrentIndex(0 if s.config.profile is None else 1)

    def show_packs(self) -> None:
        self.packs.select(self.win.session.pack_choice().pack)
        self.views.setCurrentIndex(0)

    def _packs_done(self) -> None:
        s = self.win.session
        chosen = self.packs.selected
        changed = chosen and (chosen != s.pack_choice().pack or s.config.profile != chosen)
        if changed and not self.switch(chosen):
            return
        self.rebuild()
        self.views.setCurrentIndex(1)

    def edition_changed(self) -> None:
        """The game folder now holds the other edition: its own packs, add-ons and mods."""
        self.packs.rebuild()
        self._build_pack_radios()
        self.rebuild()

    def add_own_mod(self) -> None:
        from .ownmods import CustomModsPanel

        panel = getattr(self, "own", None)
        if panel is None:
            panel = CustomModsPanel(self.win.session)
        if panel.add() is not None:
            self.packs.rebuild()
            self.rebuild()
            self.views.setCurrentIndex(1)

    # ---- state helpers ----------------------------------------------------------
    def _base_ids(self) -> set[str]:
        """Mods the chosen pack (with its add-ons and variant) brings in, before the user's add/remove/swaps."""
        s = self.win.session
        base = s.base_manifest
        c = s.pack_choice()
        if c.pack in base.packs:
            return base.pack_mod_ids(c.pack, s.chosen_addons(), c.variant)
        return {m.id for m in s.manifest.resolve(s.profile_id)}

    def _resolved_mods(self) -> dict[str, Mod]:
        """Every mod as it applies to the detected game build (older variant / unsupported), when supported."""
        return dict(self.win.session.manifest.mods)

    def _slot_groups(self) -> dict[str, list[Mod]]:
        groups: dict[str, list[Mod]] = defaultdict(list)
        for m in self._resolved_mods().values():
            if m.slot:
                groups[m.slot].append(m)
        return {k: v for k, v in groups.items() if len(v) > 1}

    # ---- building ---------------------------------------------------------------
    def _build_pack_radios(self) -> None:
        for b in self.group.buttons():
            self.group.removeButton(b)
            b.hide()
            b.setParent(None)
            b.deleteLater()
        base = self.win.session.base_manifest
        for p in base.packs.values():
            rb = QRadioButton(p.name)
            rb.setToolTip(p.description)
            rb.setProperty("pid", p.id)
            if (p.requires or {}).get("gpu") == "rtx50" and not is_rtx50(self.gpus):
                rb.setEnabled(False)
                rb.setToolTip(p.description + "\nNeeds an NVIDIA RTX 50-series GPU.")
            self.group.addButton(rb)
            self.pack_row.addWidget(rb)

    def _build_variants(self) -> None:
        for b in self.variant_group.buttons():
            self.variant_group.removeButton(b)
            b.hide()
            b.setParent(None)
            b.deleteLater()
        self.variant_buttons = {}
        s = self.win.session
        pack = s.base_manifest.packs.get(s.pack_choice().pack)
        if pack is None or not pack.variants:
            self.variant_box.hide()
            return
        current = pack.variant(s.pack_choice().variant)
        gpus = self._gpu_names()
        for v in pack.variants:
            note = gpu_note((getattr(v, "requires", None) or {}).get("gpu"), gpus)
            rb = QRadioButton(v.name + ("  (not recommended for your card)" if note else ""))
            rb.setToolTip(v.description + (f"\n{note}" if note else ""))
            rb.setProperty("vid", v.id)
            rb.setChecked(current is not None and v.id == current.id)
            self.variant_group.addButton(rb)
            self.variant_row.addWidget(rb)
            self.variant_buttons[v.id] = rb
        self.variant_desc.setText(current.description if current else "")
        self.variant_box.show()

    def _gpu_names(self) -> list[str]:
        try:
            return list(getattr(self, "gpus", None) or self.win.session.gpus())
        except Exception:  # noqa: BLE001 - no GPU list: nothing is greyed out
            return []

    def rebuild(self) -> None:
        self._building = True
        s = self.win.session
        base = s.base_manifest
        choice = s.pack_choice()
        for b in self.group.buttons():
            b.setChecked(b.property("pid") == choice.pack)
        pack = base.packs.get(choice.pack)
        self.desc.setText(pack.description if pack else s.manifest.profile(s.profile_id).description)
        self._build_variants()
        selected = {m.id for m in s.mods()}
        gpus = self.gpus
        slot_groups = self._slot_groups()
        in_slot = {m.id: slot for slot, ms in slot_groups.items() for m in ms}

        body = W.clear_background(QWidget())
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)
        self.cards.clear()
        self.addon_cards = {}
        self.slot_buttons: dict[str, QButtonGroup] = {}
        resolved = self._resolved_mods()
        # -- add-ons of the chosen pack, by category
        if pack is not None:
            chosen = set(s.chosen_addons())
            in_pack = base.pack_mod_ids(pack.id, (), s.pack_choice().variant)  # base + the variant's add-ons
            for cat_id, addons in base.addons_for(pack.id).items():
                cat = base.categories.get(cat_id)
                lay.addSpacing(6)
                lay.addWidget(W._label(f"ADD-ONS · {(cat.name if cat else cat_id).upper()}", "eyebrow"))
                if cat and cat.description:
                    lay.addWidget(W._label(cat.description, "caption", wrap=True))
                holder, flow = W.flow_box(14)
                gpus = self._gpu_names()
                for a in addons:
                    mods = [resolved[i] for i in a.mods if i in resolved]
                    blocked = next((n for n in (gpu_note((m.requires or {}).get("gpu"), gpus) for m in mods) if n), "")
                    card = AddonCard(a, mods, a.id in chosen, self.toggle_addon,
                                     included=bool(a.mods) and set(a.mods) <= in_pack,
                                     pictures=getattr(self.win, "pictures", None), blocked=blocked)
                    self.addon_cards[a.id] = card
                    flow.addWidget(card)
                lay.addWidget(holder)
        # -- your own mods
        from .ownmods import CustomModsPanel

        lay.addSpacing(6)
        self.own = CustomModsPanel(s)
        self.own.changed.connect(self._own_changed)
        lay.addWidget(self.own)
        # -- every mod, by layer (your own mods are in their panel above)
        by_layer: dict[str, list[Mod]] = defaultdict(list)
        for m in resolved.values():
            if m.tier != "custom":
                by_layer[m.layer].append(m)
        build = s.game_version()
        self.build_label.setText(f"Game build: <b>{build or 'unknown'}</b>. Mods are shown in the version that works "
                                 "on this build; greyed-out mods have no working version for it.")
        done_slots: set[str] = set()
        base_ids = self._base_ids()
        for layer, mods in by_layer.items():
            lay.addSpacing(6)
            lay.addWidget(W._label(layer.upper(), "eyebrow"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(14)
            grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
            i = 0
            for m in mods:
                slot = in_slot.get(m.id)
                if slot and slot in done_slots:
                    continue
                members = slot_groups[slot] if slot else [m]
                if slot:
                    done_slots.add(slot)
                    bg = QButtonGroup(self)
                    bg.setExclusive(True)
                    self.slot_buttons[slot] = bg
                for mm in members:
                    if slot:
                        ctl: QCheckBox | QRadioButton = QRadioButton("Use this one")
                        bg.addButton(ctl)
                        ctl.setChecked(mm.id in selected)
                        ctl.toggled.connect(lambda on, mid=mm.id, sl=slot: on and self.pick_slot(sl, mid))
                    else:
                        ctl = QCheckBox("Include")
                        ctl.setChecked(mm.id in selected)
                        if mm.layer in LOCKED_LAYERS and mm.id in base_ids:
                            ctl.setEnabled(False)
                            ctl.setToolTip("Required: other mods depend on it.")
                        if mm.requires.get("gpu") == "rtx50" and not is_rtx50(gpus):
                            ctl.setEnabled(False)
                            ctl.setToolTip("Needs an NVIDIA RTX 50-series GPU.")
                        ctl.toggled.connect(lambda on, mid=mm.id: self.toggle(mid, on))
                    reason = getattr(mm, "unsupported", None)
                    if reason:
                        ctl.setEnabled(False)
                        ctl.setToolTip(reason)
                    card = ModCard(self, mm, ctl)
                    if reason:
                        card.setEnabled(False)
                        card.setProperty("disabled", True)
                        card.setToolTip(reason)
                        card.layout().insertWidget(1, _note(f"Not available for your game build: {reason}"))
                    self.cards[mm.id] = card
                    grid.addWidget(card, i // COLUMNS, i % COLUMNS)
                    i += 1
                    self.win.images.request(mm.id, mm.image, mm.page)
            lay.addLayout(grid)
        lay.addStretch()
        old = self.scroll.takeWidget()
        self.scroll.setWidget(body)
        if old is not None:
            old.hide()
            old.deleteLater()
        self.summary.setText(f"<b>{len(selected)}</b> mods selected.")
        self._building = False

    def _image_loaded(self, key: str, path: str) -> None:
        card = self.cards.get(key)
        if card and path:
            pictures = getattr(self.win, "pictures", None)  # decoded once for the whole window
            card.thumb.set_image(path, pictures.pixmap(path) if pictures is not None else None)

    def _own_changed(self) -> None:
        self.packs.rebuild()
        QTimer.singleShot(0, self.rebuild)  # the panel that sent this is replaced

    # ---- choices ----------------------------------------------------------------
    def switch(self, pack_id: str, addons=None, variant: str | None = None) -> bool:
        """Save a new pack / add-ons / variant. Installed mods that leave the selection: ask whether to roll them
        back (newest first; packs.rollback_mods keeps one a kept mod's later step shares files with), keep them, or
        cancel the switch. A new variant on an installed setup: offer to write its locked settings now."""
        s = self.win.session
        old = s.pack_choice()
        old_variant = self._effective_variant(old.pack, old.variant)
        before = set(s.selection_ids())
        s.choose_pack(pack_id, addons, variant)
        after = set(s.selection_ids())
        installed = s.log.installed_mods()
        leaving = sorted((before - after) & installed)
        if leaving:
            names = [s.base_manifest.mods[m].name if m in s.base_manifest.mods else m for m in leaving]
            box = QMessageBox(QMessageBox.Icon.Question, PACK_NAME,
                              f"{len(leaving)} installed mod{'s are' if len(leaving) != 1 else ' is'} not in your new "
                              f"choice: {', '.join(names)}.\n\nRoll {'them' if len(leaving) != 1 else 'it'} back now "
                              "(newest first, like Undo), or keep them installed?", parent=self)
            roll = box.addButton("Roll back", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Keep installed", QMessageBox.ButtonRole.DestructiveRole)
            cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is None or clicked is cancel:
                s.choose_pack(old.pack, old.addons, old.variant)
                self.rebuild()
                return False
            if clicked is roll:
                self._rollback(set(leaving))
        new_variant = self._effective_variant(pack_id, variant)
        if new_variant != old_variant and installed and s.installed_settings():
            name = s.base_manifest.packs[pack_id].variant(new_variant).name if new_variant else "default"
            if QMessageBox.question(self, PACK_NAME, f"Write the {name} settings into the installed mods now? "
                                    "(Logged and undoable; nothing is reinstalled.)") == QMessageBox.StandardButton.Yes:
                self._apply_settings()
        self.win.update_sidebar()
        return True

    def _effective_variant(self, pack_id: str, variant: str | None) -> str | None:
        pack = self.win.session.base_manifest.packs.get(pack_id)
        v = pack.variant(variant) if pack else None
        return v.id if v else None

    def _rollback(self, mod_ids: set[str]) -> list[str]:
        from ..packs import rollback_mods

        ui = self.win.log_ui(self)
        try:
            report = rollback_mods(self.win.session, ui, mod_ids)
        except Exception as exc:  # noqa: BLE001 - shown, the choice is already saved
            report = [f"Couldn't roll back: {exc}"]
        for line in report:
            ui.info(line)
        QMessageBox.information(self, PACK_NAME, "\n".join(report) or "Nothing to roll back.")
        return report

    def _apply_settings(self) -> list[str]:
        ui = self.win.log_ui(self)
        try:
            report = self.win.session.apply_settings(ui)
        except Exception as exc:  # noqa: BLE001
            report = [f"Couldn't write the settings: {exc}"]
        QMessageBox.information(self, PACK_NAME, "\n".join(report) or "The settings were already right.")
        return report

    def pick_profile(self, rb: QRadioButton) -> None:
        pid = rb.property("pid")
        if pid != self.win.session.pack_choice().pack or self.win.session.config.profile != pid:
            self.switch(pid)
        self.packs.select(self.win.session.pack_choice().pack)
        self.rebuild()

    def pick_variant(self, variant_id: str) -> None:
        s = self.win.session
        c = s.pack_choice()
        if variant_id != self._effective_variant(c.pack, c.variant):
            self.switch(c.pack, c.addons, variant_id)
        self.rebuild()

    def toggle_addon(self, addon_id: str, on: bool) -> None:
        if self._building:
            return
        s = self.win.session
        c = s.pack_choice()
        chosen = [a for a in s.chosen_addons() if a != addon_id] + ([addon_id] if on else [])
        self.switch(c.pack, chosen, c.variant)
        QTimer.singleShot(0, self.rebuild)  # the card that sent this is replaced

    def toggle(self, mod_id: str, on: bool) -> None:
        if self._building:
            return
        c = self.win.session.config
        base = self._base_ids()
        if on:
            if mod_id in c.remove:
                c.remove.remove(mod_id)
            if mod_id not in base and mod_id not in c.add:
                c.add.append(mod_id)
        else:
            if mod_id in c.add:
                c.add.remove(mod_id)
            if mod_id in base and mod_id not in c.remove:
                c.remove.append(mod_id)
        self.win.session.save()
        self.summary.setText(f"<b>{len(self.win.session.mods())}</b> mods selected.")

    def pick_slot(self, slot: str, mod_id: str) -> None:
        """One mod per slot. The slot's default is the member the pack brings in; others are swaps for it."""
        if self._building:
            return
        s = self.win.session
        members = [m.id for m in self._slot_groups()[slot]]
        base = self._base_ids()
        default = next((mid for mid in members if mid in base), members[0])
        for mid in members:
            s.config.swaps.pop(mid, None)
            if mid in s.config.add and mid != mod_id:
                s.config.add.remove(mid)
        if default not in base:  # the pack has no member of this slot: just add the chosen one
            if mod_id not in s.config.add:
                s.config.add.append(mod_id)
        elif mod_id != default:
            s.config.swaps[default] = mod_id
        s.save()
        self.summary.setText(f"<b>{len(s.mods())}</b> mods selected.")
