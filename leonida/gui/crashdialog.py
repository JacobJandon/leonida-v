"""Leonida's log and crash handling for the window (the engine side is leonida/logs.py).

    crashdialog.install(app, state)     # once, in gui/app.py main(), after the QApplication exists

It:
  - starts the log with a per-session file (``logs.setup(state, session="gui")``; Debug mode from the config);
  - routes Qt's own messages (warnings, criticals) into the log as "leonida.qt";
  - logs what the user does as "leonida.gui": every button / action clicked (its text) and every page that's shown,
    through an application-wide event filter, so the pages themselves need no logging code;
  - turns an uncaught exception (main thread or a worker) into a friendly dialog, "Something went wrong", with
    "Copy report" (the error, the traceback and where the log is; secrets masked) and "Open logs folder".
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QtMsgType, QUrl, Signal, qInstallMessageHandler
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QAbstractButton, QApplication, QMessageBox, QStackedWidget, QWidget

from .. import PACK_NAME, logs

gui_log = logging.getLogger("leonida.gui")
qt_log = logging.getLogger("leonida.qt")
_QT_LEVELS = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}


def qt_message_handler(mode, context, message) -> None:
    where = f" ({context.file}:{context.line})" if getattr(context, "file", None) else ""
    qt_log.log(_QT_LEVELS.get(mode, logging.INFO), "%s%s", message, where)


class ActionLog(QObject):
    """Application-wide event filter: logs clicked buttons and the pages (children of a QStackedWidget) shown."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt naming
        try:
            kind = event.type()
            if kind == QEvent.Type.MouseButtonRelease and isinstance(obj, QAbstractButton) and obj.isEnabled() \
                    and obj.rect().contains(event.position().toPoint()):
                gui_log.info("click: %r (%s) in %s", obj.text() or obj.toolTip() or obj.objectName(),
                             type(obj).__name__, _where(obj))
            elif kind == QEvent.Type.KeyRelease and isinstance(obj, QAbstractButton) \
                    and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                gui_log.info("key-press: %r in %s", obj.text() or obj.objectName(), _where(obj))
            elif kind == QEvent.Type.Show and isinstance(obj, QWidget) and isinstance(obj.parentWidget(), QStackedWidget):
                gui_log.info("page: %s", type(obj).__name__)
            elif kind == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
                gui_log.debug("window shown: %s %r", type(obj).__name__, obj.windowTitle())
        except Exception:  # noqa: BLE001 - logging must never break the UI
            pass
        return False


def _where(w: QWidget) -> str:
    p = w.parentWidget()
    while p is not None and not (isinstance(p.parentWidget(), QStackedWidget) or p.isWindow()):
        p = p.parentWidget()
    return type(p).__name__ if p is not None else type(w.window()).__name__


class _Bridge(QObject):
    """Crash reports from any thread reach the dialog on the UI thread."""

    crashed = Signal(str)


def show_crash(text: str, state: Path | str, parent: QWidget | None = None) -> int:
    """The friendly crash dialog. Returns the button the user ended with (for tests)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(PACK_NAME)
    box.setText("Something went wrong")
    box.setInformativeText("Leonida V ran into an error it didn't expect. Nothing in your game was changed by "
                           "this message. You can copy a report for a bug report, or look at the logs.")
    box.setDetailedText(text)
    copy = box.addButton("Copy report", QMessageBox.ButtonRole.ActionRole)
    folder = box.addButton("Open logs folder", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    copy.clicked.disconnect()
    folder.clicked.disconnect()
    copy.clicked.connect(lambda: copy_report(text))
    folder.clicked.connect(lambda: open_logs(state))
    return box.exec()


def copy_report(text: str) -> None:
    QGuiApplication.clipboard().setText(logs.redact_secrets(text))
    gui_log.info("crash report copied to the clipboard")


def open_logs(state: Path | str) -> None:
    folder = logs.log_dir(state)
    folder.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("LEONIDA_NO_OPEN"):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    gui_log.info("opened the logs folder")


def install(app: QApplication, state: Path | str, debug: bool | None = None) -> QObject:
    """Set everything up (see the module docstring); returns the event filter (kept alive by the app)."""
    logs.setup(state, debug=debug, session="gui")
    qInstallMessageHandler(qt_message_handler)
    bridge = _Bridge(app)
    bridge.crashed.connect(lambda text: show_crash(text, state, QApplication.activeWindow()),
                           Qt.ConnectionType.QueuedConnection)
    logs.install_excepthooks(on_crash=bridge.crashed.emit)
    actions = ActionLog(app)
    app.installEventFilter(actions)
    app.setProperty("leonida_crash_bridge", bridge)  # keep them alive with the app
    app.setProperty("leonida_action_log", actions)
    gui_log.info("window starting (Qt %s, %s)", app.applicationVersion() or "?", sys.platform)
    return actions


def uninstall(app: QApplication) -> None:
    """Undo ``install`` (tests; a window that's closing for good)."""
    actions = app.property("leonida_action_log")
    if actions is not None:
        app.removeEventFilter(actions)
    app.setProperty("leonida_action_log", None)
    app.setProperty("leonida_crash_bridge", None)
    qInstallMessageHandler(None)
    logs.uninstall_excepthooks()
