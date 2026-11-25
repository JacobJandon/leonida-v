"""Check the release assets before they are published (the release job runs this; it fails on any problem).

    python build/check_release.py [DIST]        # default: dist/ (reads dist/release-assets.txt)

Checks:
  - the asset list is exactly: Leonida-V-Setup-<v>.exe, LeonidaV-<v>-win64.zip, leonida-v-<v>.zip, SHA256SUMS.txt
    (and modpack.json when there is one), all for leonida.__version__;
  - SHA256SUMS.txt has a line for every other asset and each matches;
  - **no CodeWalker file anywhere**: not in the zips, not in the setup exe's own archive, not in the win64 zip the
    setup carries (CodeWalker.Core.dll, CodeWalker*.exe, SharpDX*.dll, a built LeonidaRpf.exe, CodeWalker's source);
  - the setup carries exactly the released win64 zip (same SHA-256), so installing and updating give the same app;
  - the win64 zip has LeonidaV.exe + leonida.exe; the source zip has pyproject.toml and the leonida package;
  - modpack.json loads, and its mods.json version matches.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = re.compile(r"(^|/)(codewalker[^/]*\.(dll|exe)|sharpdx[^/]*\.dll|leonidarpf\.exe)$|(^|/)\.cw-src/|"
                       r"(^|/)codewalker\.core/|(^|/)codewalker/bin/", re.IGNORECASE)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def forbidden(names: list[str]) -> list[str]:
    return [n for n in names if FORBIDDEN.search(n.replace("\\", "/"))]


def check(dist: Path, version: str) -> list[str]:
    problems: list[str] = []
    listing = dist / "release-assets.txt"
    if listing.is_file():
        names = [Path(line.strip()).name for line in listing.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif (dist / "SHA256SUMS.txt").is_file():  # assets downloaded from the published release: the sums list them
        names = [line.split()[-1].lstrip("*") for line in
                 (dist / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
        names.append("SHA256SUMS.txt")
    else:
        return [f"{listing} is missing: run build/build_exe.py --release (or download the release's assets)"]
    assets = {name: dist / name for name in names}
    want = {f"Leonida-V-Setup-{version}.exe", f"LeonidaV-{version}-win64.zip", f"leonida-v-{version}.zip",
            "SHA256SUMS.txt"}
    extra = set(assets) - want - {"modpack.json"}
    if want - set(assets) or extra:
        problems.append(f"asset list: missing {sorted(want - set(assets))}, unexpected {sorted(extra)}")
    for name, path in assets.items():
        if not path.is_file():
            problems.append(f"{name} is listed but missing")
    if problems:
        return problems

    # SHA256SUMS
    sums = {}
    for line in assets["SHA256SUMS.txt"].read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([0-9a-f]{64})\s+\*?(.+)$", line.strip())
        if m:
            sums[m.group(2)] = m.group(1)
    data = {name: path.read_bytes() for name, path in assets.items() if name != "SHA256SUMS.txt"}
    for name, blob in data.items():
        if sums.get(name) != sha256(blob):
            problems.append(f"SHA256SUMS.txt: {name} {'is missing' if name not in sums else 'does not match'}")

    # the zips
    win_name, src_name = f"LeonidaV-{version}-win64.zip", f"leonida-v-{version}.zip"
    win_names = zipfile.ZipFile(io.BytesIO(data[win_name])).namelist()
    src_names = zipfile.ZipFile(io.BytesIO(data[src_name])).namelist()
    for name, names in ((win_name, win_names), (src_name, src_names)):
        bad = forbidden(names)
        if bad:
            problems.append(f"CodeWalker / helper files in {name}: {bad[:5]}")
    if not {"LeonidaV/LeonidaV.exe", "LeonidaV/leonida.exe"} <= set(win_names):
        problems.append(f"{win_name} has no LeonidaV/LeonidaV.exe + leonida.exe")
    if "leonida-v/pyproject.toml" not in src_names or "leonida-v/leonida/__init__.py" not in src_names:
        problems.append(f"{src_name} is not the source kit (no pyproject.toml / leonida package)")

    # the setup: its own archive, and the win64 zip it carries
    setup = f"Leonida-V-Setup-{version}.exe"
    try:
        from PyInstaller.archive.readers import CArchiveReader

        reader = CArchiveReader(str(assets[setup]))
        toc = list(reader.toc)
        bad = forbidden(toc)
        if bad:
            problems.append(f"CodeWalker / helper files in {setup}: {bad[:5]}")
        meta_key = next((n for n in toc if n.replace("\\", "/") == "payload/payload.json"), None)
        if meta_key is None:
            problems.append(f"{setup} has no payload/payload.json")
        else:
            meta = json.loads(reader.extract(meta_key))
            zip_key = next((n for n in toc if n.replace("\\", "/") == f"payload/{meta.get('file')}"), None)
            inner = reader.extract(zip_key) if zip_key else b""
            if meta.get("version") != version or meta.get("file") != win_name:
                problems.append(f"{setup} carries {meta.get('file')} ({meta.get('version')}), not {win_name}")
            elif sha256(inner) != sums.get(win_name) or meta.get("sha256") != sums.get(win_name):
                problems.append(f"{setup}'s payload is not the released {win_name} (SHA-256 differs)")
            else:
                bad = forbidden(zipfile.ZipFile(io.BytesIO(inner)).namelist())
                if bad:
                    problems.append(f"CodeWalker / helper files in {setup}'s payload: {bad[:5]}")
    except ImportError:
        problems.append("PyInstaller is needed to look inside the setup exe (pip install -e .[build])")

    # modpack.json
    if "modpack.json" in data:
        try:
            pack = json.loads(data["modpack.json"])
            mods = json.loads((ROOT / "leonida" / "manifest" / "mods.json").read_text(encoding="utf-8"))
            if pack.get("version") != mods.get("version"):
                problems.append(f"modpack.json is for mods.json {pack.get('version')}, not {mods.get('version')}")
            if re.search(r"codewalker\.core\.dll|sharpdx", data["modpack.json"].decode("utf-8"), re.IGNORECASE):
                problems.append("modpack.json lists a CodeWalker file")
        except ValueError as exc:
            problems.append(f"modpack.json doesn't load: {exc}")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    dist = Path(args[0]) if args else ROOT / "dist"
    sys.path.insert(0, str(ROOT))
    from leonida import __version__

    problems = check(dist, __version__)
    for name in (dist / "release-assets.txt").read_text(encoding="utf-8").splitlines() if \
            (dist / "release-assets.txt").is_file() else []:
        p = dist / Path(name.strip()).name
        if name.strip() and p.is_file():
            print(f"  {p.name:<36} {p.stat().st_size:>12,} B")
    if problems:
        for p in problems:
            print(f"::error::{p}" if "GITHUB_ACTIONS" in __import__("os").environ else f"FAIL  {p}")
        return 1
    print(f"Release assets for {__version__}: OK (checksums match, the setup carries the released zip, "
          "no CodeWalker file anywhere)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
