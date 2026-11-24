"""List and safely extract mod archives (.zip built in; .7z/.rar via 7-Zip if installed)."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ARCHIVE_EXTS = (".zip", ".7z", ".rar")


class ArchiveError(RuntimeError):
    pass


def is_archive(path: Path) -> bool:
    return Path(path).suffix.lower() in ARCHIVE_EXTS


def _norm(member: str) -> str:
    return str(PurePosixPath(member.replace("\\", "/"))).lstrip("/")


def _safe(member: str) -> bool:
    p = PurePosixPath(_norm(member))
    return not p.is_absolute() and ".." not in p.parts and not (p.parts and p.parts[0].endswith(":"))


def list_members(path: Path, seven_zip: Path | None = None) -> list[str]:
    """File members (POSIX-style relative paths). Directories are implied."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".zip":
        try:
            with zipfile.ZipFile(path) as zf:
                return [_norm(i.filename) for i in zf.infolist() if not i.is_dir()]
        except zipfile.BadZipFile as exc:
            raise ArchiveError(f"{path.name} is not a valid zip: {exc}") from None
    if ext in (".7z", ".rar"):
        if not seven_zip:
            raise ArchiveError(f"{path.name}: install 7-Zip (https://www.7-zip.org/) to open {ext} files")
        res = subprocess.run([str(seven_zip), "l", "-slt", "-ba", str(path)],
                             check=False, capture_output=True, text=True, errors="replace")
        if res.returncode != 0:
            raise ArchiveError(f"7-Zip could not list {path.name}: {res.stderr.strip()[:300]}")
        members, current, is_dir = [], None, False
        for line in res.stdout.splitlines() + [""]:
            if line.startswith("Path = "):
                current, is_dir = line[7:], False
            elif line.startswith("Folder = "):
                is_dir = line.endswith("+")
            elif line.startswith("Attributes = ") and "D" in line[13:].split(" ")[0]:
                is_dir = True
            elif not line.strip() and current is not None:
                if not is_dir:
                    members.append(_norm(current))
                current = None
        return members
    raise ArchiveError(f"{path.name} is not an archive")


def extract(path: Path, dest: Path, seven_zip: Path | None = None) -> Path:
    """Extract into ``dest``; refuses members that would escape it (zip-slip)."""
    path, dest = Path(path), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    ext = path.suffix.lower()
    if ext == ".zip":
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if not _safe(info.filename):
                    raise ArchiveError(f"{path.name}: unsafe path in archive: {info.filename!r}")
                target = (dest / _norm(info.filename)).resolve()
                if root not in target.parents and target != root:
                    raise ArchiveError(f"{path.name}: unsafe path in archive: {info.filename!r}")
            zf.extractall(dest)
        return dest
    if ext in (".7z", ".rar"):
        for m in list_members(path, seven_zip):
            if not _safe(m):
                raise ArchiveError(f"{path.name}: unsafe path in archive: {m!r}")
        res = subprocess.run([str(seven_zip), "x", "-y", f"-o{dest}", str(path)],
                             check=False, capture_output=True, text=True, errors="replace")
        if res.returncode != 0:
            raise ArchiveError(f"7-Zip could not extract {path.name}: {res.stderr.strip()[:300]}")
        return dest
    raise ArchiveError(f"{path.name} is not an archive")
