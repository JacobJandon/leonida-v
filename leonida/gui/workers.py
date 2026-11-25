"""Run slow work (downloads, installs) off the UI thread, and let that work ask the UI thread for dialogs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QObject, Qt, QThread, Signal, Slot

STOP_TIMEOUT_MS = 8000  # how long app exit waits for running workers (a download/install step) to finish

# Every running worker thread, so app exit can stop and wait for them: a QThread destroyed while it still runs
# aborts the whole process ("QThread: Destroyed while thread is still running").
_live: set[QThread] = set()
_hooked_app: list[QCoreApplication] = []


def _hook_app_exit() -> None:
    app = QCoreApplication.instance()
    if app is not None and (not _hooked_app or _hooked_app[0] is not app):
        _hooked_app[:] = [app]
        app.aboutToQuit.connect(stop_all_workers)


def live_workers() -> list[QThread]:
    return [t for t in list(_live) if t.isRunning()]


def stop_all_workers(timeout_ms: int = STOP_TIMEOUT_MS) -> list[QThread]:
    """Ask every running worker thread to stop and wait for it (shared deadline). Returns those still running.

    Connected to QApplication.aboutToQuit by start_worker(). A worker blocked in a long download can't be
    interrupted; it gets until the deadline, so closing the app never hangs for long."""
    deadline = QDeadlineTimer(timeout_ms)
    for t in list(_live):
        t.requestInterruption()
        t.quit()
    left = []
    for t in list(_live):
        if not t.wait(deadline):
            left.append(t)
    return left


class _Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, fn: Callable[..., Any], pass_progress: bool):
        super().__init__()
        self.fn = fn
        self.pass_progress = pass_progress

    @Slot()
    def run(self) -> None:
        try:
            res = self.fn(self.progress.emit) if self.pass_progress else self.fn()
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            logging.getLogger("leonida.gui").error("background task %s failed", getattr(self.fn, "__qualname__", "?"),
                                                   exc_info=True)  # the traceback goes into the log
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.finished.emit(res)


class _Relay(QObject):
    """Lives on the UI thread so the callbacks below always run there (a bare lambda would run on the worker)."""

    def __init__(self, parent: QObject, on_done, on_fail, on_progress):
        super().__init__(parent)
        self.on_done, self.on_fail, self.on_progress = on_done, on_fail, on_progress

    @Slot(object)
    def done(self, res: Any) -> None:
        if self.on_done:
            self.on_done(res)

    @Slot(str)
    def fail(self, msg: str) -> None:
        if self.on_fail:
            self.on_fail(msg)

    @Slot(object)
    def progress(self, payload: Any) -> None:
        if self.on_progress:
            self.on_progress(payload)


def start_worker(parent: QObject, fn: Callable[..., Any], *, on_done=None, on_fail=None, on_progress=None,
                 pass_progress: bool = False) -> QThread:
    """Run ``fn()`` (or ``fn(progress_emit)``) on a new QThread; callbacks run on the UI thread."""
    thread = QThread(parent)
    worker = _Worker(fn, pass_progress)
    relay = _Relay(parent, on_done, on_fail, on_progress)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(relay.done)
    worker.failed.connect(relay.fail)
    worker.progress.connect(relay.progress)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    keep = getattr(parent, "_leonida_workers", None)
    if keep is None:
        keep = set()
        parent._leonida_workers = keep  # type: ignore[attr-defined]
    entry = (thread, worker, relay)
    keep.add(entry)
    _live.add(thread)
    _hook_app_exit()

    def cleanup() -> None:
        keep.discard(entry)
        _live.discard(thread)
        worker.deleteLater()
        relay.deleteLater()
        thread.deleteLater()

    thread.finished.connect(cleanup)
    thread.start()
    return thread


class MainThreadCaller(QObject):
    """``call(fn)`` runs fn on the UI thread and returns its result, blocking the calling worker thread.

    Create it on the UI thread. Called from the UI thread itself, it just runs fn.
    """

    _call = Signal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._call.connect(self._run, Qt.ConnectionType.BlockingQueuedConnection)

    @Slot(object)
    def _run(self, box: dict) -> None:
        try:
            box["result"] = box["fn"]()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the worker
            box["error"] = exc

    def call(self, fn: Callable[[], Any]) -> Any:
        if QThread.currentThread() == self.thread():
            return fn()
        box: dict = {"fn": fn}
        self._call.emit(box)
        if "error" in box:
            raise box["error"]
        return box.get("result")
