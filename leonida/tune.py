"""`leonida settings tune`: push GTA's settings as far as this PC really takes them, measured, not guessed.

The ladder is data (``gamesettings.json`` "tune"): steps, each a settings.xml key with its values from low to high
(the last is the hard maximum) and what it costs (``gpu``, ``vram`` or ``ram``). From the values the PC has now, the
tune tries the next value of one key at a time:

1. write it (a logged ``settings:gta-settings`` step, like every game setting),
2. run the play test (the game starts, reaches story mode, the memory is sampled every 2 s, the game closes),
3. keep it when every run passed, peak video memory stays under ``vramBudget`` of the card, and, for a RAM step,
   free RAM at the peak stays above ``minFreeRamMB``; else put the previous value back and go to the next key.

Values listed in ``knownCrash`` are never tried. The result is ``<state>/tuned-settings.json``: the kept values (they
win over the variant and the graphics card's tier in gamesettings.wanted, source "tuned on this PC") and every
measurement, so a later run starts from there. ``run_test`` is injectable (tests use a fake).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from . import gamesettings as G

TUNED_FILE = "tuned-settings.json"


@dataclass
class TuneRun:
    key: str
    value: str
    status: str                        # the play test's status ("passed", "crashed", ...), "+"-joined for several runs
    vram_peak_mb: float | None
    vram_total_mb: float | None
    free_ram_mb: float | None
    kept: bool
    why: str = ""


def load_tuned(state: Path | str) -> dict:
    try:
        data = json.loads((Path(state) / TUNED_FILE).read_text(encoding="utf-8"))
        return dict(data.get("values", {}))
    except (OSError, ValueError, AttributeError):
        return {}


def save_tuned(state: Path | str, values: dict, runs: list[TuneRun] | None = None, pc: str = "") -> Path:
    path = Path(state) / TUNED_FILE
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    history = list(old.get("runs", [])) + [asdict(r) for r in (runs or [])]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"values": values, "pc": pc or old.get("pc", ""),
                                "at": time.strftime("%Y-%m-%d %H:%M"), "runs": history}, indent=1), encoding="utf-8")
    return path


def _num(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return {"false": 0.0, "true": 1.0}.get(str(v).strip().lower())


def plan(current: dict, rules: dict | None = None) -> list[tuple[str, str | None, list[str], str]]:
    """[(key, its value now, the higher values to try, cost)] from the ladder; knownCrash values left out."""
    rules = rules or G.load_rules()
    tune = rules.get("tune", {})
    crash = tune.get("knownCrash", {})
    out = []
    for step in tune.get("steps", []):
        key, values = step["key"], [str(v) for v in step["values"]]
        now = current.get(key)
        if now is None:
            start = 1          # not locked: the game's own value, taken as the ladder's floor
        elif now in values:
            start = values.index(now) + 1
        else:
            n = _num(now)
            start = sum(1 for v in values if n is not None and _num(v) is not None and _num(v) <= n)
        ups = [v for v in values[start:] if v not in {str(c) for c in crash.get(key, [])}]
        out.append((key, now, ups, step.get("cost", "gpu")))
    return out


def _measure(reports) -> tuple[bool, str, float | None, float | None]:
    ok = all(getattr(r, "ok", False) for r in reports)
    status = "+".join(getattr(r, "status", "?") for r in reports)
    peaks = [((getattr(r, "memory", None) or {}).get("peak") or {}) for r in reports]
    vram = [p.get("gpu_used_mb") for p in peaks if p.get("gpu_used_mb") is not None]
    free = [p.get("sys_free_mb") for p in peaks if p.get("sys_free_mb") is not None]
    return ok, status, (max(vram) if vram else None), (min(free) if free else None)


def tune(session, run_test: Callable | None = None, *, budget: float | None = None, min_free_mb: float | None = None,
         runs_per_step: int = 1, keys: list[str] | None = None, ui=None,
         progress: Callable[[str], None] | None = None) -> list[TuneRun]:
    """Run the ladder on this PC (see the module doc). Returns every try; the kept values are saved."""
    from .playtest import playtest

    rules = G.load_rules()
    tune_cfg = rules.get("tune", {})
    budget = budget if budget is not None else float(tune_cfg.get("vramBudget", 0.9))
    floor = min_free_mb if min_free_mb is not None else tune_cfg.get("minFreeRamMB")
    run_test = run_test or (lambda s: playtest(s))
    say = progress or (lambda m: None)
    pc = session.pc_specs()
    total = pc.vram_gb * 1024 if pc.vram_gb else None
    if total is None:
        raise ValueError("Leonida can't read this graphics card's video memory, so it can't keep the tune in "
                         "budget. Nothing was changed.")
    tuned = load_tuned(session.state)
    current = {w.key: str(w.value) for w in session.game_settings()}
    runs: list[TuneRun] = []

    def write():
        save_tuned(session.state, tuned, pc=pc.describe())
        session.apply_game_settings(ui) if ui is not None else session.apply_game_settings(_QuietUI())

    for key, now, ups, cost in plan(current, rules):
        if keys and key not in keys:
            continue
        for value in ups:
            tuned[key] = value
            write()
            n = max(runs_per_step, 2 if cost == "ram" else 1)
            say(f"{key.split('/')[1]} = {value}: {n} play test(s) ...")
            ok, status, vram, free = _measure([run_test(session) for _ in range(n)])
            why = ""
            if not ok:
                why = f"the play test didn't pass ({status})"
            elif vram is None:
                why = "no video memory measurement"
                ok = False
            elif vram > budget * total:
                why = f"peak video memory {vram / 1024:.1f} GB is over {budget:.0%} of {total / 1024:.0f} GB"
                ok = False
            elif cost == "ram" and floor is not None and free is not None and free < floor:
                why = f"free RAM fell to {free / 1024:.1f} GB (the floor is {floor / 1024:.1f} GB)"
                ok = False
            runs.append(TuneRun(key, value, status, vram, total, free, ok, why))
            say("kept" if ok else f"back to {now}: {why}")
            if ok:
                now = value
                continue
            if now is None:
                tuned.pop(key, None)
            else:
                tuned[key] = now
            write()
            break
    save_tuned(session.state, tuned, runs, pc.describe())
    return runs


class _QuietUI:
    """The installer's UI calls during a tune: settings writes only (no questions are asked)."""

    def info(self, *a, **k):
        pass

    def warn(self, *a, **k):
        pass

    def confirm(self, *a, **k):
        return True

    def wait_done(self, *a, **k):
        return True

    def launch(self, *a, **k):
        pass
