"""Verify files: are the files Leonida installed still what the install log says?

For every path the active steps touched, the LAST action decides what should be there:

  add / replace / external-add / external-change   the file, with the logged sha256 (when one was logged)
  mkdir                                            the folder
  external-remove                                  nothing (a file the step removed must not have come back)
  rpf-edit                                         the archive copy, with each changed entry's logged hash
                                                   (checked with the RPF helper; skipped when it isn't installed)

Nothing is changed here: the launcher re-applies the locked settings afterwards (Session.apply_settings, logged
through the Installer), and a damaged mod is installed again with Disable / Enable. Stdlib only.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import log as L
from .matcher import sha256_file

log = logging.getLogger(__name__)

MISSING, CHANGED, CAME_BACK, ENTRIES = "missing", "changed", "came back", "archive entries changed"


@dataclass
class Problem:
    step: int
    mod: str
    path: str
    problem: str
    detail: str = ""

    def line(self) -> str:
        return f"{self.path}: {self.problem}" + (f" ({self.detail})" if self.detail else "")


@dataclass
class FileCheck:
    checked: int = 0
    problems: list[Problem] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def mods(self) -> list[str]:
        """The mods (ids; "settings:<id>" steps count for their mod) with a problem, in step order."""
        out: list[str] = []
        for p in self.problems:
            mid = p.mod.split(":", 1)[1] if p.mod.startswith("settings:") else p.mod
            if mid not in out:
                out.append(mid)
        return out

    def summary(self, names: dict[str, str] | None = None) -> list[str]:
        names = names or {}
        if self.ok:
            lines = [f"All {self.checked} installed file(s) are as Leonida installed them."]
        else:
            lines = [f"{len(self.problems)} of {self.checked} installed file(s) differ from the install log:"]
            for mid in self.mods():
                mine = [p for p in self.problems if p.mod in (mid, f"settings:{mid}")]
                lines.append(f"  {names.get(mid, mid)}:")
                lines += [f"    {p.line()}" for p in mine[:12]]
                if len(mine) > 12:
                    lines.append(f"    ... and {len(mine) - 12} more")
        lines += [f"  not checked: {s}" for s in self.skipped]
        return lines


def expected(log_: L.InstallLog) -> dict[str, tuple[L.Step, L.Action]]:
    """path (lower case) -> the last active step and action that touched it."""
    out: dict[str, tuple[L.Step, L.Action]] = {}
    for st in log_.active_steps():
        if st.status != "done":
            continue
        for a in st.actions:
            out[a.path.rstrip("/").lower()] = (st, a)
    return out


def check_files(log_: L.InstallLog, game_dir: Path, state_dir: Path, helper: list[str] | None = None,
                progress: Callable[[int, int, str], None] | None = None, only: set[str] | None = None) -> FileCheck:
    """Compare the game folder with the install log (see the module doc). ``progress(done, total, path)``;
    ``only``: just these paths (e.g. again after the locked settings were written)."""
    game, state = Path(game_dir), Path(state_dir)
    todo = [v for k, v in expected(log_).items() if only is None or k in {p.rstrip("/").lower() for p in only}]
    out = FileCheck()
    rpf_checks: list[tuple[L.Step, L.Action, dict]] = []
    for i, (st, a) in enumerate(todo):
        if progress is not None:
            progress(i, len(todo), a.path)
        target = game / a.path.rstrip("/")
        out.checked += 1
        try:
            if a.op == L.MKDIR:
                if not target.is_dir():
                    out.problems.append(Problem(st.id, st.mod, a.path, MISSING))
            elif a.op == L.EXT_REMOVE:
                if target.exists():
                    out.problems.append(Problem(st.id, st.mod, a.path, CAME_BACK,
                                                "the step removed it; something put it back"))
            elif a.op == L.RPF_EDIT:
                if not target.is_file():
                    out.problems.append(Problem(st.id, st.mod, a.path, MISSING))
                    continue
                manifest = _entries(state, a)
                if manifest is not None:
                    rpf_checks.append((st, a, manifest))
            else:
                if not target.is_file():
                    if target.is_dir() and a.op in (L.EXT_ADD, L.ADD) and a.sha256 is None:
                        continue  # a folder a run/guided step made
                    out.problems.append(Problem(st.id, st.mod, a.path, MISSING))
                elif a.sha256 and sha256_file(target) != a.sha256:
                    out.problems.append(Problem(st.id, st.mod, a.path, CHANGED, "not the file Leonida installed"))
        except OSError as exc:
            out.problems.append(Problem(st.id, st.mod, a.path, "can't be read", exc.strerror or str(exc)))
    if rpf_checks:
        _check_entries(out, rpf_checks, game, helper)
    if progress is not None:
        progress(len(todo), len(todo), "")
    log.info("verify files: %d checked, %d problem(s)", out.checked, len(out.problems))
    return out


def _entries(state: Path, a: L.Action) -> dict | None:
    from .rpf import ENTRY_MANIFEST

    if not a.backup:
        return None
    try:
        return json.loads((state / a.backup / ENTRY_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _check_entries(out: FileCheck, checks: list[tuple[L.Step, L.Action, dict]], game: Path,
                   helper: list[str] | None) -> None:
    from . import rpf as R

    if helper is None:
        out.skipped.append(f"entries inside {len(checks)} archive copy(ies): the RPF helper isn't installed")
        return
    ops = [{"op": "hash", "rpf": str(game / a.path), "entries": [r["entry"] for r in m.get("entries", [])]}
           for _st, a, m in checks]
    try:
        results = R.run_helper(helper, game, ops)
    except R.RpfError as exc:
        out.skipped.append(f"entries inside {len(checks)} archive copy(ies): {exc}")
        return
    for (st, a, m), res in zip(checks, results, strict=False):
        hashes = res.get("hashes") or {}
        bad = [r["entry"] for r in m.get("entries", []) if r.get("after") and hashes.get(r["entry"]) != r["after"]]
        if bad:
            out.problems.append(Problem(st.id, st.mod, a.path, ENTRIES, ", ".join(bad[:5])
                                        + (f" and {len(bad) - 5} more" if len(bad) > 5 else "")))
