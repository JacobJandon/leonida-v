from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

import pytest

from leonida.log import InstallLog
from leonida.manifest import load_manifest

os.environ.setdefault("LEONIDA_NO_OPEN", "1")
os.environ.setdefault("LEONIDA_FAKE_GPU", "")


def make_zip(path: Path, members: dict[str, bytes | str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data.encode() if isinstance(data, str) else data)
    return path


class AutoUI:
    """Non-interactive UI for tests. Callbacks simulate what a user/installer does."""

    def __init__(self, on_wait=None, on_launch=None, confirm=True, done=True):
        self.lines: list[str] = []
        self.on_wait = on_wait
        self.on_launch = on_launch
        self._confirm = confirm
        self._done = done

    def info(self, msg):
        self.lines.append(msg)

    def warn(self, msg):
        self.lines.append("WARN " + msg)

    def confirm(self, msg, default=True):
        return self._confirm

    def wait_done(self, title, steps, folder):
        if self.on_wait:
            self.on_wait(folder)
        return self._done

    def launch(self, path):
        if self.on_launch:
            self.on_launch(path)


@pytest.fixture
def manifest():
    return load_manifest()


@pytest.fixture
def game(tmp_path: Path) -> Path:
    g = tmp_path / "Grand Theft Auto V Enhanced"
    (g / "update").mkdir(parents=True)
    (g / "x64").mkdir()
    (g / "GTA5_Enhanced.exe").write_bytes(b"MZ fake exe")
    (g / "bink2w64.dll").write_bytes(b"original bink")
    (g / "update" / "update.rpf").write_bytes(b"RPF7" * 100)
    return g


@pytest.fixture
def state(tmp_path: Path) -> Path:
    s = tmp_path / "state"
    s.mkdir()
    return s


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    d = tmp_path / "Downloads" / "LeonidaV"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def log(state: Path) -> InstallLog:
    return InstallLog(state / "install-log.json")


# ------------------------------------------------------------------------------------- Qt (GUI tests)
def flush_deletes(rounds: int = 3) -> None:
    """Really delete everything passed to deleteLater(). processEvents() alone never runs DeferredDelete events,
    and a QWebEngine window still waiting for its deferred delete when the interpreter exits crashes it (exit 139)."""
    from PySide6.QtCore import QCoreApplication, QEvent

    for _ in range(rounds):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()


def qt_shutdown() -> None:
    """End-of-session Qt teardown, in the order the real app's exit uses: stop worker threads, wait for picture
    jobs, close and delete every window (BrowserWindow deletes its page before its profile), flush the deletes."""
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    if "leonida.gui.workers" in sys.modules:
        sys.modules["leonida.gui.workers"].stop_all_workers(5000)
    QThreadPool.globalInstance().waitForDone(5000)
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    flush_deletes()


@pytest.fixture(scope="session")
def qt_app():
    """The one QApplication for the whole run (QtWebEngine needs AA_ShareOpenGLContexts set before it exists)."""
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    if QCoreApplication.instance() is None:
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _own_state_and_closed_logs(monkeypatch, tmp_path_factory):
    """No test writes Leonida's log (or any state) into the real %LOCALAPPDATA%\\LeonidaV, and none runs the real RPF
    helper: the default state folder is a temp one and the helper is tests/fake_rpf_helper.py, unless a test sets
    its own (tests of the default path / a missing helper set or delete the variable themselves). The log's
    file handlers and crash hooks are closed after every test, so temp folders can be deleted on Windows."""
    if not os.environ.get("LEONIDA_STATE_DIR"):
        monkeypatch.setenv("LEONIDA_STATE_DIR", str(tmp_path_factory.mktemp("default-state")))
    if not os.environ.get("LEONIDA_RPF_HELPER"):  # never the real LeonidaRpf.exe (CodeWalker) in a test
        monkeypatch.setenv("LEONIDA_RPF_HELPER", str(Path(__file__).resolve().parent / "fake_rpf_helper.py"))
    yield
    from leonida import logs

    if "leonida.gui.crashdialog" in sys.modules:  # a test ran the window's main(): its event filter and Qt handler
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is not None:
            sys.modules["leonida.gui.crashdialog"].uninstall(QApplication.instance())
    logs.uninstall_excepthooks()
    logs.shutdown()


@pytest.fixture(autouse=True)
def _qt_app_look_restored():
    """A test that runs main() applies the app-wide theme; put the look back afterwards. A leftover app stylesheet
    makes every later widget polish against it, which slows the rest of the suite down several times."""
    app = None
    if "PySide6.QtWidgets" in sys.modules:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
    saved = (app.styleSheet(), app.palette(), app.font(), app.style().name()) if app is not None else None
    yield
    if saved is None:
        return
    sheet, palette, font, style = saved
    if app.styleSheet() != sheet:
        app.setStyleSheet(sheet)
    if app.style().name() != style and style:
        app.setStyle(style)
    app.setPalette(palette)
    app.setFont(font)


@pytest.fixture(autouse=True)
def _no_real_defender(monkeypatch):
    """Tests never run the PC's Windows Defender: installs see "not scanned" unless a test sets the stub Defender
    (tests/test_quarantine.py)."""
    monkeypatch.setenv("LEONIDA_DEFENDER", "off")
    # nor look at the PC's running processes: online-safe refuses while GTA runs (tests/test_online_safe.py)
    monkeypatch.setattr("leonida.onlinesafe.game_running", lambda names=(): [])
    # the launcher's Playing / Stop watch sees no game either (tests/test_gamestate.py drives it by hand)
    monkeypatch.setattr("leonida.gamestate.process_names", lambda: set())


@pytest.fixture(scope="session", autouse=True)
def _qt_clean_exit():
    """Whatever GUI tests ran, leave Qt with no running threads and no pending deletes before Python exits."""
    yield
    qt_shutdown()


# ------------------------------------------------------------------------------------- CI annotations
def _annotation(text: str) -> str:
    """Escape a value for a GitHub Actions workflow command (one line)."""
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """On GitHub Actions, list each failure as an ::error annotation. Annotations are public, while the job log of
    a public repo needs a signed-in GitHub account, so CI failures can be read without one."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    reports = terminalreporter.stats.get("failed", []) + terminalreporter.stats.get("error", [])
    for rep in reports[:20]:
        path, line, _ = rep.location if rep.location else ("", 0, "")
        crash = getattr(getattr(rep, "longrepr", None), "reprcrash", None)
        msg = crash.message if crash is not None else str(rep.longrepr)[-600:]
        terminalreporter.write_line(
            f"::error file=tests/{Path(path).name},line={(line or 0) + 1},"
            f"title={_annotation(rep.nodeid)[:200]}::{_annotation(msg)[:900]}")
