"""Edit GTA V Enhanced .rpf archives for mods: copies in the game's mods\\ folder, through the LeonidaRpf helper.

Install method ``rpf`` in mods.json (see the manifest docstring)::

    "install": {"method": "rpf",
                "files": [{"match": "spMapFixes_Gen9", "type": "dir", "to": "mods/update/x64/dlcpacks"}],
                "rpf": [
                  {"archive": "update\\\\update.rpf", "dlclist": "dlcpacks:/spMapFixes_Gen9/"},
                  {"archive": "update\\\\update.rpf", "put": "physicstasks.ymt", "to": "x64\\\\data\\\\tune\\\\physicstasks.ymt"},
                  {"archive": "update\\\\update.rpf", "xml": "common\\\\data\\\\x.xml", "edits": [{"type": "add", ...}]},
                  {"archive": "update\\\\update.rpf", "delete": "x64\\\\data\\\\old.meta"},
                  {"oiv": "MP Map Fixes.oiv"}]}

Every archive path is relative to the game folder ("update\\\\update.rpf") and is always applied to the copy in
``<game>\\mods\\`` (OpenRPF loads those first). The original game archives are never written:

* no mods\\ copy yet: the step logs ADD and then copies the game's archive there (or creates an empty one when an
  .oiv says ``createIfNotExist``), so rollback deletes it;
* a mods\\ copy exists (an earlier step made it): it is backed up whole first and logged as REPLACE, so rollback
  restores it byte for byte.

The helper (``LeonidaRpf.exe``, built by build/build_rpf_helper.py on CodeWalker.Core by dexyfex) does the archive
work in one batch: CodeWalker reads the keys from GTA5_Enhanced.exe itself and switches each edited archive to OPEN
encryption, exactly as CodeWalker RPF Explorer does ("converting for OpenRPF").

.oiv packages (OpenIV): ``assembly.xml`` ``<content>`` is applied the way OpenIV's "mods folder" install does:
``<archive path createIfNotExist>`` (nested archives too) with ``<add source>``, ``<delete>`` and ``<xml path>``
(``add``/``replace``/``remove`` by XPath 1.0, evaluated by .NET in the helper); loose ``<add>``/``<delete>`` outside
archives go to the game folder, or to mods\\ when they are game data (under update\\ or x64\\, or an .rpf).
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

HELPER_NAME = "LeonidaRpf.exe"
HELPER_ENV = "LEONIDA_RPF_HELPER"
MODS = "mods"
DLCLIST = "common\\data\\dlclist.xml"
MODS_REDIRECT_TOP = ("update", "x64")   # loose .oiv files under these are game data: they go into mods\
TIMEOUT = 6 * 3600                       # big packages on update.rpf (3 GB) can take a while
OP_KEYS = {"archive", "put", "to", "dlclist", "xml", "edits", "delete", "oiv"}
XML_EDIT_TYPES = ("add", "replace", "remove")


class RpfError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------- the helper
def find_helper(state_dir: Path | None = None) -> list[str] | None:
    """Command for the helper: $LEONIDA_RPF_HELPER (an .exe, or a .py run with this Python: tests), then
    <state>/tools/LeonidaRpf/LeonidaRpf.exe, then build/codewalker/bin/ in a source checkout. None = not built."""
    cands: list[Path] = []
    env = os.environ.get(HELPER_ENV)
    if env:
        cands.append(Path(env))
    if state_dir:
        cands.append(Path(state_dir) / "tools" / "LeonidaRpf" / HELPER_NAME)
    cands.append(Path(__file__).resolve().parent.parent / "build" / "codewalker" / "bin" / HELPER_NAME)
    for c in cands:
        if c.is_file():
            return [sys.executable, str(c)] if c.suffix.lower() == ".py" else [str(c)]
    return None


def run_helper(cmd: list[str], game_dir: Path, ops: list[dict], timeout: float = TIMEOUT) -> list[dict]:
    """Run one batch; returns the per-op results or raises RpfError with the helper's message."""
    with tempfile.TemporaryDirectory(prefix="leonida-rpf-") as tmp:
        ops_file = Path(tmp) / "ops.json"
        ops_file.write_text(json.dumps(ops), encoding="utf-8")
        try:
            p = subprocess.run([*cmd, str(game_dir), str(ops_file)], capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RpfError(f"The RPF helper could not run: {exc}") from None
    try:
        out = json.loads(p.stdout.decode("utf-8", errors="replace") or "{}")
    except ValueError:
        out = {}
    if not out.get("ok"):
        err = out.get("error") or p.stderr.decode("utf-8", errors="replace").strip()[-500:] or f"exit code {p.returncode}"
        where = f" (operation {out['op'] + 1} of {len(ops)}: {ops[out['op']].get('op')} {ops[out['op']].get('entry', '')})" \
            if isinstance(out.get("op"), int) and 0 <= out["op"] < len(ops) else ""
        raise RpfError(f"RPF edit failed{where}: {err}")
    return out.get("results", [])


# ------------------------------------------------------------------------------------------- the work
def win(path: str) -> str:
    """'\\x64/data\\\\f.ymt ' -> 'x64\\data\\f.ymt' (archive-internal and game-relative paths use backslashes)."""
    parts = [p for p in str(path).strip().replace("/", "\\").split("\\") if p and p != "."]
    if any(p == ".." for p in parts):
        raise RpfError(f"Path {path!r} leaves the game folder")
    return "\\".join(parts)


def mods_rel(archive: str) -> str:
    """'update\\update.rpf' -> 'mods/update/update.rpf' (POSIX, relative to the game folder, as the install log uses)."""
    return PurePosixPath(MODS, *PureWindowsPath(win(archive)).parts).as_posix()


@dataclass
class ArchiveWork:
    path: str                 # relative to the game folder, backslashes ("update\\update.rpf")
    create: bool = False      # may be created empty when the game has no such archive (.oiv createIfNotExist)
    ops: list[dict] = field(default_factory=list)   # helper ops without "rpf"


@dataclass
class Work:
    archives: dict[str, ArchiveWork] = field(default_factory=dict)   # key: path lower-cased
    loose_adds: list[tuple[Path, str]] = field(default_factory=list)  # (source file, dest POSIX relative to game)
    loose_deletes: list[str] = field(default_factory=list)           # POSIX relative to game
    notes: list[str] = field(default_factory=list)

    def archive(self, path: str, create: bool = False) -> ArchiveWork:
        p = win(path)
        aw = self.archives.setdefault(p.lower(), ArchiveWork(p, create))
        aw.create = aw.create or create
        return aw

    def merge(self, other: Work) -> None:
        for aw in other.archives.values():
            self.archive(aw.path, aw.create).ops += aw.ops
        self.loose_adds += other.loose_adds
        self.loose_deletes += other.loose_deletes
        self.notes += other.notes

    def describe(self) -> list[str]:
        lines = []
        for aw in self.archives.values():
            kinds: dict[str, int] = {}
            for op in aw.ops:
                kinds[op["op"]] = kinds.get(op["op"], 0) + 1
            what = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
            lines.append(f"  rpf {mods_rel(aw.path)}: {what or 'copy only'}")
        if self.loose_adds:
            lines.append(f"  copy {len(self.loose_adds)} loose file(s) from the .oiv")
        if self.loose_deletes:
            lines.append(f"  delete {len(self.loose_deletes)} old file(s) if present: {', '.join(self.loose_deletes[:4])}")
        return lines + [f"  note: {n}" for n in self.notes]


def dlclist_edit(item: str) -> dict:
    """XML edit that adds <Item>item</Item> to dlclist.xml's Paths unless it is already there."""
    if "'" in item:
        raise RpfError(f"dlclist item {item!r} may not contain a quote")
    return {"type": "add", "append": "Last", "xpath": f"/SMandatoryPacksData/Paths[not(Item[.='{item}'])]",
            "xml": f"<Item>{_esc(item)}</Item>"}


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def check_ops(ops: list, where: str) -> None:
    """Validate mods.json ``install.rpf`` (raises ValueError with a readable message)."""
    if not isinstance(ops, list) or not ops:
        raise ValueError(f"{where}: 'rpf' must be a non-empty list")
    for i, op in enumerate(ops):
        w = f"{where}: rpf[{i}]"
        if not isinstance(op, dict) or set(op) - OP_KEYS:
            raise ValueError(f"{w}: unknown keys {sorted(set(op) - OP_KEYS) if isinstance(op, dict) else op!r}")
        actions = [k for k in ("put", "dlclist", "xml", "delete", "oiv") if k in op]
        if len(actions) != 1:
            raise ValueError(f"{w}: give exactly one of put, dlclist, xml, delete, oiv")
        if "oiv" in op:
            if set(op) != {"oiv"}:
                raise ValueError(f"{w}: 'oiv' takes no other keys")
            continue
        if not isinstance(op.get("archive"), str) or not op["archive"].lower().endswith(".rpf"):
            raise ValueError(f"{w}: 'archive' must be a game-relative .rpf path, e.g. update\\update.rpf")
        if "put" in op and not isinstance(op.get("to"), str):
            raise ValueError(f"{w}: 'put' needs 'to' (the path inside the archive)")
        if "xml" in op:
            edits = op.get("edits")
            if not isinstance(edits, list) or not edits or any(
                    not isinstance(e, dict) or e.get("type") not in XML_EDIT_TYPES or not e.get("xpath") for e in edits):
                raise ValueError(f"{w}: 'edits' must be a list of {{type: add|replace|remove, xpath, xml}}")
        for key in ("archive", "to", "xml", "delete"):
            if key in op:
                try:
                    win(op[key])
                except RpfError as exc:
                    raise ValueError(f"{w}: {exc}") from None


def manifest_work(ops: list[dict], root: Path, members: list[str]) -> Work:
    """Turn mods.json ``install.rpf`` ops into archive work; ``root`` is the extracted download."""
    work = Work()
    for op in ops:
        if "oiv" in op:
            for pkg in find_oivs(root, op["oiv"]):
                work.merge(parse_oiv_file(pkg))
            continue
        aw = work.archive(op["archive"])
        if "put" in op:
            src = find_member(root, members, op["put"])
            to = win(op["to"])
            if op["to"].replace("/", "\\").endswith("\\"):
                to = f"{to}\\{src.name}" if to else src.name
            aw.ops.append({"op": "put", "entry": to, "src": str(src)})
        elif "dlclist" in op:
            aw.ops.append({"op": "xml", "entry": DLCLIST, "edits": [dlclist_edit(op["dlclist"])]})
        elif "xml" in op:
            aw.ops.append({"op": "xml", "entry": win(op["xml"]), "edits": op["edits"]})
        elif "delete" in op:
            aw.ops.append({"op": "delete", "entry": win(op["delete"])})
    return work


def find_member(root: Path, members: list[str], name: str) -> Path:
    hits = sorted((m for m in members if PurePosixPath(m.replace("\\", "/")).name.lower() == name.lower()),
                  key=lambda m: ("legacy" in m.lower(), len(m)))
    if not hits:
        raise RpfError(f"{name} is not in the download")
    return root / hits[0]


def find_oivs(root: Path, pattern: str) -> list[Path]:
    hits = sorted(p for p in root.rglob("*") if p.is_file() and fnmatch.fnmatch(p.name.lower(), pattern.lower()))
    if not hits:
        raise RpfError(f"No .oiv package matching {pattern!r} in the download")
    return hits


# ------------------------------------------------------------------------------------------- .oiv
def parse_oiv_file(path: Path, into: Path | None = None) -> Work:
    """Unpack an .oiv (a zip) next to it (or into ``into``) and read its assembly.xml."""
    dest = into or path.with_name(path.name + ".unpacked")
    if not (dest / "assembly.xml").is_file():
        try:
            with zipfile.ZipFile(path) as z:
                for m in z.infolist():
                    target = (dest / m.filename.replace("\\", "/")).resolve()
                    if not str(target).startswith(str(dest.resolve())):
                        raise RpfError(f"{path.name}: unsafe path {m.filename!r} in the package")
                    if m.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(m) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
        except zipfile.BadZipFile:
            raise RpfError(f"{path.name} is not a valid .oiv package") from None
    return parse_oiv(dest)


def parse_oiv(root: Path) -> Work:
    """assembly.xml in ``root`` (an unpacked .oiv) -> the work, mods-folder style (see the module docstring)."""
    asm = root / "assembly.xml"
    if not asm.is_file():
        raise RpfError(f"No assembly.xml in {root.name}")
    try:
        pkg = ET.parse(asm).getroot()
    except ET.ParseError as exc:
        raise RpfError(f"assembly.xml can't be read: {exc}") from None
    content = pkg.find("content")
    if content is None:
        raise RpfError("assembly.xml has no <content>")
    work = Work()
    name = (pkg.findtext("metadata/name") or root.name).strip()

    def source(rel: str | None) -> Path:
        src = root / "content" / PurePosixPath(*PureWindowsPath(win(rel or "")).parts)
        if not src.is_file():
            raise RpfError(f"{name}: content file {rel!r} is missing from the package")
        return src

    def archive_ops(el: ET.Element, aw: ArchiveWork, prefix: str) -> None:
        for c in el:
            if c.tag == "add":
                aw.ops.append({"op": "put", "entry": prefix + win(c.text or ""), "src": str(source(c.get("source")))})
            elif c.tag == "delete":
                aw.ops.append({"op": "delete", "entry": prefix + win(c.text or "")})
            elif c.tag == "archive":
                archive_ops(c, aw, prefix + win(c.get("path", "")) + "\\")
            elif c.tag == "xml":
                aw.ops.append({"op": "xml", "entry": prefix + win(c.get("path", "")), "edits": xml_edits(c, name)})
            elif c.tag in ("text", "defragmentation"):
                raise RpfError(f"{name}: <{c.tag}> in assembly.xml is not supported yet")

    for c in content:
        if c.tag == "archive":
            if (c.get("type") or "RPF7").upper() != "RPF7":
                raise RpfError(f"{name}: archive type {c.get('type')} is not supported")
            aw = work.archive(c.get("path", ""), (c.get("createIfNotExist") or "").lower() == "true")
            archive_ops(c, aw, "")
        elif c.tag == "add":
            work.loose_adds.append((source(c.get("source")), loose_dest(c.text or "")))
        elif c.tag == "delete":
            work.loose_deletes.append(loose_dest(c.text or ""))
        elif c.tag == "xml":
            raise RpfError(f"{name}: <xml> outside an <archive> (a loose file) is not supported yet")
    return work


def xml_edits(el: ET.Element, name: str) -> list[dict]:
    edits = []
    for op in el:
        if op.tag not in XML_EDIT_TYPES or not op.get("xpath"):
            raise RpfError(f"{name}: unsupported xml edit <{op.tag}>")
        inner = "".join(_inner(ch) for ch in op)
        edits.append({"type": op.tag, "xpath": op.get("xpath"), "append": op.get("append", "Last"),
                      "xml": inner or (op.text or "").strip()})
    return edits


def _inner(el: ET.Element) -> str:
    tail, el.tail = el.tail, None
    try:
        return ET.tostring(el, encoding="unicode")
    finally:
        el.tail = tail


def loose_dest(path: str) -> str:
    """Where a loose .oiv file goes: game data (update\\..., x64\\..., *.rpf) into mods\\, the rest into the game folder."""
    parts = PureWindowsPath(win(path)).parts
    if not parts:
        raise RpfError("empty file path in assembly.xml")
    if parts[0].lower() in MODS_REDIRECT_TOP or parts[-1].lower().endswith(".rpf"):
        parts = (MODS, *parts)
    return PurePosixPath(*parts).as_posix()


def space_needed(game: Path, work: Work) -> int:
    """Bytes the step writes for archive copies / backups (the bulk of it: update.rpf is ~3 GB)."""
    total = 0
    for aw in work.archives.values():
        mods = game / mods_rel(aw.path)
        orig = game / PurePosixPath(*PureWindowsPath(aw.path).parts)
        src = mods if mods.is_file() else orig
        if src.is_file():
            total += src.stat().st_size
    return total
