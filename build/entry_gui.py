"""Frozen entry point for LeonidaV.exe (the GUI). PyInstaller runs this file as __main__.

leonida/gui/app.py uses relative imports, so it cannot be the entry script itself.
The browser self-test (build/selftest.py) runs only when LEONIDA_SELFTEST is set, and the screenshots of
build/real_screens.py only when LEONIDA_SCREENS=<folder> is set (release checks); users never set either.
"""

import os
import sys

if __name__ == "__main__":
    if os.environ.get("LEONIDA_SELFTEST"):
        from selftest import run

        sys.exit(run())
    if os.environ.get("LEONIDA_SCREENS"):  # build/real_screens.py inside the frozen app (release checks only)
        from real_screens import main as screens

        sys.exit(screens(["--out", os.environ["LEONIDA_SCREENS"]]))

    from leonida.gui.app import main

    sys.exit(main())
