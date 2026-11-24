"""'Choose mods' page: profile picker plus a picture card per mod, grouped by layer, with alternatives side by side."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..detect import is_rtx50
from ..manifest import Mod

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
    lab = QLabel(f"<small style='color:#c0392b'>{text}</small>")
    lab.setWordWrap(True)
    return lab


def how_text(mod: Mod) -> str:
    if mod.download:
        return "automatic download"
    return SOURCE_TEXT.get(mod.source, "in-app download (author's page)")


class _Thumb(QLabel):
    def __init__(self, card: ModCard):
        super().__init__()
        self.card = card
        self.setFixedSize(THUMB_W, THUMB_H)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#1f2430;color:#8a93a6;border-radius:6px;")
        self.setText(card.mod.layer)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.full: QPixmap | None = None

    def set_image(self, path: str) -> None:
        pix = QPixmap(path)
        if pix.isNull():
            return
        self.full = pix
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
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(THUMB_W + 24)
        lay = QVBoxLayout(self)
        self.thumb = _Thumb(self)
        lay.addWidget(self.thumb)
        name = QLabel(f"<b>{mod.name}</b><br><span style='color:#888'>{mod.author or ''}</span>")
        name.setWordWrap(True)
        lay.addWidget(name)
        version = f" &middot; v{mod.version}" if mod.version and mod.version[:1].isdigit() else ""
        badge = QLabel(f"<small>{mod.tier}{version} &middot; {how_text(mod)}</small>")
        if mod.version:
            badge.setToolTip(f"Version used for your game build: {mod.version}")
        badge.setWordWrap(True)
        lay.addWidget(badge)
        if mod.notes:
            short = mod.notes.split(" Game builds:")[0].strip()  # research citations stay in the tooltip
            if len(short) > NOTE_CHARS:
                short = short[:NOTE_CHARS].rsplit(" ", 1)[0] + " ..."
            notes = QLabel(f"<small>{short}</small>")
            notes.setWordWrap(True)
            notes.setToolTip(f"<p style='max-width:480px'>{mod.notes}</p>")
            lay.addWidget(notes)
        row = QHBoxLayout()
        row.addWidget(control)
        row.addStretch()
        link = QPushButton("Page")
        link.setToolTip(mod.page)
        link.clicked.connect(lambda: page.win.open_page(mod))
        row.addWidget(link)
        lay.addLayout(row)
        lay.addStretch()


class ChoosePage(QWidget):
    """Replaces the old profile page. Writes profile / add / remove / swaps into the saved config."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cards: dict[str, ModCard] = {}
        self._building = False
        outer = QVBoxLayout(self)
        title = QLabel("<span style='font-size:16pt;font-weight:bold'>Choose your mods</span>")
        outer.addWidget(title)
        s = win.session
        gpus = s.gpus()
        outer.addWidget(QLabel(f"GPU: {', '.join(gpus) or 'unknown'}.  Click a picture to enlarge it."))
        prow = QHBoxLayout()
        self.group = QButtonGroup(self)
        for p in s.manifest.profiles.values():
            rb = QRadioButton(p.name)
            rb.setToolTip(p.description)
            rb.setProperty("pid", p.id)
            if p.requires.get("gpu") == "rtx50" and not is_rtx50(gpus):
                rb.setEnabled(False)
                rb.setToolTip(p.description + "\nNeeds an NVIDIA RTX 50-series GPU.")
            self.group.addButton(rb)
            prow.addWidget(rb)
        prow.addStretch()
        outer.addLayout(prow)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        outer.addWidget(self.desc)
        self.build_label = QLabel()
        self.build_label.setWordWrap(True)
        outer.addWidget(self.build_label)
        self.summary = QLabel()
        outer.addWidget(self.summary)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll, 1)
        self.group.buttonClicked.connect(self.pick_profile)
        win.images.loaded.connect(self._image_loaded)
        self.rebuild()

    # ---- state helpers ----------------------------------------------------------
    def _base_ids(self) -> set[str]:
        """Mods the current profile brings in, before the user's add/remove/swaps."""
        s = self.win.session
        return {m.id for m in s.manifest.resolve(s.profile_id)}

    def _resolved_mods(self) -> dict[str, Mod]:
        """Every mod as it applies to the detected game build (older variant / unsupported), when supported."""
        s = self.win.session
        manifest = s.manifest
        for_build = getattr(manifest, "for_build", None)
        if for_build is not None:
            try:
                manifest = for_build(s.game_version())
            except Exception:  # noqa: BLE001 - fall back to the plain manifest
                manifest = s.manifest
        return dict(manifest.mods)

    def _slot_groups(self) -> dict[str, list[Mod]]:
        groups: dict[str, list[Mod]] = defaultdict(list)
        for m in self._resolved_mods().values():
            if m.slot:
                groups[m.slot].append(m)
        return {k: v for k, v in groups.items() if len(v) > 1}

    # ---- building ---------------------------------------------------------------
    def rebuild(self) -> None:
        self._building = True
        s = self.win.session
        for b in self.group.buttons():
            b.setChecked(b.property("pid") == s.profile_id)
        self.desc.setText(s.manifest.profile(s.profile_id).description)
        selected = {m.id for m in s.mods()}
        gpus = s.gpus()
        slot_groups = self._slot_groups()
        in_slot = {m.id: slot for slot, ms in slot_groups.items() for m in ms}

        body = QWidget()
        lay = QVBoxLayout(body)
        self.cards.clear()
        self.slot_buttons: dict[str, QButtonGroup] = {}
        by_layer: dict[str, list[Mod]] = defaultdict(list)
        for m in self._resolved_mods().values():
            by_layer[m.layer].append(m)
        build = s.game_version()
        self.build_label.setText(f"Game build: <b>{build or 'unknown'}</b>. Mods are shown in the version that works "
                                 "on this build; greyed-out mods have no working version for it.")
        done_slots: set[str] = set()
        for layer, mods in by_layer.items():
            head = QLabel(f"<span style='font-size:12pt;font-weight:bold'>{layer}</span>")
            lay.addWidget(head)
            grid = QGridLayout()
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
                        if mm.layer in LOCKED_LAYERS and mm.id in self._base_ids():
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
                        card.setToolTip(reason)
                        card.layout().insertWidget(1, _note(f"Not available for your game build: {reason}"))
                    self.cards[mm.id] = card
                    grid.addWidget(card, i // COLUMNS, i % COLUMNS)
                    i += 1
                    self.win.images.request(mm.id, mm.image, mm.page)
            lay.addLayout(grid)
        lay.addStretch()
        self.scroll.setWidget(body)
        self.summary.setText(f"<b>{len(selected)}</b> mods selected.")
        self._building = False

    def _image_loaded(self, key: str, path: str) -> None:
        card = self.cards.get(key)
        if card and path:
            card.thumb.set_image(path)

    # ---- choices ----------------------------------------------------------------
    def pick_profile(self, rb: QRadioButton) -> None:
        s = self.win.session
        s.config.profile = rb.property("pid")
        s.save()
        self.rebuild()

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
        """One mod per slot. The slot's default is the member the profile brings in; others are swaps for it."""
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
        if default not in base:  # the profile has no member of this slot: just add the chosen one
            if mod_id not in s.config.add:
                s.config.add.append(mod_id)
        elif mod_id != default:
            s.config.swaps[default] = mod_id
        s.save()
        self.summary.setText(f"<b>{len(s.mods())}</b> mods selected.")
