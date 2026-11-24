"""Self-check for the frozen GUI build. Bundled into LeonidaV.exe but only reachable when LEONIDA_SELFTEST is set.

It opens the main window, then Leonida's built-in browser (QtWebEngine) on an inline page that runs JavaScript,
and exits with 0 when everything worked (1 = a check failed, 2 = timeout). The exe is windowed, so the result is
also written as JSON to LEONIDA_SELFTEST_OUT (default: <state dir>/selftest.json).
Optional: LEONIDA_SELFTEST_URL=https://... additionally loads a real page (needs network).

Run it with build/build_exe.py --selftest, which points the state and download folders at a fresh temp folder.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

TIMEOUT_MS = 90_000
PAGE = ("data:text/html,<html><head><title>loading</title></head><body>"
        "<script>document.title='leonida-js-'+(40+2)</script></body></html>")
EXPECTED_TITLE = "leonida-js-42"


def run() -> int:
    from PySide6.QtCore import Qt, QTimer, QUrl
    from PySide6.QtWidgets import QApplication

    from leonida import __version__
    from leonida.paths import state_dir

    out = Path(os.environ.get("LEONIDA_SELFTEST_OUT") or state_dir() / "selftest.json")
    result: dict = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "checks": {}, "ok": False}
    checks = result["checks"]

    def finish(code: int) -> None:
        result["ok"] = code == 0
        result["exit"] = code
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        QApplication.instance().exit(code)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)

    try:
        base = Path(getattr(sys, "_MEIPASS", ""))
        if base.name:
            procs = list(base.rglob("QtWebEngineProcess*"))
            checks["webengine_process"] = str(procs[0]) if procs else None
            checks["webengine_locales"] = len(list(base.rglob("qtwebengine_locales/*.pak")))
            checks["manifest_files"] = sorted(p.name for p in (base / "leonida" / "manifest").glob("*.json"))

        # Every module of the package must be importable from the frozen app (lazy imports included).
        import importlib
        import pkgutil

        import leonida

        # Skipped: __main__ (runs the CLI on import) and cli (console-only; checked through the frozen leonida.exe;
        # it reads sys.stdout.isatty() at import, and sys.stdout is None in this windowed exe).
        names = sorted(m.name for m in pkgutil.walk_packages(leonida.__path__, "leonida.")
                       if m.name not in ("leonida.__main__", "leonida.cli"))
        for name in names:
            importlib.import_module(name)
        checks["modules_imported"] = len(names)
        missing = {"leonida.verify", "leonida.modpack", "leonida.modupdate", "leonida.updater",
                   "leonida.downloader", "leonida.gui.browser"} - set(names)
        if missing:
            raise ImportError(f"not bundled: {sorted(missing)}")

        from leonida.gui import app as gui_app

        logo = getattr(gui_app, "logo_path", None)
        if logo is not None:
            checks["logo"] = str(logo())
            if not logo().is_file():
                raise FileNotFoundError(f"logo not bundled: {logo()}")
        MainWindow = gui_app.MainWindow  # noqa: N806

        try:  # bundled fonts (leonida/gui/assets/fonts) must load from the frozen build
            from leonida.gui import theme
        except ImportError:
            theme = None
        if theme is not None:
            checks["fonts"] = theme.load_fonts()
            if not {"Inter", "Montserrat"} <= set(checks["fonts"]):
                raise FileNotFoundError(f"bundled fonts missing: loaded {checks['fonts']}")

        win = MainWindow()
        win.show()
        checks["window_visible"] = win.isVisible()
        checks["window_title"] = win.windowTitle()
        checks["manifest_mods"] = len(win.session.manifest.mods)

        from leonida.gui.browser import BrowserWindow

        browser = BrowserWindow(win.session.state, win.session.config.downloads(), win)
        browser.show()
        checks["browser_visible"] = browser.isVisible()
    except Exception:
        result["error"] = traceback.format_exc()
        finish(1)
        return 1

    extra_url = os.environ.get("LEONIDA_SELFTEST_URL", "")
    stage = {"name": "inline"}

    def got_title(title) -> None:
        checks["inline_js_title"] = title
        if title != EXPECTED_TITLE:
            result["error"] = f"JavaScript did not run: title {title!r}"
            finish(1)
        elif extra_url:
            stage["name"] = "url"
            browser.view.load(QUrl(extra_url))
        else:
            finish(0)

    def loaded(ok: bool) -> None:
        if stage["name"] == "inline":
            checks["inline_load_ok"] = ok
            if not ok:
                result["error"] = "inline page failed to load"
                finish(1)
                return
            browser.view.page().runJavaScript("document.title", 0, got_title)
        else:
            checks["url_load_ok"] = ok
            checks["url_title"] = browser.view.title()
            finish(0 if ok else 1)

    def timeout() -> None:
        result["error"] = f"timeout after {TIMEOUT_MS} ms at stage {stage['name']}"
        finish(2)

    browser.view.loadFinished.connect(loaded)
    QTimer.singleShot(TIMEOUT_MS, timeout)
    browser.view.load(QUrl(PAGE))
    return app.exec()


if __name__ == "__main__":  # also runnable unfrozen: python build/selftest.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(run())
