"""Read the crash reason out of a Windows minidump (.dmp): exception code, faulting address and the module it's in.

    info = read_minidump(path)   # MinidumpInfo | None
    info.describe()              # "EXCEPTION_ACCESS_VIOLATION (0xC0000005) in GTA5_Enhanced.exe+0x1A2B3C"

The crashing thread's stack is summed up too (``stack``): the return addresses on it that land in a module (a scan
of the stack from the crash's RSP, no symbols, so a heuristic), the native's hash when Script Hook V called one
(the qword after ScriptHookV.dll's return address), snake_case strings left on the stack (entity-set or model
names a script passed), and the thread's name.

Stdlib only (struct), read-only, and never the whole file: only the header, the stream directory, the exception
stream and its CPU context, the module list, the thread list and names, and the crashing thread's stack. Anything
unreadable gives None or a partial answer, never an exception.
Format: https://learn.microsoft.com/windows/win32/api/minidumpapiset/ (MINIDUMP_HEADER, MINIDUMP_DIRECTORY,
MINIDUMP_EXCEPTION_STREAM, MINIDUMP_MODULE_LIST).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

THREAD_LIST_STREAM, MODULE_LIST_STREAM, EXCEPTION_STREAM, THREAD_NAMES_STREAM = 3, 4, 6, 24
_RSP, _CONTEXT_MIN = 0x98, 0x100     # x64 CONTEXT: Rsp at 0x98 (Rip at 0xF8)
_STACK_SCAN = 0x4000                 # bytes of stack from RSP scanned for return addresses
_STRING_SCAN = 0x10000               # bytes read from RSP
_STACK_BYTES = 0x40000               # most of a stack read for strings
_MAX_STACK = 16
SYSTEM_MODULES = ("ntdll.dll", "kernel32.dll", "kernelbase.dll", "ucrtbase.dll", "msvcp140.dll",
                  "vcruntime140.dll", "vcruntime140_1.dll", "combase.dll", "user32.dll", "win32u.dll")
_MODULE_SIZE = 108          # sizeof(MINIDUMP_MODULE)
_MAX_MODULES = 4096
_MAX_NAME = 1024            # bytes of a module name (UTF-16)

CODES = {
    0xC0000005: "EXCEPTION_ACCESS_VIOLATION",
    0xC0000017: "STATUS_NO_MEMORY",
    0xC000001D: "EXCEPTION_ILLEGAL_INSTRUCTION",
    0xC0000025: "EXCEPTION_NONCONTINUABLE_EXCEPTION",
    0xC000008C: "EXCEPTION_ARRAY_BOUNDS_EXCEEDED",
    0xC0000094: "EXCEPTION_INT_DIVIDE_BY_ZERO",
    0xC00000FD: "EXCEPTION_STACK_OVERFLOW",
    0xC0000374: "STATUS_HEAP_CORRUPTION",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN",
    0xC0000420: "STATUS_ASSERTION_FAILURE",
    0x80000003: "EXCEPTION_BREAKPOINT",
    0xE06D7363: "C++ exception",
    0xE0434352: ".NET exception",
}


@dataclass
class MinidumpInfo:
    path: Path
    code: int | None = None
    address: int | None = None
    thread_id: int | None = None
    access: str = ""                  # access violations: "reading 0x..." / "writing 0x..."
    module: str = ""                  # file name of the module holding the address
    offset: int | None = None         # address - module base
    modules: list[str] = field(default_factory=list)
    thread_name: str = ""             # the crashing thread's name, when the game or a library named it
    stack: list[str] = field(default_factory=list)          # "ScriptHookV.dll+0xE55B", from the crash outward
    native: int | None = None         # the native's hash when Script Hook V was calling one
    native_name: str = ""             # filled in by the caller (leonida.nativenames)
    stack_strings: list[str] = field(default_factory=list)  # "entity_set_car_lift_default", ...

    @property
    def via(self) -> str:
        """Who called into the crash, from the stack: a Script Hook V .NET script, a Script Hook V script, an ASI."""
        low = [s.split("+")[0].lower() for s in self.stack]
        if "scripthookv.dll" in low and any(m in low for m in ("clr.dll", "scripthookvdotnet.asi",
                                                              "scripthookvdotnet2.dll", "scripthookvdotnet3.dll")):
            return "a Script Hook V .NET script, through a native call"
        if "scripthookv.dll" in low:
            return "a Script Hook V script, through a native call"
        asis = [s.split("+")[0] for s in self.stack if s.lower().split("+")[0].endswith(".asi")]
        return f"{asis[0]}" if asis else ""

    def stack_summary(self) -> str:
        """One line: "called from ScriptHookV.dll+0xE55B < clr.dll+0x634A5 < ... (a Script Hook V .NET script ...);
        native ACTIVATE_INTERIOR_ENTITY_SET (0x55E86AF2712B36A1); thread 'x'; on the stack: entity_set_..."."""
        parts = []
        if self.stack:
            chain = " < ".join(self.stack[:8])
            parts.append(f"called from {chain}" + (f" ({self.via})" if self.via else ""))
        if self.native is not None:
            parts.append(f"native {self.native_name or 'unknown'} (0x{self.native:016X})")
        if self.thread_name:
            parts.append(f"thread '{self.thread_name}'")
        if self.stack_strings:
            parts.append("on the stack: " + ", ".join(self.stack_strings))
        return "; ".join(parts)

    @property
    def code_name(self) -> str:
        if self.code is None:
            return "no exception record"
        return f"{CODES.get(self.code, 'exception')} (0x{self.code:08X})"

    @property
    def site(self) -> str:
        """Where it crashed, the same for the same bug: "GTA5_Enhanced.exe+0xBCC6AD" (or the raw address)."""
        if self.module:
            return f"{self.module}+0x{self.offset:X}"
        return f"0x{self.address:X}" if self.address is not None else "unknown"

    @property
    def asis(self) -> list[str]:
        """The ASI plugins loaded in the game when it crashed (in load order, each once)."""
        seen: dict[str, str] = {}
        for m in self.modules:
            if m.lower().endswith(".asi") and m.lower() not in seen:
                seen[m.lower()] = m
        return list(seen.values())

    def describe(self) -> str:
        where = ""
        if self.module:
            where = f" in {self.module}+0x{self.offset:X}"
        elif self.address is not None:
            where = f" at 0x{self.address:X} (outside the loaded modules)"
        return f"{self.code_name}{where}{(' ' + self.access) if self.access else ''}"


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def read_minidump(path: Path) -> MinidumpInfo | None:
    """The exception and its module from a minidump, or None when it isn't one (or can't be read)."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if len(head) < 32 or head[:4] != b"MDMP":
                return None
            count, dir_rva = _u32(head, 8), _u32(head, 12)
            if not 0 < count <= 512:
                return None
            f.seek(dir_rva)
            directory = f.read(12 * count)
            streams: dict[int, tuple[int, int]] = {}
            for i in range(len(directory) // 12):
                kind, size, rva = struct.unpack_from("<III", directory, i * 12)
                streams.setdefault(kind, (size, rva))
            info = MinidumpInfo(Path(path))
            rsp = None
            if EXCEPTION_STREAM in streams:
                _, rva = streams[EXCEPTION_STREAM]
                f.seek(rva)
                ex = f.read(8 + 152 + 8)
                if len(ex) >= 8 + 152 + 8:
                    ctx_size, ctx_rva = struct.unpack_from("<II", ex, 8 + 152)
                    if ctx_size >= _CONTEXT_MIN:
                        f.seek(ctx_rva + _RSP)
                        raw_rsp = f.read(8)
                        rsp = struct.unpack("<Q", raw_rsp)[0] if len(raw_rsp) == 8 else None
                if len(ex) >= 8 + 32:
                    info.thread_id = _u32(ex, 0)
                    code, _flags, _rec, addr, nparams = struct.unpack_from("<IIQQI", ex, 8)
                    info.code, info.address = code, addr
                    # ExceptionInformation[] follows NumberParameters and a 4-byte alignment: 8 + 32 bytes in
                    if code == 0xC0000005 and nparams >= 2 and len(ex) >= 8 + 32 + 16:
                        rw, target = struct.unpack_from("<QQ", ex, 8 + 32)
                        info.access = f"{({0: 'reading', 1: 'writing', 8: 'executing'}).get(rw, 'accessing')} " \
                                      f"0x{target:X}"
            bases: list[tuple[int, int, str]] = []
            if MODULE_LIST_STREAM in streams:
                _, rva = streams[MODULE_LIST_STREAM]
                f.seek(rva)
                n = _u32(f.read(4).ljust(4, b"\0"), 0)
                raw = f.read(_MODULE_SIZE * min(n, _MAX_MODULES))
                for i in range(len(raw) // _MODULE_SIZE):
                    base, size, _ck, _ts, name_rva = struct.unpack_from("<QIIII", raw, i * _MODULE_SIZE)
                    f.seek(name_rva)
                    ln = _u32(f.read(4).ljust(4, b"\0"), 0)
                    name = f.read(min(ln, _MAX_NAME)).decode("utf-16-le", "replace")
                    short = name.replace("/", "\\").rsplit("\\", 1)[-1]
                    bases.append((base, size, short))
                    info.modules.append(short)
            if info.address is not None:
                for base, size, short in bases:
                    if base <= info.address < base + size:
                        info.module, info.offset = short, info.address - base
                        break
            if rsp is not None and info.thread_id is not None:
                _read_stack(f, streams, info, rsp, bases)
            return info
    except (OSError, struct.error, ValueError):
        return None


def _read_stack(f, streams: dict, info: MinidumpInfo, rsp: int, bases: list[tuple[int, int, str]]) -> None:
    """Fill ``stack``, ``native``, ``stack_strings`` and ``thread_name`` from the crashing thread."""
    if THREAD_NAMES_STREAM in streams:
        _, rva = streams[THREAD_NAMES_STREAM]
        f.seek(rva)
        n = _u32(f.read(4).ljust(4, b"\0"), 0)
        raw = f.read(12 * min(n, 4096))
        for i in range(len(raw) // 12):
            tid, name_rva = struct.unpack_from("<IQ", raw, 12 * i)
            if tid == info.thread_id:
                f.seek(name_rva)
                ln = _u32(f.read(4).ljust(4, b"\0"), 0)
                info.thread_name = f.read(min(ln, _MAX_NAME)).decode("utf-16-le", "replace")
                break
    if THREAD_LIST_STREAM not in streams:
        return
    _, rva = streams[THREAD_LIST_STREAM]
    f.seek(rva)
    n = _u32(f.read(4).ljust(4, b"\0"), 0)
    raw = f.read(48 * min(n, 16384))
    sorted_bases = sorted(bases)

    def where(v: int) -> str | None:
        for base, size, short in sorted_bases:
            if base <= v < base + size:
                return f"{short}+0x{v - base:X}"
            if base > v:
                return None
        return None

    for i in range(len(raw) // 48):
        tid, _s, _c, _p, _teb, st_start, st_size, st_rva = struct.unpack_from("<IIIIQQII", raw, 48 * i)
        if tid != info.thread_id or not st_start <= rsp < st_start + st_size:
            continue
        f.seek(st_rva + (rsp - st_start))
        stack = f.read(min(st_size - (rsp - st_start), _STRING_SCAN))

        hits: list[str] = []
        shv_at = None
        for o in range(0, min(len(stack), _STACK_SCAN) - 7, 8):
            v = struct.unpack_from("<Q", stack, o)[0]
            w = where(v)
            if not w or w.split("+")[0].lower() in SYSTEM_MODULES:
                continue
            if w.lower().startswith("scripthookv.dll+") and shv_at is None:
                shv_at = o
            if len(hits) < _MAX_STACK and (not hits or hits[-1] != w):
                hits.append(w)
        info.stack = hits
        if shv_at is not None and shv_at + 16 <= len(stack):
            cand = struct.unpack_from("<Q", stack, shv_at + 8)[0]
            if cand > 0xFFFFFFFF and where(cand) is None and not st_start <= cand < st_start + st_size:
                info.native = cand
        # strings: the whole captured stack, below RSP too (the callee frames that just returned hold the arguments
        # a script passed, e.g. the entity-set name), nearest to RSP first
        f.seek(st_rva)
        whole = f.read(min(st_size, _STACK_BYTES))
        here = rsp - st_start
        found = sorted(re.finditer(rb"[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}", whole), key=lambda m: abs(m.start() - here))
        seen: list[str] = []
        for m in found:
            s = m.group().decode("ascii")
            if len(s) >= 10 and s not in seen:
                seen.append(s)
            if len(seen) >= 6:
                break
        info.stack_strings = seen
        return
