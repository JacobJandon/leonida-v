"""The window's log and crash handling (leonida/gui/crashdialog.py): clicks and pages in the log, Qt messages, the
"Something went wrong" dialog with Copy report / Open logs folder."""

from __future__ import annotations

import logging
import sys
import threading

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, Qt, QtMsgType  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget  # noqa: E402

from leonida import logs  # noqa: E402
from leonida.gui import crashdialog as C  # noqa: E402


@pytest.fixture
def installed(qt_app, tmp_path):
    actions = C.install(qt_app, tmp_path, debug=True)
    yield qt_app, tmp_path
    C.uninstall(qt_app)
    assert qt_app.property("leonida_action_log") is None and actions is not None


def log_text(state) -> str:
    logs.shutdown()
    return (logs.log_dir(state) / logs.MAIN_LOG).read_text(encoding="utf-8")


def test_clicks_and_pages_are_logged(installed):
    app, state = installed
    win = QWidget()
    lay = QVBoxLayout(win)
    stack = QStackedWidget()
    first, second = QLabel("one"), QLabel("two")
    stack.addWidget(first)
    stack.addWidget(second)
    lay.addWidget(stack)
    btn = QPushButton("Install next")
    btn.clicked.connect(lambda: stack.setCurrentIndex(1))
    lay.addWidget(btn)
    win.show()
    QApplication.processEvents()
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    QTest.keyClick(btn, Qt.Key.Key_Space)
    QApplication.processEvents()
    sess = logs.session_log()
    text = log_text(state)
    assert "click: 'Install next' (QPushButton)" in text and "key-press: 'Install next'" in text
    assert "page: QLabel" in text and "window starting" in text
    assert sess.exists() and "Install next" in sess.read_text(encoding="utf-8")
    win.close()


def test_qt_messages_go_to_the_log(installed):
    _app, state = installed

    class Ctx:
        file, line = "qwidget.cpp", 42

    C.qt_message_handler(QtMsgType.QtWarningMsg, Ctx(), "QWidget::setLayout: already has a layout")
    C.qt_message_handler(QtMsgType.QtInfoMsg, object(), "plain info")
    text = log_text(state)
    assert "WARNING  leonida.qt" in text and "already has a layout (qwidget.cpp:42)" in text and "plain info" in text


def test_crash_in_a_thread_reaches_the_dialog(installed, monkeypatch):
    _app, state = installed
    shown = []
    monkeypatch.setattr(C, "show_crash", lambda text, st, parent=None: shown.append((text, st)))
    # install() connected its bridge to the real show_crash; reconnect to the patched one
    bridge = _app.property("leonida_crash_bridge")
    bridge.crashed.disconnect()
    bridge.crashed.connect(lambda text: C.show_crash(text, state), Qt.ConnectionType.QueuedConnection)
    t = threading.Thread(target=lambda: (_ for _ in ()).throw(ValueError("worker broke")), name="dl-worker")
    t.start()
    t.join()
    for _ in range(5):
        QApplication.processEvents()
    assert shown and "ValueError: worker broke" in shown[0][0] and "thread dl-worker" in shown[0][0]
    try:
        raise RuntimeError("main thread")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    QApplication.processEvents()
    assert any("RuntimeError: main thread" in s for s, _ in shown)
    assert "Unhandled exception in thread dl-worker" in log_text(state)


def test_dialog_buttons(qt_app, tmp_path, monkeypatch):
    logs.setup(tmp_path)
    pressed = []

    def fake_exec(box):
        assert box.text() == "Something went wrong" and "Traceback" in box.detailedText()
        for b in box.buttons():
            if b.text() in ("Copy report", "Open logs folder"):
                b.click()
                pressed.append(b.text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    C.show_crash("Traceback ...\nValueError: x token=abc", tmp_path)
    assert pressed == ["Copy report", "Open logs folder"]
    clip = QGuiApplication.clipboard().text()
    assert "ValueError: x" in clip and "abc" not in clip and "token=<redacted>" in clip
    assert logs.log_dir(tmp_path).is_dir()
    assert "crash report copied" in log_text(tmp_path)


def test_worker_failures_are_logged_with_traceback(qt_app, tmp_path):
    from leonida.gui.workers import _Worker

    logs.setup(tmp_path)

    def broken():
        raise KeyError("missing mod")

    w = _Worker(broken, False)
    got = []
    w.failed.connect(got.append)
    w.run()
    assert got == ["'missing mod'"]
    text = log_text(tmp_path)
    assert "background task" in text and "broken" in text and "KeyError: 'missing mod'" in text
    logging.getLogger("leonida").handlers.clear()
