"""Build the Windows one-folder release of Leonida V with PyInstaller.

    pip install -e ".[gui,build]"
    python build/build_exe.py              # -> dist/LeonidaV/LeonidaV.exe (GUI) + leonida.exe (CLI)
    python build/build_exe.py --selftest   # also run the frozen GUI's browser self-check (temp state folder)
    python build/build_exe.py --release    # also write the release assets into dist/ (list in dist/release-assets.txt):
                                           #   LeonidaV-<ver>-win64.zip   the app folder + GUIDE.md, README.md, LICENSE
                                           #   leonida-v-<ver>.zip        source kit, git archive of HEAD
                                           #   Leonida-V-Setup-<ver>.exe  per-user installer (build/build_setup.py)
                                           #   modpack.json               release/modpack.json, checked (if it exists)
                                           #   SHA256SUMS.txt             a line per asset above
    python build/build_exe.py --no-build --selftest   # re-check an existing build

One folder, not one file: QtWebEngine is ~200 MB and a one-file exe would unpack it to %TEMP% on every start.
The spec is build/leonida.spec; PyInstaller's work files go to build/work/ (ignored by git).
Mod files are never release assets: modpack.json only lists names, sizes, hashes and the authors' URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APP_DIR = DIST / "LeonidaV"
WORK = ROOT / "build" / "work"
SPEC = ROOT / "build" / "leonida.spec"
MODPACK = ROOT / "release" / "modpack.json"
# Files shipped next to LeonidaV.exe (source -> name in the app folder)
APP_DOCS = {ROOT / "docs" / "GUIDE.md": "GUIDE.md", ROOT / "README.md": "README.md", ROOT / "LICENSE": "LICENSE"}
# The only names a release may carry. Mod archives are never among them.
ASSET_PATTERNS = (r"LeonidaV-[\w.+-]+-win64\.zip", r"leonida-v-[\w.+-]+\.zip", r"Leonida-V-Setup-[\w.+-]+\.exe",
                  r"modpack\.json", r"SHA256SUMS\.txt")
# Never in a release: CodeWalker's files (dexyfex hasn't given permission; leonida/cwtools.py fetches its source from
# his GitHub at first use and builds the helper on the user's PC), and our helper's build output.
FORBIDDEN = ("codewalker.core.dll", "codewalker.exe", "sharpdx.dll", "sharpdx.mathematics.dll", "leonidarpf.exe",
             "/.cw-src/", "/codewalker/bin/")


def check_no_codewalker(archive: Path) -> None:
    """Refuse the release when ``archive`` holds any CodeWalker file (or a built helper)."""
    with zipfile.ZipFile(archive) as z:
        bad = [n for n in z.namelist() if any(f in "/" + n.lower().replace("\\", "/") or
                                               n.lower().endswith(f) for f in FORBIDDEN)]
    if bad:
        sys.exit(f"Refusing to release {archive.name}: it contains CodeWalker / helper binaries: {bad[:5]}")


def notice(msg: str) -> None:
    print(f"::notice::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"NOTICE: {msg}")


def copy_docs() -> None:
    for src, name in APP_DOCS.items():
        if src.is_file():
            shutil.copy2(src, APP_DIR / name)
        else:
            notice(f"{src.relative_to(ROOT)} is missing, so it is not shipped next to the exe.")


def version() -> str:
    text = (ROOT / "leonida" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def build() -> None:
    if sys.platform != "win32":
        sys.exit("The exe build runs on Windows only.")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(WORK), str(SPEC)], check=True, cwd=ROOT)
    for exe in ("LeonidaV.exe", "leonida.exe"):
        if not (APP_DIR / exe).is_file():
            sys.exit(f"Build finished but {APP_DIR / exe} is missing.")
    copy_docs()
    print(f"Built {APP_DIR} ({folder_size(APP_DIR) / 2**20:.0f} MB)")


def selftest(url: str = "", timeout: int = 180) -> bool:
    """Start the frozen LeonidaV.exe with LEONIDA_SELFTEST and empty temp state/download folders; True if it passed."""
    exe = APP_DIR / "LeonidaV.exe"
    with tempfile.TemporaryDirectory(prefix="leonida-selftest-") as tmp:
        out = Path(tmp) / "selftest.json"
        env = dict(os.environ, LEONIDA_SELFTEST="1", LEONIDA_SELFTEST_OUT=str(out),
                   LEONIDA_STATE_DIR=str(Path(tmp) / "State"), LEONIDA_DOWNLOAD_DIR=str(Path(tmp) / "Downloads"),
                   LEONIDA_NO_OPEN="1")
        env.pop("LEONIDA_SELFTEST_URL", None)
        if url:
            env["LEONIDA_SELFTEST_URL"] = url
        else:
            env["LEONIDA_NO_NET"] = "1"  # no update check / image fetches; the inline test page needs no network
        proc = subprocess.Popen([str(exe)], env=env, cwd=tmp)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            print(f"Self-test: LeonidaV.exe did not exit within {timeout} s (killed).")
            return False
        report = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
        print(json.dumps(report, indent=2) if report else "Self-test wrote no report.")
        print(f"Self-test exit code: {code}")
        return code == 0 and bool(report.get("ok"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_folder(src: Path, dest: Path, arc_root: str) -> None:
    dest.unlink(missing_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, f"{arc_root}/{f.relative_to(src).as_posix()}")


def check_modpack(path: Path = MODPACK) -> Path | None:
    """Validate release/modpack.json for this release; None (with a notice) when there is none.

    It must load (leonida.modpack.load_file), be built from this mods.json version, and every entry must pass the same
    rule clients apply (author's source only; re-hosting only with mods.json's redistribution permission)."""
    if not path.is_file():
        notice(f"{path.relative_to(ROOT).as_posix()} not found: releasing without modpack.json. Make it on a tested PC "
               "with `leonida modpack build --out release/modpack.json` and commit it.")
        return None
    sys.path.insert(0, str(ROOT))
    from leonida.manifest import load_manifest
    from leonida.modpack import ModpackError, entry_problem, load_file

    try:
        pack = load_file(path)
    except ModpackError as exc:
        sys.exit(f"release/modpack.json is invalid: {exc}")
    manifest = load_manifest()
    if pack.get("version") != manifest.version:
        sys.exit(f"release/modpack.json was built with mods.json version {pack.get('version')!r}, but this release "
                 f"ships {manifest.version!r}. Rebuild it: leonida modpack build --out release/modpack.json")
    problems = [p for build, section in pack["builds"].items() for mod_id, entry in section["mods"].items()
                if (p := entry_problem(mod_id, entry, manifest, build))]
    if problems:
        sys.exit("release/modpack.json can't be published:\n  " + "\n  ".join(problems))
    builds = ", ".join(f"{b} ({len(s['mods'])} mods)" for b, s in pack["builds"].items())
    print(f"modpack.json ok: mods.json {manifest.version}, builds {builds}")
    return path


def release(setup: bool = True) -> list[Path]:
    ver = version()
    copy_docs()  # also for --no-build, so the zip always has them
    win_zip = DIST / f"LeonidaV-{ver}-win64.zip"
    zip_folder(APP_DIR, win_zip, "LeonidaV")
    src_zip = DIST / f"leonida-v-{ver}.zip"
    src_zip.unlink(missing_ok=True)
    # Tracked files at HEAD only (no venv, State, Downloads or local edits), under a leonida-v/ folder like the kit zip.
    subprocess.run(["git", "archive", "--format=zip", "--prefix=leonida-v/", "-o", str(src_zip), "HEAD"],
                   check=True, cwd=ROOT)
    assets = [win_zip, src_zip]
    for archive in assets:
        check_no_codewalker(archive)
    for old in DIST.glob("Leonida-V-Setup-*.exe"):
        old.unlink()
    if setup:  # the per-user installer around the win64 zip (build/build_setup.py)
        sys.path.insert(0, str(ROOT / "build"))
        from build_setup import build as build_setup

        assets.append(build_setup(win_zip, DIST, ver))
    (DIST / "modpack.json").unlink(missing_ok=True)
    pack = check_modpack()
    if pack:
        assets.append(Path(shutil.copy2(pack, DIST / "modpack.json")))
    sums_path = DIST / "SHA256SUMS.txt"
    sums = "".join(f"{sha256(a)}  {a.name}\n" for a in assets)
    sums_path.write_text(sums, encoding="utf-8", newline="\n")
    assets.append(sums_path)
    for a in assets:
        if not any(re.fullmatch(p, a.name) for p in ASSET_PATTERNS):
            sys.exit(f"Refusing to release {a.name}: not a Leonida V release asset.")
    # The CI job uploads exactly what this file lists.
    (DIST / "release-assets.txt").write_text("".join(f"dist/{a.name}\n" for a in assets), encoding="utf-8", newline="\n")
    print(sums, end="")
    return assets


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-build", action="store_true", help="skip PyInstaller, use the existing dist/LeonidaV")
    ap.add_argument("--selftest", action="store_true", help="run the frozen GUI + built-in browser self-check")
    ap.add_argument("--selftest-url", default="", help="also load this https page in the self-check (needs network)")
    ap.add_argument("--release", action="store_true", help="write the release zips and SHA256SUMS.txt into dist/")
    ap.add_argument("--no-setup", action="store_true", help="with --release: skip Leonida-V-Setup-<ver>.exe")
    args = ap.parse_args()

    if not args.no_build:
        if APP_DIR.exists():
            shutil.rmtree(APP_DIR)
        build()
    if args.selftest or args.selftest_url:
        if not selftest(args.selftest_url):
            sys.exit("Self-test FAILED.")
        print("Self-test passed.")
    if args.release:
        release(setup=not args.no_setup)


if __name__ == "__main__":
    main()
