"""One Leonida window per state folder.

Two windows on the same State would race on install-log.json, config.json and the browser profile (QtWebEngine locks
it). The first start holds a ``QLockFile`` in the state folder and listens on a ``QLocalServer`` named after that
folder; a second start finds the lock taken, tells the first one to come to the front, and exits.

Stale-safe: a lock left behind by a crashed Leonida names a process that no longer runs, so ``QLockFile`` takes it
over; the local server's name is removed before listening again.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

LOCK_NAME = "leonida-gui.lock"
MESSAGE = b"raise\n"


def server_name(state: Path) -> str:
    """The local server's name for a state folder (the same folder, however it is spelled, gives the same name)."""
    key = os.path.normcase(os.path.abspath(str(state)))
    return "LeonidaV-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


class SingleInstance(QObject):
    """``acquire()`` is True for the first Leonida on a state folder; ``activated`` fires there when another start
    asked it to come to the front."""

    activated = Signal()

    def __init__(self, state: Path, parent: QObject | None = None):
        super().__init__(parent)
        self.state = Path(state)
        self.name = server_name(self.state)
        self.lock: QLockFile | None = None
        self.server: QLocalServer | None = None
        self._got: dict[int, bytes] = {}   # what each connection sent so far
        self._socks: list[QLocalSocket] = []

    def acquire(self, wait_ms: int = 300) -> bool:
        self.state.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(self.state / LOCK_NAME))
        lock.setStaleLockTime(0)  # only "the owner's process is gone" makes a lock stale, never its age
        if not lock.tryLock(wait_ms):
            self.notify()
            return False
        self.lock = lock
        QLocalServer.removeServer(self.name)  # a crashed owner's leftover (Unix sockets; harmless on Windows)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if server.listen(self.name):
            server.newConnection.connect(self._incoming)
            self.server = server
        return True

    def notify(self, timeout_ms: int = 1500) -> bool:
        """Ask the running Leonida to come to the front. False when it doesn't answer (still starting up)."""
        if sys.platform == "win32":  # let the running window take the foreground from this process
            with contextlib.suppress(Exception):
                import ctypes

                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(timeout_ms):
            return False
        sock.write(MESSAGE)
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
        return True

    def _incoming(self) -> None:
        while self.server is not None and self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()  # a child of the server: deleted with it, never on its own
            self._socks.append(sock)
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._read(s))
            self._read(sock)

    def _read(self, sock: QLocalSocket) -> None:
        key = id(sock)
        got = self._got.get(key, b"") + bytes(sock.readAll())
        if MESSAGE.strip() in got:
            self._got[key] = b""  # one message, one wake-up
            self.activated.emit()
        else:
            self._got[key] = got

    def release(self) -> None:
        for sock in self._socks:  # quiet first: no handler may run while the server and its sockets are deleted
            sock.blockSignals(True)
            sock.abort()
        self._socks.clear()
        self._got.clear()
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()  # with its connections, once Qt is done with them
            self.server = None
        if self.lock is not None:
            self.lock.unlock()
            self.lock = None


def bring_to_front(win) -> None:
    """Show a window that may be minimized or behind others."""
    win.showNormal() if win.isMinimized() else win.show()
    win.raise_()
    win.activateWindow()
