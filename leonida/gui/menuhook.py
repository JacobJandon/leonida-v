"""Leonida's window answers the in-game menu (leonida/menubridge.py) while it's open.

    menuhook.install(win)     # once, from MainWindow (gui/app.py)

Every few seconds a timer runs ``Bridge.poll`` on a background thread (building the menu's data reads files and can
take a second; installing a switched-on mod takes longer), never two at once. When the menu asked for Leonida after
the game closed, the window comes to the front. Only once the menu is installed; never on the offscreen platform
(tests, screenshots) and never with LEONIDA_NO_MENU_BRIDGE=1.
"""

from __future__ import annotations

import logging
import os
import threading

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

log = logging.getLogger("leonida.gui")
INTERVAL_MS = 3000


class MenuHook:
    def __init__(self, win, interval_ms: int = INTERVAL_MS):
        self.win = win
        self.busy = threading.Lock()
        self.bridge = None
        self.timer = QTimer(win)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def _installed(self) -> bool:
        try:
            from ..menubridge import MENU_ID

            return MENU_ID in self.win.session.log.installed_mods()
        except Exception:  # noqa: BLE001
            return False

    def tick(self) -> None:
        from .. import menubridge

        s = self.win.session
        if menubridge.want_window(s.state):
            self.win.showNormal()
            self.win.raise_()
            self.win.activateWindow()
        if not self._installed() or not self.busy.acquire(blocking=False):
            return
        if self.bridge is None or self.bridge.s is not s:
            self.bridge = menubridge.Bridge(s)
        bridge = self.bridge

        def work() -> None:
            try:
                for a in bridge.poll(menubridge.game_running()):
                    log.info("in-game menu: %s %s: %s", a.kind, a.status, a.message)
            except Exception:  # noqa: BLE001 - logged; the next round tries again
                log.exception("in-game menu bridge")
            finally:
                self.busy.release()

        threading.Thread(target=work, name="leonida-menu-bridge", daemon=True).start()


def install(win) -> MenuHook | None:
    if os.environ.get("LEONIDA_NO_MENU_BRIDGE") or QGuiApplication.platformName() == "offscreen":
        return None
    return MenuHook(win)
