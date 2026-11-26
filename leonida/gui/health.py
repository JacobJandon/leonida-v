"""The Library's first card: one line on how the setup is doing: mods on and checked in game, the last play test,
crash notices and a free-memory warning. Cheap (two small JSON files and one Windows call), so the pack page can
build it on every visit."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QFrame, QVBoxLayout

from . import widgets as W

LOW_FREE_MB = 6 * 1024          # memwatch.LOW_FREE_MB: the play test's own low-memory warning


def free_ram_mb() -> float | None:
    """Free physical memory now (GlobalMemoryStatusEx; None elsewhere or when it fails). LEONIDA_FAKE_FREE_MB
    overrides it (tests)."""
    fake = os.environ.get("LEONIDA_FAKE_FREE_MB")
    if fake:
        try:
            return float(fake)
        except ValueError:
            return None
    if os.name != "nt":
        return None
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(st)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return st.ullAvailPhys / 2**20
    except (OSError, AttributeError):
        pass
    return None


@dataclass
class Health:
    parts: list[str] = field(default_factory=list)
    tone: str = "success"            # success | info | warning
    details: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "  ·  ".join(self.parts)


def last_playtest(state: Path) -> dict | None:
    try:
        data = json.loads((Path(state) / "playtest" / "last-report.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def health(session, mods, pack_id: str | None, free_mb: float | None = None) -> Health:
    """The line for the chosen pack's ``mods``. ``free_mb``: free RAM (None: measured now)."""
    from .. import gamestate as GS
    from .. import ingame

    h = Health()

    def warn(text: str, detail: str = "") -> None:
        h.parts.append(text)
        h.tone = "warning"
        if detail:
            h.details.append(detail)

    ids = [m.id for m in mods if not getattr(m, "unsupported", None)]
    installed = session.log.installed_mods()
    on = [m for m in ids if m in installed and m not in set(session.config.disabled)]
    recs = ingame.checked(session.state)
    checked = sum(1 for m in on if (recs.get(m) or {}).get("ok"))
    bad = [m for m in on if m in recs and not recs[m].get("ok")]
    if not on:
        h.parts.append("No mods on yet")
        h.tone = "info"
    else:
        text = f"{len(on)} of {len(ids)} mods on"
        if recs:
            text += f", {checked} checked in game"
        h.parts.append(text)
        if bad:
            warn(f"{len(bad)} not confirmed in game", "Not confirmed in game: " + ", ".join(bad))
    rep = last_playtest(session.state)
    if rep:
        status = str(rep.get("status", "?"))
        when = str(rep.get("when", ""))[5:16].replace("-", "/")        # "11/26 18:40"
        line = f"last play test {status}" + (f" ({when})" if when else "")
        if status == "passed":
            h.parts.append(line)
        else:
            warn(line, str(rep.get("message", "")))
    elif on:
        h.parts.append("no play test yet")
        if h.tone == "success":
            h.tone = "info"
    st = GS.stats_for(session.state, pack_id) if pack_id else None
    if st is not None and st.last_end == GS.BEFORE_STORY:
        warn("last game start closed before story mode (a crash?)",
             f"The last session ended after {GS.duration(st.last_seconds)}, before story mode loaded.")
    free = free_ram_mb() if free_mb is None else free_mb
    if free is not None and free < LOW_FREE_MB:
        warn(f"only {free / 1024:.1f} GB of RAM free", "Close some apps before playing: GTA V with this pack wants "
                                                      f"{LOW_FREE_MB / 1024:.0f} GB or more free.")
    elif free is not None:
        h.details.append(f"{free / 1024:.1f} GB of RAM free ({time.strftime('%H:%M')}).")
    return h


def health_card(win, info) -> QFrame | None:
    """The card (None for a pack that isn't the chosen one, or the other edition's)."""
    s = win.session
    if not info.chosen or info.edition != s.edition:
        return None
    h = health(s, info.mods, info.pack.id)
    card = QFrame()
    card.setProperty("card", True)
    if h.tone == "warning":
        card.setProperty("tone", "warning")
    card.setObjectName("healthCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 10, 16, 10)
    mark = {"success": "✓ ", "warning": "⚠ ", "info": ""}[h.tone]
    line = W._label(mark + h.text, None, h.tone if h.tone != "info" else None, wrap=True)
    line.setObjectName("healthLine")
    line.setToolTip("\n".join(h.details))
    lay.addWidget(line)
    card.health = h  # type: ignore[attr-defined]
    return card


def health_key(state: Path) -> tuple:
    """What the line depends on besides Session.stamp (the pack page's rebuild key)."""
    from .. import ingame

    out = []
    for p in (Path(state) / "playtest" / "last-report.json", Path(state) / ingame.CHECKED_FILE):
        try:
            out.append(p.stat().st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)
