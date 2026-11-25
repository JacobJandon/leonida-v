"""Click every button on every page and tab of the launcher (offscreen, against a fake game folder) and check that
none raises, none is dead (each click shows something: a page, a dialog, a notification, a status line, a changed
label or list, a menu, an opened page), and none blocks the window for long (long work belongs on a worker).

Never touches the real game, the PC's processes, the Start menu or the Desktop: game detection, the play test,
process control, restarts and shortcut folders are stubbed. ``print_report`` lists every click (pytest -s).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QProcess  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QCheckBox,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QRadioButton,
    QTableWidget,
    QTabWidget,
    QTextEdit,
)
from test_gui_pages import dialogs, make_win, qapp, wait_idle  # noqa: E402,F401  (fixtures)

import leonida.gui.app as A  # noqa: E402
from leonida import firstrun as FR  # noqa: E402
from leonida.detect import GameInstall  # noqa: E402

# A click that keeps the window busy longer than STALL_MS does its work on the UI thread (3x on CI runners). Clicks
# over SLOW_MS are listed (building a page full of cards after a pack change takes a few hundred ms).
STALL_MS = 600 * (3 if os.environ.get("CI") else 1)
SLOW_MS = 300


def _visible_state(win, extra) -> tuple:
    """Everything a click could visibly change."""
    page = win.stack.currentWidget()
    texts = []
    for w in page.findChildren(QLabel):
        if w.isVisibleTo(page):
            texts.append(w.text())
    for kind in (QPlainTextEdit, QTextEdit):
        for w in page.findChildren(kind):
            texts.append(w.toPlainText())
    for w in page.findChildren(QAbstractButton):
        if w.isVisibleTo(page):
            texts.append(f"{w.text()}|{w.isEnabled()}|{w.isChecked()}")
    for w in page.findChildren(QListWidget):
        texts.append(str(w.count()) + "".join(w.item(i).text() for i in range(min(w.count(), 30))))
    for w in page.findChildren(QTableWidget):
        texts.append(str(w.rowCount()) + str(w.isVisibleTo(page)))
    for w in page.findChildren(QTabWidget):
        texts.append(str(w.currentIndex()))
    tops = tuple(sorted(type(t).__name__ for t in QApplication.topLevelWidgets() if t.isVisible()))
    return (id(page), len(win.notifications.items), win.statusBar().currentMessage(), win.toast.text.text(),
            win.toast.isVisible(), tops, hash("\x00".join(texts)), win.bottom.work.text(), extra())


def _close_popups(win) -> None:
    """Menus and side windows a click opened (What's new, ...): closed before the next click."""
    for t in QApplication.topLevelWidgets():
        if t is not win and t.isVisible():
            t.close()


def _settle(win, seconds: float = 0.4) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    wait_idle(win, *win.pages, win.setup_flow, win.settings_page, win.about_page, win.browse, win.pack_page,
              timeout=60)
    QApplication.processEvents()


def _views(win):
    """(name, show) for every page and tab."""
    out = []
    for i, name in enumerate(A.PAGES):
        page = win.pages[i]
        tabs = page.findChildren(QTabWidget)
        if tabs:
            for t in range(tabs[0].count()):
                out.append((f"{name} / {tabs[0].tabText(t)}", lambda i=i, t=t, tw=tabs[0]: (win.go(i),
                                                                                           tw.setCurrentIndex(t))))
        else:
            out.append((name, lambda i=i: win.go(i)))
    for t in range(win.browse.tabs.count()):
        out.append((f"Browse / {win.browse.tabs.tabText(t)}",
                    lambda t=t: (win.show_home("browse"), win.browse.tabs.setCurrentIndex(t))))
    for t in range(win.pack_page.tabs.count()):
        out.append((f"My modpack / {win.pack_page.tabs.tabText(t).replace('&&', '&')}",
                    lambda t=t: (win.show_home("pack"), win.pack_page.tabs.setCurrentIndex(t))))
    out.append(("Settings", lambda: win.show_home("settings")))
    out.append(("About & help", lambda: win.show_home("about")))
    for k, step in enumerate(FR.STEPS):
        out.append((f"Setup / {step}", lambda k=k: win.setup_flow.begin(k)))
    return out


def _buttons(page) -> list[str]:
    seen, out = set(), []
    for b in page.findChildren(QAbstractButton):
        if not b.isVisibleTo(page) or not b.isEnabled() or isinstance(b, (QCheckBox, QRadioButton)):
            continue
        if b.isCheckable() and b.isChecked() and b.group() is not None and b.group().exclusive():
            continue   # the chip that is already selected: clicking it again is meant to change nothing
        if b.text() and b.text() not in seen and not b.objectName().startswith("qt_"):
            seen.add(b.text())
            out.append(b.text())
    return out


def _ms(row: str) -> float:
    return float(row.rsplit(" ms", 1)[0].split()[-1])


def _find(page, text):
    return next((b for b in page.findChildren(QAbstractButton)
                 if b.text() == text and b.isVisibleTo(page) and b.isEnabled()), None)


def test_click_every_button(make_win, dialogs, game, downloads, tmp_path, monkeypatch):  # noqa: F811
    # ---- nothing real: the game's processes, detection, the play test, restarts, shortcut folders
    from leonida import detect, playtest, shortcuts
    from leonida.gui import memcheck

    started = []
    monkeypatch.setenv("LEONIDA_STARTMENU_DIR", str(tmp_path / "startmenu"))
    monkeypatch.setenv("LEONIDA_DESKTOP_DIR", str(tmp_path / "desktop"))
    monkeypatch.setenv("LEONIDA_NO_SHORTCUTS", "1")
    monkeypatch.setattr(shortcuts, "desktop_dir", lambda: tmp_path / "desktop")
    fake_games = lambda names=None, extra=None: [  # noqa: E731
        GameInstall(game, "steam", game / "GTA5_Enhanced.exe", "1.0.1013.20", "enhanced")]
    monkeypatch.setattr(detect, "detect_games", fake_games)
    monkeypatch.setattr(A, "detect_games", fake_games)

    class NoProcesses:
        def __getattr__(self, name):
            return lambda *a, **k: started.append((name, a)) or []

    monkeypatch.setattr(playtest, "ProcessOps", NoProcesses)
    monkeypatch.setattr(playtest, "playtest", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stubbed play test")))
    monkeypatch.setattr(memcheck, "confirm", lambda *a, **k: True)
    class FakePopen:
        """A process that started and ended at once with no output, usable everywhere a real Popen is: a `with`
        block, subprocess.run / check_output (which platform and others use on some Pythons and systems)."""

        def __init__(self, args, *a, **k):
            started.append(("popen", args))
            self.args, self.pid, self.returncode = args, 0, 0
            text = k.get("text") or k.get("universal_newlines") or k.get("encoding")
            self._empty = "" if text else b""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def communicate(self, input=None, timeout=None):  # noqa: A002 - Popen's own name
            return self._empty, self._empty

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def kill(self):
            pass

        terminate = kill

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(QProcess, "startDetached", staticmethod(lambda *a, **k: started.append(("restart", a))))
    dialogs.items = [lambda items: ("", False)] * 100
    from PySide6.QtWidgets import QFileDialog

    from leonida.gui import extras as E

    asked = []
    monkeypatch.setattr(A, "_open", lambda target: dialogs.opened.append(("open", target)))
    monkeypatch.setattr(E, "_open", lambda target: dialogs.opened.append(("open", target)))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: asked.append(a) or ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: asked.append(a) or ("", "")))
    errors = []
    clicking = ["(opening the window)"]       # the view and button being clicked: named with each exception

    def hook(t, v, tb) -> None:
        import traceback

        where = "".join(traceback.format_tb(tb)[-2:]).strip()
        errors.append(f"{clicking[0]}: {t.__name__}: {v}\n{where}")

    monkeypatch.setattr(sys, "excepthook", hook)

    # ---- a set-up launcher: a pack, two installed steps, a download
    win = make_win(show=True)
    s = win.session
    s.choose_pack(s.base_manifest.default_pack)
    for m in s.mods()[:2]:
        st = s.log.new_step(m.id, "copy")
        st.status = "done"
    s.log.save()
    (downloads / "random-download.zip").write_bytes(b"PK")
    win.resize(1600, 1000)
    _settle(win)

    def extra():
        return (len(dialogs.calls), len(dialogs.boxes), len(dialogs.dialogs), len(dialogs.opened), len(started),
                len(dialogs.item_prompts), len(asked), QApplication.clipboard().text())

    rows, dead, slow = [], [], []
    for view, show in _views(win):
        show()
        _settle(win, 0.2)
        page = win.stack.currentWidget()
        for text in _buttons(page):
            show()
            _settle(win, 0.1)
            page = win.stack.currentWidget()
            b = _find(page, text)
            if b is None:
                continue
            _close_popups(win)
            _settle(win, 0.05)
            before = _visible_state(win, extra)
            clicking[0] = f"{view} / {text}"
            t = time.perf_counter()
            b.click()
            ms = (time.perf_counter() - t) * 1000
            _settle(win)
            after = _visible_state(win, extra)
            what = "ok" if after != before else "NO VISIBLE EFFECT"
            if after == before:
                dead.append(f"{view}: {text}")
            if ms > STALL_MS:
                slow.append(f"{view}: {text} ({ms:.0f} ms)")
            rows.append(f"{view:32} {text[:40]:40} {ms:6.0f} ms  {what}")
            if win.stack.currentWidget() is not page and win.stack.currentWidget() is win.setup_flow:
                win.setup_flow.leave()
    report = "\n".join(["clicked:", *rows, f"over {SLOW_MS} ms:", *[r for r in rows if _ms(r) > SLOW_MS]])
    enc = sys.stdout.encoding or "utf-8"
    print(report.encode(enc, "replace").decode(enc))      # a cp1252 console can't show every character
    try:
        assert not errors, "exceptions:\n" + "\n".join(errors)
        assert not dead, "buttons with no visible effect:\n" + "\n".join(dead)
        assert not slow, "clicks that block the window:\n" + "\n".join(slow)
        assert len(rows) > 80
        assert not [x for x in started if x[0] in ("kill", "start")]     # the game itself was never touched
    finally:
        _settle(win)
