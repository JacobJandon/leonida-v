"""A debug report: one zip with what's needed to work out a problem on someone else's PC.

    names = preview(session)              # [(name in the zip, size)]: show this before saving
    path = build(session, out_dir=None)   # the zip (default: the Desktop); `leonida report [--out DIR] [--yes]`

Contents (only these files; nothing else is ever read into the report):
  - leonida/: Leonida's own logs (<state>/logs: leonida.log + its rotations, the GUI session logs);
  - game-logs/: the mods' logs from the game folder (ScriptHookV.log, ScriptHookVDotNet.log, asiloader.log,
    menyooLog.txt, DirectStorageFix.log, ResourceExtensions.log, the UAL logs, LeonidaProbe.log) and the previous
    play test's copies and probe log from <state>/playtest;
  - state/: install-log.json, config.json, pack.json, settings-unlocked.json, custom-mods.json, the lockfile,
    paid-status.json, the last play test report;
  - results/: `leonida check` (findings), `leonida verify` (the game's logs read now), the manifest and game info;
  - system.json: Windows version, CPU, RAM, GPU + driver (CIM), free disk per drive, Python / Leonida versions;
  - game-files.txt: the game folder's top-level files (names and sizes only) and the mods\\ folder listing.

Privacy: every text is cleaned before it goes into the zip:
  - the Windows user name and the home folder (C:\\Users\\<name>, in every spelling, JSON-escaped too) become
    <user>, and the PC name <pc>;
  - what looks like a token, key, password or cookie is masked (logs.redact_secrets).
Never included: the built-in browser's profile (cookies, logins), the Downloads folder's contents, backups,
credentials. Only the files listed above are read.
"""

from __future__ import annotations

import contextlib
import getpass
import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from . import __version__, logs
from .paths import CONFIG_NAME, LOCK_NAME, LOG_NAME

log = logging.getLogger(__name__)

STATE_FILES = (LOG_NAME, CONFIG_NAME, "pack.json", "settings-unlocked.json", "custom-mods.json", LOCK_NAME,
               "paid-status.json", "update-check.json", "playtest/last-report.json")
MAX_FILE = 4 * 1024 * 1024        # bigger logs: only their last 4 MB
MAX_LISTING = 3000                # mods\ entries listed
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ------------------------------------------------------------------------------------------- redaction
def _identity() -> tuple[list[str], list[str], str | None]:
    """(home folder spellings, user names, PC name) to replace."""
    homes = {str(Path.home())}
    for var in ("USERPROFILE", "HOME"):
        if os.environ.get(var):
            homes.add(os.environ[var])
    users = set()
    for name in (os.environ.get("USERNAME"), os.environ.get("USER")):
        if name:
            users.add(name)
    with contextlib.suppress(Exception):  # no user name: nothing to replace
        users.add(getpass.getuser())
    users |= {Path(h).name for h in homes if Path(h).name}
    pc = os.environ.get("COMPUTERNAME") or platform.node() or None
    return sorted(homes, key=len, reverse=True), sorted(users, key=len, reverse=True), pc


def redact(text: str, homes: list[str] | None = None, users: list[str] | None = None, pc: str | None = None) -> str:
    """The user's home folder and name -> <user>, the PC name -> <pc>, secrets masked. Without arguments: this
    PC's own (``_identity``)."""
    if homes is None and users is None and pc is None:
        homes, users, pc = _identity()
    for home in homes or []:
        variants = {home, home.replace("\\", "/"), home.replace("\\", "\\\\"), home.replace("/", "\\")}
        for v in sorted(variants, key=len, reverse=True):
            text = re.sub(re.escape(v), "<user>", text, flags=re.I)
    for user in users or []:
        if len(user) >= 3:  # a one- or two-letter name would hit ordinary words
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(user)}(?![A-Za-z0-9])", "<user>", text, flags=re.I)
    if pc and len(pc) >= 3:
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(pc)}(?![A-Za-z0-9])", "<pc>", text, flags=re.I)
    return logs.redact_secrets(text)


# ------------------------------------------------------------------------------------------- collecting
def _read_text(path: Path) -> str | None:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > MAX_FILE:
                f.seek(size - MAX_FILE)
            data = f.read()
    except OSError:
        return None
    text = data.decode("utf-8", errors="replace")
    if size > MAX_FILE:
        text = f"[only the last {MAX_FILE // 1024 // 1024} MB of {size} bytes]\n" + text
    return text


def _game_logs(session) -> list[tuple[str, Path]]:
    from . import verify as V
    from .playtest import LOGS
    from .probe import PROBE_LOG

    out: list[tuple[str, Path]] = []
    game = session.game_dir()
    if game and game.is_dir():
        found = V.Logs(game)
        for name in (*LOGS, PROBE_LOG):
            p = found.path(name)
            if p is not None and p.is_file():
                out.append((f"game-logs/{p.name}", p))
    prev = session.state / "playtest"
    if prev.is_dir():
        out += [(f"game-logs/previous-run/{p.name}", p) for p in sorted((prev / "previous").glob("*"))
                if p.is_file()]
        if (prev / PROBE_LOG).is_file():
            out.append((f"game-logs/previous-run/{PROBE_LOG}", prev / PROBE_LOG))
    return out


def _leonida_logs(session) -> list[tuple[str, Path]]:
    folder = logs.log_dir(session.state)
    if not folder.is_dir():
        return []
    return [(f"leonida/{p.name}", p) for p in sorted(folder.iterdir())
            if p.is_file() and (p.suffix == ".log" or p.name.startswith("leonida.log"))]


def _state_files(session) -> list[tuple[str, Path]]:
    return [(f"state/{rel}", session.state / rel) for rel in STATE_FILES if (session.state / rel).is_file()]


def _check_text(session) -> str:
    from .checks import ERROR, INFO, WARNING

    try:
        findings = session.findings()
    except Exception as exc:  # noqa: BLE001 - the report must still be made
        return f"leonida check failed: {type(exc).__name__}: {exc}\n"
    tag = {ERROR: "ERROR  ", WARNING: "WARNING", INFO: "info   "}
    lines = [f"{tag.get(f.level, f.level)} {f.code}: {f.message}" for f in findings]
    return "\n".join(lines or ["All checks passed."]) + "\n"


def _verify_text(session) -> str:
    from .verify import verify_session

    try:
        results = verify_session(session)
    except Exception as exc:  # noqa: BLE001
        return f"leonida verify failed: {type(exc).__name__}: {exc}\n"
    lines = [f"{r.status.upper():9} {r.mod or '-'}: {r.message}" + (f"\n          {r.log}: {r.line}" if r.line else "")
             for r in results]
    return "\n".join(lines or ["Nothing installed by Leonida V yet."]) + "\n"


def _store_of(game: Path | None) -> str:
    low = str(game or "").lower()
    for key, name in (("steamapps", "Steam"), ("epic games", "Epic Games"), ("rockstar games", "Rockstar Games")):
        if key in low:
            return name
    return "unknown"


def _game_info(session) -> dict:
    game = session.game_dir()
    try:
        m = session.manifest
        manifest = {"pack": m.pack, "version": m.version, "edition": m.edition, "tested_builds": list(m.tested_builds)}
    except Exception as exc:  # noqa: BLE001
        manifest = {"error": str(exc)}
    try:
        choice = session.pack_choice()
        pack = {"pack": choice.pack, "addons": list(choice.addons) if choice.addons is not None else None,
                "variant": choice.variant}
    except Exception as exc:  # noqa: BLE001
        pack = {"error": str(exc)}
    return {
        "leonida": __version__, "manifest": manifest, "pack": pack,
        "game": {"folder": str(game) if game else None, "edition": session.game_edition,
                 "mod_list_edition": session.edition, "build": session.game_version(), "store": _store_of(game)},
        "installed_mods": sorted(session.log.installed_mods()),
    }


def _game_files(session) -> str:
    game = session.game_dir()
    if not game or not game.is_dir():
        return "No game folder set.\n"
    lines = [f"Game folder: {game}", "", "Top level (names and sizes only):"]
    for p in sorted(game.iterdir(), key=lambda x: x.name.lower()):
        try:
            lines.append(f"  {p.name}/" if p.is_dir() else f"  {p.name}  {p.stat().st_size}")
        except OSError:
            lines.append(f"  {p.name}  ?")
    mods = game / "mods"
    lines += ["", "mods\\ folder:"]
    if mods.is_dir():
        for n, p in enumerate(sorted(mods.rglob("*"))):
            if n >= MAX_LISTING:
                lines.append(f"  ... (more than {MAX_LISTING} entries)")
                break
            rel = p.relative_to(game).as_posix()
            try:
                lines.append(f"  {rel}/" if p.is_dir() else f"  {rel}  {p.stat().st_size}")
            except OSError:
                lines.append(f"  {rel}  ?")
    else:
        lines.append("  (none)")
    return "\n".join(lines) + "\n"


CIM = ("$o=Get-CimInstance Win32_OperatingSystem; $c=Get-CimInstance Win32_Processor; "
       "$s=Get-CimInstance Win32_ComputerSystem; $g=Get-CimInstance Win32_VideoController; "
       "[pscustomobject]@{os=$o.Caption; os_version=$o.Version; os_build=$o.BuildNumber; "
       "cpu=@($c | ForEach-Object Name); cores=@($c | ForEach-Object NumberOfCores); "
       "ram_bytes=$s.TotalPhysicalMemory; gpus=@($g | ForEach-Object { [pscustomobject]@{name=$_.Name; "
       "driver=$_.DriverVersion; driver_date=[string]$_.DriverDate} })} | ConvertTo-Json -Depth 4 -Compress")


def system_info(run=subprocess.run) -> dict:
    info: dict = {"platform": platform.platform(), "python": sys.version.split()[0],
                  "python_bits": 64 if sys.maxsize > 2**32 else 32, "leonida": __version__, "frozen": getattr(sys, "frozen", False)}
    if sys.platform == "win32":
        try:
            p = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", CIM], capture_output=True, text=True,
                    errors="replace", timeout=40, check=False, creationflags=_NO_WINDOW)
            info.update(json.loads(p.stdout or "{}"))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            info["cim_error"] = str(exc)
        drives = [f"{c}:\\" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]
    else:
        drives = ["/"]
    disks = {}
    for d in drives:
        try:
            u = shutil.disk_usage(d)
            disks[d] = {"free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1)}
        except OSError:
            continue
    info["disks"] = disks
    return info


# ------------------------------------------------------------------------------------------- the report
def collect(session) -> list[tuple[str, str]]:
    """(name in the zip, text) for everything the report holds, cleaned (``redact``)."""
    for h in logging.getLogger(logs.ROOT).handlers:  # what's been logged so far is in the files
        h.flush()
    homes, users, pc = _identity()
    out: list[tuple[str, str]] = []
    for name, path in _leonida_logs(session) + _game_logs(session) + _state_files(session):
        text = _read_text(path)
        if text is not None:
            out.append((name, text))
    out.append(("results/check.txt", _check_text(session)))
    out.append(("results/verify.txt", _verify_text(session)))
    out.append(("results/game.json", json.dumps(_game_info(session), indent=1)))
    out.append(("system.json", json.dumps(system_info(), indent=1)))
    out.append(("game-files.txt", _game_files(session)))
    readme = (f"Leonida V {__version__} debug report, made {time.strftime('%Y-%m-%d %H:%M')}.\n"
              "The user's name, home folder and PC name are replaced with <user> / <pc>, and anything that looks "
              "like a token, key, password or cookie is masked. No browser profile, cookies, logins or downloaded "
              "files are in it.\n")
    out.append(("README.txt", readme))
    return [(name, redact(text, homes, users, pc)) for name, text in out]


def preview(session) -> list[tuple[str, int]]:
    """What ``build`` would put in the zip: [(name, size in bytes)], to show before saving."""
    return [(name, len(text.encode("utf-8"))) for name, text in collect(session)]


def default_dir() -> Path:
    """The Desktop (OneDrive's when Windows keeps it there), else the home folder."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for cand in (home / "OneDrive" / "Desktop", home / "Desktop"):
        if cand.is_dir():
            return cand
    return home


def build(session, out_dir: Path | str | None = None, contents: list[tuple[str, str]] | None = None) -> Path:
    """Write the report zip into ``out_dir`` (default: the Desktop) and return its path. ``contents``: the result
    of ``collect`` when it was already shown to the user (so the zip holds exactly what they saw)."""
    contents = contents if contents is not None else collect(session)
    folder = Path(out_dir) if out_dir else default_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Leonida-report-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in contents:
            z.writestr(name, text)
    path.write_bytes(buf.getvalue())
    log.info("debug report saved: %s (%d files)", path.name, len(contents))
    return path
