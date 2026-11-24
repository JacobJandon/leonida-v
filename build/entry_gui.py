"""Frozen entry point for LeonidaV.exe (the GUI). PyInstaller runs this file as __main__.

leonida/gui/app.py uses relative imports, so it cannot be the entry script itself.
The browser self-test (build/selftest.py) runs only when LEONIDA_SELFTEST is set; users never set it.
"""

import os
import sys

if __name__ == "__main__":
    if os.environ.get("LEONIDA_SELFTEST"):
        from selftest import run

        sys.exit(run())

    from leonida.gui.app import main

    sys.exit(main())
