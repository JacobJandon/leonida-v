"""End-to-end check of the installer and the installed app's self-update (Windows; real exes, temp folders only).

    python build/e2e_setup.py --old DIST_N --new DIST_N1 [--keep]
    python build/e2e_setup.py --smoke DIST          # just install + uninstall one setup silently

DIST_N:  a dist/ folder of version N with Leonida-V-Setup-<N>.exe (build_exe.py --release).
DIST_N1: a dist/ folder of version N+1 with release-assets.txt (its win64 zip, source zip, SHA256SUMS.txt).

What it does, with the real exes:
  1. Leonida-V-Setup-<N>.exe /S into <tmp>\\Programs\\Leonida V with the data in <tmp>\\Leonida V: files, the
     registry (HKCU\\<own test root>), the Apps & features entry, Start menu + desktop shortcuts, State's config;
  2. a fake GitHub on 127.0.0.1 (LEONIDA_GITHUB_API) publishes release N+1;
  3. first with a corrupt win64 zip: the installed `leonida.exe self-update` must refuse it (SHA256SUMS mismatch)
     and change nothing;
  4. then the real one: it downloads, verifies, stages, and its helper swaps the folder after the app exits and
     restarts LeonidaV.exe, which (LEONIDA_SELFTEST) reports its version: N+1; State/Downloads are kept, the old
     folder stays as "Leonida V.old", Apps & features shows N+1;
  5. "LeonidaV.exe --uninstall --silent": shortcuts, registry and the program folder go; State/Downloads stay.
Nothing touches the real Start menu, desktop, registry entries or any game.
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
import time
import winreg
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.e2e_real_install import Report  # noqa: E402
from leonida import shortcuts, updater  # noqa: E402


def read_key(root: str, sub: str) -> dict:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{root}\\{sub}") as k:
            out, i = {}, 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    return out
                out[name] = value
                i += 1
    except OSError:
        return {}


def run(cmd: list, env: dict, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], env=env, capture_output=True, text=True, errors="replace",
                          timeout=timeout)


def version_of(install: Path, env: dict) -> str:
    p = run([install / "leonida.exe", "--version"], env, 120)
    return (p.stdout or p.stderr).strip().split()[-1] if (p.stdout or p.stderr).strip() else "?"


class FakeGitHub:
    """/api/repos/<REPO>/releases/latest -> one release; /dl/<name> -> files from ``files`` (name -> path)."""

    def __init__(self, tag: str, files: dict[str, Path]):
        self.files = dict(files)
        outer = self

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                if self.path == f"/api/repos/{updater.REPO}/releases/latest":
                    body = json.dumps(outer.release).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                name = self.path.rsplit("/", 1)[-1]
                src = outer.files.get(name)
                if not self.path.startswith("/dl/") or src is None:
                    self.send_error(404)
                    return
                data = src.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.release = {
            "tag_name": tag, "name": f"Leonida V {tag[1:]}", "body": "End-to-end check", "draft": False,
            "html_url": f"https://github.com/{updater.REPO}/releases/tag/{tag}",
            "assets": [{"name": n, "size": p.stat().st_size, "browser_download_url": f"{self.base}/dl/{n}"}
                       for n, p in files.items()]}
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


def setup_exe(dist: Path) -> Path:
    found = sorted(dist.glob("Leonida-V-Setup-*.exe"))
    if not found:
        raise SystemExit(f"No Leonida-V-Setup-*.exe in {dist}: run build_exe.py --release there first.")
    return found[-1]


def base_env(tmp: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LEONIDA_", "QT_"))}
    env.update(LEONIDA_REG_ROOT=f"Software\\LeonidaV-e2e-{os.getpid()}", LEONIDA_STARTMENU_DIR=str(tmp / "startmenu"),
               LEONIDA_DESKTOP_DIR=str(tmp / "desktop"), LEONIDA_NO_UPDATE_CHECK="1", QT_QPA_PLATFORM="offscreen",
               QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu",
               LEONIDA_DATA_SEARCH="")   # never search the real drives for a data folder (winsetup.find_data_dirs)
    return env


def install_step(rep: Report, exe: Path, install: Path, data: Path, env: dict, expect: str) -> bool:
    p = run([exe, "/S", "--dir", install, "--data", data, "--log", install.parent.parent / "setup.log"], env, 900)
    ok = p.returncode == 0 and (install / "LeonidaV.exe").is_file() and (install / "leonida.exe").is_file()
    rep.check(ok, f"setup: {exe.name} /S installed into {install} (exit {p.returncode})")
    if not ok:
        return False
    root = env["LEONIDA_REG_ROOT"]
    app = read_key(root, "Leonida V")
    uninst = read_key(root, "Uninstall\\LeonidaV")
    rep.check(app.get("InstallDir") == str(install) and app.get("DataDir") == str(data) and app.get("Version") == expect,
              f"setup: registered InstallDir / DataDir / Version {expect}")
    rep.check(uninst.get("DisplayName") == "Leonida V" and uninst.get("DisplayVersion") == expect
              and "--uninstall" in str(uninst.get("UninstallString")) and uninst.get("NoModify") == 1
              and int(uninst.get("EstimatedSize", 0)) > 10_000,
              "setup: Apps & features entry (name, version, uninstaller, size)")
    lnks = [Path(env["LEONIDA_STARTMENU_DIR"]) / "Leonida V.lnk", Path(env["LEONIDA_DESKTOP_DIR"]) / "Leonida V.lnk"]
    exe_path = install / "LeonidaV.exe"

    def points_at_exe(lnk: Path) -> bool:
        # the same file, not the same spelling: CI's temp folder can come back as an 8.3 short path (RUNNER~1)
        target = shortcuts.read(lnk)["target"]
        try:
            return os.path.samefile(target, exe_path)
        except OSError:
            return target.lower() == str(exe_path).lower()

    targets = {lnk.name + " in " + lnk.parent.name: (shortcuts.read(lnk)["target"] if lnk.is_file() else "missing")
               for lnk in lnks}
    rep.check(all(lnk.is_file() for lnk in lnks) and all(points_at_exe(lnk) for lnk in lnks),
              "setup: Start menu and desktop shortcuts point at the installed LeonidaV.exe"
              + ("" if all(lnk.is_file() and points_at_exe(lnk) for lnk in lnks)
                 else f" (expected {exe_path}; found {targets})"))
    cfg = json.loads((data / "State" / "config.json").read_text(encoding="utf-8"))
    rep.check(cfg.get("download_dir") == str(data / "Downloads") and (data / "Downloads").is_dir(),
              "setup: State\\config.json uses <data>\\Downloads")
    rep.check(version_of(install, env) == expect, f"installed leonida.exe --version: {expect}")
    return True


def check_update(rep: Report, tmp: Path, install: Path, data: Path, env: dict, new_dist: Path, old_v: str,
                 new_v: str) -> None:
    assets = [new_dist / Path(line.strip()).name for line in
              (new_dist / "release-assets.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    files = {a.name: a for a in assets if a.suffix != ".exe"}
    win = next(a for a in assets if a.name.endswith("-win64.zip"))
    corrupt = tmp / "corrupt" / win.name
    corrupt.parent.mkdir()
    blob = bytearray(win.read_bytes())
    blob[len(blob) // 2] ^= 0xFF
    corrupt.write_bytes(bytes(blob))
    gh = FakeGitHub(f"v{new_v}", {**files, win.name: corrupt})
    env = dict(env, LEONIDA_GITHUB_API=f"{gh.base}/api")
    (data / "State" / "e2e-sentinel.txt").write_text("keep me", encoding="utf-8")
    (data / "Downloads" / "some-mod.zip").write_bytes(b"PK mod")
    try:
        # the installed app reads its data folder from the registry: the check is cached into <data>\State
        p = run([install / "leonida.exe", "self-update", "--check"], env)
        rep.check(p.returncode == 0 and new_v in p.stdout and (data / "State" / "update-check.json").is_file(),
                  f"installed app sees {new_v} (and keeps its state in the data folder)")
        p = run([install / "leonida.exe", "self-update"], env, 600)
        rep.check(p.returncode != 0 and "SHA-256" in p.stdout and not install.with_name(install.name + ".new").exists()
                  and version_of(install, env) == old_v,
                  "corrupt download refused (SHA256SUMS mismatch), nothing switched over")
        gh.files[win.name] = win
        restart_report = tmp / "restarted.json"
        env2 = dict(env, LEONIDA_SELFTEST="1", LEONIDA_SELFTEST_OUT=str(restart_report))  # the restarted app reports
        p = run([install / "leonida.exe", "self-update"], env2, 900)
        rep.check(p.returncode == 0 and "downloaded and unpacked" in p.stdout,
                  f"good download verified and staged ({p.stdout.strip().splitlines()[-1][:120] if p.stdout else ''})")
        end = time.time() + 300
        while time.time() < end and not restart_report.is_file():
            time.sleep(2)
        report = json.loads(restart_report.read_text(encoding="utf-8")) if restart_report.is_file() else {}
        title = str(report.get("checks", {}).get("window_title", "")) if report else ""
        rep.check(report.get("version") == new_v and report.get("frozen"),
                  f"the helper swapped and restarted LeonidaV.exe: it runs {report.get('version')} ({title or 'no report'})")
        rep.check(version_of(install, env) == new_v, f"installed leonida.exe --version: {new_v}")
        old = install.with_name(install.name + ".old")
        rep.check(old.is_dir() and version_of(old, env) == old_v, f"the previous {old_v} is kept in {old.name}")
        rep.check((data / "State" / "e2e-sentinel.txt").read_text(encoding="utf-8") == "keep me"
                  and (data / "Downloads" / "some-mod.zip").is_file(), "State and Downloads kept")
        root = env["LEONIDA_REG_ROOT"]
        end = time.time() + 30
        while time.time() < end and read_key(root, "Uninstall\\LeonidaV").get("DisplayVersion") != new_v:
            time.sleep(1)
        rep.check(read_key(root, "Uninstall\\LeonidaV").get("DisplayVersion") == new_v
                  and read_key(root, "Leonida V").get("Version") == new_v,
                  f"Apps & features shows {new_v} after the update")
    finally:
        gh.httpd.shutdown()


def uninstall_step(rep: Report, install: Path, data: Path, env: dict) -> None:
    p = run([install / "LeonidaV.exe", "--uninstall", "--silent"], env, 120)
    end = time.time() + 120
    while time.time() < end and install.exists():
        time.sleep(1)
    root = env["LEONIDA_REG_ROOT"]
    rep.check(p.returncode == 0 and not install.exists(), "uninstall: the program folder is removed (after it exited)")
    rep.check(not read_key(root, "Leonida V") and not read_key(root, "Uninstall\\LeonidaV"),
              "uninstall: registry entries removed")
    rep.check(not any(Path(env[k], "Leonida V.lnk").exists() for k in ("LEONIDA_STARTMENU_DIR", "LEONIDA_DESKTOP_DIR")),
              "uninstall: shortcuts removed")
    rep.check((data / "State").is_dir() and (data / "Downloads").is_dir(),
              "uninstall: State and Downloads kept (not asked to delete them)")


def reinstall_step(rep: Report, exe: Path, install: Path, data: Path, env: dict, expect: str) -> None:
    """Uninstalled (data kept) -> the setup again with no data folder given: it finds the same data, nothing is lost,
    and Leonida doesn't start over (the owner: "remember, never set up again, never redownload")."""
    cfg_path = data / "State" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.update(game_dir=r"C:\Games\GTA V (e2e)", profile="owner-pick")
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    (data / "Downloads" / "e2e-mod-1.0.zip").write_bytes(b"kept")
    p = run([exe, "/S", "--dir", install, "--log", install.parent.parent / "setup-again.log"], env, 900)
    app = read_key(env["LEONIDA_REG_ROOT"], "Leonida V")
    rep.check(p.returncode == 0 and app.get("DataDir") == str(data),
              f"reinstall: setup /S without --data found the kept data folder {data} (got {app.get('DataDir')})")
    again = json.loads(cfg_path.read_text(encoding="utf-8"))
    rep.check(again.get("game_dir") == cfg["game_dir"] and again.get("profile") == "owner-pick"
              and (data / "Downloads" / "e2e-mod-1.0.zip").read_bytes() == b"kept",
              "reinstall: the game folder, the pack and the downloads are all still there")
    rep.check(version_of(install, env) == expect, f"reinstall: leonida.exe --version {expect}")


def main() -> int:
    if sys.platform != "win32":
        sys.exit("Windows only.")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", type=Path)
    ap.add_argument("--new", type=Path)
    ap.add_argument("--smoke", type=Path, help="only install + uninstall the setup in this dist folder")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    rep = Report()
    tmp = Path(tempfile.mkdtemp(prefix="leonida-e2e-setup-"))
    env = base_env(tmp)
    install, data = tmp / "Programs" / "Leonida V", tmp / "Leonida V"
    try:
        dist = a.smoke or a.old
        exe = setup_exe(dist)
        old_v = exe.stem.removeprefix("Leonida-V-Setup-")
        if install_step(rep, exe, install, data, env, old_v):
            if not a.smoke:
                new_v = setup_exe(a.new).stem.removeprefix("Leonida-V-Setup-")
                check_update(rep, tmp, install, data, env, a.new, old_v, new_v)
            uninstall_step(rep, install, data, env)
            reinstall_step(rep, exe, install, data, env, old_v)
            uninstall_step(rep, install, data, env)
    except Exception as exc:  # noqa: BLE001 - report it with the rest
        rep.problems.append(f"{type(exc).__name__}: {exc}")
    finally:
        subprocess.run(["reg", "delete", f"HKCU\\{env['LEONIDA_REG_ROOT']}", "/f"], capture_output=True)
        if a.keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    for line in rep.ok:
        print("  ok    " + line)
    for line in rep.problems:
        print("  FAIL  " + line)
        if os.environ.get("GITHUB_ACTIONS"):  # an annotation: readable on the run page without opening the log
            print("::error title=Setup smoke test::" + line.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))
    print("PASSED" if rep.passed else "FAILED", f"({len(rep.ok)} ok, {len(rep.problems)} failed)")
    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
