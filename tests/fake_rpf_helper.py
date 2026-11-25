"""Stand-in for LeonidaRpf.exe in tests (no CodeWalker, no game keys): same command line and JSON protocol.

A "fake RPF" is a zip file. put/delete/extract/export/hash/list work on its members (backslash paths); xml edits are recorded
as JSON members under "__xml__/" so tests can check what would be applied; "open" encryption is marked by a member
"__open__". Set FAKE_RPF_FAIL_AT=<op index> (or FAKE_RPF_FAIL_ON=<op>:<n>, the n-th op of that kind) to make that op
fail (tests the error path), FAKE_RPF_LOG=<file> to
append each batch's ops (tests that one batch is used).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path


def norm(entry: str) -> str:
    """Zip member name for an archive entry (zipfile stores "/" separators)."""
    return "/".join(p for p in entry.replace("\\", "/").split("/") if p).lower()


def read(rpf: Path) -> dict[str, bytes]:
    if not rpf.is_file():
        raise FileNotFoundError(f"archive not found: {rpf}")
    with zipfile.ZipFile(rpf) as z:
        return {n: z.read(n) for n in z.namelist()}


def write(rpf: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(rpf, "w") as z:
        for n, data in sorted(members.items()):
            z.writestr(n, data)


def entry_hash(data: bytes) -> str:
    return hashlib.sha256(b"B" + data).hexdigest()


def missing_container(m: dict[str, bytes], name: str) -> str | None:
    """The first folder / nested archive on the path that holds nothing yet (backslash path), or None."""
    parts = name.split("/")
    for i in range(1, len(parts)):
        prefix = "/".join(parts[:i])
        if not any(n.startswith(prefix + "/") for n in m):
            return "\\".join(parts[:i])
    return None


def run(op: dict) -> dict:
    kind = op["op"]
    rpf = Path(op.get("rpf", ""))
    if kind == "keys":
        return {"op": kind, "ok": True}
    if kind == "create":
        rpf.parent.mkdir(parents=True, exist_ok=True)
        write(rpf, {"__open__": b""})
        return {"op": kind, "rpf": str(rpf)}
    m = read(rpf)
    if kind == "list":
        return {"op": kind, "entries": [{"path": n} for n in m if not n.startswith("__")],
                "encryption": "OPEN" if "__open__" in m else "NG"}
    if kind == "hash":
        hashes, created = {}, {}
        names = [n for n in m if not n.startswith("__")] if op.get("all") else []
        for n in names:
            hashes[n.replace("/", "\\")] = entry_hash(m[n])
        for e in op.get("entries") or []:
            n = norm(e)
            hashes[e] = entry_hash(m[n]) if n in m else None
            if n not in m:
                created[e] = missing_container(m, n)
        return {"op": kind, "hashes": hashes, "created": created,
                "encryption": "OPEN" if "__open__" in m else "NG"}
    entry = norm(op["entry"])
    if kind == "export":
        if entry not in m:
            return {"op": kind, "entry": op["entry"], "exists": False}
        out = Path(op["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(m[entry])
        return {"op": kind, "entry": op["entry"], "exists": True, "hash": entry_hash(m[entry])}
    if kind == "extract":
        Path(op["out"]).parent.mkdir(parents=True, exist_ok=True)
        Path(op["out"]).write_bytes(m[entry])
        return {"op": kind, "entry": entry}
    m["__open__"] = b""
    if kind == "put":
        existed = entry in m
        m[entry] = Path(op["src"]).read_bytes()
        write(rpf, m)
        return {"op": kind, "entry": entry, "replaced": existed}
    if kind == "delete":
        deleted = m.pop(entry, None) is not None
        for n in [n for n in m if n.startswith(entry + "/")]:  # a folder / nested archive and what's in it
            del m[n]
            deleted = True
        write(rpf, m)
        return {"op": kind, "entry": entry, "deleted": deleted}
    if kind == "ytd":
        if entry not in m:
            raise FileNotFoundError(f"{entry} (a texture dictionary) not found")
        texture = op.get("texture") or Path(op["src"]).stem
        if f"<{texture}>".encode() not in m[entry]:
            raise KeyError(f"no texture {texture} in {entry}")
        old = m[entry].split(b"|", 1)[0]
        m[entry] = old + b"|" + texture.encode() + b"=" + hashlib.sha256(Path(op["src"]).read_bytes()).hexdigest().encode()
        write(rpf, m)
        return {"op": kind, "entry": entry, "texture": texture}
    if kind == "xml":
        if entry not in m:
            raise FileNotFoundError(f"{entry} not found")
        key = f"__xml__/{entry}.json"
        done = json.loads(m.get(key, b"[]"))
        done += op["edits"]
        m[key] = json.dumps(done).encode()
        m[entry] = m[entry] + b"<!--" + json.dumps(op["edits"]).encode() + b"-->"  # the entry itself changes too
        write(rpf, m)
        return {"op": kind, "entry": entry, "matched": [1] * len(op["edits"])}
    raise ValueError(f"unknown op {kind}")


def main() -> int:
    game, ops_file = Path(sys.argv[1]), Path(sys.argv[2])
    ops = json.loads(ops_file.read_text(encoding="utf-8"))
    if os.environ.get("FAKE_RPF_LOG"):
        with open(os.environ["FAKE_RPF_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps(ops) + "\n")
    fail_at = int(os.environ.get("FAKE_RPF_FAIL_AT", "-1"))
    fail_kind, _, fail_nth = os.environ.get("FAKE_RPF_FAIL_ON", "").partition(":")  # "delete:1" = the 1st delete
    seen: dict[str, int] = {}
    results = []
    for i, op in enumerate(ops):
        try:
            if not (game / "GTA5_Enhanced.exe").is_file():
                raise FileNotFoundError(f"GTA5_Enhanced.exe not found in {game}")
            seen[op["op"]] = seen.get(op["op"], 0) + 1
            if i == fail_at or (op["op"] == fail_kind and str(seen[op["op"]]) == (fail_nth or "1")):
                raise RuntimeError("simulated failure")
            results.append(run(op))
        except Exception as exc:  # noqa: BLE001 - reported like the real helper
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}", "op": i, "results": results}))
            return 1
    print(json.dumps({"ok": True, "results": results, "scanErrors": []}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
