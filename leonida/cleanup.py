"""Clean up: duplicates and old leftovers, to the Recycle Bin, logged.

Two kinds:

* **Automatic** (safe; on every start of the launcher, `leonida clean`): exact duplicate downloads (same SHA-256; the
  one the lockfile names stays), partial downloads (``*.part`` and friends) older than a day, older LeonidaMenu
  packages, the picture cache over its size (least recently used first), logs past rotation, play-test CSVs and
  series and crash folders older than 30 days, GTA's own crash dumps (Rockstar's CrashLogs) older than 30 days, and
  the folders of earlier Leonida updates.
* **Ask first** (Settings > Storage, `leonida clean --all`): downloads of mods that aren't in the chosen pack and its
  add-ons (they can be downloaded again; paid ones only with an extra yes), wrong-edition files, backups of steps
  that were rolled back (never those of installed steps: Undo needs them), and stray State / Downloads folders from
  an earlier setup (``%LOCALAPPDATA%\\LeonidaV`` and ``Downloads\\LeonidaV`` when the real ones are elsewhere).

Never: anything in the game folder, Leonida's own state files, backups of active steps, the download of an installed
mod, a paid mod's file without an explicit yes. Everything goes to the Recycle Bin (Windows' SHFileOperation, so it
can be restored); where Windows can't recycle it, it stays. Each item is written to ``<state>/logs/cleanup.log``.
Stdlib only.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

DAY = 24 * 3600
OLD_DAYS = 30
IMAGE_CAP = 300 * 2**20             # the picture cache's size (least recently used pictures go first)
PARTIAL = (".crdownload", ".part", ".tmp", ".download", ".partial")
MENU_PACKAGE = re.compile(r"^LeonidaMenu-(\d+(?:\.\d+)*)\.zip$", re.I)
WRONG_DIR = "_wrong-edition"
LOG_NAME = "cleanup.log"

AUTO = ("duplicates", "partial", "old-packages", "image-cache", "old-logs", "playtest", "crash-dumps", "updates")
ASK = ("not-in-pack", "wrong-edition", "rolled-back-backups", "stray-folders")
TITLES = {"duplicates": "Duplicate downloads", "partial": "Unfinished downloads", "old-packages":
          "Older LeonidaMenu packages", "image-cache": "Pictures over the cache size", "old-logs": "Old logs",
          "playtest": "Old play-test files", "crash-dumps": "GTA crash dumps older than 30 days",
          "updates": "Earlier Leonida updates", "not-in-pack": "Downloads of mods not in your pack",
          "wrong-edition": "Wrong-edition downloads", "rolled-back-backups": "Backups of undone steps",
          "stray-folders": "Leonida folders from an earlier setup"}


@dataclass
class Item:
    path: Path
    size: int
    category: str
    why: str
    paid: bool = False


@dataclass
class Report:
    moved: list[tuple[Item, str]] = field(default_factory=list)     # (item, where it went)
    failed: list[tuple[Item, str]] = field(default_factory=list)    # (item, why it stayed)
    dry_run: bool = False

    @property
    def freed(self) -> int:
        return sum(i.size for i, _w in self.moved)

    def lines(self) -> list[str]:
        verb = "Would move" if self.dry_run else "Moved"
        out = [f"{verb} {len(self.moved)} item(s), {size_text(self.freed)}, to the Recycle Bin."]
        out += [f"  {i.path} ({size_text(i.size)}): {i.why}" for i, _w in self.moved[:40]]
        if len(self.moved) > 40:
            out.append(f"  … and {len(self.moved) - 40} more")
        out += [f"  stayed: {i.path}: {why}" for i, why in self.failed]
        return out


def size_text(n: int) -> str:
    if n >= 2**30:
        return f"{n / 2**30:.1f} GB"
    if n >= 2**20:
        return f"{n / 2**20:.0f} MB"
    return f"{max(0, n) // 1024} KB" if n >= 1024 else f"{n} B"


def summary(items: Iterable[Item]) -> dict[str, tuple[int, int]]:
    """category -> (count, bytes)."""
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for i in items:
        out[i.category][0] += 1
        out[i.category][1] += i.size
    return {k: (v[0], v[1]) for k, v in out.items()}


# ------------------------------------------------------------------------------------------------- helpers
def rockstar_dirs() -> list[Path]:
    """GTA's own CrashLogs folders (the tests replace this: never the PC's real ones)."""
    from .playtest import rockstar_crash_dirs

    return rockstar_crash_dirs()


def _size(p: Path) -> int:
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def _age(p: Path, now: float) -> float:
    try:
        return now - p.stat().st_mtime
    except OSError:
        return 0.0


def _files(folder: Path) -> list[Path]:
    try:
        return [p for p in Path(folder).iterdir() if p.is_file()]
    except OSError:
        return []


def _within(p: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        return Path(p).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split("."))


# ------------------------------------------------------------------------------------------------- what's there
class Scanner:
    """What could go, from a session. ``now`` and the folders are injectable (tests)."""

    def __init__(self, session, now: float | None = None, image_cap: int = IMAGE_CAP,
                 crash_dirs: list[Path] | None = None, home_state: Path | None = None,
                 home_downloads: Path | None = None):
        self.s = session
        self.now = time.time() if now is None else now
        self.image_cap = image_cap
        self.crash_dirs = crash_dirs
        self.home_state = home_state
        self.home_downloads = home_downloads
        self.state = Path(session.state)
        self.downloads = Path(session.config.downloads())

    # -- automatic ---------------------------------------------------------------
    def auto(self) -> list[Item]:
        out: list[Item] = []
        for fn in (self.duplicates, self.partial, self.old_packages, self.image_cache, self.old_logs,
                   self.playtest, self.crash_dumps, self.updates):
            try:
                out += fn()
            except Exception:  # noqa: BLE001 - one category failing must not stop the others
                log.warning("cleanup: %s could not be looked at", fn.__name__, exc_info=True)
        return out

    def _locked(self) -> set[str]:
        from .matcher import read_lock
        from .paths import LOCK_NAME

        try:
            lock = read_lock(self.state / LOCK_NAME) or {}
        except (OSError, ValueError):
            lock = {}
        return {str(e.get("file", "")).lower() for e in lock.get("entries", []) or []}

    def duplicates(self) -> list[Item]:
        """Downloads with the same content: one stays (the lockfile's, else the matched one, else the oldest)."""
        from .matcher import sha256_file

        by_size: dict[int, list[Path]] = defaultdict(list)
        for p in _files(self.downloads):
            if not p.name.lower().endswith(PARTIAL):
                by_size[p.stat().st_size].append(p)
        locked = self._locked()
        matched = {Path(p).name.lower() for p in self._matched().values()}
        out = []
        for size, paths in by_size.items():
            if len(paths) < 2 or size == 0:
                continue
            by_hash: dict[str, list[Path]] = defaultdict(list)
            for p in paths:
                by_hash[sha256_file(p)].append(p)
            for same in by_hash.values():
                if len(same) < 2:
                    continue
                keep = min(same, key=lambda p: (p.name.lower() not in locked, p.name.lower() not in matched,
                                                p.stat().st_mtime, p.name))
                out += [Item(p, size, "duplicates", f"the same file as {keep.name}") for p in same if p != keep]
        return out

    def partial(self) -> list[Item]:
        out = []
        for folder in (self.downloads, *(d for d in (self.state / "updates").glob("*") if d.is_dir())):
            for p in _files(folder):
                if p.name.lower().endswith(PARTIAL) and _age(p, self.now) > DAY:
                    out.append(Item(p, _size(p), "partial", "an unfinished download, more than a day old"))
        return out

    def old_packages(self) -> list[Item]:
        menus = [(p, MENU_PACKAGE.match(p.name)) for p in _files(self.downloads)]
        menus = [(p, _version(m.group(1))) for p, m in menus if m]
        if len(menus) < 2:
            return []
        newest = max(v for _p, v in menus)
        locked = self._locked()
        return [Item(p, _size(p), "old-packages", f"an older LeonidaMenu ({'.'.join(map(str, newest))} is there)")
                for p, v in menus if v < newest and p.name.lower() not in locked]

    def image_cache(self) -> list[Item]:
        folder = self.state / "images"
        pics = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() != ".json"] if folder.is_dir() else []
        total = sum(p.stat().st_size for p in pics)
        if total <= self.image_cap:
            return []
        out = []
        for p in sorted(pics, key=lambda p: max(p.stat().st_atime, p.stat().st_mtime)):   # least recently used
            if total <= self.image_cap:
                break
            size = p.stat().st_size
            out.append(Item(p, size, "image-cache", "the picture cache is over its size; shown again from the net"))
            total -= size
        return out

    def old_logs(self) -> list[Item]:
        from .logs import BACKUPS, MAIN_LOG, SESSIONS_KEPT

        folder = self.state / "logs"
        out = []
        for p in _files(folder):
            m = re.fullmatch(re.escape(MAIN_LOG) + r"\.(\d+)", p.name)
            if m and int(m.group(1)) > BACKUPS:
                out.append(Item(p, _size(p), "old-logs", "a log past its rotation"))
        sessions = sorted((p for p in _files(folder) if p.name.startswith("session-") and p.suffix == ".log"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        out += [Item(p, _size(p), "old-logs", f"an older session log (the newest {SESSIONS_KEPT} stay)")
                for p in sessions[SESSIONS_KEPT:]]
        return out

    def playtest(self) -> list[Item]:
        folder = self.state / "logs" / "playtest"
        out = []
        if not folder.is_dir():
            return out
        for p in folder.iterdir():
            old = _age(p, self.now) > OLD_DAYS * DAY
            if p.is_file() and old and (p.name.startswith(("run-", "series-"))):
                out.append(Item(p, _size(p), "playtest", f"a play test from more than {OLD_DAYS} days ago"))
            elif p.is_dir() and old and p.name.startswith("crash-"):
                out.append(Item(p, _size(p), "playtest", f"a crash report from more than {OLD_DAYS} days ago"))
        return out

    def crash_dumps(self) -> list[Item]:
        out = []
        for folder in (self.crash_dirs if self.crash_dirs is not None else rockstar_dirs()):
            for p in _files(folder):
                if p.suffix.lower() == ".dmp" and _age(p, self.now) > OLD_DAYS * DAY:
                    out.append(Item(p, _size(p), "crash-dumps", f"a GTA crash dump from more than {OLD_DAYS} days ago"))
        return out

    def updates(self) -> list[Item]:
        from . import __version__
        from .updater import parse_version

        folder = self.state / "updates"
        out = []
        current = parse_version(__version__)
        if not folder.is_dir() or current is None:
            return out
        for d in folder.iterdir():
            v = parse_version(d.name)
            if d.is_dir() and v is not None and v <= current:
                out.append(Item(d, _size(d), "updates", "a Leonida update that is installed now"))
        return out

    # -- ask first -----------------------------------------------------------------
    def ask(self) -> list[Item]:
        out: list[Item] = []
        for fn in (self.not_in_pack, self.wrong_edition, self.rolled_back_backups, self.stray_folders):
            try:
                out += fn()
            except Exception:  # noqa: BLE001
                log.warning("cleanup: %s could not be looked at", fn.__name__, exc_info=True)
        return out

    def _matched(self) -> dict[str, Path]:
        if not hasattr(self, "_all_matched"):
            res = self.s.matches(list(self.s.manifest.mods.values()))
            self._all_matched, self._wrong = dict(res.matched), dict(res.wrong)
        return self._all_matched

    def not_in_pack(self) -> list[Item]:
        mine = {m.id for m in self.s.mods()}
        keep = mine | self.s.log.installed_mods() | set(self.s.config.disabled)
        mods = self.s.manifest.mods
        out = []
        for mid, path in self._matched().items():
            if mid in keep or Path(path).parent.resolve() != self.downloads.resolve():
                continue
            m = mods.get(mid)
            if m is None or m.tier == "custom":
                continue
            paid = m.tier == "paid"
            out.append(Item(Path(path), _size(Path(path)), "not-in-pack",
                            f"{m.name} isn't in your pack" + (" (a paid mod you bought)" if paid else
                                                              "; it can be downloaded again"), paid=paid))
        return out

    def wrong_edition(self) -> list[Item]:
        self._matched()
        mods = self.s.manifest.mods
        out = []
        for path, (mid, why) in self._wrong.items():
            m = mods.get(mid)
            out.append(Item(Path(path), _size(Path(path)), "wrong-edition", f"not usable: {why}",
                            paid=bool(m is not None and m.tier == "paid")))
        folder = self.downloads / WRONG_DIR
        if folder.is_dir():
            out.append(Item(folder, _size(folder), "wrong-edition", "files Leonida set aside as the wrong edition"))
        return out

    def rolled_back_backups(self) -> list[Item]:
        from .paths import BACKUPS_DIR

        folder = self.state / BACKUPS_DIR
        if not folder.is_dir():
            return []
        steps = {st.id: st for st in self.s.log.steps}
        out = []
        for d in folder.iterdir():
            m = re.fullmatch(r"step-(\d+)", d.name)
            if not (d.is_dir() and m):
                continue
            st = steps.get(int(m.group(1)))
            if st is None:
                out.append(Item(d, _size(d), "rolled-back-backups", "backups of a step no longer in the install log"))
            elif st.status == "rolled-back":
                out.append(Item(d, _size(d), "rolled-back-backups", f"backups of step {st.id} ({st.mod}), undone"))
        return out

    def _stray_candidates(self) -> tuple[list[Path], list[Path]]:
        if self.home_state is not None or self.home_downloads is not None:
            return [d for d in (self.home_state,) if d], [d for d in (self.home_downloads,) if d]
        if os.environ.get("LEONIDA_STATE_DIR") or os.environ.get("LEONIDA_DOWNLOAD_DIR"):
            return [], []          # an explicit folder: the usual ones may well be another copy's, in use
        from .paths import default_download_dir, home_state_dir

        local = os.environ.get("LOCALAPPDATA")
        states = [home_state_dir()] + ([Path(local) / "LeonidaV"] if sys.platform == "win32" and local else [])
        return states, [default_download_dir(), Path.home() / "Downloads" / "LeonidaV"]

    def _another_setup(self, folder: Path) -> bool:
        """Whether ``folder`` is still a working state folder of another copy: its pointer names another folder, or
        its install log has installed steps (Undo needs their backups)."""
        from .log import InstallLog
        from .paths import LOG_NAME as INSTALL_LOG
        from .relocate import POINTER

        pointer = folder / POINTER
        if pointer.is_file():
            try:
                target = Path(pointer.read_text(encoding="utf-8").strip())
                if target.resolve() != self.state.resolve():
                    return True
            except (OSError, ValueError):
                return True
        try:
            return bool((folder / INSTALL_LOG).is_file() and InstallLog(folder / INSTALL_LOG).active_steps())
        except Exception:  # noqa: BLE001 - unreadable: leave it alone
            return True

    def stray_folders(self) -> list[Item]:
        from .relocate import POINTER

        states, downloads = self._stray_candidates()
        out: list[Item] = []
        seen: set[Path] = set()
        for home in states:
            home = Path(home)
            if (not home.is_dir() or home.resolve() in seen or home.resolve() == self.state.resolve()
                    or _within(self.state, home) or _within(home, self.state) or self._another_setup(home)):
                continue
            seen.add(home.resolve())
            for p in home.iterdir():   # its pointer stays: it says where the real state folder is
                if p.name != POINTER:
                    out.append(Item(p, _size(p), "stray-folders", f"from an earlier Leonida state folder ({home})"))
        paid = {mid for mid, m in self.s.manifest.mods.items() if m.tier == "paid"}
        for dl in downloads:
            dl = Path(dl)
            if (not dl.is_dir() or dl.resolve() in seen or dl.resolve() == self.downloads.resolve()
                    or _within(self.downloads, dl) or _within(dl, self.downloads) or _within(dl, self.state)):
                continue
            seen.add(dl.resolve())
            files = [p for p in _files(dl)]
            try:
                found = self.s._compute_matches(list(self.s.manifest.mods.values()), files).matched
            except Exception:  # noqa: BLE001 - unknown: treat every file as possibly paid
                found = {f"?{i}": f for i, f in enumerate(files)}
                paid |= set(found)
            paid_files = {Path(f).resolve() for mid, f in found.items() if mid in paid}
            for p in dl.iterdir():
                is_paid = p.resolve() in paid_files
                out.append(Item(p, _size(p), "stray-folders", f"in an earlier Leonida downloads folder ({dl}; the "
                                f"real one is {self.downloads})" + (" - a paid mod" if is_paid else ""), paid=is_paid))
        return out


# ------------------------------------------------------------------------------------------------- moving
def _guard(session, item: Item) -> str | None:
    """Why ``item`` must stay (None: it may go)."""
    from .paths import BACKUPS_DIR, BASELINE_NAME, CONFIG_NAME, LOCK_NAME
    from .paths import LOG_NAME as INSTALL_LOG

    p = Path(item.path)
    g = session.game_dir()
    if _within(p, g):
        return "it is in the game folder"
    state = Path(session.state)
    if p.resolve() in {(state / n).resolve() for n in (CONFIG_NAME, INSTALL_LOG, BASELINE_NAME, LOCK_NAME,
                                                       "pack.json")}:
        return "it is one of Leonida's own files"
    if p.resolve() == state.resolve() or p.resolve() == Path(session.config.downloads()).resolve():
        return "it is a folder Leonida uses"
    active = {st.id for st in session.log.active_steps()}
    m = re.search(r"step-(\d+)", p.as_posix())
    if _within(p, state / BACKUPS_DIR) and m and int(m.group(1)) in active:
        return "Undo needs it (an installed step's backup)"
    return None


def recycle(path: Path) -> str:
    """Move ``path`` to the Recycle Bin (Windows: SHFileOperationW with undo). Returns where it went; raises
    OSError when Windows refused (the file stays)."""
    if sys.platform != "win32":
        raise OSError("no Recycle Bin on this system")
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(Path(path).resolve()) + "\0\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted or Path(path).exists():
        raise OSError(f"Windows didn't move it to the Recycle Bin (code {rc})")
    return "Recycle Bin"


def clean(session, items: Iterable[Item], dry_run: bool = False, paid: bool = False,
          trash: Callable[[Path], str] | None = None) -> Report:
    """Move ``items`` to the Recycle Bin (``trash``: tests pass their own). Paid files only with ``paid=True``."""
    trash = trash or recycle
    report = Report(dry_run=dry_run)
    lines = []
    for item in items:
        why = _guard(session, item)
        if why is None and item.paid and not paid:
            why = "a paid mod's file: only with an explicit yes"
        if why is None and not Path(item.path).exists():
            why = "it is gone already"
        if why is not None:
            report.failed.append((item, why))
            continue
        if dry_run:
            report.moved.append((item, "Recycle Bin"))
            continue
        try:
            where = trash(Path(item.path))
        except OSError as exc:
            report.failed.append((item, str(exc)))
            continue
        report.moved.append((item, where))
        lines.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{item.category}\t{item.size}\t{item.path}\t-> {where}"
                     f"\t({item.why})")
    if lines:
        folder = Path(session.state) / "logs"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / LOG_NAME).open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass
        log.info("cleanup: %d item(s), %s, to the Recycle Bin", len(lines), size_text(report.freed))
    return report


def auto_clean(session, trash: Callable[[Path], str] | None = None, **scan) -> Report:
    """The automatic pass (every start of the launcher)."""
    return clean(session, Scanner(session, **scan).auto(), trash=trash)


def move_to(folder: Path) -> Callable[[Path], str]:
    """A ``trash`` that moves into ``folder`` (tests, and systems without a Recycle Bin)."""
    def trash(path: Path) -> str:
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{int(time.time() * 1000)}-{path.name}"
        shutil.move(str(path), str(dest))
        return str(dest)
    return trash
