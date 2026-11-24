"""Clean Qt shutdown: worker threads, picture jobs and the QtWebEngine browser must not crash the process at exit.

Regression tests for the exit-code-139 crash after the GUI tests (pending QtWebEngine deletes at interpreter exit,
QThreads destroyed while running, the browser profile released before its page).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from leonida.gui import workers  # noqa: E402
from leonida.gui.images import ImageLoader  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def app(qt_app):
    return qt_app


def test_stop_all_workers_waits_for_running_threads(app):
    gate = threading.Event()
    th = workers.start_worker(app, lambda: gate.wait(5))
    assert th in workers.live_workers()
    assert workers._hooked_app and workers._hooked_app[0] is QCoreApplication.instance()
    threading.Timer(0.2, gate.set).start()
    assert workers.stop_all_workers(5000) == []
    assert not th.isRunning()
    QCoreApplication.processEvents()
    assert th not in workers.live_workers()


def test_stop_all_workers_gives_up_at_the_deadline(app):
    gate = threading.Event()
    th = workers.start_worker(app, lambda: gate.wait(5))
    try:
        t0 = time.monotonic()
        assert workers.stop_all_workers(100) == [th]
        assert time.monotonic() - t0 < 2
    finally:
        gate.set()
        assert workers.stop_all_workers(5000) == []


def test_exit_hook_is_connected_once(app):
    workers._hook_app_exit()
    workers._hook_app_exit()
    assert workers._hooked_app == [QCoreApplication.instance()]


def test_image_loader_shutdown_drops_queue_and_waits(app, tmp_path):
    loader = ImageLoader(tmp_path / "img")
    loader.pool.setMaxThreadCount(1)
    started, ran = threading.Event(), []

    def slow():
        started.set()
        time.sleep(0.3)
        ran.append("slow")

    loader.pool.start(slow)
    loader.pool.start(lambda: ran.append("queued"))
    assert started.wait(5)
    assert loader.shutdown() is True
    assert ran == ["slow"]  # the queued job was dropped, the running one finished


def _run(script: str, timeout: int = 120) -> subprocess.CompletedProcess:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LEONIDA_NO_NET="1", LEONIDA_NO_OPEN="1",
               PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-c", textwrap.dedent(script)], capture_output=True, text=True,
                          timeout=timeout, env=env, cwd=str(ROOT))


def test_app_exit_with_running_worker_and_pictures_is_clean(tmp_path):
    """Like closing Leonida while a download runs: exec() returns, the worker is waited for, exit code 0."""
    r = _run(f"""
        import sys, time
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMainWindow
        from leonida.gui.workers import start_worker, live_workers
        from leonida.gui.images import ImageLoader
        app = QApplication([])
        win = QMainWindow(); win.show()
        start_worker(win, lambda: time.sleep(1.0))
        loader = ImageLoader(r"{tmp_path / 'img'}", win)
        loader.pool.start(lambda: time.sleep(0.5))
        QTimer.singleShot(200, app.quit)
        rc = app.exec()
        print("live", len(live_workers()), "rc", rc)
    """)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "live 0 rc 0" in r.stdout
    assert "Destroyed while thread is still running" not in r.stderr


@pytest.mark.webengine
def test_release_web_deletes_page_then_profile(app, tmp_path):
    import shiboken6

    pytest.importorskip("PySide6.QtWebEngineWidgets")
    from conftest import flush_deletes

    from leonida.gui.browser import BrowserWindow

    bw = BrowserWindow(tmp_path / "state", tmp_path / "dl")
    page, profile = bw.page, bw.profile
    kids = bw.children()
    assert kids.index(bw.view) < kids.index(profile)  # view (owns the page) is deleted before the profile
    assert page.profile() is profile
    gone = []
    page.destroyed.connect(lambda: gone.append("page"))
    profile.destroyed.connect(lambda: gone.append("profile"))
    bw.release_web()
    assert gone == ["page", "profile"]
    assert bw.page is None and bw.profile is None
    assert not shiboken6.isValid(page) and not shiboken6.isValid(profile)
    bw.release_web()  # idempotent
    bw.deleteLater()
    flush_deletes()


@pytest.mark.webengine
def test_browser_page_goes_before_profile_and_app_exit_is_clean(tmp_path):
    """The real QtWebEngine browser open (a page loaded) when the app quits: no crash, profile released."""
    r = _run(f"""
        import time
        from PySide6.QtCore import QCoreApplication, Qt, QTimer, QUrl
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        import PySide6.QtWebEngineWidgets
        from PySide6.QtWidgets import QApplication
        from leonida.gui.browser import BrowserWindow
        app = QApplication([])
        bw = BrowserWindow(r"{tmp_path / 'state'}", r"{tmp_path / 'dl'}")
        kids = bw.children()
        print("order", kids.index(bw.view) < kids.index(bw.profile))
        done = []
        bw.view.loadFinished.connect(done.append)
        bw.view.load(QUrl("data:text/html,<title>x</title>hi"))
        end = time.monotonic() + 30
        while not done and time.monotonic() < end:
            app.processEvents(); time.sleep(0.01)
        print("loaded", done)
        bw.show()
        QTimer.singleShot(100, app.quit)
        app.exec()
        print("released", bw.profile is None and bw.page is None)
        bw.release_web()  # idempotent
    """)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "order True" in r.stdout and "loaded [True]" in r.stdout and "released True" in r.stdout
