"""The bridge between the in-game menu (LeonidaMenu, leonida/menu/) and Leonida. All files are in ``<state>/menu/``:

    menu-model.json      Leonida -> menu: what the menu shows (status, mods + locked settings, packs, GTA's
                         settings, keys, help), a heartbeat, and Leonida's answers to requests ("applied").
    menu-requests.json   menu -> Leonida: {"requests": [{"id", "kind", ...}]}. Only the menu writes it.
    menu-processed.json  Leonida's own record of each request it has handled (so nothing is applied twice).
    selftest.flag        `leonida playtest --deep`: the menu builds every page, writes selftest-report.json, closes.

The menu never edits a mod's files or the game folder; Leonida applies every request through the Installer /
settings engine, so it's logged and undoable like everything else:

    kind         fields                    when
    ping         -                         at once ("Leonida answered": the self-test's round trip)
    setting      mod, file, key, value     a pick among the key's ``choices``. At once while the game runs when it's
                                           safe live (a script's .ini in scripts\\: reload scripts to use it), else
                                           after the game closes
    unlock       mod, file, key, on        at once (a flag); locking again rewrites the value like ``setting``
    mod          mod, on                   after the game closes: switch off (roll back, keep the download) / on
    pack         pack                      after the game closes: the pack is chosen; Leonida's Install page adds or
                                           removes the mods that differ
    variant      variant                   after the game closes: chosen + its settings written
    report       -                         at once: a debug report on the Desktop (leonida/diagnostics.py)
    open_leonida -                         when the game closes, Leonida's window comes up (``want_window``)

``Bridge(session).tick(game_running)`` does one round: reads the requests, applies what it may now, writes the
model. The GUI calls it from a timer; ``leonida menu serve`` loops it; ``leonida menu apply`` runs once.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__
from . import settings as S

log = logging.getLogger(__name__)

MENU_ID = "leonidamenu"
MODEL = "menu-model.json"
REQUESTS = "menu-requests.json"
PROCESSED = "menu-processed.json"
SELFTEST_FLAG = "selftest.flag"
SELFTEST_REPORT = "selftest-report.json"
WANT_WINDOW = "open-leonida.flag"
SCHEMA = 1
KEEP_ANSWERS = 40
KINDS = ("ping", "setting", "unlock", "mod", "pack", "variant", "report", "open_leonida")
APPLIED, PENDING, REFUSED, FAILED = "applied", "pending", "refused", "failed"


def bridge_dir(state: Path) -> Path:
    return Path(state) / "menu"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_requests(state: Path) -> list[dict]:
    data = _read_json(bridge_dir(state) / REQUESTS)
    reqs = data.get("requests") if isinstance(data, dict) else None
    return [r for r in reqs or [] if isinstance(r, dict) and isinstance(r.get("id"), str)]


class _QuietUI:
    """The installer's questions answered without a person (the player is in the game): yes to the expected ones,
    messages to the log."""

    def info(self, msg: str) -> None:
        log.info("menu bridge: %s", msg)

    def warn(self, msg: str) -> None:
        log.warning("menu bridge: %s", msg)

    def confirm(self, msg: str, default: bool = True) -> bool:
        return default

    def wait_done(self, title: str, steps: list[str], folder: Path | None) -> bool:
        return False   # a guided step needs a person: not from the menu

    def launch(self, path: Path) -> None:
        log.info("menu bridge: not launching %s", path)


@dataclass
class Answer:
    id: str
    kind: str
    status: str
    message: str
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "message": self.message,
                "at": time.strftime("%H:%M:%S", time.localtime(self.at))}


# ------------------------------------------------------------------------------------------------- the model
def _raw_checks(session) -> dict[str, list[str]]:
    """mods.json "checks" (what to look for in game) by mod id."""
    from importlib import resources

    name = "mods-legacy.json" if getattr(session.manifest, "edition", "enhanced") == "legacy" else "mods.json"
    try:
        raw = json.loads(resources.files("leonida.manifest").joinpath(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {m["id"]: [c for c in m.get("checks", []) if isinstance(c, str)] for m in raw.get("mods", []) if "id" in m}


def _first_sentences(text: str, most: int = 280) -> str:
    """The start of a mod's notes, cut at a sentence end before ``most`` characters."""
    text = re.split(r"\s(?:Sources?|Game builds?|Older builds|Builds before)\b[^:]*:", text or "")[0].strip()
    if len(text) <= most:
        return text
    cut = text[:most]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > 80 else cut.rstrip() + "..."


def _is_live(mod, file: str) -> bool:
    """A value that may change while the game runs: a script's .ini in scripts\\ (read when scripts reload)."""
    p = PurePosixPath(file.replace("\\", "/"))
    return (p.parts[:1] == ("scripts",) and p.suffix.lower() == ".ini"
            and getattr(mod, "method", "") in ("copy", "generic"))


def _current_value(game: Path | None, file: str, fmt: str, key: str) -> str | None:
    if not game:
        return None
    path = Path(game) / PurePosixPath(file.replace("\\", "/"))
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        return S.get_value(text, fmt, key)
    except (OSError, S.SettingsError, ValueError):
        return None


def _settings_rows(session, mod, unlocked: set[str]) -> list[dict]:
    pack = session.base_manifest.packs.get(session.profile_id)
    variant = pack.variant(session.pack_choice().variant) if pack else None
    locked = {(w.file, w.key): w.value for w in session.settings_for(mod)}
    game = session.game_dir()
    rows = []
    for spec in getattr(mod, "settings", ()) or ():
        file, fmt = spec["file"], S.format_of(spec["file"], spec.get("format"))
        for key, rule in spec["keys"].items():
            value = locked.get((file, key))
            if value is None:
                value = S.rule_value(rule, session.profile_id, variant.id if variant else None,
                                     set(session.selection_ids()))
            current = _current_value(game, file, fmt, key)
            rows.append({
                "file": file, "key": key,
                "value": current if current is not None else S._text(value) if value is not None else "",
                "locked": S._text(value) if value is not None else "",
                "choices": [S._text(c) for c in S.rule_choices(rule)] if S.rule_choices(rule) else None,
                "unlocked": S.unlock_key(mod.id, file, key) in unlocked,
                "live": _is_live(mod, file),
                "why": rule.get("why", "") if isinstance(rule, dict) else "",
            })
    return rows


def _game_rows(session) -> dict:
    """GTA's own settings (settings.xml): Leonida's locked values for this pack / variant / PC, and what's there."""
    from . import playinfo

    out: dict = {"values": [], "preset": "", "note": ""}
    try:
        wanted = session.game_settings()
    except Exception:  # noqa: BLE001 - a broken rule file must not stop the menu's data
        log.debug("game settings unavailable", exc_info=True)
        wanted = []
    path = playinfo.settings_xml()
    text = None
    if path:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            text = None
    try:
        from . import gamesettings

        labels = {k: r.get("label", "") for k, r in gamesettings.load_rules().get("keys", {}).items()}
    except Exception:  # noqa: BLE001
        labels = {}
    for w in wanted:
        have = S.get_value(text, w.format, w.key) if text else None
        label = labels.get(w.key) or w.key.split("/")[-2 if w.key.endswith("@value") else -1]
        mark = "" if have is None or S.same(have, w.value) else f" (now {have})"
        out["values"].append({"name": label, "value": f"{S._text(w.value)}{mark}"})
    if wanted:
        pack = session.base_manifest.packs.get(session.profile_id)
        variant = pack.variant(session.pack_choice().variant) if pack else None
        out["preset"] = f"{pack.name if pack else session.profile_id}, {variant.name if variant else 'default'}"
        with contextlib.suppress(Exception):   # the PC facts are only extra words here
            out["preset"] += f" ({session.pc_specs().describe()})"
    out["note"] = ("Leonida writes GTA's settings after the game closes (GTA rewrites settings.xml when it exits). "
                   "Change one in GTA's own Settings and Leonida asks whether to keep it.") if wanted else \
        "Leonida sets GTA's graphics once a pack is installed."
    return out


def _status(session) -> dict:
    from . import playtest

    pack = session.base_manifest.packs.get(session.profile_id)
    choice = session.pack_choice()
    variant = pack.variant(choice.variant) if pack else None
    installed = session.log.installed_mods()
    selected = set(session.selection_ids())
    report = _read_json(Path(session.state) / "playtest" / "last-report.json") or {}
    last = ""
    if report:
        last = f"{str(report.get('status', '')).upper()} {report.get('when', '')}".strip()
        if report.get("story_mode_after"):
            last += f" (story mode after {report['story_mode_after']:.0f} s)"
    crash = ""
    try:
        newest = None
        for d in playtest.rockstar_crash_dirs():
            for p in d.glob("*.dmp"):
                if p.stat().st_size and (newest is None or p.stat().st_mtime > newest.stat().st_mtime):
                    newest = p
        if newest is not None and time.time() - newest.stat().st_mtime < 2 * 86400:
            from .minidump import read_minidump

            info = read_minidump(newest)
            when = time.strftime("%d %b %H:%M", time.localtime(newest.stat().st_mtime))
            crash = f"GTA crashed {when}" + (f" at {info.site}" if info and info.code is not None else "") + \
                ": Leonida's Manage page and `leonida report` have the details"
    except OSError:
        pass
    return {"pack": pack.name if pack else session.profile_id, "variant": variant.name if variant else "default",
            "build": session.game_version() or "unknown",
            "mods_on": f"{len(installed & selected)} of {len(selected)}", "last_playtest": last or "none yet",
            "crash": crash}


def _keys(session) -> list[dict]:
    from .checks import hotkey_map
    from .playinfo import key_label

    rows = []
    for key, users in sorted(hotkey_map(session.manifest, session.mods(), session.config.key_overrides).items()):
        names = [f"{session.manifest.mod(m).name}: {act}" for m, act in users]
        rows.append({"key": key, "label": key_label(key), "users": names, "clash": len({u[0] for u in users}) > 1})
    return rows


def _packs(session) -> dict:
    choice = session.pack_choice()
    out = {"current": choice.pack, "variant": choice.variant or "", "list": [],
           "note": "A switch happens after you quit the game; Leonida's Install page then adds or removes the mods "
                   "that differ (logged, undoable)."}
    for p in session.base_manifest.packs.values():
        out["list"].append({"id": p.id, "name": p.name,
                            "variants": [{"id": v.id, "name": v.name} for v in p.variants]})
    return out


def _reload_key(session) -> str:
    game = session.game_dir()
    if not game:
        return ""
    try:
        text = (Path(game) / "ScriptHookVDotNet.ini").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    return (S.ini_get(text, "ReloadKeyBinding") or "").strip()


def build_model(session, answers: list[dict] | None = None) -> dict:
    """Everything the menu shows, as plain JSON (the menu's own small reader handles it)."""
    installed = session.log.installed_mods()
    selected = set(session.selection_ids())
    unlocked = S.unlocked(session.state)
    checks = _raw_checks(session)
    mods = []
    for m in sorted(session.mods(), key=lambda m: (m.order, m.name)):
        on = m.id in installed
        mods.append({
            "id": m.id, "name": m.name, "on": on, "selected": m.id in selected,
            "disabled": m.id in session.config.disabled,
            "can_toggle": m.id != MENU_ID and (on or m.id in session.config.disabled),
            "what": _first_sentences(m.notes), "help": " ".join(checks.get(m.id, [])),
            "settings": _settings_rows(session, m, unlocked),
        })
    return {"schema": SCHEMA, "leonida": __version__, "heartbeat": round(time.time(), 1),
            "written": time.strftime("%Y-%m-%d %H:%M:%S"), "reload_key": _reload_key(session),
            "status": _status(session), "mods": mods, "packs": _packs(session), "game": _game_rows(session),
            "keys": _keys(session), "applied": answers or []}


# ------------------------------------------------------------------------------------------------ requests
class Bridge:
    """One Leonida-side endpoint of the bridge (see the module docstring)."""

    def __init__(self, session, ui=None, now: Callable[[], float] = time.time):
        self.s = session
        self.ui = ui or _QuietUI()
        self.now = now
        self.dir = bridge_dir(session.state)
        self._done: dict[str, dict] | None = None

    # -- the record of handled requests
    @property
    def done(self) -> dict[str, dict]:
        if self._done is None:
            data = _read_json(self.dir / PROCESSED)
            self._done = data if isinstance(data, dict) else {}
        return self._done

    def _save_done(self) -> None:
        if len(self._done or {}) > 200:   # keep the newest
            keep = sorted(self._done.items(), key=lambda kv: kv[1].get("t", 0))[-200:]
            self._done = dict(keep)
        _write_json(self.dir / PROCESSED, self._done)

    def answers(self) -> list[dict]:
        rows = sorted(self.done.items(), key=lambda kv: kv[1].get("t", 0), reverse=True)[:KEEP_ANSWERS]
        return [{"id": k, **{x: v.get(x, "") for x in ("kind", "status", "message", "at")}} for k, v in rows]

    def _answer(self, req: dict, status: str, message: str) -> Answer:
        a = Answer(req["id"], str(req.get("kind", "")), status, message, self.now())
        self.done[req["id"]] = {**a.as_dict(), "t": a.at}
        log.info("menu request %s (%s): %s: %s", a.id, a.kind, status, message)
        return a

    # -- one round
    def tick(self, game_running: bool) -> list[Answer]:
        """Handle the requests that may be handled now, then write the model. Returns this round's answers."""
        out = []
        for req in read_requests(self.s.state):
            prev = self.done.get(req["id"])
            if prev and prev.get("status") != PENDING:
                continue
            try:
                a = self.handle(req, game_running)
            except Exception as exc:  # noqa: BLE001 - one bad request must not stop the others
                log.exception("menu request %s failed", req.get("id"))
                a = self._answer(req, FAILED, f"{type(exc).__name__}: {exc}")
            if a is not None and (not prev or prev.get("status") != a.status or prev.get("message") != a.message):
                out.append(a)
        if out:
            self._save_done()
        self.write_model()
        return out

    def poll(self, game_running: bool, heartbeat: float = 15.0) -> list[Answer]:
        """The launcher's timer: a full ``tick`` when the menu wrote requests, when the game has just closed, or
        when requests wait for a closed game; else only a fresh model every ``heartbeat`` seconds."""
        try:
            mtime = (self.dir / REQUESTS).stat().st_mtime_ns
        except OSError:
            mtime = None
        ended = getattr(self, "_was_running", False) and not game_running
        self._was_running = game_running
        waiting = not game_running and any(v.get("status") == PENDING for v in self.done.values())
        if mtime != getattr(self, "_seen_requests", None) or ended or waiting:
            self._seen_requests = mtime
            return self.tick(game_running)
        if self.now() - getattr(self, "_model_at", 0.0) >= heartbeat:
            self.write_model()
        return []

    def tick_if_changed(self, game_running: bool) -> list[Answer]:
        """``tick`` only when the menu wrote new requests (cheap enough for a play test's poll loop)."""
        try:
            mtime = (self.dir / REQUESTS).stat().st_mtime_ns
        except OSError:
            return []
        if mtime == getattr(self, "_seen_requests", None):
            return []
        self._seen_requests = mtime
        return self.tick(game_running)

    def write_model(self) -> Path:
        path = self.dir / MODEL
        try:
            model = build_model(self.s, self.answers())
        except Exception as exc:  # noqa: BLE001 - the menu still gets the heartbeat and the answers
            log.exception("menu model failed")
            model = {"schema": SCHEMA, "leonida": __version__, "heartbeat": round(time.time(), 1),
                     "status": {"pack": "?", "crash": f"Leonida couldn't read its data: {exc}"},
                     "applied": self.answers()}
        _write_json(path, model)
        self._model_at = self.now()
        return path

    # -- the kinds
    def handle(self, req: dict, game_running: bool) -> Answer | None:
        kind = req.get("kind")
        if kind not in KINDS:
            return self._answer(req, REFUSED, f"Leonida doesn't know the request {kind!r}")
        return getattr(self, f"_do_{kind}")(req, game_running)

    def _later(self, req: dict, what: str) -> Answer:
        return self._answer(req, PENDING, f"{what}: after you quit the game")

    def _do_ping(self, req, game_running):
        return self._answer(req, APPLIED, f"Leonida {__version__} answered")

    def _find_rule(self, mod_id: str, file: str, key: str):
        mod = self.s.manifest.mods.get(mod_id)
        if mod is None:
            return None, None
        for spec in getattr(mod, "settings", ()) or ():
            if spec["file"] == file and key in spec["keys"]:
                return mod, spec["keys"][key]
        return mod, None

    def _apply_settings(self) -> str:
        changed = self.s.apply_settings(self.ui)
        return "; ".join(changed[:3]) if changed else "nothing to change"

    def _do_setting(self, req, game_running):
        mod_id, file, key, value = req.get("mod"), req.get("file"), req.get("key"), req.get("value")
        mod, rule = self._find_rule(str(mod_id), str(file), str(key))
        if rule is None:
            return self._answer(req, REFUSED, f"{mod_id}: no locked setting {file} {key}")
        choices = S.rule_choices(rule)
        if not choices or not any(S.same(value, c) for c in choices):
            return self._answer(req, REFUSED, f"{key} can be {', '.join(map(str, choices))}" if choices else
                                f"{key} is locked; unlock it to keep your own value")
        live = mod is not None and _is_live(mod, str(file))
        if game_running and not live:
            if req["id"] not in self.done:
                S.set_chosen(self.s.state, str(mod_id), str(file), str(key), value)
            return self._later(req, f"{key} = {value}")
        S.set_chosen(self.s.state, str(mod_id), str(file), str(key), value)
        self._apply_settings()
        hint = " Reload scripts (Tools) to use it." if game_running else ""
        return self._answer(req, APPLIED, f"{key} = {value} written to {file}.{hint}")

    def _do_unlock(self, req, game_running):
        mod_id, file, key, on = req.get("mod"), req.get("file"), req.get("key"), bool(req.get("on"))
        mod, rule = self._find_rule(str(mod_id), str(file), str(key))
        if rule is None:
            return self._answer(req, REFUSED, f"{mod_id}: no locked setting {file} {key}")
        if on:
            S.set_unlocked(self.s.state, str(mod_id), str(file), str(key), True)
            return self._answer(req, APPLIED, f"{key} unlocked: Leonida leaves your value in {file}")
        live = mod is not None and _is_live(mod, str(file))
        if game_running and not live:
            return self._later(req, f"locking {key} again")
        S.set_unlocked(self.s.state, str(mod_id), str(file), str(key), False)
        self._apply_settings()
        return self._answer(req, APPLIED, f"{key} locked again and written to {file}")

    def _do_mod(self, req, game_running):
        mod_id, on = str(req.get("mod")), bool(req.get("on"))
        mod = self.s.manifest.mods.get(mod_id)
        if mod is None or mod_id == MENU_ID:
            return self._answer(req, REFUSED, f"{mod_id} can't be switched from the menu")
        if game_running:
            return self._later(req, f"switching {mod.name} {'on' if on else 'off'}")
        if on:
            msgs = self.s.enable_mod(mod_id, self.ui)
        else:
            done, notes = self.s.disable_mod(mod_id, self.ui)
            msgs = [*done, *notes]
        return self._answer(req, APPLIED, f"{mod.name} switched {'on' if on else 'off'}" +
                            (f" ({'; '.join(map(str, msgs[:2]))})" if msgs else ""))

    def _do_pack(self, req, game_running):
        pack_id = str(req.get("pack"))
        pack = self.s.base_manifest.packs.get(pack_id)
        if pack is None:
            return self._answer(req, REFUSED, f"no pack {pack_id!r}")
        if game_running:
            return self._later(req, f"switching to {pack.name}")
        self.s.choose_pack(pack_id)
        return self._answer(req, APPLIED, f"{pack.name} chosen: open Leonida's Install page to add or remove the "
                                          "mods that differ")

    def _do_variant(self, req, game_running):
        choice = self.s.pack_choice()
        pack = self.s.base_manifest.packs.get(choice.pack)
        variant = pack.variant(str(req.get("variant"))) if pack else None
        if variant is None:
            return self._answer(req, REFUSED, f"no variant {req.get('variant')!r} in this pack")
        if game_running:
            return self._later(req, f"switching to {variant.name}")
        self.s.choose_pack(choice.pack, choice.addons, variant.id)
        self._apply_settings()
        return self._answer(req, APPLIED, f"{variant.name}: its settings are written. If its mods differ, Leonida's "
                                          "Install page adds or removes them")

    def _do_report(self, req, game_running):
        from . import diagnostics

        path = diagnostics.build(self.s)
        return self._answer(req, APPLIED, f"report saved: {path.name} (Desktop)")

    def _do_open_leonida(self, req, game_running):
        if game_running:
            return self._later(req, "opening Leonida")
        (self.dir / WANT_WINDOW).parent.mkdir(parents=True, exist_ok=True)
        (self.dir / WANT_WINDOW).write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        return self._answer(req, APPLIED, "Leonida opened")


def want_window(state: Path, clear: bool = True) -> bool:
    """True once when the menu asked for Leonida's window after the game closed (the GUI raises itself)."""
    flag = bridge_dir(state) / WANT_WINDOW
    if not flag.is_file():
        return False
    if clear:
        flag.unlink(missing_ok=True)
    return True


def game_running() -> bool:
    from . import gamestate

    try:
        return bool(gamestate.running())
    except Exception:  # noqa: BLE001
        return False


def serve(session, interval: float = 2.0, stop: Callable[[], bool] | None = None, say=print,
          sleep: Callable[[float], None] = time.sleep, running: Callable[[], bool] = game_running) -> int:
    """`leonida menu serve`: answer the menu until ``stop()`` (Ctrl+C on the command line)."""
    bridge = Bridge(session)
    rounds = 0
    try:
        while not (stop and stop()):
            for a in bridge.poll(running()):
                say(f"{a.kind}: {a.status}: {a.message}")
            rounds += 1
            sleep(interval)
    except KeyboardInterrupt:
        pass
    return rounds


# ------------------------------------------------------------------------------------------------ self-test
def request_selftest(state: Path) -> Path:
    """Ask the menu to test itself on its next start (playtest --deep). Removes an old report."""
    d = bridge_dir(state)
    d.mkdir(parents=True, exist_ok=True)
    (d / SELFTEST_REPORT).unlink(missing_ok=True)
    flag = d / SELFTEST_FLAG
    flag.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    return flag


def cancel_selftest(state: Path) -> None:
    (bridge_dir(state) / SELFTEST_FLAG).unlink(missing_ok=True)


def read_selftest(state: Path) -> dict | None:
    data = _read_json(bridge_dir(state) / SELFTEST_REPORT)
    return data if isinstance(data, dict) else None


EXPECTED_PAGES = ("Status", "Mods", "Pack & variant", "Game settings", "Keys", "Help", "Tools")


def judge_selftest(report: dict | None) -> list[tuple[str, str]]:
    """[(status, message)] for the play test: ok / failed per check of the menu's self-test report."""
    if not report:
        return [("failed", "LeonidaMenu wrote no self-test report: it didn't load (check ScriptHookVDotNet.log "
                           "for LeonidaMenu) or the game closed first")]
    out = []
    pages = report.get("pages") or {}
    missing = [p for p in EXPECTED_PAGES if p not in pages]
    out.append(("ok" if not missing else "failed",
                "LeonidaMenu built every page" if not missing else f"LeonidaMenu didn't build: {', '.join(missing)}"))
    out.append(("ok" if report.get("model") else "failed",
                "LeonidaMenu read Leonida's menu data" if report.get("model") else
                "LeonidaMenu found no menu data (scripts\\LeonidaMenu.ini StateDir?)"))
    answer = str(report.get("ping_answer") or "")
    out.append(("ok" if answer.startswith(APPLIED) else "failed",
                "LeonidaMenu and Leonida talk both ways (request answered)" if answer.startswith(APPLIED) else
                "LeonidaMenu's request got no answer from Leonida"))
    errors = report.get("errors") or []
    if errors:
        out.append(("failed", f"LeonidaMenu errors: {'; '.join(map(str, errors[:3]))}"))
    out.append(("info", f"LeonidaMenu {report.get('menu', '?')}: open with {report.get('key', '?')}, phone: "
                        f"{report.get('phone', '?')}"))
    return out
