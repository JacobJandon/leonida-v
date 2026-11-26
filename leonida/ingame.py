"""Zero-touch in game (plan F8): the Leonida menu's side of the mods' ``inGameSetup`` and ``verify`` data.

The data and its schema are leonida/zerotouch.py's (``verify`` with ``in: files | game``, ``inGameSetup`` with
``action`` / ``when`` / ``verify`` / ``why`` / ``onFail``). This module connects it to the game:

    model_setup(session)    the menu model's "setup" list: per installed, switched-on mod with inGameSetup, its
                            actions and its install stamp (a new stamp = installed or updated again)
    model_checks(session)   the menu model's "checks" list: per installed mod, its ``in: game`` verify entries
                            plus the ``in: files`` ones the menu can read itself (asi / script / file / log)
    record_setup(state, r)  a "setup" request from the menu -> <state>/ingame/setup.json
    judge(report, ...)      after `playtest --deep`: the menu's in-game checks (in its self-test report) and
                            zerotouch.check_files -> verify results, and per mod "on and checked in game"
                            (<state>/ingame/checked.json), shown on the launcher's Manage page

What the menu does with the data (leonida/menu/LeonidaMenu.cs):
    when "first-load"    once per install stamp, after the player has control
    when "verify-fails"  every game start: check ``verify`` (a log: within ``withinSeconds`` of the player having
                         control, default 15 s), and only if it fails do the action, once per game start; after a
                         reload-scripts it checks again and shows ``onFail`` if it still fails
    action "reload-scripts"  press Script Hook V .NET's own reload key (ReloadKeyBinding)
    action "check"           check ``verify``; show ``onFail`` (a GTA feed notification) when it fails
Only public natives and the mods' documented hooks; the in-game checks are read-only (IS_DLC_PRESENT,
IS_IPL_ACTIVE, no-argument GET_/IS_/HAS_ natives).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import zerotouch as Z

SETUP_FILE = Path("ingame") / "setup.json"
CHECKED_FILE = Path("ingame") / "checked.json"
MENU_READABLE = ("dlc", "ipl", "native", "asi", "script", "file", "log")   # what LeonidaMenu can check itself
NATIVE_PREFIXES = ("GET_", "IS_", "HAS_")
ON, NOT_CONFIRMED = "on and checked in game", "not confirmed in game"


def stamp(session, mod_id: str) -> str:
    """Changes whenever the mod is installed or updated again (its newest done step)."""
    steps = [s for s in session.log.steps if s.mod == mod_id and s.status == "done"]
    return f"{steps[-1].id}:{steps[-1].finished or steps[-1].started}" if steps else ""


def _live_mods(session) -> list:
    installed = session.log.installed_mods()
    disabled = set(getattr(session.config, "disabled", ()) or ())
    return [m for m in sorted(session.mods(), key=lambda m: (m.order, m.name))
            if m.id in installed and m.id not in disabled]


def _menu_check(c: dict) -> bool:
    if c.get("kind") not in MENU_READABLE:
        return False
    if c["kind"] == "native":
        return str(c.get("name", "")).startswith(NATIVE_PREFIXES)
    if c["kind"] == "log":
        return bool(c.get("file"))
    return True


def model_setup(session) -> list[dict]:
    out = []
    for m in _live_mods(session):
        actions = [a for a in Z.in_game_setup(m.id, session.edition) if isinstance(a, dict)]
        if actions:
            out.append({"mod": m.id, "name": m.name, "stamp": stamp(session, m.id), "actions": actions})
    return out


def model_checks(session) -> list[dict]:
    out = []
    for m in _live_mods(session):
        checks = [c for c in Z.verify_for(m.id, session.edition) if _menu_check(c)]
        if checks:
            out.append({"mod": m.id, "name": m.name, "verify": checks})
    return out


def record_setup(state: Path, req: dict, now: float | None = None) -> str:
    """A "setup" request from the menu: keep the newest run per mod. Returns the answer's message."""
    mod = str(req.get("mod", ""))
    results = [r for r in (req.get("results") if isinstance(req.get("results"), list) else []) if isinstance(r, dict)]
    data = _read(Path(state) / SETUP_FILE)
    data[mod] = {"at": now if now is not None else time.time(), "stamp": str(req.get("stamp", "")),
                 "results": [{k: r.get(k, "") for k in ("action", "ok", "message")} for r in results]}
    _write(Path(state) / SETUP_FILE, data)
    bad = [r for r in data[mod]["results"] if r["ok"] is not True]
    done = len(results) - len(bad)
    return (f"in-game setup of {mod}: {done}/{len(results)} ok" + (f" ({bad[0]['message']})" if bad else ""))


def setup_results(state: Path) -> dict[str, dict]:
    return _read(Path(state) / SETUP_FILE)


# ------------------------------------------------------------------------------------------- the play test
def judge(session, report: dict | None, since: float | None, now: float | None = None):
    """Verify results for the deep play test: the menu's in-game checks plus the files proofs. Saves each mod's
    "on and checked in game" state. Returns (results, per-mod state)."""
    from .verify import FAILED, NOT_SEEN, OK, VerifyResult

    res: list[VerifyResult] = []
    mods = _live_mods(session)
    ids = {m.id for m in mods}
    ingame = (report or {}).get("ingame") if isinstance(report, dict) else None
    ingame = ingame if isinstance(ingame, dict) else {}
    told: dict[str, list[bool]] = {}
    for mod, checks in sorted(ingame.items()):
        if mod not in ids or not isinstance(checks, list):
            continue
        for c in checks:
            if not isinstance(c, dict):
                continue
            ok = c.get("ok")
            what = c.get("what") or c.get("kind", "?")
            if ok is True:
                res.append(VerifyResult(OK, "ingame-ok", f"In game: {what}.", mod, "menu"))
            elif ok is False:
                res.append(VerifyResult(FAILED, "ingame-failed", f"In game: {what}: {c.get('detail') or 'no'}.",
                                        mod, "menu"))
            else:
                res.append(VerifyResult(NOT_SEEN, "ingame-skipped", f"In game: {what}: {c.get('detail', '')}.",
                                        mod, "menu"))
                continue
            told.setdefault(mod, []).append(ok is True)
    for p in Z.check_files(session.game_dir(), mods, session.edition, since):
        if p.ok is None or p.check.get("in") == "game":
            continue
        desc = Z.describe(p.check)
        if p.ok:
            res.append(VerifyResult(OK, "files-ok", f"After the game start: {desc}.", p.mod))
        else:
            res.append(VerifyResult(FAILED, "files-failed", f"After the game start: {p.detail or desc}.", p.mod))
        told.setdefault(p.mod, []).append(bool(p.ok))
    state = save_checked(session.state, res, told, now)
    return res, state


def save_checked(state: Path, results, told: dict[str, list[bool]], now: float | None = None) -> dict[str, dict]:
    data = _read(Path(state) / CHECKED_FILE)
    at = now if now is not None else time.time()
    for mod, oks in told.items():
        msgs = [r.message for r in results if r.mod == mod and r.code.startswith(("ingame-", "files-"))]
        bad = [r.message for r in results if r.mod == mod and r.code in ("ingame-failed", "files-failed")]
        data[mod] = {"ok": bool(oks) and all(oks), "at": at, "checks": msgs[:12], "failed": bad[:6]}
    _write(Path(state) / CHECKED_FILE, data)
    return data


def checked(state: Path) -> dict[str, dict]:
    return _read(Path(state) / CHECKED_FILE)


def checked_line(state: Path, mod_id: str, rec: dict | None = None) -> tuple[str, str] | None:
    """(label, tooltip) for the launcher; None when no deep play test has checked the mod yet. ``rec``: the mod's
    record from ``checked`` when the caller already read it."""
    rec = rec if rec is not None else checked(state).get(mod_id)
    if not rec:
        return None
    when = time.strftime("%d %b %H:%M", time.localtime(rec.get("at", 0)))
    if rec.get("ok"):
        return ON, f"Checked by the play test on {when}:\n" + "\n".join(rec.get("checks") or [])
    return NOT_CONFIRMED, f"Play test on {when}:\n" + "\n".join(rec.get("failed") or rec.get("checks") or [])


def _read(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
