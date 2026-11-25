"""Run Leonida's AutoDownloader (the GUI's "Download everything") without the main window.

    python build/autodl_run.py                 # visible browser window, missing mods of the chosen pack
    python build/autodl_run.py --offscreen     # no window (sites that need a sign-in will report need_login)
    python build/autodl_run.py --mods drivev visualv

Uses the real state/download folders (LEONIDA_STATE_DIR / LEONIDA_DOWNLOAD_DIR or the defaults).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offscreen", action="store_true")
    ap.add_argument("--mods", nargs="*", help="mod ids (default: every missing mod of the chosen pack)")
    a = ap.parse_args(argv)
    if a.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])
    from leonida.gui.autodl import AutoDownloader, manual_reason
    from leonida.gui.browser import BrowserWindow
    from leonida.session import Session

    s = Session()
    mods = s.mods()
    res = s.matches(mods)
    todo = [m for m in mods if m.id not in res.matched and not m.download]
    if a.mods:
        todo = [m for m in mods if m.id in set(a.mods)]
    for m in list(todo):
        why = manual_reason(m)
        if why:
            print("manual:", why, flush=True)
            todo.remove(m)
    if not todo:
        print("Nothing to download.")
        return 0
    print("Downloading:", ", ".join(m.id for m in todo), flush=True)
    browser = BrowserWindow(s.state, s.config.downloads())
    dl = AutoDownloader(browser, s, todo)
    dl.status.connect(lambda t: print("  ", t, flush=True))
    dl.need_login.connect(lambda site: print(f"  SIGN IN NEEDED: {site}", flush=True))
    dl.mod_done.connect(lambda mid, p: print(f"DONE {mid}: {Path(p).name}", flush=True))
    dl.mod_failed.connect(lambda mid, why: print(f"FAILED {mid}: {why}", flush=True))
    dl.finished.connect(app.quit)
    dl.start()
    app.exec()
    failed = [k for k, (state, _) in dl.results.items() if state != "done"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
