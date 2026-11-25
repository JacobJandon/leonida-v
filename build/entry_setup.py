"""Leonida-V-Setup-<version>.exe: installs the exe build for this Windows user (no administrator rights).

The release's LeonidaV-<version>-win64.zip is inside this exe (payload/, with its SHA-256 in payload/payload.json,
checked before anything is written). leonida/winsetup.py does the work; leonida/setupui.py shows Windows' own dialogs.

    Leonida-V-Setup-1.0.0.exe                          the dialogs
    Leonida-V-Setup-1.0.0.exe /S [--dir D] [--data D]  silent (winget, tests): exit code 0 = installed
        [--no-desktop] [--no-shortcuts] [--launch] [--log FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def payload_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / "dist"))
    return base / "payload"


def load_payload() -> tuple[Path, dict]:
    meta = json.loads((payload_dir() / "payload.json").read_text(encoding="utf-8"))
    zip_path = payload_dir() / meta["file"]
    h = hashlib.sha256()
    with open(zip_path, "rb") as fh:
        while block := fh.read(1 << 20):
            h.update(block)
    if h.hexdigest() != meta["sha256"]:
        raise RuntimeError(f"The setup's own payload is damaged ({meta['file']}: SHA-256 doesn't match). Download "
                           "Leonida-V-Setup again from the GitHub release.")
    return zip_path, meta


def parse(argv: list[str]) -> argparse.Namespace:
    argv = ["--silent" if a.upper() in ("/S", "/SILENT", "/VERYSILENT", "-S") else a for a in argv]
    ap = argparse.ArgumentParser(prog="Leonida-V-Setup", add_help=False)
    ap.add_argument("--silent", action="store_true")
    ap.add_argument("--dir", type=Path)
    ap.add_argument("--data", type=Path)
    ap.add_argument("--no-desktop", action="store_true")
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--launch", action="store_true", help="silent: start Leonida V afterwards")
    ap.add_argument("--log", type=Path)
    a, _unknown = ap.parse_known_args(argv)
    return a


def main(argv: list[str] | None = None) -> int:
    a = parse(sys.argv[1:] if argv is None else argv)
    from leonida import winsetup
    from leonida.winsetup import SetupError

    def log(text: str) -> None:
        if a.log:
            with open(a.log, "a", encoding="utf-8") as fh:
                fh.write(text.rstrip() + "\n")

    try:
        payload, meta = load_payload()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        log(f"ERROR {exc}")
        if not a.silent:
            from leonida import setupui

            setupui.message(str(exc), error=True)
        return 2
    version = meta["version"]
    install_dir = a.dir or winsetup.default_install_dir()
    previous = winsetup.registered() or {}
    data_dir = a.data or Path(str(previous.get("DataDir") or winsetup.default_data_dir()))

    if a.silent:
        try:
            res = winsetup.install(payload, install_dir, data_dir, version=version, shortcuts=not a.no_shortcuts,
                                   desktop=not a.no_desktop)
        except SetupError as exc:
            log(f"ERROR {exc}")
            return 1
        winsetup.write_receipt(res)
        log(winsetup.summary_text(res))
        if a.launch:
            subprocess.Popen([str(res.install_dir / winsetup.GUI_EXE)], cwd=str(res.install_dir))
        return 0

    from leonida import setupui

    upgrade = (install_dir / winsetup.GUI_EXE).is_file()
    while True:
        choice, desktop = setupui.ask_install(version, install_dir, data_dir, upgrade)
        if choice == "cancel":
            return 1
        if choice == "folder":
            picked = setupui.pick_folder("Where should Leonida V keep your data (State and Downloads)? A folder "
                                         "with space for the mods' downloads, outside the game folder.", data_dir)
            if picked:
                game = winsetup.game_folder_near(picked)
                if game:
                    setupui.message(f"{picked} is inside the game folder ({game}). Pick a folder outside it.",
                                    error=True)
                else:
                    data_dir = picked if picked.name.lower() in ("leonida v", "leonidav") else picked / "Leonida V"
            continue
        break
    try:
        res = setupui.run_with_progress(
            f"{'Updating' if upgrade else 'Installing'} Leonida V {version}", f"Copying the program into "
            f"{install_dir} ...", lambda progress: winsetup.install(payload, install_dir, data_dir, version=version,
                                                                    desktop=desktop, progress=progress))
    except SetupError as exc:
        setupui.message(str(exc), error=True, main="Leonida V was not installed")
        return 1
    winsetup.write_receipt(res)
    if setupui.finished(winsetup.summary_text(res), main=f"Leonida V {version} is "
                                                       f"{'updated' if res.upgraded else 'installed'}"):
        subprocess.Popen([str(res.install_dir / winsetup.GUI_EXE)], cwd=str(res.install_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
