"""Pure GTA: play the game with no mods at all, in one click, and get the mods back by themselves afterwards.

    start(session)        moves every mod out of the game folder exactly as Online-safe does (onlinesafe.py), writes
                          <state>/pure-mode.json, then starts the game through PlayGTAV.exe (``launch=False``: move
                          only). Refuses while GTA V runs.
    finish(session)       when Pure GTA is on and the game isn't running: brings the mods back and clears the record.
                          Called when the game closes (the launcher's game watch), at every Leonida start, and by
                          ``leonida pure --back``. Mods that were already out before (Online-safe on) stay out.
    active(session)       Pure GTA is on (the record exists).

Nothing is deleted: the mods wait in the game folder's ``_LeonidaV_offline`` folder, as with Online-safe, and the game
folder holds only the game's own files while Pure GTA is on. Story mode or Online is the player's choice; for GTA
Online keep using Online-safe, which keeps the mods out until it is switched off.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from . import onlinesafe

RECORD = "pure-mode.json"
LAUNCHER = "PlayGTAV.exe"


class PureModeError(RuntimeError):
    pass


def _record(session) -> Path:
    return Path(session.state) / RECORD


def active(session) -> bool:
    return _record(session).is_file()


def info(session) -> dict:
    try:
        return json.loads(_record(session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def game_exe(session) -> Path | None:
    g = session.game_dir()
    if not g:
        return None
    exe = Path(g) / LAUNCHER
    if exe.is_file():
        return exe
    from .detect import find_exe

    return find_exe(Path(g), session.base_manifest.exe_names)


def launch(session, popen: Callable[..., object] = subprocess.Popen) -> str:
    exe = game_exe(session)
    if exe is None or not exe.is_file():
        raise PureModeError(f"No {LAUNCHER} in {session.game_dir()}.")
    if os.environ.get("LEONIDA_NO_OPEN"):
        return f"Would start {exe.name} (opening is off)."
    from .installer import windows_launch_command

    popen(windows_launch_command(exe), cwd=str(exe.parent))
    return f"Starting {exe.name} with no mods (Pure GTA)."


def start(session, launch_game: bool = True, running: Callable[[], list[str]] | None = None,
          popen: Callable[..., object] = subprocess.Popen) -> list[str]:
    """Move every mod out, remember that Pure GTA is on, and (``launch_game``) start the game. Returns what it did."""
    g = session.game_dir()
    if not g or not Path(g).is_dir():
        raise PureModeError("Find your game first (leonida detect).")
    if active(session):
        lines = ["Pure GTA is already on: the mods are out."]
    else:
        was = session.online_status()
        moved: list[str] = []
        if was != "online-safe":          # Online-safe already moved them out: nothing to move, and they stay out
            try:
                moved = session.online_safe_on(running=running)
            except onlinesafe.OnlineSafeError as exc:
                raise PureModeError(str(exc)) from None
        rec = _record(session)
        rec.parent.mkdir(parents=True, exist_ok=True)
        rec.write_text(json.dumps({"since": time.time(), "moved": moved,
                                   "was_online_safe": was == "online-safe"}, indent=1), encoding="utf-8")
        lines = [f"Pure GTA: moved {len(moved)} mod item(s) out of the game folder." if moved else
                 "Pure GTA: no mod files were in the game folder."]
    if launch_game:
        try:
            lines.append(launch(session, popen))
        except PureModeError:
            finish(session, running=lambda: [])   # nothing started: put the mods straight back
            raise
    return lines


def finish(session, running: Callable[[], list[str]] | None = None) -> list[str]:
    """Bring the mods back after Pure GTA (no-op when it isn't on, or while the game still runs)."""
    if not active(session):
        return []
    found = (running or onlinesafe.game_running)()
    if found:
        return [f"Pure GTA stays on while GTA V runs ({', '.join(found)}); the mods come back when it closes."]
    data = info(session)
    if data.get("was_online_safe"):
        _record(session).unlink(missing_ok=True)
        return ["Pure GTA is off. Online-safe was on before, so the mods stay out (switch it off on Manage)."]
    try:
        back = session.online_safe_off(running=running or (lambda: []))
    except onlinesafe.OnlineSafeError as exc:
        return [f"Couldn't bring the mods back yet: {exc}"]
    _record(session).unlink(missing_ok=True)
    return [f"Pure GTA is off: {len(back)} mod item(s) are back in the game folder."]
