"""Release dry run: prove the self-updater consumes exactly what build_exe.py --release produces (opt-in, Windows).

    python build/build_exe.py --release       # first: dist/LeonidaV-<ver>-win64.zip, leonida-v-<ver>.zip, SHA256SUMS.txt
    python build/e2e_update.py [--keep]

It serves dist/ over http://127.0.0.1 with a fake GitHub "releases/latest" (tag v9.9.9, the assets listed in
dist/release-assets.txt), points leonida.downloader.GITHUB_API at it, and runs updater.check() + apply() on
throwaway copies in a temp folder, one per install kind:
  git  - a clone of this repo rewound one commit: apply() fast-forwards it (git pull --ff-only from its origin);
  zip  - a portable kit (Start-Leonida.bat + leonida-v + .venv marker): apply() stages leonida-v.new, then the real
         Start-Leonida.bat (with LEONIDA_SWAP_ONLY=1, so it stops after the swap) switches it in;
  exe  - an unpacked LeonidaV folder: apply() (as the frozen exe) stages LeonidaV.new and writes the real helper .bat,
         which is then run (restart off, so no window opens) and must swap the folder.
Nothing outside the temp folder is touched. Exit code 0 = everything passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.e2e_real_install import Report  # noqa: E402
from leonida import downloader, updater  # noqa: E402

DIST = ROOT / "dist"
TAG = "v9.9.9"
SENTINEL = "OLD-COPY.txt"


def serve(dist: Path, assets: list[Path]) -> tuple[ThreadingHTTPServer, str]:
    """dist/ under /dl/, and the fake API under /api/repos/<REPO>/releases/latest."""
    state: dict = {}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(dist), **k)

        def log_message(self, *a):  # quiet
            pass

        def do_GET(self):  # noqa: N802 - http.server naming
            if self.path == f"/api/repos/{updater.REPO}/releases/latest":
                body = json.dumps(state["release"]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/dl/"):
                self.path = self.path[3:]
                return super().do_GET()
            self.send_error(404)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    state["release"] = {
        "tag_name": TAG, "name": f"Leonida V {TAG[1:]}", "body": "Release dry run", "draft": False,
        "html_url": f"https://github.com/{updater.REPO}/releases/tag/{TAG}",
        "assets": [{"name": a.name, "size": a.stat().st_size, "browser_download_url": f"{base}/dl/{a.name}"}
                   for a in assets],
    }
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, base


def release_assets() -> list[Path]:
    listing = DIST / "release-assets.txt"
    if not listing.is_file():
        raise SystemExit("No dist/release-assets.txt: run python build/build_exe.py --release first.")
    return [ROOT / line.strip() for line in listing.read_text(encoding="utf-8").splitlines() if line.strip()]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def check_git(rep: Report, tmp: Path, info) -> None:
    clone = tmp / "git" / "leonida-v"
    subprocess.run(["git", "clone", "-q", str(ROOT), str(clone)], check=True)
    head = git(clone, "rev-parse", "HEAD")
    git(clone, "reset", "-q", "--hard", "HEAD~1")
    rep.check(updater.install_kind(clone) == "git", "git: a clone is seen as a git install")
    msg = updater.apply(info, clone, tmp / "git-state")
    rep.check(git(clone, "rev-parse", "HEAD") == head and "Updated the git clone" in msg,
              f"git: apply() fast-forwarded the clone to {head[:10]}")
    (clone / "pyproject.toml").write_text("local edit", encoding="utf-8")
    try:
        updater.apply(info, clone, tmp / "git-state")
        rep.problems.append("git: local changes were not refused")
    except updater.UpdateError as exc:
        rep.check("local changes" in str(exc), "git: local changes are refused, never reset")


def make_kit(tmp: Path, src_zip: Path) -> Path:
    kit = tmp / "kit"
    kit.mkdir()
    shutil.copy2(ROOT / "Start-Leonida.bat", kit / "Start-Leonida.bat")
    with zipfile.ZipFile(src_zip) as z:
        z.extractall(kit)
    (kit / "leonida-v" / SENTINEL).write_text("old", encoding="utf-8")
    (kit / ".venv").mkdir()
    (kit / ".venv" / updater.INSTALLED_MARKER).write_text("ok", encoding="utf-8")
    return kit


def check_zip(rep: Report, tmp: Path, info, src_zip: Path) -> None:
    kit = make_kit(tmp, src_zip)
    project = kit / "leonida-v"
    rep.check(updater.install_kind(project) == "zip", "zip: an unpacked kit is seen as a portable install")
    msg = updater.apply(info, project, kit / "State")
    staged = kit / "leonida-v.new"
    rep.check((staged / updater.READY_MARKER).is_file() and (staged / "pyproject.toml").is_file()
              and "Warning" not in msg, "zip: leonida-v.new staged and verified against SHA256SUMS.txt")
    env = dict(os.environ, LEONIDA_SWAP_ONLY="1", LEONIDA_NO_SHORTCUTS="1")
    p = subprocess.run(["cmd", "/d", "/c", str(kit / "Start-Leonida.bat")], cwd=kit, env=env, capture_output=True,
                       text=True, timeout=120)
    rep.check(p.returncode == 0, f"zip: Start-Leonida.bat ran (exit {p.returncode}) {p.stdout.strip()[-200:]}")
    rep.check(not staged.exists() and (kit / "leonida-v.old" / SENTINEL).is_file()
              and not (project / SENTINEL).exists() and not (project / updater.READY_MARKER).exists(),
              "zip: Start-Leonida.bat swapped leonida-v.new in and kept the previous copy as leonida-v.old")
    rep.check(not (kit / ".venv" / updater.INSTALLED_MARKER).exists(),
              "zip: the .venv marker was removed, so the next start reinstalls the package")


def check_exe(rep: Report, tmp: Path, info, win_zip: Path) -> None:
    apps = tmp / "apps"
    with zipfile.ZipFile(win_zip) as z:
        z.extractall(apps)
    install = apps / "LeonidaV"
    (install / SENTINEL).write_text("old", encoding="utf-8")
    exe = install / updater.GUI_EXE
    state = tmp / "exe-state"
    with mock.patch.object(sys, "frozen", True, create=True), \
            mock.patch.object(updater, "_current_exe", lambda: exe), \
            mock.patch.dict(os.environ, {"LEONIDA_NO_OPEN": "1"}):  # don't let apply() start the helper itself
        rep.check(updater.install_kind(install) == "exe", "exe: the frozen build is seen as an exe install")
        msg = updater.apply(info, install, state)
    staged = apps / "LeonidaV.new"
    helper = state / "updates" / "apply-update.bat"
    rep.check((staged / updater.GUI_EXE).is_file() and helper.is_file() and "Warning" not in msg,
              "exe: LeonidaV.new staged and verified; apply-update.bat written")
    text = helper.read_text(encoding="utf-8")
    rep.check(f'set "DIR={install}"' in text and 'start "" "%DIR%\\LeonidaV.exe"' in text,
              "exe: the helper swaps this folder and restarts LeonidaV.exe")
    # Run the same helper, but for a process that has already exited and without the restart (no window).
    gone = subprocess.Popen(["cmd", "/c", "exit 0"])
    gone.wait()  # its PID no longer runs: the helper's wait loop ends at once
    updater.write_helper(install, staged, helper, pid=gone.pid, restart=False, wait=20, tries=5)
    p = subprocess.run(["cmd", "/d", "/c", str(helper)], cwd=helper.parent, capture_output=True, text=True,
                       timeout=180)
    rep.check(p.returncode == 0 or not helper.exists(), f"exe: apply-update.bat ran (exit {p.returncode})")
    rep.check(not staged.exists() and (apps / "LeonidaV.old" / SENTINEL).is_file()
              and (install / updater.GUI_EXE).is_file() and not (install / SENTINEL).exists()
              and not (install / updater.READY_MARKER).exists(),
              "exe: the helper swapped LeonidaV.new in and kept the previous folder as LeonidaV.old")


def run(keep: bool = False) -> Report:
    rep = Report()
    assets = release_assets()
    names = [a.name for a in assets]
    win_zip = next((a for a in assets if a.name.lower().endswith("-win64.zip")), None)
    src_zip = next((a for a in assets if a.name.lower().startswith("leonida-v-")), None)
    rep.check(bool(win_zip and src_zip and "SHA256SUMS.txt" in names and all(a.is_file() for a in assets)),
              f"release assets present: {', '.join(names)}")
    if rep.problems:
        return rep
    httpd, base = serve(DIST, assets)
    tmp = Path(tempfile.mkdtemp(prefix="leonida-e2e-update-"))
    try:
        with mock.patch.object(downloader, "GITHUB_API", f"{base}/api"):
            info = updater.check()
        rep.check(info.latest == TAG[1:] and info.newer, f"check(): {info.current} -> {info.latest}, newer")
        rep.check(info.zip_url and info.zip_url.endswith(src_zip.name) and info.exe_url
                  and info.exe_url.endswith(win_zip.name), "check(): picked the source zip and the win64 zip")
        rep.check(set(info.sha256) >= {win_zip.name, src_zip.name}, "check(): read SHA256SUMS.txt")
        for name, fn, arg in (("git", check_git, None), ("zip", check_zip, src_zip), ("exe", check_exe, win_zip)):
            try:
                fn(rep, tmp, info) if arg is None else fn(rep, tmp, info, arg)
            except Exception as exc:  # noqa: BLE001 - report and continue with the next kind
                rep.problems.append(f"{name}: {type(exc).__name__}: {exc}")
    finally:
        httpd.shutdown()
        if keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return rep


def main() -> int:
    if sys.platform != "win32":
        sys.exit("Windows only (Start-Leonida.bat and the helper .bat).")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true")
    rep = run(ap.parse_args().keep)
    for line in rep.ok:
        print("  ok    " + line)
    for line in rep.problems:
        print("  FAIL  " + line)
    print("PASSED" if rep.passed else "FAILED", f"({len(rep.ok)} ok, {len(rep.problems)} failed)")
    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
