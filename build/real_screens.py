"""Screenshots of the real launcher on the real state (pack, installed steps, downloads, mod pictures).

    python build/real_screens.py --out D:\\Leonida\\Screenshots

Reads LEONIDA_STATE_DIR / LEONIDA_DOWNLOAD_DIR (or the defaults). Only reads: it never installs, downloads mods or
touches the game folder. Mod pictures load from the image cache / authors' pages like in the app.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="screens")
    ap.add_argument("--size", default="1600x1000")
    a = ap.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    os.environ["LEONIDA_NO_OPEN"] = "1"
    os.environ["LEONIDA_NO_UPDATE_CHECK"] = "1"

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])
    from leonida.gui import theme
    from leonida.gui.app import PAGES, MainWindow
    from leonida.session import Session

    theme.apply_theme(app)
    w, h = (int(v) for v in a.size.split("x"))
    win = MainWindow(Session())
    win.resize(w, h)
    win.show()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    def settle(sec: float) -> None:
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.03)

    for i, name in enumerate(PAGES):
        win.go(i)
        settle(25 if name == "Choose mods" else 4)  # pictures load in the background
        path = out / f"{i + 1:02d}-{name.lower().replace(' ', '-')}.png"
        win.grab().save(str(path))
        print("saved", path, flush=True)
    # the launcher views: Browse (packs, mods + details), the Modpack page and each of its tabs
    shots = [("browse-packs", lambda: (win.show_home("browse"), win.browse.tabs.setCurrentIndex(0))),
             ("browse-mods", lambda: (win.browse.tabs.setCurrentIndex(1),
                                      win.browse.rows and win.browse.rows[0].clicked.emit()))]
    shots.append(("browse-setups", lambda: (win.show_home("browse"), win.browse.tabs.setCurrentIndex(2))))
    for n, tab in enumerate(("overview", "mods", "variants", "screenshots", "files", "paid")):
        shots.append((f"pack-{tab}", lambda n=n: (win.show_home("pack"), win.pack_page.tabs.setCurrentIndex(n))))
    shots += [("settings", lambda: win.show_home("settings")), ("about", lambda: win.show_home("about"))]
    from leonida import firstrun as FR

    shots.append(("setup-pack-step", lambda: win.setup_flow.begin(FR.STEPS.index("pack"))))
    for i, (name, show) in enumerate(shots, len(PAGES) + 1):
        show()
        settle(8)
        path = out / f"{i:02d}-{name}.png"
        win.grab().save(str(path))
        print("saved", path, flush=True)
    win.close()
    settle(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
