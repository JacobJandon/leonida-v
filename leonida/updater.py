"""Leonida V self-updater: check the latest GitHub release and update a git clone, portable zip or .exe build.

Nothing updates unless the user asks (the GUI's Update button or ``leonida self-update``). Files come only from
the Leonida V GitHub releases; the zip and exe are checked against the release's SHA256SUMS file when it has one.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import __version__, downloader
from .archive import ArchiveError, extract
from .downloader import DownloadError, DownloadPlan

log = logging.getLogger(__name__)

REPO = "JacobJandon/leonida-v"
ZIP_GLOB = "leonida-v-*.zip"
EXE_GLOB = "leonidav-*-win64.zip"  # the whole PyInstaller onedir folder (dist/LeonidaV)
GUI_EXE = "LeonidaV.exe"
SUMS_GLOB = "sha256sums*"
READY_MARKER = ".leonida-update-ready"
INSTALLED_MARKER = ".leonida-installed"
MAX_NOTES = 2000
CACHE_NAME = "update-check.json"
DAY = 24 * 3600
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class UpdateError(DownloadError):
    """The update was refused or failed. The message says why and what to do; nothing was half-applied."""


@dataclass
class UpdateInfo:
    current: str            # leonida.__version__
    latest: str | None      # tag of the latest release, without a leading "v"; None = no release yet
    newer: bool
    notes: str              # release body (first ~2000 chars)
    page: str               # release html_url
    zip_url: str | None     # asset matching "leonida-v-*.zip"
    exe_url: str | None     # frozen builds: asset matching "LeonidaV-*-win64.zip" (the whole install folder)
    sha256: dict[str, str] = field(default_factory=dict)  # asset name -> sha256 (from SHA256SUMS*)
    checked_at: float | None = None  # when GitHub was asked (epoch seconds)
    from_cache: bool = False         # True when check() answered from <state>/update-check.json

    @property
    def age(self) -> float | None:
        """Seconds since this result was fetched from GitHub."""
        return None if self.checked_at is None else max(0.0, time.time() - self.checked_at)


# --------------------------------------------------------------------------------------------- versions
_VERSION_RE = re.compile(
    r"^v?(?P<release>\d+(?:\.\d+)*)"
    r"(?:[.-]?(?P<pre>a|alpha|b|beta|rc|c|pre|preview)[.-]?(?P<pre_n>\d*))?"
    r"(?:[.-]?(?P<post>post|rev|r)[.-]?(?P<post_n>\d*))?"
    r"(?:[.-]?(?P<dev>dev)[.-]?(?P<dev_n>\d*))?"
    r"(?:\+[a-z0-9.]*)?$",
    re.IGNORECASE,
)
_PRE_RANK = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2, "pre": 2, "preview": 2}
_INF = float("inf")


def parse_version(text: str | None) -> tuple | None:
    """A sortable key for a PEP 440-style version (1.0.0.dev1 < 1.0.0a1 < 1.0.0 < 1.0.0.post1), or None."""
    m = _VERSION_RE.match(str(text or "").strip())
    if not m:
        return None
    release = [int(x) for x in m["release"].split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    if m["pre"]:
        pre = (_PRE_RANK[m["pre"].lower()], int(m["pre_n"] or 0))
    elif m["dev"] and not m["post"]:
        pre = (-1, 0)  # 1.0.dev1 sorts before 1.0a1
    else:
        pre = (_INF, 0)
    post = int(m["post_n"] or 0) if m["post"] else -1
    dev = int(m["dev_n"] or 0) if m["dev"] else _INF
    return (tuple(release), pre, post, dev)


def is_newer(latest: str | None, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


# ---------------------------------------------------------------------------------------------- where am I
def project_dir() -> Path:
    """The folder holding pyproject.toml / .git (the parent of the ``leonida`` package)."""
    return Path(__file__).resolve().parent.parent


def install_kind(project_dir: Path) -> str:
    """"exe" for a frozen build, "git" for a clone (has .git), else "zip" (portable kit)."""
    if getattr(sys, "frozen", False):
        return "exe"
    if (Path(project_dir) / ".git").exists():
        return "git"
    return "zip"


def _current_exe() -> Path:
    return Path(sys.executable)


# --------------------------------------------------------------------------------------------------- check
def _parse_sums(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            sums[m.group(2).replace("\\", "/").split("/")[-1]] = m.group(1).lower()
    return sums


def cached_check(cache_dir: Path) -> UpdateInfo | None:
    """The last saved check result, however old (no network). None if there is none or it's unreadable.
    ``newer`` is recomputed against the running version."""
    try:
        data = json.loads((Path(cache_dir) / CACHE_NAME).read_text(encoding="utf-8"))
        fields = {k: v for k, v in data.items() if k in UpdateInfo.__dataclass_fields__}
        info = UpdateInfo(**fields)
    except (OSError, ValueError, TypeError):
        return None
    info.current = __version__
    info.newer = is_newer(info.latest, __version__)
    info.from_cache = True
    return info


def _save_cache(cache_dir: Path, info: UpdateInfo) -> None:
    try:
        path = Path(cache_dir) / CACHE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in asdict(info).items() if k != "from_cache"}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # the cache is only a convenience


def check(timeout: float = 15, cache_dir: Path | None = None, max_age: float | None = None) -> UpdateInfo:
    """Latest release of Leonida V. No release yet -> latest=None, newer=False. Network problems raise DownloadError.

    With ``cache_dir`` (the state folder) the result is saved to ``update-check.json``; with ``max_age`` (seconds)
    a saved result younger than that is returned without asking GitHub (``from_cache`` True). ``max_age=0`` or
    None always asks GitHub. The daily auto-check passes ``max_age=DAY``; "Check now" passes 0."""
    if cache_dir is not None and max_age:
        cached = cached_check(cache_dir)
        if cached is not None and cached.age is not None and cached.age <= max_age:
            return cached
    info = _check_github(timeout)
    log.info("update check: current %s, latest %s, newer %s", info.current, info.latest, info.newer)
    if cache_dir is not None:
        _save_cache(cache_dir, info)
    return info


def _check_github(timeout: float) -> UpdateInfo:
    base = downloader.GITHUB_API.rstrip("/")
    release = downloader._github_json(f"{base}/repos/{REPO}/releases/latest", REPO, timeout)
    if not release:
        return UpdateInfo(__version__, None, False, "", f"https://github.com/{REPO}/releases", None, None, {},
                          checked_at=time.time())
    latest = str(release.get("tag_name") or release.get("name") or "").strip()
    latest = latest[1:] if latest[:1] in ("v", "V") else latest
    assets = [a for a in release.get("assets") or [] if a.get("browser_download_url")]

    def pick(glob: str, exclude: str = "") -> dict | None:
        for a in assets:
            name = str(a.get("name", "")).lower()
            if fnmatch.fnmatchcase(name, glob) and not (exclude and fnmatch.fnmatchcase(name, exclude)):
                return a
        return None

    zip_a, exe_a, sums_a = pick(ZIP_GLOB, exclude="*win64*"), pick(EXE_GLOB), pick(SUMS_GLOB)
    sums: dict[str, str] = {}
    if sums_a:
        try:
            with downloader._open(sums_a["browser_download_url"], timeout) as r:
                sums = _parse_sums(r.read(256 * 1024).decode("utf-8", errors="replace"))
        except Exception:  # missing sums only means "can't verify": apply() warns about it
            sums = {}
    return UpdateInfo(
        current=__version__,
        latest=latest or None,
        newer=is_newer(latest, __version__),
        notes=str(release.get("body") or "")[:MAX_NOTES],
        page=str(release.get("html_url") or f"https://github.com/{REPO}/releases"),
        zip_url=zip_a["browser_download_url"] if zip_a else None,
        exe_url=exe_a["browser_download_url"] if exe_a else None,
        sha256=sums,
        checked_at=time.time(),
    )


# --------------------------------------------------------------------------------------------------- apply
def apply(info: UpdateInfo, project_dir: Path, state_dir: Path,
          progress: Callable[[int, int | None], None] | None = None, force: bool = False) -> str:
    """Update this copy of Leonida V to ``info.latest``. Returns a message for the user; raises UpdateError
    (a DownloadError) when the update is refused or fails.

    ``force=True`` (re)installs the latest release even when it isn't newer (same version, or a broken copy):
    git -> fetch + pull --ff-only and the package reinstalls on the next start; zip/exe -> a fresh download,
    verified and staged/swapped as usual. Local git changes are still refused, never reset."""
    if not info.latest:
        if force:
            raise UpdateError("No Leonida V release has been published yet")
        return f"Leonida V {info.current} is up to date."
    if not info.newer and not force:
        return f"Leonida V {info.current} is up to date."
    log.info("update: %s -> %s%s", info.current, info.latest, " (forced)" if force else "")
    try:
        return _apply(info, Path(project_dir), Path(state_dir), progress, force)
    except OSError as exc:  # disk full, locked file, no permission...: a clear message, nothing switched over
        log.error("update failed: %s", exc)
        raise UpdateError(f"Updating Leonida V failed: {exc}. Nothing was switched over; try again.") from None


def _apply(info: UpdateInfo, project_dir: Path, state_dir: Path, progress, force: bool) -> str:
    kind = install_kind(project_dir)
    if kind == "git":
        return _apply_git(info, project_dir, force)
    note = ""
    if force and parse_version(info.current) and parse_version(info.latest) \
            and parse_version(info.current) > parse_version(info.latest):
        note = f"Note: this replaces your newer {info.current} with the release {info.latest}.\n"
    if kind == "exe":
        return note + _apply_exe(info, state_dir, progress, force)
    return note + _apply_zip(info, project_dir, state_dir, progress, force)


def request_reinstall(project_dir: Path) -> str:
    """Offline repair for a git/zip copy: delete ``.venv\\.leonida-installed`` so the next Start-Leonida.bat
    reinstalls the package and its dependencies. Returns a message; UpdateError for an .exe build."""
    project_dir = Path(project_dir)
    if install_kind(project_dir) == "exe":
        raise UpdateError("The .exe build has no Python package to reinstall; use Force update instead.")
    venv = _venv_dir(project_dir)
    if venv is None:
        return (f"No .venv next to {project_dir}, so there's nothing to reset; Start-Leonida.bat creates it "
                "on the next start.")
    (venv / INSTALLED_MARKER).unlink(missing_ok=True)
    return f"Close Leonida V and start it again with Start-Leonida.bat: it reinstalls the package into {venv}."


def _git(project: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True,
                              errors="replace", check=False, creationflags=_NO_WINDOW)
    except FileNotFoundError:
        raise UpdateError("git is not installed or not on PATH. Install Git for Windows, or update by hand.") from None


def _venv_dir(project: Path) -> Path | None:
    for cand in (project.parent / ".venv", project / ".venv"):
        if cand.is_dir():
            return cand
    return None


def _apply_git(info: UpdateInfo, project: Path, force: bool = False) -> str:
    dirty = _git(project, "status", "--porcelain", "--untracked-files=no")
    if dirty.returncode != 0:
        raise UpdateError(f"git status failed in {project}:\n{(dirty.stderr or dirty.stdout).strip()}")
    if dirty.stdout.strip():
        raise UpdateError(
            f"Not updating: {project} has local changes:\n{dirty.stdout.rstrip()}\n"
            "Commit or undo them first (Leonida never stashes or resets your work), then try again."
        )
    old = _git(project, "rev-parse", "HEAD").stdout.strip()
    output = ""
    if force:
        fetch = _git(project, "fetch")
        output = (fetch.stdout + fetch.stderr).strip()
        if fetch.returncode != 0:
            raise UpdateError(f"git fetch failed:\n{output}")
    pull = _git(project, "pull", "--ff-only")
    output = "\n".join(x for x in (output, (pull.stdout + pull.stderr).strip()) if x)
    if pull.returncode != 0:
        raise UpdateError(f"git pull --ff-only failed:\n{output}")
    new = _git(project, "rev-parse", "HEAD").stdout.strip()
    if force:
        venv = _venv_dir(project)
        if venv:
            (venv / INSTALLED_MARKER).unlink(missing_ok=True)
        head = "Already at the latest commit" if not old or old == new else f"Updated the git clone to {new[:10]}"
        lines = [f"{head} (forced).", output,
                 "Close Leonida V and start it again with Start-Leonida.bat: it reinstalls the package."]
        return "\n".join(x for x in lines if x)
    if not old or old == new:
        return f"Already up to date (git).\n{output}"
    changed = _git(project, "diff", "--name-only", old, new).stdout.split()
    msg = f"Updated the git clone to {new[:10]}.\n{output}\n"
    if "pyproject.toml" in changed:
        venv = _venv_dir(project)
        if venv:
            (venv / INSTALLED_MARKER).unlink(missing_ok=True)
        return msg + "Dependencies changed: close Leonida V and start it again with Start-Leonida.bat (it reinstalls)."
    return msg + "Restart Leonida V to use the new version."


def _asset_name(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def _fetch_verified(info: UpdateInfo, url: str, state_dir: Path, progress, fresh: bool = False) -> tuple[Path, str]:
    """Download a release asset into <state>/updates/<version>/ and check it. Returns (path, warning).
    ``fresh`` deletes an earlier download of it first (force update / repair)."""
    name = downloader._safe_name(_asset_name(url)) or "leonida-update.bin"
    folder = state_dir / "updates" / downloader._safe_name(info.latest or "latest")
    if fresh:
        (folder / name).unlink(missing_ok=True)
        (folder / f"{name}.part").unlink(missing_ok=True)
    plan = DownloadPlan("leonida-v", "auto", info.page, url=url, filename=name)
    path = downloader.download(plan, folder, progress=progress)
    expected = info.sha256.get(name)
    if not expected:
        return path, f"Warning: the release has no SHA-256 for {name}, so the download could not be verified."
    actual = _sha256(path)
    if actual != expected.lower():
        path.unlink(missing_ok=True)
        raise UpdateError(
            f"Not updating: {name} does not match the release's SHA-256 (expected {expected}, got {actual}). "
            f"The file was deleted; try again later or download it from {info.page}"
        )
    return path, ""


def _stage(archive: Path, staged: Path, key_file: str, also: str | None = None) -> None:
    """Unpack ``archive`` into ``staged`` (zip-slip safe). A single top folder is flattened. ``key_file`` (and the
    folder ``also``) must then exist at the top, else the staging folder is removed and UpdateError raised."""
    if staged.exists():
        shutil.rmtree(staged)
    try:
        extract(archive, staged)
        if not (staged / key_file).is_file():
            inner = [p for p in staged.iterdir() if p.is_dir() and (p / key_file).is_file()]
            if len(inner) != 1 or len(list(staged.iterdir())) != 1:
                raise UpdateError(f"{archive.name} does not look like a Leonida V release (no {key_file}).")
            for child in list(inner[0].iterdir()):
                shutil.move(str(child), str(staged / child.name))
            inner[0].rmdir()
        if also and not (staged / also).exists():
            raise UpdateError(f"{archive.name} does not look like a Leonida V release (no {also}).")
    except (ArchiveError, OSError, UpdateError) as exc:
        shutil.rmtree(staged, ignore_errors=True)
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"Could not unpack {archive.name}: {exc}") from None


def _apply_zip(info: UpdateInfo, project: Path, state_dir: Path, progress, force: bool = False) -> str:
    if not info.zip_url:
        raise UpdateError(f"The {info.latest} release has no leonida-v-*.zip. Download it from {info.page}")
    if project.name.lower() != "leonida-v":
        raise UpdateError(
            f"This copy lives in {project}, but Start-Leonida.bat expects a 'leonida-v' folder. "
            f"Update by hand from {info.page}"
        )
    path, warning = _fetch_verified(info, info.zip_url, state_dir, progress, fresh=force)
    staged = project.parent / "leonida-v.new"
    _stage(path, staged, "pyproject.toml", "leonida")
    try:
        (staged / READY_MARKER).write_text(f"{info.latest}\n", encoding="utf-8")
    except OSError:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    msg = (f"Leonida V {info.latest} is ready in {staged}.\n"
           "Close Leonida V and start it again with Start-Leonida.bat to switch over "
           "(State and Downloads are kept; the old copy stays in leonida-v.old).")
    return f"{warning}\n{msg}" if warning else msg


_HELPER = r"""@echo off
setlocal EnableExtensions
rem Written by Leonida V: once Leonida V has exited, swap the downloaded version into place and restart it.
rem State and downloads live outside this folder, so nothing in it needs keeping.
set "DIR={dir}"
set "NEW={new}"
set "OLD={old}"
set "TL=%SystemRoot%\System32\tasklist.exe"
set "FIND=%SystemRoot%\System32\find.exe"
set /a N=0
:waitpid
"%TL%" /FI "PID eq {pid}" /NH 2>nul | "%FIND%" " {pid} " >nul || goto :waitexe
set /a N+=1
if %N% GEQ {wait} goto :giveup
ping -n 2 127.0.0.1 >nul
goto :waitpid
:waitexe
{exe_checks}goto :swap
:busy
set /a N+=1
if %N% GEQ {wait} goto :giveup
ping -n 2 127.0.0.1 >nul
goto :waitexe
:swap
if exist "%OLD%" rmdir /s /q "%OLD%"
if exist "%OLD%" goto :giveup
set /a N=0
:moveold
move "%DIR%" "%OLD%" >nul 2>&1 && goto :movenew
set /a N+=1
if %N% GEQ {tries} goto :giveup
ping -n 2 127.0.0.1 >nul
goto :moveold
:movenew
move "%NEW%" "%DIR%" >nul 2>&1 && goto :done
move "%OLD%" "%DIR%" >nul 2>&1
goto :giveup
:done
del "%DIR%\{marker}" >nul 2>&1
{restart}
(goto) 2>nul & del "%~f0" >nul 2>&1
:giveup
echo Leonida V could not switch "%DIR%" to the downloaded update in "%NEW%". Close Leonida V and run this file again: "%~f0"> "%~dpn0.log"
exit /b 1
"""


def _q(p: Path) -> str:
    return str(p).replace("%", "%%")


LEONIDA_EXES = ("LeonidaV.exe", "leonida.exe")


def write_helper(install: Path, staged: Path, helper: Path, pid: int, restart: bool = True,
                 wait: int = 300, tries: int = 30, exes: tuple[str, ...] = LEONIDA_EXES) -> Path:
    """Write the .bat that swaps ``staged`` in for ``install`` once process ``pid`` and every Leonida exe (``exes``)
    exited."""
    old = install.with_name(install.name + ".old")
    restart_cmd = f'start "" "%DIR%\\{GUI_EXE}"' if restart else "rem (no restart)"
    checks = "".join(f'"%TL%" /FI "IMAGENAME eq {e}" /NH 2>nul | "%FIND%" /i "{e}" >nul && goto :busy\n'
                     for e in exes)
    text = _HELPER.format(dir=_q(install), new=_q(staged), old=_q(old), pid=pid, wait=wait, tries=tries,
                          marker=READY_MARKER, restart=restart_cmd, exe_checks=checks)
    helper.parent.mkdir(parents=True, exist_ok=True)
    with open(helper, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(text)
    return helper


def _apply_exe(info: UpdateInfo, state_dir: Path, progress, force: bool = False) -> str:
    if not info.exe_url:
        raise UpdateError(f"The {info.latest} release has no LeonidaV-*-win64.zip. Download it from {info.page}")
    install = _current_exe().parent
    staged = install.with_name(install.name + ".new")
    path, warning = _fetch_verified(info, info.exe_url, state_dir, progress, fresh=force)
    _stage(path, staged, GUI_EXE)
    try:
        (staged / READY_MARKER).write_text(f"{info.latest}\n", encoding="utf-8")
        helper = write_helper(install, staged, state_dir / "updates" / "apply-update.bat", os.getpid())
    except OSError:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    if sys.platform == "win32" and not os.environ.get("LEONIDA_NO_OPEN"):
        # A hidden console (not DETACHED_PROCESS, so tasklist/ping don't pop up windows), outside the install dir.
        flags = _NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(["cmd", "/c", str(helper)], cwd=str(helper.parent), creationflags=flags, close_fds=True)
    msg = (f"Leonida V {info.latest} is downloaded and unpacked. Close Leonida V to finish: it switches to the new "
           f"version and restarts (the old one stays in {install.name}.old).")
    return f"{warning}\n{msg}" if warning else msg
