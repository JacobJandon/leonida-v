"""Stand-in for LeonidaRpf.exe in tests (no CodeWalker, no game keys): same command line and JSON protocol.

A "fake RPF" is a zip file. put/delete/extract/list work on its members (backslash paths); xml edits are recorded
as JSON members under "__xml__/" so tests can check what would be applied; "open" encryption is marked by a member
"__open__". Set FAKE_RPF_FAIL_AT=<op index> to make that op fail (tests the error path), FAKE_RPF_LOG=<file> to
append each batch's ops (tests that one batch is used).
"""

from __future__ import annotations

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
    entry = norm(op["entry"])
    if kind == "extract":
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
        write(rpf, m)
        return {"op": kind, "entry": entry, "deleted": deleted}
    if kind == "xml":
        if entry not in m:
            raise FileNotFoundError(f"{entry} not found")
        key = f"__xml__/{entry}.json"
        done = json.loads(m.get(key, b"[]"))
        done += op["edits"]
        m[key] = json.dumps(done).encode()
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
    results = []
    for i, op in enumerate(ops):
        try:
            if not (game / "GTA5_Enhanced.exe").is_file():
                raise FileNotFoundError(f"GTA5_Enhanced.exe not found in {game}")
            if i == fail_at:
                raise RuntimeError("simulated failure")
            results.append(run(op))
        except Exception as exc:  # noqa: BLE001 - reported like the real helper
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}", "op": i, "results": results}))
            return 1
    print(json.dumps({"ok": True, "results": results, "scanErrors": []}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
