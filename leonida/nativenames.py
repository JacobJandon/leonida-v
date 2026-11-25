"""Native names for crash reports: 0x55E86AF2712B36A1 -> "ACTIVATE_INTERIOR_ENTITY_SET".

    names = native_names(game_dir)     # {hash: name}, from Script Hook V .NET's own GTA.Native.Hash enum
    names.get(0x55E86AF2712B36A1)

The names come from the user's own ScriptHookVDotNet3.dll (else ScriptHookVDotNet2.dll) in the game folder: its
metadata holds the Hash enum as ulong constants. This reads only the file's .NET metadata tables (ECMA-335 II.22-24)
with struct: nothing is loaded or run, and Leonida ships no list of its own. Anything unexpected gives {}.
"""

from __future__ import annotations

import functools
import struct
from pathlib import Path

DLLS = ("ScriptHookVDotNet3.dll", "ScriptHookVDotNet2.dll")
_ELEMENT_U8 = 0x0B   # ulong constants: the Hash enum's values

# Metadata tables before Constant (0x0B), in order, with their column kinds:
#   2/4: fixed bytes; "s"/"g"/"b": #Strings/#GUID/#Blob index; ("t", n): index into table n;
#   ("c", tables): coded index over those tables.
_TYPE_DEF_OR_REF = (0x02, 0x01, 0x1B)
_RESOLUTION_SCOPE = (0x00, 0x1A, 0x23, 0x01)
_MEMBER_REF_PARENT = (0x02, 0x01, 0x1A, 0x06, 0x1B)
_HAS_CONSTANT = (0x04, 0x08, 0x17)
_SCHEMA = {
    0x00: (2, "s", "g", "g", "g"),                                   # Module
    0x01: (("c", _RESOLUTION_SCOPE), "s", "s"),                      # TypeRef
    0x02: (4, "s", "s", ("c", _TYPE_DEF_OR_REF), ("t", 0x04), ("t", 0x06)),  # TypeDef
    0x03: (("t", 0x04),),                                            # FieldPtr
    0x04: (2, "s", "b"),                                             # Field
    0x05: (("t", 0x06),),                                            # MethodPtr
    0x06: (4, 2, 2, "s", "b", ("t", 0x08)),                          # MethodDef
    0x07: (("t", 0x08),),                                            # ParamPtr
    0x08: (2, 2, "s"),                                               # Param
    0x09: (("t", 0x02), ("c", _TYPE_DEF_OR_REF)),                    # InterfaceImpl
    0x0A: (("c", _MEMBER_REF_PARENT), "s", "b"),                     # MemberRef
    0x0B: (1, 1, ("c", _HAS_CONSTANT), "b"),                         # Constant
}


def _rva_to_offset(pe: bytes, rva: int) -> int | None:
    lfanew = struct.unpack_from("<I", pe, 0x3C)[0]
    nsec = struct.unpack_from("<H", pe, lfanew + 6)[0]
    opt = struct.unpack_from("<H", pe, lfanew + 20)[0]
    sec = lfanew + 24 + opt
    for i in range(nsec):
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", pe, sec + 40 * i + 8)
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return rawptr + rva - vaddr
    return None


def read_hash_enum(path: Path) -> dict[int, str]:
    """{value: name} of every ulong constant field in a .NET assembly's metadata (the native Hash enum)."""
    pe = Path(path).read_bytes()
    if pe[:2] != b"MZ":
        return {}
    lfanew = struct.unpack_from("<I", pe, 0x3C)[0]
    magic = struct.unpack_from("<H", pe, lfanew + 24)[0]
    dirs = lfanew + 24 + (96 if magic == 0x10B else 112)
    cli_rva = struct.unpack_from("<I", pe, dirs + 14 * 8)[0]
    cli = _rva_to_offset(pe, cli_rva)
    if not cli_rva or cli is None:
        return {}
    md = _rva_to_offset(pe, struct.unpack_from("<I", pe, cli + 8)[0])
    if md is None or pe[md:md + 4] != b"BSJB":
        return {}
    vlen = struct.unpack_from("<I", pe, md + 12)[0]
    pos = md + 16 + vlen + 2
    nstreams = struct.unpack_from("<H", pe, pos)[0]
    pos += 2
    streams = {}
    for _ in range(nstreams):
        off, size = struct.unpack_from("<II", pe, pos)
        end = pe.index(b"\0", pos + 8)
        name = pe[pos + 8:end].decode("ascii")
        pos = (end + 4) & ~3
        streams[name] = (md + off, size)
    tables_off = streams.get("#~", streams.get("#-"))[0]
    strings_off = streams["#Strings"][0]
    blob_off = streams["#Blob"][0]
    heap = pe[tables_off + 6]
    valid = struct.unpack_from("<Q", pe, tables_off + 8)[0]
    rows: dict[int, int] = {}
    p = tables_off + 24
    for t in range(64):
        if valid >> t & 1:
            rows[t] = struct.unpack_from("<I", pe, p)[0]
            p += 4
    sizes = {"s": 4 if heap & 1 else 2, "g": 4 if heap & 2 else 2, "b": 4 if heap & 4 else 2}

    def col_size(c) -> int:
        if isinstance(c, int):
            return c
        if isinstance(c, str):
            return sizes[c]
        if c[0] == "t":
            return 4 if rows.get(c[1], 0) > 0xFFFF else 2
        bits = (len(c[1]) - 1).bit_length()
        return 4 if max(rows.get(t, 0) for t in c[1]) >= 1 << (16 - bits) else 2

    def read(off: int, size: int) -> int:
        return struct.unpack_from("<I" if size == 4 else "<H" if size == 2 else "<B", pe, off)[0]

    starts: dict[int, tuple[int, list[int]]] = {}
    for t in range(0x0C):
        if t not in rows:
            continue
        if t not in _SCHEMA:
            return {}
        cols = [col_size(c) for c in _SCHEMA[t]]
        starts[t] = (p, cols)
        p += sum(cols) * rows[t]
    if 0x0B not in starts or 0x04 not in starts:
        return {}

    def string(idx: int) -> str:
        end = pe.index(b"\0", strings_off + idx)
        return pe[strings_off + idx:end].decode("utf-8", "replace")

    field_off, field_cols = starts[0x04]
    const_off, const_cols = starts[0x0B]
    hc_bits = 2
    out: dict[int, str] = {}
    for i in range(rows[0x0B]):
        row = const_off + sum(const_cols) * i
        if pe[row] != _ELEMENT_U8:
            continue
        parent = read(row + 2, const_cols[2])
        if parent & ((1 << hc_bits) - 1) != 0:          # not a Field
            continue
        fidx = (parent >> hc_bits) - 1
        blob = read(row + 2 + const_cols[2], const_cols[3])
        b = blob_off + blob
        if pe[b] != 8:                                   # an 8-byte blob
            continue
        value = struct.unpack_from("<Q", pe, b + 1)[0]
        frow = field_off + sum(field_cols) * fidx
        out[value] = string(read(frow + field_cols[0], field_cols[1]))
    return out


@functools.lru_cache(maxsize=4)
def _cached(path: str, mtime: float) -> dict[int, str]:
    try:
        return read_hash_enum(Path(path))
    except (OSError, ValueError, struct.error, IndexError, KeyError, TypeError):
        return {}


def native_names(game_dir: Path | str | None) -> dict[int, str]:
    """{hash: name} from the game folder's Script Hook V .NET, or {} without it."""
    if not game_dir:
        return {}
    for name in DLLS:
        p = Path(game_dir) / name
        try:
            if p.is_file():
                names = _cached(str(p), p.stat().st_mtime)
                if names:
                    return names
        except OSError:
            continue
    return {}
