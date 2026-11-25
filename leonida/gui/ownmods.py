"""'Your own mods': add a mod from a file or a page, say which files go where, list / edit / remove / export.

The entries live in ``<state>/custom-mods.json`` (leonida/custommods.py). Each becomes an ordinary mod (tier
"custom") with the same logged install, rollback, conflict checks and online-safe handling as the curated ones.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .. import PACK_NAME, custommods
from ..manifest import ManifestError
from . import widgets as W

# (method, label) in the order the dialog offers them; "generic" = Leonida's .asi / scripts / .oiv rules
METHODS = (
    ("generic", "Let Leonida place it (.asi, .dll, scripts, mods folder)"),
    ("copy", "Copy these files into a folder"),
    ("run", "Run its installer"),
    ("guided", "I follow its readme; Leonida records the changes"),
)
TARGETS = (".", "scripts", "plugins", "mods", "update")
METHOD_TEXT = {"generic": "placed by Leonida", "copy": "copied", "run": "its installer", "guided": "by hand"}


def _split(text: str) -> list[str]:
    return [p.strip() for p in text.replace(";", ",").replace("\n", ",").split(",") if p.strip()]


def describe(entry: dict) -> str:
    """One caption line for an entry: where it comes from, how it installs, where it goes."""
    page = entry.get("page", "")
    src = Path(entry["file"]).name if entry.get("file") else (urlparse(page).netloc or page)
    method = entry.get("method") or ("copy" if entry.get("files") else "generic")
    how = METHOD_TEXT.get(method, method)
    files = entry.get("files") or []
    if files:
        to = files[0].get("to", ".")
        names = ", ".join(f.get("match", "?") for f in files[:3]) + (" ..." if len(files) > 3 else "")
        how = f"{names} -> {'game folder' if to in ('.', '') else to}"
    return f"{src} · {how}"


class CustomModDialog(QDialog):
    """Add or edit one of your own mods. ``entry`` (an existing entry) pre-fills it and keeps its id and order."""

    def __init__(self, session, entry: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.entry = dict(entry) if entry else None
        self.saved: dict | None = None
        self.setWindowTitle("Edit your mod" if entry else "Add your own mod")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        lay.addWidget(W._label("YOUR OWN MOD", "eyebrow"))
        lay.addWidget(W._label("Any mod, from a file on this PC or its page. It installs after the pack's mods, "
                               "logged and undoable like every other step.", "muted", wrap=True))
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. My trainer")
        form.addRow("Name", self.name)
        src = QWidget()
        sl = QVBoxLayout(W.clear_background(src))
        sl.setContentsMargins(0, 0, 0, 0)
        self.src_group = QButtonGroup(self)
        self.from_file = QRadioButton("A file on this PC")
        self.from_page = QRadioButton("Its page (download it there)")
        for rb in (self.from_file, self.from_page):
            self.src_group.addButton(rb)
        frow = QHBoxLayout()
        frow.addWidget(self.from_file)
        self.file = QLineEdit()
        self.file.setPlaceholderText("D:\\Mods\\trainer.zip")
        frow.addWidget(self.file, 1)
        self.browse_btn = W.button("Browse...", "ghost", self.browse)
        frow.addWidget(self.browse_btn)
        sl.addLayout(frow)
        prow = QHBoxLayout()
        prow.addWidget(self.from_page)
        self.page = QLineEdit()
        self.page.setPlaceholderText("https://www.gta5-mods.com/scripts/...")
        prow.addWidget(self.page, 1)
        sl.addLayout(prow)
        form.addRow("From", src)
        self.archive = QLineEdit()
        self.archive.setPlaceholderText("trainer*.zip  (how its download is named; needed with a page)")
        form.addRow("Download name", self.archive)
        self.method = QComboBox()
        for key, label in METHODS:
            self.method.addItem(label, key)
        form.addRow("How it installs", self.method)
        self.files = QLineEdit()
        self.files.setPlaceholderText("trainer.asi, trainer.ini")
        form.addRow("Files", self.files)
        self.target = QComboBox()
        self.target.setEditable(True)
        self.target.addItems(TARGETS)
        self.target.setToolTip("A folder inside the game folder ('.' = the game folder itself)")
        form.addRow("Into folder", self.target)
        self.run = QLineEdit()
        self.run.setPlaceholderText("setup.exe")
        form.addRow("Installer to run", self.run)
        self.notes = QLineEdit()
        form.addRow("Notes", self.notes)
        lay.addLayout(form)
        self.error = W._label("", "caption", "error", wrap=True)
        self.error.hide()
        lay.addWidget(self.error)
        box = QDialogButtonBox()
        self.ok_btn = box.addButton("Save" if entry else "Add mod", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok_btn.setProperty("variant", "primary")
        box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.method.currentIndexChanged.connect(self._update)
        self.src_group.buttonToggled.connect(lambda *_: self._update())
        self._fill(self.entry or {})
        self._update()

    def _fill(self, e: dict) -> None:
        self.name.setText(e.get("name", ""))
        self.file.setText(e.get("file", ""))
        self.page.setText(e.get("page", ""))
        (self.from_page if e.get("page") and not e.get("file") else self.from_file).setChecked(True)
        self.archive.setText(", ".join(e.get("archive", [])))
        files = e.get("files") or []
        method = e.get("method") or ("copy" if files else "generic")
        self.method.setCurrentIndex(max(0, self.method.findData(method)))
        self.files.setText(", ".join(f.get("match", "") for f in files))
        self.target.setCurrentText(files[0].get("to", ".") if files else ".")
        self.run.setText(e.get("run", ""))
        self.notes.setText(e.get("notes", ""))

    def _update(self) -> None:
        file_mode = self.from_file.isChecked()
        self.file.setEnabled(file_mode)
        self.browse_btn.setEnabled(file_mode)
        self.page.setEnabled(not file_mode)
        method = self.method.currentData()
        self.files.setEnabled(method == "copy")
        self.target.setEnabled(method == "copy")
        self.run.setEnabled(method == "run")

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Your mod's file", "",
                                              "Mods (*.zip *.7z *.rar *.oiv *.asi *.dll);;All files (*)")
        if path:
            self.file.setText(path)
            if not self.name.text().strip():
                self.name.setText(Path(path).stem)

    def values(self) -> dict:
        method = self.method.currentData()
        file_mode = self.from_file.isChecked()
        return {
            "name": self.name.text().strip(),
            "file": self.file.text().strip() or None if file_mode else None,
            "page": self.page.text().strip() or None if not file_mode else None,
            "archive": _split(self.archive.text()) or None,
            "files": _split(self.files.text()) if method == "copy" else None,
            "to": (self.target.currentText().strip() or ".") if method == "copy" else ".",
            "method": method,
            "run": self.run.text().strip() or None if method == "run" else None,
            "notes": self.notes.text().strip(),
        }

    def save(self) -> None:
        """Validate and save (custommods.add); a problem shows in the dialog, which stays open."""
        v = self.values()
        s = self.session
        if v["method"] == "copy" and not v["files"]:
            return self._fail("Say which files to copy (their names inside the download).")
        try:
            entry = custommods.add(s.state, s.manifest_for(s.edition), name=v["name"], file=v["file"], page=v["page"],
                                   archive=v["archive"], files=v["files"], to=v["to"], method=v["method"],
                                   run=v["run"], notes=v["notes"],
                                   mod_id=self.entry.get("id") if self.entry else None,
                                   order=self.entry.get("order") if self.entry else None)
        except (ManifestError, OSError) as exc:
            return self._fail(str(exc))
        if self.entry is not None and self.entry.get("enabled") is False:  # editing keeps it switched off
            set_enabled(s.state, entry["id"], False)
        self.saved = entry
        self.accept()

    def _fail(self, text: str) -> None:
        self.error.setText(text)
        self.error.show()


def set_enabled(state: Path, mod_id: str, on: bool) -> None:
    entries = custommods.load_entries(state)
    for e in entries:
        if e.get("id") == mod_id:
            e["enabled"] = bool(on)
    custommods.save_entries(state, entries)


class CustomModsPanel(QFrame):
    """The list of your own mods with Add / Edit / Remove / Export. ``changed`` fires after every edit."""

    changed = Signal()

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(W._icon_label("mods", W.C["coral"], 20))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(W._label("Your own mods", "subtitle"))
        col.addWidget(W._label("Bring any mod: a file or a page link. It installs after the pack, with the same "
                               "logged install, rollback and online-safe handling.", "caption", wrap=True))
        top.addLayout(col, 1)
        self.export_btn = W.button("Export...", "ghost", self.export)
        top.addWidget(self.export_btn)
        self.add_btn = W.button("Add a mod", "secondary", self.add, "download")
        top.addWidget(self.add_btn)
        lay.addLayout(top)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        lay.addLayout(self.rows)
        self.row_widgets: dict[str, QWidget] = {}
        self.refresh()

    def entries(self) -> list[dict]:
        try:
            return custommods.load_entries(self.session.state)
        except ManifestError:
            return []

    def refresh(self) -> None:
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.row_widgets = {}
        try:
            entries = custommods.load_entries(self.session.state)
        except ManifestError as exc:
            self.rows.addWidget(W._label(str(exc), "caption", "error", wrap=True))
            return
        installed = self.session.log.installed_mods()
        for e in entries:
            mid = e.get("id", "?")
            w = W.clear_background(QWidget())
            row = QHBoxLayout(w)
            row.setContentsMargins(30, 2, 0, 2)
            on = QCheckBox()
            on.setChecked(e.get("enabled", True))
            on.setToolTip("Include it in your mod list")
            on.toggled.connect(lambda v, m=mid: self.set_enabled(m, v))
            row.addWidget(on)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(W._label(e.get("name", mid)))
            col.addWidget(W._label(describe(e), "caption", wrap=True))
            row.addLayout(col, 1)
            if mid in installed:
                row.addWidget(W.Badge("Installed", "success"))
            row.addWidget(W.button("Edit", "ghost", lambda _=False, x=e: self.edit(x)))
            row.addWidget(W.button("Remove", "ghost", lambda _=False, m=mid: self.remove(m)))
            self.row_widgets[mid] = w
            self.rows.addWidget(w)
        self.export_btn.setEnabled(bool(entries))

    # ---- actions ----------------------------------------------------------------------------------------------
    def add(self) -> dict | None:
        return self._open(None)

    def edit(self, entry: dict) -> dict | None:
        return self._open(entry)

    def _open(self, entry: dict | None) -> dict | None:
        dlg = CustomModDialog(self.session, entry, self.window())
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.saved is None:
            return None
        self._changed()
        return dlg.saved

    def set_enabled(self, mod_id: str, on: bool) -> None:
        set_enabled(self.session.state, mod_id, on)
        self.changed.emit()

    def remove(self, mod_id: str) -> bool:
        name = next((e.get("name", mod_id) for e in self.entries() if e.get("id") == mod_id), mod_id)
        extra = ("\n\nIt is installed: its files stay until you undo that step or uninstall."
                 if mod_id in self.session.log.installed_mods() else "")
        if QMessageBox.question(self, PACK_NAME, f"Remove {name} from your mods?{extra}") \
                != QMessageBox.StandardButton.Yes:
            return False
        custommods.remove(self.session.state, mod_id)
        self._changed()
        return True

    def export(self) -> Path | None:
        path, _ = QFileDialog.getSaveFileName(self, "Export your mods", "leonida-my-mods.json", "JSON (*.json)")
        if not path:
            return None
        out = custommods.export(self.session.state, Path(path))
        QMessageBox.information(self, PACK_NAME, f"Saved your {len(self.entries())} mod(s) to {out}.")
        return out

    def _changed(self) -> None:
        self.refresh()
        self.changed.emit()
