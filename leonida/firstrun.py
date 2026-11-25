"""The first-run setup ("Initialize"): where the person is in it, and the choices it suggests.

``<state>/setup.json``::

    {"step": 3, "finished": false, "skipped": ["prereqs"], "started": "2026-11-25T18:02:11+00:00"}

The flow runs when Leonida starts with no config.json in its state folder (a first start), resumes at ``step``
when it was closed half-way, and starts again from Settings > "Run setup again". Stdlib only.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .paths import CONFIG_NAME

SETUP_NAME = "setup.json"
STEPS = ("welcome", "game", "prereqs", "pack", "download", "install", "playtest", "done")
RECOMMENDED_PACK = "owner-pick"     # the owner's tested set (modpacks.json); the default pack when it isn't there

# Where each prerequisite comes from: its maker's own page, and the winget package that installs it (run only when
# the person clicks it, in a console they can see).
PREREQS = {
    "dotnet48": (".NET Framework 4.8", "https://dotnet.microsoft.com/download/dotnet-framework/net48", None),
    "vcredist": ("Visual C++ 2015-2022 (x64)",
                 "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
                 "Microsoft.VCRedist.2015+.x64"),
    "7zip": ("7-Zip (for .7z and .rar downloads)", "https://www.7-zip.org/download.html", "7zip.7zip"),
}


def load(state: Path) -> dict:
    try:
        data = json.loads((Path(state) / SETUP_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(state: Path, data: dict) -> None:
    p = Path(state) / SETUP_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(p)


def start(state: Path) -> dict:
    data = {"step": 0, "finished": False, "skipped": [],
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    save(state, data)
    return data


def should_run(state: Path) -> int | None:
    """The step to open at start-up: 0 on a first start (no config.json), the saved step when the setup was left
    half-way, None otherwise."""
    data = load(state)
    if data:
        return None if data.get("finished") else max(0, min(int(data.get("step", 0) or 0), len(STEPS) - 1))
    return 0 if not (Path(state) / CONFIG_NAME).is_file() else None


def total_ram_gb() -> float | None:
    """Installed RAM in GB (Windows), None elsewhere or when it can't be read."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(st)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return st.ullTotalPhys / 2**30
    except (OSError, AttributeError, ValueError):
        return None


def variant_for_ram(variants, ram_gb: float | None) -> str | None:
    """The variant named for RAM ("ram16", "ram32") that fits this PC: the biggest one not above its RAM (Windows
    reports a little less than what's installed, so 31.9 GB counts as 32). None when no variant is named for RAM or
    the RAM is unknown."""
    sized = []
    for v in variants:
        m = re.fullmatch(r"ram(\d+)", getattr(v, "id", "") or "")
        if m:
            sized.append((int(m.group(1)), v.id))
    if not sized or ram_gb is None:
        return None
    sized.sort()
    fits = [vid for gb, vid in sized if gb <= ram_gb * 1.05]
    return fits[-1] if fits else sized[0][1]


def recommended_pack(manifest) -> str | None:
    if RECOMMENDED_PACK in manifest.packs:
        return RECOMMENDED_PACK
    return manifest.default_pack or next(iter(manifest.packs), None)
