"""One Leonida window per State folder, and Start-Leonida.bat not holding a caller's output pipe open."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from conftest import flush_deletes  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from leonida.gui.single import LOCK_NAME, SingleInstance, bring_to_front, server_name  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SECOND_START = """
import sys
sys.path.insert(0, {root!r})
from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])
from leonida.gui.single import SingleInstance
print("first" if SingleInstance({state!r}).acquire(wait_ms=50) else "second", flush=True)
"""


def second_start(state: Path) -> subprocess.Popen:
    """Another Leonida process starting on ``state`` (prints "second" when it backs off)."""
    return subprocess.Popen([sys.executable, "-c", SECOND_START.format(root=str(ROOT), state=str(state))],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def spin(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        QApplication.processEvents()
        time.sleep(0.01)
    return cond()


def test_second_start_wakes_the_first_and_backs_off(qt_app, tmp_path):
    first = SingleInstance(tmp_path / "State")
    assert first.acquire()
    woken = []
    first.activated.connect(lambda: woken.append(1))
    assert SingleInstance(tmp_path / "State" / ".." / "State").name == first.name  # same folder, other spelling
    proc = second_start(tmp_path / "State")
    assert spin(lambda: proc.poll() is not None, 60), "the second start didn't end"
    assert proc.stdout.read().strip() == "second", proc.stderr.read()
    assert spin(lambda: woken)                                     # the running one is asked to come to the front
    other = SingleInstance(tmp_path / "OtherState")                # another State: its own Leonida
    assert other.acquire() and other.name != first.name
    other.release()
    first.release()
    third = SingleInstance(tmp_path / "State")                     # closed normally: the next start is the first
    assert third.acquire()
    third.release()
    flush_deletes()                                                # its server and sockets, gone for good


def test_a_crashed_leonidas_lock_is_taken_over(qt_app, tmp_path):
    state = tmp_path / "State"
    child = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {str(ROOT)!r})
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication([])
        from leonida.gui.single import SingleInstance
        g = SingleInstance({str(state)!r})
        print("acquired" if g.acquire() else "busy", flush=True)
        os._exit(3)   # a crash: no unlock, no cleanup
    """)
    out = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "acquired", out.stderr
    assert (state / LOCK_NAME).exists()                            # left behind by the dead process
    again = SingleInstance(state)
    assert again.acquire(wait_ms=50)                               # its owner is gone: stale, taken over
    again.release()


class _Window:
    """Records what bring_to_front asks of the window (minimizing a real window aborts Qt's offscreen platform)."""

    def __init__(self, minimized):
        self.minimized, self.calls = minimized, []

    def isMinimized(self):  # noqa: N802
        return self.minimized

    def __getattr__(self, name):
        return lambda: self.calls.append(name)


@pytest.mark.parametrize(("minimized", "first"), [(True, "showNormal"), (False, "show")])
def test_bring_to_front_restores_and_raises(minimized, first):
    w = _Window(minimized)
    bring_to_front(w)
    assert w.calls == [first, "raise_", "activateWindow"]


def test_main_ends_at_once_when_leonida_already_runs(qt_app, tmp_path, monkeypatch):
    import leonida.gui.app as A

    monkeypatch.setenv("LEONIDA_STATE_DIR", str(tmp_path / "State"))
    running = SingleInstance(tmp_path / "State")
    assert running.acquire()
    told = []
    monkeypatch.setattr(A, "MainWindow", lambda *a, **k: pytest.fail("a second window was opened"))
    monkeypatch.setattr("leonida.gui.single.SingleInstance.notify", lambda self, timeout_ms=1500: told.append(1))
    assert A.main() == 0 and told                                  # no window: it only told the running one
    running.release()


def test_server_name_is_per_folder(tmp_path):
    assert server_name(tmp_path / "a") != server_name(tmp_path / "b")
    assert server_name(tmp_path / "a").startswith("LeonidaV-")


def test_detach_usage_and_errors(tmp_path, capsys):
    from leonida import detach

    assert detach.main([]) == 2 and "usage" in capsys.readouterr().err
    assert detach.main([str(tmp_path / "nope.exe")]) == 1 and "Could not start" in capsys.readouterr().err
    marker = tmp_path / "ran.txt"
    assert detach.main([sys.executable, "-c", f"open({str(marker)!r}, 'w').write('x')"]) == 0
    end = time.monotonic() + 30
    while not marker.exists() and time.monotonic() < end:
        time.sleep(0.05)
    time.sleep(0.2)
    assert marker.read_text() == "x"


@pytest.mark.skipif(sys.platform != "win32", reason="Start-Leonida.bat is Windows only")
def test_start_leonida_does_not_keep_a_capturing_caller_waiting(tmp_path):
    """The bat's GUI start line, with the GUI swapped for a program that runs 20 s: a caller capturing the output
    must get it back at once, not when the program ends."""
    venv_py, gui = '"%VENV%\\Scripts\\python.exe"', '"%VENV%\\Scripts\\leonida-gui.exe"'
    data = (ROOT / "Start-Leonida.bat").read_bytes().decode("utf-8")
    (line,) = [x for x in data.splitlines() if gui in x and not x.startswith("rem")]
    assert line.startswith(f"{venv_py} -m leonida.detach {gui}")
    line = line.split(" || ")[0].replace(venv_py, f'"{sys.executable}"')
    line = line.replace(gui, f'"{sys.executable}" -c "import time; time.sleep(20)"')
    bat = tmp_path / "start.bat"
    bat.write_bytes(("@echo off\r\necho starting\r\n" + line + "\r\nexit /b 0\r\n").encode())
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    t0 = time.monotonic()
    p = subprocess.run(["cmd", "/d", "/c", str(bat)], capture_output=True, text=True, timeout=60, env=env)
    assert p.returncode == 0 and "starting" in p.stdout, p.stdout + p.stderr
    assert time.monotonic() - t0 < 10, "the started program kept the captured output open"


def _staged_kit(tmp_path: Path, lock_pid: int | None) -> tuple[Path, dict]:
    kit = tmp_path / "Leonida"
    (kit / "leonida-v").mkdir(parents=True)
    (kit / "leonida-v" / "old.txt").write_text("old")
    (kit / "leonida-v.new").mkdir()
    (kit / "leonida-v.new" / "pyproject.toml").write_text("[project]")
    (kit / "leonida-v.new" / ".leonida-update-ready").write_text("9.9.9")
    (kit / "State").mkdir()
    if lock_pid is not None:  # QLockFile's format: pid, app name, host name
        (kit / "State" / LOCK_NAME).write_text(f"{lock_pid}\nleonida-gui\nhost\n")
    (kit / "Start-Leonida.bat").write_bytes((ROOT / "Start-Leonida.bat").read_bytes())
    return kit, dict(os.environ, LEONIDA_SWAP_ONLY="1", LEONIDA_NO_SHORTCUTS="1")


@pytest.mark.skipif(sys.platform != "win32", reason="Start-Leonida.bat is Windows only")
@pytest.mark.parametrize("alive", [True, False])
def test_update_swap_waits_only_for_this_kits_running_leonida(tmp_path, alive):
    """The swap waits while the process in this kit's State lock runs (not for any Leonida on the PC: the owner's
    own window doesn't block another kit), and a crashed window's stale lock doesn't block it."""
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    kit, env = _staged_kit(tmp_path, os.getpid() if alive else int(dead.stdout))
    p = subprocess.run(["cmd", "/d", "/c", str(kit / "Start-Leonida.bat")], cwd=kit, env=env, capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    if alive:
        assert "still running" in p.stdout and (kit / "leonida-v.new").is_dir()
    else:
        assert "Updated." in p.stdout and not (kit / "leonida-v.new").exists()
