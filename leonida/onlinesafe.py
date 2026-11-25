"""The online-safe switch: move every mod file out of the game folder, and back.

What goes out (top-level entries of the game folder):
  * whatever matches the manifest's ``onlineSafeItems`` (dinput8.dll, *.asi, ScriptHookV.dll, scripts, mods, ...);
  * every file or folder Leonida's install log says it added at the top of the game folder (``extra``: e.g.
    ActionsV.ini, the DynamicVehicleFirstPerson data folder), but never a stock game file (``protected``: the
    baseline snapshot's own entries) and never anything Leonida didn't install (the game's own version.dll);
  * the mods' logs at the top (``*.log``, ``*.log.prev``), so nothing hints at mods.

Both directions refuse while GTA V is running: its files are in use and a half-moved folder helps nobody.
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import shutil
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

OFFLINE_DIR = "_LeonidaV_offline"
RECORD = "moved.json"
LOG_PATTERNS = ("*.log", "*.log.prev")
GAME_PROCESSES = ("GTA5_Enhanced.exe", "GTA5.exe", "PlayGTAV.exe")


class OnlineSafeError(RuntimeError):
    pass


def game_running(names: Iterable[str] = GAME_PROCESSES) -> list[str]:
    """The GTA V processes running now (Windows; [] elsewhere)."""
    if sys.platform != "win32":
        return []
    from .playtest import ProcessOps

    return find_running(names, ProcessOps())


def find_running(names: Iterable[str], ops) -> list[str]:
    """The ``names`` that ``ops.running(name)`` finds processes for (a failing lookup counts as not running)."""
    out = []
    for name in names:
        try:
            if ops.running(name):
                out.append(name)
        except Exception:  # noqa: BLE001 - no tasklist: assume it isn't running
            continue
    return out


def _refuse_while_running(running: Callable[[], list[str]] | None) -> None:
    found = (running or game_running)()
    if found:
        raise OnlineSafeError(f"GTA V is running ({', '.join(found)}): close the game first. Its files are in "
                              "use, so nothing was moved.")


def mod_items(game_dir: Path, patterns: tuple[str, ...], extra: Iterable[str] = (),
              protected: Iterable[str] = (), logs: bool = False) -> list[Path]:
    """Top-level entries in the game folder that are mods: the online-safe patterns, Leonida's own top-level items
    (``extra``, minus ``protected`` stock entries) and, with ``logs``, the mods' log files."""
    game_dir = Path(game_dir)
    pats = [p.lower() for p in patterns]
    keep = {p.lower().rstrip("/") for p in protected}
    mine = {p.lower().rstrip("/") for p in extra} - keep
    out = []
    for entry in sorted(game_dir.iterdir(), key=lambda p: p.name.lower()):
        low = entry.name.lower()
        if entry.name == OFFLINE_DIR:
            continue
        is_mod = any(fnmatch.fnmatchcase(low, p) for p in pats) or low in mine
        is_log = logs and low not in keep and entry.is_file() and any(fnmatch.fnmatchcase(low, p)
                                                                      for p in LOG_PATTERNS)
        if is_mod or is_log:
            out.append(entry)
    return out


def moved_out(game_dir: Path) -> list[str]:
    """What online-safe storage holds now ([] when mods aren't moved out)."""
    rec = Path(game_dir) / OFFLINE_DIR / RECORD
    if not rec.exists():
        return []
    try:
        return list(json.loads(rec.read_text(encoding="utf-8")).get("moved", []))
    except (OSError, ValueError):
        return []


def status(game_dir: Path, patterns: tuple[str, ...], extra: Iterable[str] = (),
           protected: Iterable[str] = ()) -> str:
    """'mods-on', 'online-safe' (mods moved out), 'clean' (no mods at all) or 'mixed'."""
    off = Path(game_dir) / OFFLINE_DIR / RECORD
    present = mod_items(game_dir, patterns, extra, protected)
    if off.exists():
        return "mixed" if present else "online-safe"
    return "mods-on" if present else "clean"


def report(game_dir: Path, patterns: tuple[str, ...], extra: Iterable[str] = (),
           protected: Iterable[str] = ()) -> tuple[str, list[str], list[str]]:
    """(status, what is moved out, which mod items are in the game folder now)."""
    present = [p.name + ("/" if p.is_dir() else "") for p in
               mod_items(game_dir, patterns, extra, protected, logs=True)]
    return status(game_dir, patterns, extra, protected), moved_out(game_dir), present


def go_online_safe(game_dir: Path, patterns: tuple[str, ...], dry_run: bool = False, *, extra: Iterable[str] = (),
                   protected: Iterable[str] = (), logs: bool = True,
                   running: Callable[[], list[str]] | None = None) -> list[str]:
    """Move the mods out (see the module docstring). Returns the names moved (or that would be, with ``dry_run``).
    ``running`` tells which GTA processes run (default: tasklist)."""
    game_dir = Path(game_dir)
    off = game_dir / OFFLINE_DIR
    if (off / RECORD).exists():
        raise OnlineSafeError("Mods are already moved out. Use Online-safe OFF (`leonida online-safe off`) to bring "
                              "them back.")
    items = mod_items(game_dir, patterns, extra, protected, logs)
    names = [p.name for p in items]
    if dry_run or not items:
        return names
    _refuse_while_running(running)
    off.mkdir(exist_ok=True)
    moved: list[str] = []
    try:
        for p in items:
            shutil.move(str(p), str(off / p.name))
            moved.append(p.name)
    finally:
        (off / RECORD).write_text(json.dumps({"moved": moved}, indent=2), encoding="utf-8")
    return moved


def restore_mods(game_dir: Path, dry_run: bool = False, *,
                 running: Callable[[], list[str]] | None = None) -> list[str]:
    game_dir = Path(game_dir)
    off = game_dir / OFFLINE_DIR
    rec = off / RECORD
    if not rec.exists():
        raise OnlineSafeError("Nothing to restore: mods are not in online-safe storage.")
    moved = json.loads(rec.read_text(encoding="utf-8")).get("moved", [])
    clashes = [n for n in moved if (game_dir / n).exists()]
    if clashes:
        raise OnlineSafeError("These already exist in the game folder, so nothing was moved back: "
                              + ", ".join(clashes))
    if dry_run:
        return moved
    _refuse_while_running(running)
    for name in moved:
        src = off / name
        if src.exists():
            shutil.move(str(src), str(game_dir / name))
    rec.unlink()
    with contextlib.suppress(OSError):
        off.rmdir()
    return moved


def leonida_items(log, baseline: dict | None) -> tuple[set[str], set[str]]:
    """(top-level names Leonida added, per its install log; the baseline's own top-level names, never moved).
    An item counts when an active step added it (a file, a folder it made, or a file at the top a hand-made step
    added); paths inside stock folders (update/, x64/ ...) don't make those folders movable."""
    stock: set[str] = set()
    for key in (baseline or {}).get("files", {}):
        stock.add(key.replace("\\", "/").split("/")[0].lower())
    stock |= {d.lower() for d in (baseline or {}).get("top_dirs", [])}
    added: set[str] = set()
    for step in log.active_steps():
        if step.status != "done":
            continue
        for a in step.actions:
            if a.op in ("add", "ext_add", "mkdir"):
                top = a.path.replace("\\", "/").strip("/").split("/")[0]
                if top:
                    added.add(top.lower())
    return added - stock, stock
