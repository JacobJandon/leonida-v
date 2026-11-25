"""CodeWalker for the archive mods, fetched at first use from its author, never shipped with Leonida.

    status(state)                       # what's there: the helper, CodeWalker's commit and SHA-256s
    plan(state)                         # what prepare() would download (for the "OK?" question)
    prepare(state, progress=print)      # fetch + build: <state>/tools/LeonidaRpf/LeonidaRpf.exe

Leonida's RPF helper (``LeonidaRpf.exe``, the archive mods' engine, leonida/rpf.py) is our own small program on
**CodeWalker.Core by dexyfex**. CodeWalker's source is published on GitHub "for educational purposes" without a
licence, and dexyfex publishes no binary releases there (github.com/dexyfex/CodeWalker has none), so Leonida
neither ships nor re-hosts any CodeWalker file. Releases carry only our helper's own source (rpfhelper/).

At first use, on the user's own PC, from the authors' own servers (https only), each file's SHA-256 recorded and
shown:
  1. CodeWalker's source at the pinned commit from dexyfex's GitHub (codeload.github.com/dexyfex/CodeWalker), into
     <state>/tools/CodeWalker/ (the zip, the CodeWalker.Core folder, source.json with URL, commit and SHA-256);
  2. a .NET 8+ SDK: the one on PATH, else Microsoft's portable one (dotnet-install.ps1 from dot.net) into
     <state>/tools/dotnet/, nothing installed system-wide;
  3. ``dotnet build`` of our helper against that CodeWalker.Core (NuGet restores SharpDX from nuget.org), output in
     <state>/tools/LeonidaRpf/ with helper.json (what was built from what).

Network use goes through leonida.downloader (https, a plain User-Agent) except the SDK script's own downloads.
Tests pass ``fetch``/``run`` fakes; nothing here runs at import time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

# dexyfex/CodeWalker master as of 2025-04-11 ("ModManager progress"): has GTA V Enhanced (gen9) key loading.
COMMIT = "485d56bec00262ed7fa472261cce7bbc6202b96e"
REPO_PAGE = "https://github.com/dexyfex/CodeWalker"
SOURCE_URL = "https://codeload.github.com/dexyfex/CodeWalker/zip/{commit}"
DOTNET_INSTALL = "https://dot.net/v1/dotnet-install.ps1"
HELPER_NAME = "LeonidaRpf.exe"
PROJECT_FILES = ("LeonidaRpf.csproj", "Program.cs")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ToolsError(RuntimeError):
    """Getting or building the helper failed; the message says why and what to do."""


def tools_dir(state: Path) -> Path:
    return Path(state) / "tools"


def cw_dir(state: Path) -> Path:
    return tools_dir(state) / "CodeWalker"


def helper_dir(state: Path) -> Path:
    return tools_dir(state) / "LeonidaRpf"


def project_dir() -> Path:
    """Our helper's source: bundled in the frozen app (leonida/rpfhelper), else build/codewalker/LeonidaRpf."""
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "leonida" / "rpfhelper"
    if getattr(sys, "frozen", False) and bundled.is_dir():
        return bundled
    here = Path(__file__).resolve().parent
    for cand in (here / "rpfhelper", here.parent / "build" / "codewalker" / "LeonidaRpf"):
        if all((cand / f).is_file() for f in PROJECT_FILES):
            return cand
    raise ToolsError("The RPF helper's source (LeonidaRpf.csproj, Program.cs) is missing from this copy of Leonida.")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def status(state: Path) -> dict:
    """{"helper": path or None, "source": source.json, "build": helper.json} for Settings / `leonida tools`."""
    exe = helper_dir(state) / HELPER_NAME
    return {"helper": str(exe) if exe.is_file() else None,
            "source": _read_json(cw_dir(state) / "source.json"),
            "build": _read_json(helper_dir(state) / "helper.json")}


def find_sdk() -> Path | None:
    """A dotnet with a .NET 8+ SDK on PATH, or None."""
    exe = shutil.which("dotnet")
    if not exe:
        return None
    try:
        sdks = subprocess.run([exe, "--list-sdks"], capture_output=True, text=True, timeout=60,
                              creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    ok = any(line.split(".")[0].isdigit() and int(line.split(".")[0]) >= 8 for line in sdks.splitlines())
    return Path(exe) if ok else None


def plan(state: Path, dotnet: Path | None = None) -> list[str]:
    """What ``prepare`` would download, one line each (shown before asking the user)."""
    lines = []
    src = _read_json(cw_dir(state) / "source.json")
    if src.get("commit") != COMMIT or not (cw_dir(state) / "src" / "CodeWalker.Core").is_dir():
        lines.append(f"CodeWalker source by dexyfex, commit {COMMIT[:10]}, from {REPO_PAGE} (about 30 MB)")
    local_sdk = tools_dir(state) / "dotnet" / "dotnet.exe"
    if not (dotnet or find_sdk() or local_sdk.is_file()):
        lines.append(f"Microsoft's .NET 8 SDK, portable, into {tools_dir(state) / 'dotnet'} (about 220 MB, from "
                     "dot.net; nothing is installed system-wide)")
    lines.append("SharpDX (CodeWalker.Core's maths library) from nuget.org, during the build (about 2 MB)")
    return lines


# --------------------------------------------------------------------------------------------- the steps
def _default_fetch(url: str, dest: Path, progress) -> Path:
    from . import downloader

    plan_ = downloader.DownloadPlan("codewalker", "auto", REPO_PAGE, url=url, filename=dest.name)
    return downloader.download(plan_, dest.parent, progress=progress)


def fetch_source(state: Path, fetch=None, say: Callable[[str], None] = print) -> Path:
    """dexyfex's CodeWalker source at COMMIT -> <state>/tools/CodeWalker/src (CodeWalker.Core only). Records the
    zip's SHA-256 in source.json. Returns the src folder."""
    folder = cw_dir(state)
    src = folder / "src"
    record = _read_json(folder / "source.json")
    if record.get("commit") == COMMIT and (src / "CodeWalker.Core").is_dir():
        return src
    folder.mkdir(parents=True, exist_ok=True)
    url = SOURCE_URL.format(commit=COMMIT)
    say(f"Downloading CodeWalker's source (dexyfex, commit {COMMIT[:10]}) from GitHub ...")
    zpath = (fetch or _default_fetch)(url, folder / f"CodeWalker-{COMMIT[:10]}.zip", None)
    digest = sha256(zpath)
    if src.exists():
        shutil.rmtree(src)
    try:
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            top = names[0].split("/")[0] if names else ""
            root = src.resolve()
            for m in z.infolist():
                rel = m.filename[len(top) + 1:]
                if not rel or not (rel.startswith("CodeWalker.Core/") or rel in ("Readme_Src.txt", "Notice.txt")):
                    continue
                target = (src / rel).resolve()
                if not str(target).startswith(str(root) + os.sep):
                    raise ToolsError(f"Unsafe path in the CodeWalker source zip: {m.filename}")
                if m.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(z.read(m))
    except zipfile.BadZipFile as exc:
        raise ToolsError(f"The CodeWalker source download is not a zip ({exc}); try again later.") from None
    if not (src / "CodeWalker.Core").is_dir():
        raise ToolsError("The CodeWalker source has no CodeWalker.Core folder: the pinned commit may be gone.")
    (folder / "source.json").write_text(json.dumps({
        "author": "dexyfex", "repository": REPO_PAGE, "commit": COMMIT, "url": url, "file": zpath.name,
        "sha256": digest, "size": zpath.stat().st_size, "fetched": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1),
        encoding="utf-8")
    say(f"CodeWalker source: {zpath.name}, SHA-256 {digest}")
    return src


def get_sdk(state: Path, dotnet: Path | None = None, fetch=None, run=None, say: Callable[[str], None] = print) -> Path:
    """A dotnet.exe with a .NET 8+ SDK: ``dotnet``, the one on PATH, a portable one already in tools/dotnet, or
    Microsoft's dotnet-install.ps1 run now into tools/dotnet (its SHA-256 recorded in tools/dotnet/install.json)."""
    if dotnet:
        return Path(dotnet)
    found = find_sdk()
    if found:
        return found
    local = tools_dir(state) / "dotnet"
    exe = local / "dotnet.exe"
    if exe.is_file():
        return exe
    local.mkdir(parents=True, exist_ok=True)
    say("Downloading Microsoft's .NET SDK installer script (dot.net) ...")
    script = (fetch or _default_fetch)(DOTNET_INSTALL, local / "dotnet-install.ps1", None)
    (local / "install.json").write_text(json.dumps({"url": DOTNET_INSTALL, "sha256": sha256(script),
                                                    "channel": "8.0"}, indent=1), encoding="utf-8")
    say("Installing a portable .NET 8 SDK (Microsoft; a few minutes, about 220 MB) ...")
    (run or _run)(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Channel", "8.0",
                   "-InstallDir", str(local), "-NoPath"], None)
    if not exe.is_file():
        raise ToolsError(f"The .NET SDK install finished but {exe} is missing.")
    return exe


def _run(cmd: list[str], env: dict | None) -> None:
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, errors="replace", creationflags=_NO_WINDOW)
    if p.returncode != 0:
        tail = (p.stdout + p.stderr).strip().splitlines()[-15:]
        raise ToolsError(f"{Path(cmd[0]).name} failed (exit {p.returncode}):\n" + "\n".join(tail))


def build(state: Path, dotnet: Path, src: Path, run=None, say: Callable[[str], None] = print) -> Path:
    """Build our helper on that CodeWalker.Core into <state>/tools/LeonidaRpf/ (staged, then swapped in)."""
    out = helper_dir(state)
    staged = out.with_name(out.name + ".new")
    work = cw_dir(state) / "LeonidaRpf"
    for folder in (staged, work):
        shutil.rmtree(folder, ignore_errors=True)
    work.mkdir(parents=True)
    for name in PROJECT_FILES:
        shutil.copy2(project_dir() / name, work / name)
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
    say("Building the RPF helper on CodeWalker.Core (a minute or two) ...")
    (run or _run)([str(dotnet), "build", str(work / "LeonidaRpf.csproj"), "-c", "Release", "-nologo",
                   f"-p:CodeWalkerSrc={src}", "-o", str(staged)], env)
    if not (staged / HELPER_NAME).is_file():
        shutil.rmtree(staged, ignore_errors=True)
        raise ToolsError(f"The build finished but {HELPER_NAME} is missing.")
    for junk in staged.glob("*.pdb"):
        junk.unlink()
    files = {p.name: sha256(p) for p in sorted(staged.iterdir()) if p.is_file()}
    source = _read_json(cw_dir(state) / "source.json")
    (staged / "helper.json").write_text(json.dumps({
        "built": time.strftime("%Y-%m-%d %H:%M:%S"), "codewalker_commit": source.get("commit", COMMIT),
        "codewalker_source_sha256": source.get("sha256"), "files": files}, indent=1), encoding="utf-8")
    if out.exists():
        shutil.rmtree(out)
    staged.rename(out)
    return out / HELPER_NAME


def prepare(state: Path, *, dotnet: Path | None = None, source_dir: Path | None = None, fetch=None, run=None,
            say: Callable[[str], None] = print) -> Path:
    """Fetch CodeWalker's source and an SDK when needed, build the helper. Returns LeonidaRpf.exe.
    ``source_dir``: an already unpacked CodeWalker source (developers; recorded as such)."""
    if sys.platform != "win32" and run is None:
        raise ToolsError("The RPF helper is built on Windows only.")
    state = Path(state)
    if source_dir:
        src = Path(source_dir).resolve()
        cw_dir(state).mkdir(parents=True, exist_ok=True)
        (cw_dir(state) / "source.json").write_text(json.dumps({
            "author": "dexyfex", "repository": REPO_PAGE, "commit": COMMIT, "local_source": str(src)}, indent=1),
            encoding="utf-8")
    else:
        src = fetch_source(state, fetch, say)
    sdk = get_sdk(state, dotnet, fetch, run, say)
    exe = build(state, sdk, Path(src).resolve(), run, say)
    say(f"RPF helper ready: {exe}")
    return exe


def describe(state: Path) -> list[str]:
    """Human lines for `leonida tools` / Settings: the helper, CodeWalker's source and its SHA-256."""
    st = status(state)
    lines = [f"RPF helper: {st['helper'] or 'not built yet'}"]
    src = st["source"]
    if src:
        where = src.get("url") or src.get("local_source", "")
        lines.append(f"CodeWalker (dexyfex) source: commit {str(src.get('commit', ''))[:10]} from {where}")
        if src.get("sha256"):
            lines.append(f"  {src.get('file')}: SHA-256 {src['sha256']} ({src.get('size', 0) / 2**20:.1f} MB)")
    files = st["build"].get("files", {}) if st["build"] else {}
    for name in ("LeonidaRpf.exe", "CodeWalker.Core.dll"):
        if name in files:
            lines.append(f"  {name}: SHA-256 {files[name]}")
    return lines
