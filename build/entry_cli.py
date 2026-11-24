"""Frozen entry point for leonida.exe (the CLI). leonida/__main__.py uses a relative import, so it can't be used directly."""

import sys

if __name__ == "__main__":
    from leonida.cli import main

    sys.exit(main())
