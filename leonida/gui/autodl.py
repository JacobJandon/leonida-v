"""Drive Leonida's browser through the missing mods, one after another, as far as the rules allow.

For each mod the AutoDownloader opens the right page in the (visible) browser window, finds the right file and
points at it, waits while the user signs in where a site needs it, notices the download, checks the file with the
matcher (name + ``requireMembers``/``rejectMembers``) and goes on with the next mod by itself.

What it does by itself, per site (the repo rule: a GitHub release or a direct link the author publishes may be
fetched; on every other page the user clicks Download; download gates, ads, logins, Patreon and Discord stay manual):
  * dev-c.com, github.com: follows the download link on the page (``PageHint.may_auto_follow``)
  * gta5-mods.com: outlines the version the mod's ``pick`` hint names (or the main Download button); the user clicks
    (so the mod page is the Referer). The current version then starts after the site's countdown; an older version
    shows a direct files.gta5-mods.com/uploads/ link after the countdown, which Leonida outlines for the user
  * nexusmods.com: opens the files tab, picks the Main file whose name fits ``archive``, outlines its button, and
    when the button says "Log in to download" emits ``need_login("nexusmods.com")`` and waits for the sign-in;
    after the user's click it outlines the "Slow download" button
  * razedmods.com and anything else: outlines what pagehints knows and waits for the user's click
  * Patreon / shop / Discord / paid mods: skipped with the reason (``mod_failed``)
It never types into a page (no credentials), never clicks a site's download button, never skips a countdown.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from .. import pagehints as H
from ..members import wrong_message

MANUAL_SOURCES = ("patreon", "shop", "discord")
LOGIN_SITES = ("nexusmods.com",)

# Outline a button/link whose text contains one of ``texts`` (searching open shadow roots too). Never clicks.
_TEXT_BUTTON_JS = r"""(function (texts) {
  function deep(root) {
    var out = Array.prototype.slice.call(root.querySelectorAll('button, a, [role="button"]'));
    root.querySelectorAll('*').forEach(function (e) { if (e.shadowRoot) { out = out.concat(deep(e.shadowRoot)); } });
    return out;
  }
  var els = deep(document);
  for (var i = 0; i < els.length; i++) {
    var t = (els[i].innerText || els[i].textContent || '').trim().toLowerCase();
    for (var j = 0; j < texts.length; j++) {
      if (t.indexOf(texts[j]) !== -1) {
        els[i].style.outline = '3px solid #ff2d95';
        els[i].style.outlineOffset = '3px';
        els[i].scrollIntoView({block: 'center'});
        return JSON.stringify({found: true, text: t});
      }
    }
  }
  return JSON.stringify({found: false, text: ''});
})"""


def text_button_script(texts: list[str]) -> str:
    return _TEXT_BUTTON_JS + "(" + json.dumps([t.lower() for t in texts]) + ");"


def manual_reason(mod) -> str | None:
    """Why the AutoDownloader leaves this mod to the user (None = it can help)."""
    if getattr(mod, "is_paid", False):
        return f"{mod.name} is paid: get it yourself from {mod.page} (Leonida never uses re-uploaded copies)."
    if mod.source in MANUAL_SOURCES:
        return f"{mod.name} comes from {mod.source}: get it yourself from {mod.page}."
    return None


class AutoDownloader(QObject):
    status = Signal(str)                 # one line for the user
    need_login = Signal(str)             # site the user has to sign in to in the browser window
    mod_status = Signal(str, str)        # mod id, short per-row status ("sign in", "click Download", "downloading")
    mod_done = Signal(str, str)          # mod id, path of the verified file
    mod_failed = Signal(str, str)        # mod id, reason
    finished = Signal()

    def __init__(self, browser, session, mods: list, *, hints: Callable[[str], H.PageHint | None] = H.hint_for,
                 poll_ms: int = 1500, idle_timeout: float = 900.0, parent: QObject | None = None):
        super().__init__(parent)
        self.browser, self.session = browser, session
        self.queue = list(mods)
        self.hints = hints
        self.idle_timeout = idle_timeout
        self.current = None
        self.running = False
        self._downloading = False
        self._login_wait = False
        self._followed: set[str] = set()
        self._opened_at = 0.0
        # the shared window may still show (or finish loading) the previous mod's page: don't act on that one
        self._prev_url = ""
        self._start = ""
        self.results: dict[str, tuple[str, str]] = {}   # mod id -> ("done", path) | ("failed", reason)
        self.timer = QTimer(self)
        self.timer.setInterval(poll_ms)
        self.timer.timeout.connect(self._tick)
        self._links = [(browser.view.loadFinished, self._loaded),
                       (browser.download_started, self._started),
                       (browser.file_saved, self._saved), (browser.file_failed, self._failed_download)]
        for signal, slot in self._links:
            signal.connect(slot)

    def _detach(self) -> None:
        """Let go of the (shared, long-lived) browser window."""
        for signal, slot in self._links:
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect(slot)
        self._links = []

    # ---- control --------------------------------------------------------------------------------------------
    def start(self) -> None:
        self.running = True
        self.browser.set_queue([])
        self.browser.show()
        self._next()

    def stop(self) -> None:
        """Stop after the current page (a running download still lands in the folder)."""
        self.timer.stop()
        if self.running:
            self.running = False
            self.current = None
            self._detach()
            self.status.emit("Stopped.")
            self.finished.emit()

    def skip(self) -> None:
        if self.current is not None and not self._downloading:
            self._fail("skipped")

    # ---- per mod --------------------------------------------------------------------------------------------
    def _next(self) -> None:
        self.timer.stop()
        self.current, self._downloading, self._login_wait, self._followed = None, False, False, set()
        if not self.running:
            return
        while self.queue:
            mod = self.queue.pop(0)
            reason = manual_reason(mod)
            if reason:
                self._record(mod.id, "failed", reason)
                continue
            existing = self.session.matches([mod]).matched.get(mod.id)
            if existing is not None:
                self._record(mod.id, "done", str(existing))
                continue
            self._open(mod)
            return
        self.running = False
        self._detach()
        self.status.emit("Every mod has been tried.")
        self.finished.emit()

    def _start_url(self, mod) -> str:
        hint = self.hints(mod.page)
        if hint is None:
            return mod.page
        if hint.site == "nexusmods.com" and "tab=files" not in mod.page:
            return mod.page.split("#")[0].rstrip("/") + ("&" if "?" in mod.page else "?") + "tab=files"
        return hint.start_url(mod.page)

    def _open(self, mod) -> None:
        self.current = mod
        self._opened_at = time.monotonic()
        hint = self.hints(mod.page)
        site = hint.site if hint else "the author's page"
        self.mod_status.emit(mod.id, "opening")
        self.status.emit(f"{mod.name}: opening {site} ...")
        self._prev_url, self._start = self._url(), QUrl(self._start_url(mod)).toString()
        title = (f"<b>{mod.name}</b>: Leonida finds the right file on this page and points at it. Sign in if the "
                 f"site asks; the download goes to <b>{self.browser.download_dir}</b> and is checked automatically.")
        self.browser.open_mod(mod, self._start, title)
        self.timer.start()

    # ---- looking at the page ----------------------------------------------------------------------------------
    def _stale(self) -> bool:
        """True while the window still shows the previous mod's (different) page."""
        url = self._url()
        return bool(self._prev_url) and url == self._prev_url and url != self._start

    def _loaded(self, ok: bool) -> None:
        if self.current is not None and not self._downloading and not self._stale():
            self._look()

    def _tick(self) -> None:
        if self.current is None or self._downloading:
            return
        if not self._login_wait and time.monotonic() - self._opened_at > self.idle_timeout:
            self._fail(f"no download started within {self.idle_timeout / 60:.0f} min")
            return
        if not self._stale():
            self._look()

    def _url(self) -> str:
        return self.browser.view.url().toString()

    def _run(self, script: str | None, then) -> None:
        if script and self.browser.page is not None:
            self.browser.page.runJavaScript(script, 0, then)

    def _look(self) -> None:
        mod, url = self.current, self._url()
        hint = self.hints(url)
        if "users.nexusmods.com" in url:
            self._ask_login("nexusmods.com")
            return
        if hint is None:
            self._say("click the author's Download button")
            return
        if hint.site == "nexusmods.com":
            self._look_nexus(mod, url, hint)
        elif hint.site == "gta5-mods.com":
            self._look_gta5mods(mod, url, hint)
        elif hint.may_auto_follow(url):
            self.browser.page.toHtml(lambda html, url=url: self._follow(mod, url, html))
        else:
            self._run(H.highlight_script(url, hint=hint), lambda _r: None)
            step = hint.step_for(url)
            self._say(step.label if step else "click the author's Download button")

    def _follow(self, mod, url: str, html: str) -> None:
        if mod is not self.current or self._downloading:
            return
        target = H.choose(H.find_links(url, html, self.hints(url)), mod.archive)
        if target and target not in self._followed:
            hint = self.hints(url)
            step = hint.step_for(url) if hint else None
            if step is not None and step.accepts(target):  # only ever a link the hint expects
                self._followed.add(target)
                self.mod_status.emit(mod.id, "following the download link")
                self.status.emit(f"{mod.name}: following {target}")
                self.browser.view.load(QUrl(target))
        elif not target:
            self._say("waiting for the download link to appear")

    def _look_gta5mods(self, mod, url: str, hint) -> None:
        step = hint.step_for(url)
        if step is not None and step.starts_by_itself:
            # the current version starts by itself; an older one shows a direct link after the countdown
            def link(value, mod=mod):
                if mod is not self.current or self._downloading:
                    return
                if H.parse_highlight_result(value)["found"]:
                    self._say("click the highlighted download link (an older version doesn't start by itself)")
                else:
                    self._say("the download starts by itself after the countdown (or a link to click appears)")
            self._run(H.highlight_script(url, hint=hint), link)
            return
        if mod.pick:
            def done(value, mod=mod):
                # only found/label matter here: Leonida points, the user clicks (parse_pick_result would also drop
                # any link that isn't a gta5-mods /download/<id> page, for callers that follow it)
                try:
                    res = {"found": False, "label": "", "labels": [], **json.loads(value)}
                except (TypeError, ValueError):
                    res = {"found": False, "label": "", "labels": []}
                if mod is not self.current:
                    return
                if res["found"]:
                    self._say(f"click the highlighted download icon of version '{res['label']}'")
                else:
                    seen = ", ".join(res["labels"]) or "none"
                    self._say(f"no version here matches the pick hint (versions: {seen}); choose the Enhanced one")
            self._run(H.pick_version_script(mod.pick), done)
        else:
            self._run(H.highlight_script(url, hint=hint), lambda _r: None)
            self._say("click the highlighted Download button")

    def _look_nexus(self, mod, url: str, hint) -> None:
        step = hint.step_for(url)
        if step is not None and step.json_attr:  # the files tab
            def pick(html, mod=mod, url=url):
                if mod is not self.current or self._downloading:
                    return
                f = H.choose_nexus_file(H.nexus_files(html), mod.archive)
                if f is None:
                    self._say("waiting for the file list")
                    return
                self._run(H.highlight_script(url, f.download_url, hint), lambda v, f=f: self._nexus_button(mod, f, v))
            self.browser.page.toHtml(pick)
            return
        # after the user's click: the download page with its "Slow download" button
        def slow(value, mod=mod):
            if mod is not self.current:
                return
            res = json.loads(value) if isinstance(value, str) and value else {}
            if res.get("found"):
                self._say("click the highlighted 'Slow download' button (Nexus may show a short wait)")
            elif step is not None and step.label == "Files tab":
                self.browser.view.load(QUrl(self._start_url(mod)))
        self._run(text_button_script(["slow download"]), slow)

    def _nexus_button(self, mod, f, value) -> None:
        if mod is not self.current or self._downloading:
            return
        res = H.parse_highlight_result(value)
        hint = self.hints(self._url())
        if res["found"] and hint is not None and hint.needs_login(res["text"]):
            self._ask_login("nexusmods.com")
        elif res["found"]:
            self._login_wait = False
            self._say(f"click the highlighted Download button of '{f.name}' ({f.kind} file)")

    def _ask_login(self, site: str) -> None:
        if not self._login_wait:
            self._login_wait = True
            self.need_login.emit(site)
        self.mod_status.emit(self.current.id, f"sign in to {site}")
        self.status.emit(f"{self.current.name}: sign in to {site} in the browser window; Leonida goes on by itself "
                         "afterwards (it never types your password).")

    def _say(self, what: str) -> None:
        if self.current is not None:
            self.mod_status.emit(self.current.id, what)
            self.status.emit(f"{self.current.name}: {what}")

    # ---- downloads ------------------------------------------------------------------------------------------
    def _started(self, name: str) -> None:
        if self.current is not None:
            self._downloading = True
            self.timer.stop()
            self.mod_status.emit(self.current.id, "downloading")
            self.status.emit(f"{self.current.name}: downloading {name} ...")

    def _saved(self, path: str) -> None:
        mod = self.current
        if mod is None:
            return
        res = self.session.matches([mod])
        got = res.matched.get(mod.id)
        p = Path(path)
        if got is not None:
            self._record(mod.id, "done", str(got))
        elif p in res.wrong:
            self._record(mod.id, "failed", f"{p.name}: {wrong_message(mod, res.wrong[p][1])} (the file was kept)")
        else:
            self._record(mod.id, "failed", f"{p.name} wasn't recognised as {mod.name} (if it is, use Assign a file)")
        self._next()

    def _failed_download(self, name: str, reason: str) -> None:
        if self.current is not None:
            self._fail(f"the download of {name} failed: {reason}")

    def _fail(self, reason: str) -> None:
        self._record(self.current.id, "failed", reason)
        self._next()

    def _record(self, mod_id: str, kind: str, detail: str) -> None:
        self.results[mod_id] = (kind, detail)
        if kind == "done":
            self.mod_status.emit(mod_id, "ready")
            self.mod_done.emit(mod_id, detail)
        else:
            self.mod_status.emit(mod_id, f"failed: {detail}")
            self.mod_failed.emit(mod_id, detail)
