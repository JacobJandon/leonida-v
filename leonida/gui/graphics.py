"""Settings > Graphics: GTA V's own settings Leonida sets (value and where it comes from: the pack, the variant, the
graphics card's tier or the tune on this PC), the measured video memory peak, "Tune for this PC" (leonida/tune.py in
the background: step, play test, video memory peak; stops after the running play test) and "Reset to recommended"
(the tuned values forgotten, the recommended ones written to settings.xml through the installer, logged)."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QFrame, QHBoxLayout, QMessageBox, QVBoxLayout

from .. import PACK_NAME
from . import widgets as W


def short_source(source: str) -> str:
    """"tuned on this PC (leonida settings tune)" -> "tuned on this PC"; "your graphics card (high tier, ...)" ->
    "GPU tier high"; "variant ram16" stays."""
    s = source or ""
    if s.startswith("tuned"):
        return "tuned on this PC"
    if s.startswith("your graphics card"):
        tier = s.split("(", 1)[1].split(" tier", 1)[0] if "(" in s else ""
        return f"GPU tier {tier}".strip()
    if s.startswith("your PC"):
        return "your PC"
    if s.startswith("pack"):
        return s.split(":", 1)[0] if s.startswith("pack:") else s
    return s or "Leonida"


def setting_name(key: str, rules: dict) -> str:
    label = (rules.get("keys", {}).get(key) or {}).get("label") or ""
    return label.split(":", 1)[0].strip() or key.rsplit("/", 1)[-1]


def wanted_values(session) -> tuple[list, bool]:
    """(the GTA settings for the pack, variant and this PC; whether Leonida writes them already). Leonida only writes
    them once it installed something (Session.game_settings); before that they are shown as what it will set."""
    from .. import gamesettings, tune
    from .. import settings as settings_mod

    game = session.game_settings()
    if game:
        return game, True
    pid = session.profile_id
    pack = session.base_manifest.packs.get(pid)
    variant = session.pack_choice().variant if pack else None
    return gamesettings.wanted(session.manifest.edition, pid, variant, set(session.selection_ids()),
                               session.pc_specs(), settings_mod.unlocked(session.state),
                               tuned=tune.load_tuned(session.state)), False


def measured_vram(state: Path) -> tuple[float | None, float | None, str]:
    """(peak video memory MB, the card's MB or None, where it was measured): the last play test, else the tune."""
    try:
        rep = json.loads((Path(state) / "playtest" / "last-report.json").read_text(encoding="utf-8"))
        peak = ((rep.get("memory") or {}).get("peak") or {})
        if peak.get("gpu_used_mb") is not None:
            return float(peak["gpu_used_mb"]), peak.get("gpu_total_mb"), f"the play test on {rep.get('when', '?')}"
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    from ..tune import TUNED_FILE

    try:
        data = json.loads((Path(state) / TUNED_FILE).read_text(encoding="utf-8"))
        runs = [r for r in data.get("runs", []) if r.get("vram_peak_mb") is not None]
        if runs:
            r = runs[-1]
            return float(r["vram_peak_mb"]), r.get("vram_total_mb"), f"the tune on {data.get('at', '?')}"
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return None, None, ""


def gb(mb: float | None) -> str:
    return "?" if mb is None else f"{mb / 1024:.1f} GB"


class GraphicsCard(QFrame):
    """The card. ``busy()``: why not now ("" = go), the Settings page's own check."""

    def __init__(self, win, busy: Callable[[], str]):
        super().__init__()
        self.win = win
        self.busy = busy
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(W._label("GRAPHICS", "eyebrow"))
        lay.addWidget(W._label("GTA V's own settings Leonida sets, and where each value comes from. The tune "
                               "raises them one at a time with a play test after each, and keeps what this PC "
                               "really runs.", "caption", wrap=True))
        self.values = W._label("", None, wrap=True)
        self.values.setObjectName("graphicsValues")
        lay.addWidget(self.values)
        self.vram = W._label("", "caption", wrap=True)
        lay.addWidget(self.vram)
        self.progress = W._label("", "caption", wrap=True)
        self.progress.hide()
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        self.tune_btn = W.button("Tune for this PC", "secondary", lambda: self.tune_or_stop())
        self.reset_btn = W.button("Reset to recommended", "ghost", lambda: self.reset())
        row.addWidget(self.tune_btn)
        row.addWidget(self.reset_btn)
        row.addStretch()
        lay.addLayout(row)
        self.running = False
        self._stop = False
        self._key = None

    # ---- what's shown
    def refresh(self, force: bool = False) -> None:
        from ..gamesettings import load_rules
        from ..tune import TUNED_FILE, load_tuned

        s = self.win.session
        state = Path(s.state)

        def mtime(p: Path):
            return p.stat().st_mtime_ns if p.is_file() else None

        key = (s.stamp(), mtime(state / TUNED_FILE), mtime(state / "playtest" / "last-report.json"), self.running)
        if key == self._key and not force:
            return
        self._key = key
        rules = load_rules()
        try:
            values, written = wanted_values(s)
        except Exception as exc:  # noqa: BLE001 - an unreadable PC or rules file: say so, never a broken page
            values, written = [], False
            self.values.setText(f"Couldn't work out the settings: {exc}")
        if values:
            lines = [f"{setting_name(w.key, rules)}: {w.value}  ·  {short_source(w.source)}" for w in values]
            self.values.setText("\n".join(lines) + ("" if written else "\n(Leonida sets these after your first "
                                                                          "install.)"))
            self.values.setToolTip("\n".join(f"{w.key} = {w.value}: {w.source}. {w.why}" for w in values))
        elif not self.values.text().startswith("Couldn't"):
            self.values.setText("No GTA V settings for this pack and PC.")
        peak, total, where = measured_vram(state)
        card = (s.pc_specs().vram_gb or 0) * 1024 or total
        self.vram.setText(f"Video memory peak: {gb(peak)}" + (f" of {gb(card)}" if card else "") + f", measured in "
                          f"{where}." if peak is not None else "Video memory peak: not measured yet (a play test or "
                          "the tune measures it).")
        tuned = load_tuned(state)
        self.reset_btn.setEnabled(bool(tuned) and not self.running)
        self.reset_btn.setToolTip(f"{len(tuned)} value(s) tuned on this PC" if tuned else "Nothing tuned yet")
        self.tune_btn.setText("Stop the tune" if self.running else "Tune for this PC")
        self.tune_btn.setEnabled(not (self.running and self._stop))

    # ---- the tune
    def tune_or_stop(self) -> bool:
        if self.running:
            self._stop = True
            self.progress.setText(self.progress.text() + "\nStopping after this play test …")
            self.tune_btn.setEnabled(False)
            return True
        return self.start_tune()

    def start_tune(self) -> bool:
        from .. import tune as T

        s = self.win.session
        why = self.busy()
        if why:
            QMessageBox.information(self, PACK_NAME, f"Not now: {why}. Try again when it's done.")
            return False
        if not s.game_dir():
            QMessageBox.information(self, PACK_NAME, "Set the game folder first.")
            return False
        current = {w.key: str(w.value) for w in s.game_settings()}
        if not current:
            QMessageBox.information(self, PACK_NAME, "Install your pack first: the tune starts from the values "
                                                     "Leonida set.")
            return False
        steps = sum(len(ups) for _k, _now, ups, _cost in T.plan(current))
        if not steps:
            QMessageBox.information(self, PACK_NAME, "Nothing left to raise: every setting is at its highest value "
                                                     "the tune tries.")
            return False
        ask = (f"The tune raises GTA V's settings one at a time and runs a play test after each: up to {steps} "
               f"step(s), 3–5 minutes each. GTA V starts and closes on its own, so save your game and don't play "
               "meanwhile. You can stop it after any play test; what was kept so far stays.\n\nStart the tune?")
        if QMessageBox.question(self, PACK_NAME, ask) != QMessageBox.StandardButton.Yes:
            return False
        from . import memcheck

        if not memcheck.confirm(self.win):
            return False
        from .workers import start_worker

        self.running, self._stop = True, False
        self._steps, self._step, self._what, self._run, self._peak = steps, 0, "", 0, None
        self.progress.setText(f"Starting the tune ({steps} step(s)) …")
        self.progress.show()
        self.refresh(force=True)

        def work(progress):
            from .. import playtest as P

            def run_test(sess):
                progress({"run": True})
                rep = P.playtest(sess)
                peak = ((getattr(rep, "memory", None) or {}).get("peak") or {}).get("gpu_used_mb")
                progress({"peak": peak, "status": getattr(rep, "status", "?")})
                return rep

            return T.tune(s, run_test=run_test, progress=lambda m: progress({"say": m}), stop=lambda: self._stop)

        start_worker(self, work, on_done=self._done, on_fail=self._failed, on_progress=self._on_progress,
                     pass_progress=True)
        return True

    def _on_progress(self, ev) -> None:
        if not isinstance(ev, dict):
            return
        say = ev.get("say")
        if say and "play test" in say:            # "TextureQuality = 2: 1 play test(s) ..."
            self._step += 1
            self._what, self._run = say.split(":", 1)[0], 0
        elif say:
            self._last = say
        if ev.get("run"):
            self._run += 1
        if "peak" in ev and ev["peak"] is not None:
            self._peak = ev["peak"]
        text = f"Step {self._step} of {self._steps}: {self._what}" if self._step else "Starting the tune …"
        if self._run:
            text += f"  ·  play test {self._run}"
        if self._peak is not None:
            text += f"  ·  video memory peak {gb(self._peak)}"
        if getattr(self, "_last", ""):
            text += f"\nLast: {self._last}"
        if self._stop:
            text += "\nStopping after this play test …"
        self.progress.setText(text)

    def _finish(self) -> None:
        self.running, self._last = False, ""
        self.refresh(force=True)

    def _done(self, runs) -> None:
        stopped = self._stop
        self._stop = False
        kept = [r for r in runs or [] if getattr(r, "kept", False)]
        self.progress.setText(("Tune stopped" if stopped else "Tune done") + f": {len(kept)} of {len(runs or [])} "
                              "step(s) kept." + "".join(f"\n  {r.key.rsplit('/', 1)[-1]} = {r.value}"
                                                         + ("" if r.kept else f" - not kept: {r.why}")
                                                         for r in runs or []))
        self.win.notify(f"{'Tune stopped' if stopped else 'Tune done'}: {len(kept)} setting step(s) kept on this PC.",
                        "success" if kept else "info")
        self._finish()

    def _failed(self, msg: str) -> None:
        self._stop = False
        self.progress.setText(f"The tune stopped: {msg}")
        QMessageBox.warning(self, PACK_NAME, f"The tune couldn't go on: {msg}")
        self._finish()

    # ---- back to the recommended values
    def reset(self) -> bool:
        from .. import tune as T

        s = self.win.session
        if self.running or not T.load_tuned(s.state):
            return False
        why = self.busy()
        if why:
            QMessageBox.information(self, PACK_NAME, f"Not now: {why}. Try again when it's done.")
            return False
        ask = ("Forget the values tuned on this PC and go back to the recommended ones (the pack, its variant and "
               "your graphics card's tier)? Leonida writes them to GTA V's settings now (a logged step you can undo).")
        if QMessageBox.question(self, PACK_NAME, ask) != QMessageBox.StandardButton.Yes:
            return False
        T.save_tuned(s.state, {})              # the measurements stay in the file's history
        try:
            lines = s.apply_game_settings(T._QuietUI())
        except Exception as exc:  # noqa: BLE001 - the values are forgotten either way; say what didn't get written
            QMessageBox.warning(self, PACK_NAME, f"The tuned values are forgotten, but writing GTA V's settings "
                                                 f"failed: {exc}")
            lines = []
        self.win.notify("Back to the recommended GTA V settings" + (" (written to settings.xml)." if lines else "."),
                        "success")
        self._key = None
        self.refresh(force=True)
        self.win.update_sidebar(force=True)
        return True
