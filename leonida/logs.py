"""Leonida's own log: what it did and why, for working out problems on other people's PCs.

    logs.setup(state, debug=None)        # once per process (the CLI's main(), the GUI's main())
    log = logging.getLogger(__name__)    # in every module: leonida.installer, leonida.rpf, ...
    logs.log_dir(state)                  # <state>/logs
    logs.host(url)                       # "www.gta5-mods.com": log hosts, never full URLs with tokens

Files in ``<state>/logs``:
  - ``leonida.log``: everything, rotating (5 files of 2 MB);
  - ``session-<time>-<name>.log``: one per GUI session (``setup(..., session="gui")``), the last 10 kept.

Levels: INFO always, DEBUG in debug mode (``setup(debug=True)``, ``leonida --debug``, ``LEONIDA_DEBUG=1``, or
Settings > Debug mode, which is ``config.json`` "debug"). The CLI's printed output doesn't change: the log is in
addition to it.

Privacy: a filter on every handler masks what looks like a secret (``token=...``, ``key=...``, ``password=...``,
``Authorization: ...``, ``Cookie: ...``, session ids in URLs). Modules log URL hosts, not URLs, and never cookies,
logins or the browser profile. The user's name and home folder stay in this local log; ``leonida report``
(diagnostics.py) replaces them before anything leaves the PC.

Crashes: ``install_excepthooks`` routes ``sys.excepthook`` and ``threading.excepthook`` into the log (CRITICAL, with
the traceback). ``on_crash(text)`` lets the GUI show its dialog; the CLI prints where the log is.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

LOG_DIR = "logs"
MAIN_LOG = "leonida.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 4                     # leonida.log + 4 rotated files = 5 x 2 MB
SESSIONS_KEPT = 10
FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(threadName)s] %(message)s"
ROOT = "leonida"
ENV = "LEONIDA_DEBUG"

_SECRET = re.compile(
    r"(?i)(\b(?:access_?token|refresh_?token|token|api_?key|key|secret|password|passwd|pwd|auth|session_?id|sid|"
    r"sig|signature|cookie|set-cookie|authorization|x-api-key|nxm_?key)\b\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s&;,\"']+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]{8,}")


class _State:
    handlers: list[logging.Handler] = []
    main_file: Path | None = None
    session_file: Path | None = None
    hooks_installed = False
    on_crash: Callable[[str], None] | None = None
    prev_excepthook = None
    prev_thread_hook = None


def redact_secrets(text: str) -> str:
    """Mask what looks like a token, key, password or cookie value."""
    text = _BEARER.sub(lambda m: m.group(1) + " <redacted>", text)
    return _SECRET.sub(lambda m: m.group(1) + "<redacted>", text)


class SecretFilter(logging.Filter):
    """Masks secrets in every record (message and arguments, once formatted)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string still gets logged
            msg = str(record.msg)
        clean = redact_secrets(msg)
        if clean != msg or record.args:
            record.msg, record.args = clean, None
        return True


def log_dir(state: Path | str) -> Path:
    return Path(state) / LOG_DIR


def debug_wanted(state: Path | str | None = None, flag: bool | None = None) -> bool:
    """Debug mode: the flag (``--debug``), else LEONIDA_DEBUG, else config.json "debug"."""
    if flag:
        return True
    if os.environ.get(ENV, "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    if state is not None:
        try:
            from .paths import Config

            return bool(Config.load(Path(state)).debug)
        except Exception:  # noqa: BLE001 - a broken config.json mustn't stop the log
            return False
    return False


def setup(state: Path | str, debug: bool | None = None, session: str | None = None) -> logging.Logger:
    """(Re)configure the "leonida" logger: rotating leonida.log, plus a per-session file when ``session`` is given.
    Safe to call again (e.g. when Debug mode is switched on): the old handlers are replaced."""
    logger = logging.getLogger(ROOT)
    for h in _State.handlers:
        logger.removeHandler(h)
        h.close()
    _State.handlers = []
    folder = log_dir(state)
    on = debug_wanted(state, debug)
    logger.setLevel(logging.DEBUG if on else logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter(FORMAT)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        main = logging.handlers.RotatingFileHandler(folder / MAIN_LOG, maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                                    encoding="utf-8", delay=True)
        handlers: list[logging.Handler] = [main]
        _State.main_file = folder / MAIN_LOG
        _State.session_file = None
        if session:
            name = re.sub(r"[^A-Za-z0-9_-]+", "-", session)[:20] or "session"
            _prune_sessions(folder, SESSIONS_KEPT - 1)  # room for this session's file
            path = folder / f"session-{time.strftime('%Y%m%d-%H%M%S')}-{name}.log"
            handlers.append(logging.FileHandler(path, encoding="utf-8"))
            _State.session_file = path
    except OSError:
        handlers = [logging.NullHandler()]  # a read-only state folder: no log rather than no Leonida
        _State.main_file = None
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(SecretFilter())
        logger.addHandler(h)
    _State.handlers = handlers
    from . import __version__

    logger.info("Leonida V %s, Python %s, %s, debug mode %s", __version__, sys.version.split()[0], sys.platform,
                "on" if on else "off")
    return logger


def _prune_sessions(folder: Path, keep: int) -> None:
    files = sorted(folder.glob("session-*.log"))
    for old in files[:max(len(files) - keep, 0)]:
        try:
            old.unlink()
        except OSError:
            continue


def main_log() -> Path | None:
    """The leonida.log in use (None before ``setup``)."""
    return _State.main_file


def session_log() -> Path | None:
    return _State.session_file


def host(url: str | None) -> str:
    """Only the host of a URL (no path, no query, no credentials), for the log."""
    try:
        return urlsplit(url or "").hostname or "?"
    except ValueError:
        return "?"


# ------------------------------------------------------------------------------------------- crashes
def crash_text(exc_type, exc, tb, where: str = "") -> str:
    from . import __version__

    lines = [f"Leonida V {__version__} crashed{(' in ' + where) if where else ''}: {exc_type.__name__}: {exc}", ""]
    lines += traceback.format_exception(exc_type, exc, tb)
    if _State.main_file:
        lines += ["", f"Log: {_State.main_file}"]
    return redact_secrets("".join(ln if ln.endswith("\n") else ln + "\n" for ln in lines))


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        (_State.prev_excepthook or sys.__excepthook__)(exc_type, exc, tb)
        return
    logging.getLogger(ROOT).critical("Unhandled exception", exc_info=(exc_type, exc, tb))
    text = crash_text(exc_type, exc, tb)
    if _State.on_crash:
        try:
            _State.on_crash(text)
            return
        except Exception:  # noqa: BLE001 - the dialog failing must not hide the crash
            pass
    (_State.prev_excepthook or sys.__excepthook__)(exc_type, exc, tb)
    if _State.main_file:
        print(f"\nLeonida V logged the details in {_State.main_file}", file=sys.stderr)


def _thread_hook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread else "thread"
    logging.getLogger(ROOT).critical("Unhandled exception in thread %s", name,
                                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    if _State.on_crash:
        try:
            _State.on_crash(crash_text(args.exc_type, args.exc_value, args.exc_traceback, f"thread {name}"))
            return
        except Exception:  # noqa: BLE001
            pass
    if _State.prev_thread_hook:
        _State.prev_thread_hook(args)


def install_excepthooks(on_crash: Callable[[str], None] | None = None) -> None:
    """Route uncaught exceptions (main thread and other threads) into the log; ``on_crash(text)`` is called with a
    report text (the GUI shows it in its dialog). Installing again only changes ``on_crash``."""
    _State.on_crash = on_crash
    if _State.hooks_installed:
        return
    _State.prev_excepthook, _State.prev_thread_hook = sys.excepthook, threading.excepthook
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    _State.hooks_installed = True


def uninstall_excepthooks() -> None:
    if not _State.hooks_installed:
        return
    sys.excepthook = _State.prev_excepthook or sys.__excepthook__
    threading.excepthook = _State.prev_thread_hook or threading.__excepthook__
    _State.hooks_installed = False
    _State.on_crash = None


def shutdown() -> None:
    """Close the file handlers (tests, and before zipping the logs)."""
    logger = logging.getLogger(ROOT)
    for h in _State.handlers:
        h.flush()
        logger.removeHandler(h)
        h.close()
    _State.handlers = []
