"""Start a program on its own and return at once: ``python -m leonida.detach PROGRAM [ARGS...]``.

Start-Leonida.bat starts the GUI this way. A plain ``start "" leonida-gui.exe`` (even with ``<nul >nul 2>&1``) passes
every inheritable handle of the batch file on to the GUI, so a caller that captures the batch file's output (a
script, a scheduled task) waits until Leonida is closed. Here the program gets the null device for its standard
streams and inherits no other handle. Standard library only.
"""

from __future__ import annotations

import subprocess
import sys

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def start(argv: list[str]) -> int:
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, creationflags=flags, start_new_session=sys.platform != "win32")
    return p.pid


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m leonida.detach PROGRAM [ARGS...]", file=sys.stderr)
        return 2
    try:
        start(args)
    except OSError as exc:
        print(f"Could not start {args[0]}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
