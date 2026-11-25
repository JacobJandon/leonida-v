"""Dry run of the GitHub release job (.github/workflows/ci.yml, windows-build), locally. Never publishes.

    python build/release_dryrun.py                  # from HEAD (a clean temporary clone)
    python build/release_dryrun.py --working-tree   # from the files as they are now (tracked + new, not ignored)
    python build/release_dryrun.py --keep DIR       # keep the build folder there

Runs the job's own steps in a separate folder (so the checkout's dist/ and build/work are untouched):
  1. the tag check: leonida.__version__ must match the tag the release would get (v<version>);
  2. release/modpack.json against mods.json;
  3. `python build/build_exe.py --selftest --release` (the app, its self-check, the zips, the setup, SHA256SUMS);
  4. `python build/e2e_setup.py --smoke dist` (the setup installs and uninstalls silently);
  5. `python build/check_release.py dist` (checksums, the setup's payload, no CodeWalker file in any asset);
then lists the artifacts the job would upload (dist/release-assets.txt) with their sizes. The "Publish GitHub
release" step is NOT run: no tag, no upload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def snapshot(dest: Path, working_tree: bool) -> Path:
    if not working_tree:
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(dest)], check=True)
        return dest
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True,
                           check=True).stdout.decode("utf-8").split("\0")
    for rel in filter(None, files):
        src = ROOT / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    # git archive (the source zip) needs a repository: one commit of exactly these files
    git = ["git", "-c", "user.name=dry-run", "-c", "user.email=dry-run@localhost"]
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "release dry run (working tree)"], cwd=dest, check=True)
    return dest


def step(title: str, cmd: list[str], cwd: Path, env: dict) -> None:
    print(f"\n== {title}\n   $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--working-tree", action="store_true")
    ap.add_argument("--keep", type=Path)
    ap.add_argument("--no-selftest", action="store_true", help="skip the frozen GUI self-check (faster)")
    a = ap.parse_args()
    work = a.keep or Path(tempfile.mkdtemp(prefix="leonida-release-dryrun-"))
    if work.exists() and any(work.iterdir()):
        sys.exit(f"{work} is not empty")
    work.mkdir(parents=True, exist_ok=True)
    src = snapshot(work / "leonida-v", a.working_tree)
    env = dict(os.environ, PYTHONPATH=str(src), LEONIDA_NO_OPEN="1", QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu")
    py = sys.executable
    ver = subprocess.run([py, "-c", "import leonida; print(leonida.__version__)"], cwd=src, env=env,
                         capture_output=True, text=True, check=True).stdout.strip()
    print(f"== Version: {ver} (the tag would be v{ver})")
    modpack = src / "release" / "modpack.json"
    if modpack.is_file():
        step("Check release/modpack.json", [py, "-c", (
            "from leonida.modpack import load_file; import json,sys; d=load_file('release/modpack.json'); "
            "m=json.load(open('leonida/manifest/mods.json',encoding='utf-8')); "
            "sys.exit(0 if d['version']==m['version'] else 'modpack.json was built with another mods.json version')")],
            src, env)
    build = [py, "build/build_exe.py", "--release"] + ([] if a.no_selftest else ["--selftest"])
    step("Build, self-check and zip", build, src, env)
    step("Setup smoke test", [py, "build/e2e_setup.py", "--smoke", "dist"], src, env)
    step("Check release assets (checksums, setup payload, no CodeWalker files)",
         [py, "build/check_release.py", "dist"], src, env)
    print("\n== Artifacts the job would upload (dist/release-assets.txt); the publish step is skipped")
    total = 0
    for line in (src / "dist" / "release-assets.txt").read_text(encoding="utf-8").splitlines():
        p = src / line.strip()
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        total += p.stat().st_size
        print(f"   {p.name:<36} {p.stat().st_size:>12,} B  {h[:16]}...")
    print(f"   {'total':<36} {total:>12,} B")
    print(json.dumps({"dist": str(src / "dist")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
