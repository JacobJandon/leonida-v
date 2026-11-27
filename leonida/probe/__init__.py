"""In-game probe for ``leonida playtest --deep``: a small Script Hook V .NET script that checks, inside the running
game, what logs can't show.

    plan = make_plan(session)                 # which DLC packs to check, which car, the handling values expected
    place(session, plan)                      # scripts\\LeonidaProbe.3.cs (recorded in <state>/playtest/probe.json)
    ... the game runs; the probe writes LeonidaProbe.log in the game folder ...
    result = parse_log(text); lines = judge(result, plan)
    remove(session)                           # always (finally / Ctrl+C), and leftovers at the next start

What it checks:
  - ``IS_DLC_PRESENT`` for every DLC pack the installed mods added (the pack's own name, ``nameHash`` in its
    setup2.xml, read from its dlc.rpf with the RPF helper; when that can't be read, the mod's own ``verify`` DLC
    name from mods.json, else the folder name);
  - each installed mod's ``verify`` interior (kind ``interior``): the player is moved to its x, y, and
    ``GET_INTERIOR_AT_COORDS`` between zMin and zMax must find an interior (then back where they were);
  - the handling the game applied to a test car (``GET_VEHICLE_HANDLING_FLOAT``), compared with the handling.meta in
    mods\\update\\update.rpf (Drive V's) and the game's own: Drive V counts as loaded when the car has its values.

The probe never waits inside a tick (Script Hook V .NET Enhanced aborts a script whose tick takes too long), has a
timeout per stage and writes a heartbeat line every tick, so a run that stops early says where and why
(LeonidaProbe.cs). The probe file is temporary: it isn't part of any install step, it's recorded before it's
written, removed after the run (also after a crash or Ctrl+C: the next run or ``remove`` cleans up what was
recorded), and its log is moved to <state>/playtest/.
"""

from __future__ import annotations

import json
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .. import rpf as R
from ..verify import FAILED, NOT_SEEN, OK, WARN, VerifyResult

PROBE_FILE = "LeonidaProbe.3.cs"        # ".3": Script Hook V .NET compiles it for API v3
PROBE_LOG = "LeonidaProbe.log"
TEMPLATE = Path(__file__).with_name("LeonidaProbe.cs")
RECORD = PurePosixPath("playtest", "probe.json")
TEST_CAR = "sultan"                     # a base-game car Drive V's handling.meta changes
FIELDS = ("fMass", "fInitialDriveForce", "fBrakeForce", "fTractionCurveMax")
DECISIVE = ("fMass", "fInitialDriveForce")  # kept as handling.meta writes them; the others are only reported
CREATED_EMPTY = "created empty: "          # installer step note: an archive made empty (not in this game build)
HANDLING = "common\\data\\handling.meta"
DRIVEV = ("drivev", "drivevnve")
PACK_PATH = re.compile(r"^(?:mods/update/x64/dlcpacks|update/x64/dlcpacks|onigiri/dlcpacks)/(?P<pack>[^/]+)/dlc\.rpf$",
                       re.I)
NAME_HASH = re.compile(r"<nameHash>\s*([^<\s]+)\s*</nameHash>", re.I)
TOLERANCE = 1e-3
STRESS_MODES = ("police", "drive")   # playtest --stress: what the probe does after its checks (LeonidaProbe.cs)


@dataclass
class Plan:
    packs: dict[str, str] = field(default_factory=dict)       # nameHash -> mod id that added the pack
    car: str = ""
    active: dict[str, float] = field(default_factory=dict)    # handling.meta in mods\update\update.rpf (Drive V)
    vanilla: dict[str, float] = field(default_factory=dict)   # the game's own update.rpf
    handling_mod: str | None = None                           # the installed Drive V, if any
    expected_missing: dict[str, str] = field(default_factory=dict)  # nameHash -> why the game won't load it
    notes: list[str] = field(default_factory=list)
    stress: str = ""                                          # "", "police" or "drive" (playtest --stress)
    stress_minutes: float = 0.0
    interiors: list[dict] = field(default_factory=list)       # verify kind "interior": name, x, y, zMin, zMax, mod


@dataclass
class ProbeLog:
    started: bool = False
    ticks: int = 0
    last_tick: str | None = None
    stages: list[str] = field(default_factory=list)
    dlc: dict[str, bool] = field(default_factory=dict)
    handling: dict[str, float] = field(default_factory=dict)
    car_error: str | None = None
    errors: list[str] = field(default_factory=list)
    gate_timeout: str | None = None
    done: str | None = None
    aborted: str | None = None
    stress: list[str] = field(default_factory=list)    # the probe's "stress ..." lines
    stress_done: str | None = None
    interiors: dict[int, tuple[int, bool]] = field(default_factory=dict)  # index -> (interior id, ready)

    @property
    def finished(self) -> bool:
        return self.done is not None or self.aborted is not None


# ------------------------------------------------------------------------------------------- the plan
def installed_packs(session) -> list[tuple[str, str]]:
    """(mod id, game-relative POSIX path of dlc.rpf) for every DLC pack the installed mods placed."""
    out: dict[str, tuple[str, str]] = {}
    for step in session.log.active_steps():
        if step.status != "done":
            continue
        for a in step.actions:
            if a.op in ("add", "external-add", "replace") and PACK_PATH.match(a.path):
                out.setdefault(a.path.lower(), (step.mod, a.path))
    return list(out.values())


def _abs(game: Path, rel: str) -> Path:
    return (Path(game) / PurePosixPath(rel.replace("\\", "/"))).resolve()


def manifest_dlc_names(mod_id: str, edition: str = "enhanced") -> list[str]:
    """The DLC pack names a mod's ``verify`` specs promise (``kind: dlc``), from mods.json."""
    from .. import zerotouch

    return [c["name"] for c in zerotouch.verify_for(mod_id, edition) if c.get("kind") == "dlc" and c.get("name")]


def fallback_name(mod_id: str, folder: str, edition: str = "enhanced") -> str:
    """The pack's name when setup2.xml can't be read: the mod's own ``verify`` DLC name when it has exactly one (or
    one matching the folder), else the folder name. A ``_g9`` folder often holds a pack named without it
    (vwp_247shop_g9 -> vwp_247shop), so guessing from the folder alone gives false failures."""
    names = manifest_dlc_names(mod_id, edition)
    low = folder.lower()
    for n in names:
        if n.lower() == low:
            return n
    stem = re.sub(r"_g9$", "", low)
    for n in names:
        if n.lower() == stem:
            return n
    return names[0] if len(names) == 1 else folder


def pack_names(game: Path, helper: list[str] | None, packs: list[tuple[str, str]], tmp: Path,
               edition: str = "enhanced") -> dict[str, str]:
    """game-relative dlc.rpf path -> the pack's nameHash (setup2.xml); when it can't be read, the mod's own verify
    DLC name (``fallback_name``)."""
    names = {rel: fallback_name(mod, PurePosixPath(rel).parent.name, edition) for mod, rel in packs}
    if helper is None or not packs:
        return names
    for i, (_mod, rel) in enumerate(packs):   # one run per pack: a broken pack mustn't hide the others' names
        out = tmp / f"setup2-{i}.xml"
        try:
            R.run_helper(helper, game, [{"op": "extract", "rpf": str(_abs(game, rel)), "entry": "setup2.xml",
                                         "out": str(out)}])
            m = NAME_HASH.search(out.read_text(encoding="utf-8-sig", errors="replace"))
            if m:
                names[rel] = m.group(1)
        except (R.RpfError, OSError):
            continue
    return names


def handling_values(text: str, car: str) -> dict[str, float]:
    """The FIELDS of ``car``'s CHandlingData item in a handling.meta (empty when it isn't there)."""
    try:
        root = ET.fromstring(text.lstrip("﻿"))
    except ET.ParseError:
        return {}
    for item in root.iter("Item"):
        name = item.findtext("handlingName")
        if (name or "").strip().lower() == car.lower():
            out = {}
            for f in FIELDS:
                el = item.find(f)
                if el is not None and el.get("value") is not None:
                    try:
                        out[f] = float(el.get("value"))
                    except ValueError:
                        continue
            return out
    return {}


def _read_handling(game: Path, helper: list[str], archive: Path, tmp: Path, car: str) -> dict[str, float]:
    if not archive.is_file():
        return {}
    out = tmp / f"handling-{abs(hash(str(archive)))}.meta"
    try:
        R.run_helper(helper, game, [{"op": "extract", "rpf": str(archive.resolve()), "entry": HANDLING,
                                     "out": str(out)}])
        return handling_values(out.read_text(encoding="utf-8-sig", errors="replace"), car)
    except (R.RpfError, OSError):
        return {}


def created_empty(session) -> set[str]:
    """dlc.rpf paths (lower case) the installer made empty because this game build has no such pack."""
    out = set()
    for step in session.log.active_steps():
        for n in step.notes:
            if n.startswith(CREATED_EMPTY):
                out.add(n[len(CREATED_EMPTY):].strip().lower())
    return out


def dlclist_items(game: Path, helper: list[str], tmp: Path) -> set[str] | None:
    """Pack folder names in the dlclist.xml the game uses (mods\\update\\update.rpf, else the game's own)."""
    for archive in (game / "mods" / "update" / "update.rpf", game / "update" / "update.rpf"):
        if not archive.is_file():
            continue
        out = tmp / "dlclist.xml"
        try:
            R.run_helper(helper, game, [{"op": "extract", "rpf": str(archive.resolve()), "entry": R.DLCLIST,
                                         "out": str(out)}])
        except (R.RpfError, OSError):
            continue
        text = out.read_text(encoding="utf-8-sig", errors="replace")
        return {m.group(1).lower() for m in re.finditer(r"dlcpacks:[/\\]([^/\\<\s]+)", text, re.I)}
    return None


def interior_specs(mod_ids, edition: str = "enhanced") -> list[dict]:
    """The installed mods' ``verify`` interior checks (kind "interior", in game): where the probe goes to look."""
    from .. import zerotouch

    out = []
    for mid in sorted(mod_ids):
        for c in zerotouch.verify_for(mid, edition):
            if c.get("kind") != "interior" or c.get("in") != "game":
                continue
            try:
                spec = {"name": str(c["name"]), "x": float(c["x"]), "y": float(c["y"]),
                        "zMin": float(c["zMin"]), "zMax": float(c["zMax"]), "mod": mid}
            except (KeyError, TypeError, ValueError):
                continue
            if spec["zMax"] >= spec["zMin"]:
                out.append(spec)
    return out


def make_plan(session, car: str = TEST_CAR) -> Plan:
    game = session.game_dir()
    installed = session.log.installed_mods()
    plan = Plan(car=car)
    helper = R.find_helper(session.state)
    if helper is None:
        plan.notes.append("The RPF helper isn't built (`leonida tools codewalker`), so the probe takes the DLC pack "
                          "names from the mod list and skips the handling check.")
    packs = installed_packs(session)
    edition = getattr(session.manifest, "edition", "enhanced") or "enhanced"
    with tempfile.TemporaryDirectory(prefix="leonida-probe-") as tmp:
        names = pack_names(game, helper, packs, Path(tmp), edition)
        plan.packs = {names[rel]: mod for mod, rel in packs}
        # packs the game won't load by design: made empty for a newer build's package, or not in this build at all
        # (no copy of the game's own and no dlclist.xml line: e.g. Bugstar Fixes' patch2026_01 on 1.0.1013.20)
        empty = created_empty(session)
        listed = dlclist_items(game, helper, Path(tmp)) if helper is not None else None
        for _mod, rel in packs:
            folder = PurePosixPath(rel).parent.name
            own = any((game / base / folder / "dlc.rpf").is_file() for base in ("update/x64/dlcpacks", "x64/dlcpacks"))
            if rel.lower() in empty:
                plan.expected_missing[names[rel]] = ("Leonida made this pack empty because this game build doesn't "
                                                     "have it (the package was written for a newer build)")
            elif not own and listed is not None and folder.lower() not in listed:
                plan.expected_missing[names[rel]] = ("this game build doesn't have this pack and no dlclist.xml line "
                                                     "loads it (a package written for a newer build)")
        plan.interiors = interior_specs(installed, edition)
        plan.handling_mod = next((m for m in DRIVEV if m in installed), None)
        if helper is not None and plan.handling_mod:
            plan.active = _read_handling(game, helper, game / "mods" / "update" / "update.rpf", Path(tmp), car)
            plan.vanilla = _read_handling(game, helper, game / "update" / "update.rpf", Path(tmp), car)
            if not plan.active:
                plan.notes.append(f"mods\\update\\update.rpf has no handling for {car}: the handling check only "
                                  "reports the values.")
    return plan


def render(plan: Plan) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    packs = ", ".join(json.dumps(p) for p in sorted(plan.packs))
    car = plan.car if re.fullmatch(r"[A-Za-z0-9_]*", plan.car or "") else ""
    stress = plan.stress if plan.stress in STRESS_MODES else ""
    minutes = max(0.0, min(float(plan.stress_minutes or 0), 120.0)) if stress else 0.0
    interiors = ", ".join(json.dumps("|".join([re.sub(r"[|\"\\\r\n]", " ", i["name"]),
                                                *(repr(float(i[k])) for k in ("x", "y", "zMin", "zMax"))]))
                          for i in plan.interiors)
    return (text.replace("/*PACKS*/", packs).replace("/*INTERIORS*/", interiors)
            .replace('"/*CAR*/"', json.dumps(car))
            .replace('"/*STRESS*/"', json.dumps(stress)).replace("/*STRESSMIN*/0", repr(minutes)))


# ------------------------------------------------------------------------------------------- placing / removing
def place(session, plan: Plan) -> Path:
    """Write the probe into scripts\\ (recorded first, so a crash can't leave it behind unnoticed)."""
    game = session.game_dir()
    target = game / "scripts" / PROBE_FILE
    record = session.state / RECORD
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"files": [f"scripts/{PROBE_FILE}", PROBE_LOG],
                                  "made_scripts_dir": not (game / "scripts").is_dir()}), encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    (game / PROBE_LOG).unlink(missing_ok=True)
    target.write_text(render(plan), encoding="utf-8")
    return target


def remove(session) -> list[str]:
    """Remove the probe and move its log to <state>/playtest/LeonidaProbe.log; returns what was removed."""
    game = session.game_dir()
    record = session.state / RECORD
    removed = []
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"files": [f"scripts/{PROBE_FILE}"], "made_scripts_dir": False}
    if game:
        probe = game / "scripts" / PROBE_FILE
        if probe.is_file():
            probe.unlink()
            removed.append(f"scripts/{PROBE_FILE}")
        log = game / PROBE_LOG
        if log.is_file():
            dest = session.state / "playtest" / PROBE_LOG
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.unlink(missing_ok=True)
            try:
                log.replace(dest)
                removed.append(PROBE_LOG)
            except OSError:
                pass  # the game still holds it open: it's overwritten by the next probe
        scripts = game / "scripts"
        if data.get("made_scripts_dir") and scripts.is_dir() and not any(scripts.iterdir()):
            scripts.rmdir()
    record.unlink(missing_ok=True)
    return removed


def read_log(session) -> str | None:
    game = session.game_dir()
    p = game / PROBE_LOG if game else None
    try:
        return p.read_text(encoding="utf-8", errors="replace") if p else None
    except OSError:
        return None


# ------------------------------------------------------------------------------------------- the log
def parse_log(text: str | None) -> ProbeLog:
    out = ProbeLog()
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln.startswith("START"):
            out.started = True
        elif ln.startswith("TICK "):
            out.last_tick = ln
            m = re.search(r"\bn=(\d+)", ln)
            out.ticks = max(out.ticks, int(m.group(1))) if m else out.ticks + 1
        elif ln.startswith("stage="):
            out.stages.append(ln)
        elif ln.startswith("dlc.") and "=" in ln:
            name, _, value = ln[4:].partition("=")
            out.dlc[name] = value.strip().lower() == "true"
        elif ln.startswith("handling.") and "=" in ln:
            name, _, value = ln[9:].partition("=")
            try:
                out.handling[name] = float(value)
            except ValueError:
                out.errors.append(ln)
        elif ln.startswith("interior.") and "=" in ln:
            m = re.match(r"interior\.(\d+)=(-?\d+)\s+ready=(\w+)", ln)
            if m:
                out.interiors[int(m.group(1))] = (int(m.group(2)), m.group(3).lower() == "true")
        elif ln.startswith("car_error="):
            out.car_error = ln.partition("=")[2]
        elif ln.startswith("probe_error"):
            if "ThreadAbortException" not in ln:  # the probe's own Abort() after DONE (older probes logged it)
                out.errors.append(ln)
        elif ln.startswith("gate_timeout"):
            out.gate_timeout = ln
        elif ln.startswith("stress "):
            out.stress.append(ln)
            if ln.startswith("stress done"):
                out.stress_done = ln[len("stress done"):].strip()
        elif ln.startswith("DONE"):
            out.done = ln[4:].strip()
        elif ln.startswith("ABORTED"):
            out.aborted = ln[7:].strip()
    return out


def diagnose(log: ProbeLog) -> str:
    """Why a probe didn't finish, from what it wrote."""
    if not log.started:
        return ("the probe never started: Script Hook V .NET didn't compile or load LeonidaProbe.3.cs (see "
                "ScriptHookVDotNet.log)")
    if log.aborted is not None:
        return f"the probe was stopped from outside ({log.aborted}): Script Hook V .NET aborted it"
    if not log.ticks:
        return ("the probe was loaded but never ticked: Script Hook V .NET didn't run its scripts' ticks (story "
                "mode still loading, or scripts paused)")
    if not log.stages:
        return f"the probe kept waiting for the player to have control; its last heartbeat: {log.last_tick}"
    return f"the probe stopped after {log.stages[-1]}; its last heartbeat: {log.last_tick}"


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE * max(1.0, abs(a), abs(b))


def _matches(got: dict[str, float], want: dict[str, float]) -> bool:
    """The car has these handling values (the DECISIVE fields that both sides have; at least one)."""
    keys = [f for f in DECISIVE if f in got and f in want]
    return bool(keys) and all(_same(got[f], want[f]) for f in keys)


def judge(log: ProbeLog, plan: Plan, finished_in_time: bool = True) -> list[VerifyResult]:
    """The probe's findings as verify results (mod = the mod they're about)."""
    res: list[VerifyResult] = []

    def r(status, code, message, mod="shvdne", line=None):
        res.append(VerifyResult(status, code, message, mod, PROBE_LOG, line))

    if not log.dlc and not log.handling and not log.interiors:
        why = diagnose(log)
        r(WARN, "probe-incomplete", f"In-game probe: no results, {why}.", line=log.last_tick)
        return res
    for name, mod in sorted(plan.packs.items()):
        if name not in log.dlc:
            r(WARN, "dlc-not-checked", f"In-game probe: DLC pack {name} wasn't checked.", mod)
        elif not log.dlc[name] and name in plan.expected_missing:
            r(NOT_SEEN, "dlc-not-on-build", f"In-game probe: DLC pack {name} isn't loaded, as expected: "
                                            f"{plan.expected_missing[name]}.", mod)
        elif log.dlc[name]:
            r(OK, "dlc-loaded", f"In-game probe: DLC pack {name} is loaded (IS_DLC_PRESENT).", mod)
        else:
            r(FAILED, "dlc-missing", f"In-game probe: DLC pack {name} is NOT loaded (IS_DLC_PRESENT is false). Is "
                                     f"its <Item>dlcpacks:/{name}/</Item> line in dlclist.xml?", mod)
    if plan.handling_mod:
        mod = plan.handling_mod
        got = log.handling
        if not got:
            r(WARN, "handling-not-read", f"In-game probe: the {plan.car} handling wasn't read"
                                         + (f" ({log.car_error})" if log.car_error else "") + ".", mod)
        elif plan.active and _matches(got, plan.active):
            same_as_game = plan.vanilla and _matches(got, plan.vanilla)
            r(OK, "handling-active", f"In-game probe: the {plan.car}'s handling is the one in "
                                     "mods\\update\\update.rpf" + (" (same as the game's own for these values)"
                                                                   if same_as_game else "") + ".", mod)
        elif plan.vanilla and _matches(got, plan.vanilla):
            r(FAILED, "handling-vanilla", f"In-game probe: the {plan.car} still has the game's own handling, not "
                                          "the one in mods\\update\\update.rpf: the handling mod isn't loaded.", mod)
        else:
            vals = ", ".join(f"{k}={v:g}" for k, v in sorted(got.items()))
            want = ", ".join(f"{k}={v:g}" for k, v in sorted(plan.active.items())) or "unknown"
            r(WARN, "handling-differs", f"In-game probe: the {plan.car}'s handling ({vals}) matches neither "
                                        f"mods\\update\\update.rpf ({want}) nor the game's own.", mod)
    for i, spec in enumerate(plan.interiors):
        where = f"({spec['x']:g}, {spec['y']:g})"
        if i not in log.interiors:
            r(WARN, "interior-not-checked", f"In-game probe: the {spec['name']} interior wasn't checked.", spec["mod"])
            continue
        iid, ready = log.interiors[i]
        if iid:
            r(OK, "interior-loaded", f"In-game probe: the {spec['name']} interior is there at {where} (interior "
                                     f"{iid}{', ready' if ready else ', still streaming'}).", spec["mod"])
        else:
            r(FAILED, "interior-missing", f"In-game probe: no interior at the {spec['name']} {where} between "
                                          f"z {spec['zMin']:g} and {spec['zMax']:g} (GET_INTERIOR_AT_COORDS is 0): its "
                                          "map files aren't loaded.", spec["mod"])
    if plan.stress:
        beats = [ln for ln in log.stress if ln.startswith("stress hb")]
        if log.stress_done is not None:
            r(OK, "stress-done", f"Stress test ({plan.stress}): done, {log.stress_done}; {len(beats)} heartbeat(s).",
              line=beats[-1] if beats else None)
        else:
            last = (beats[-1] if beats else (log.stress[-1] if log.stress else "it never started"))
            r(WARN, "stress-incomplete", f"Stress test ({plan.stress}) didn't finish; its last line: {last}.",
              line=last)
    for e in log.errors[:3]:
        r(WARN, "probe-error", f"In-game probe: {e}")
    if not finished_in_time and not log.finished:
        r(WARN, "probe-incomplete", f"In-game probe: didn't finish in time; {diagnose(log)}.", line=log.last_tick)
    return res
