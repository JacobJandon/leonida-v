"""Drive Leonida's browser through the missing mods, one after another, and download them as the user would.

For each mod the AutoDownloader opens the right page in the (visible) browser window, finds the right file, follows
the site's own Download buttons, waits while the user signs in where a site needs it, notices the download, checks
the file with the matcher (name + ``requireMembers``/``rejectMembers``) and goes on with the next mod by itself.

Within the owner's rule (CLAUDE.md, decision of 2026-11-24): Leonida may follow a site's OWN Download buttons for the
user, always waits through the site's countdowns and timers, never skips or hides ads, never types or stores
passwords, never uses private APIs or premium-only routes, and never touches paid content or Discord.
  * dev-c.com, github.com: follows the download link on the page (``PageHint.may_auto_follow``)
  * gta5-mods.com: on the mod page goes to the version the mod's ``pick`` hint names (from the page, so the mod page
    is the Referer), or presses the main Download button; on the /download/<id> page it waits ``countdown_grace``
    seconds (the site's countdown) and then, unless the download already started by itself (current version),
    clicks the files.gta5-mods.com/uploads/ link the page shows after the countdown (older versions)
  * nexusmods.com: opens the files tab and picks the Main file whose name fits ``archive``; while its button says
    "Log in to download" (or Nexus bounces to users.nexusmods.com) it emits ``need_login("nexusmods.com")`` and waits
    for the user to sign in themselves; then it opens that file's own ``downloadUrl`` from the files tab, presses
    "Slow download" (never the premium button) and waits for Nexus's timer and the file
  * mediafire.com (an author's own folder, e.g. VisualV): scrolls the folder's list as a person would, opens the
    file for the mod's version (``choose_host_file``; a folder without it fails at once, with the reason, instead of
    waiting) and presses the file page's own Download button (no countdown; the page's ads are left alone)
  * razedmods.com and anything else: outlines what pagehints knows and waits for the user's click
  * Patreon / shop / Discord / paid mods: skipped with the reason (``mod_failed``)
It never types into a page, never skips a countdown or timer, never clicks an ad.
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
                 countdown_grace: float = 20.0, reclick_after: float = 45.0,
                 poll_ms: int = 1500, idle_timeout: float = 900.0, parent: QObject | None = None):
        super().__init__(parent)
        self.browser, self.session = browser, session
        self.queue = list(mods)
        self.hints = hints
        self.idle_timeout = idle_timeout
        self.countdown_grace = countdown_grace   # seconds on a gta5-mods /download/ page before clicking its link
        self.reclick_after = reclick_after       # a click that started nothing is tried again after this long
        self._page = ("", 0.0)                   # (url, when it was first seen) for countdown timing
        self._clicked: dict[str, float] = {}     # url -> when Leonida last clicked something on it
        self.current = None
        self.running = False
        self._downloading = False
        self._login_wait = False
        self._followed: set[str] = set()
        self._opened_at = 0.0
        # the shared window may still show (or finish loading) the previous mod's page: don't act on that one
        self._prev_url = ""
        self._start = ""
        self._scan: tuple[str, int] = ("", 0)    # (folder url, scans in a row that reached the end of its list)
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
        self._clicked = {}
        self._scan = ("", 0)
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
        """True while the window still shows the previous mod's (different) page. Once it has shown any other page,
        that's over: the flow may come back to the same URL later (e.g. after signing in)."""
        url = self._url()
        if url != self._prev_url or url == self._start:
            self._prev_url = ""
        return bool(self._prev_url)

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
        elif hint.site == "mediafire.com":
            self._look_mediafire(mod, url, hint)
        elif hint.may_auto_follow(url):
            self.browser.page.toHtml(lambda html, url=url: self._follow(mod, url, html))
        else:
            self._run(H.highlight_script(url, hint=hint), lambda _r: None)
            step = hint.step_for(url)
            self._say(step.label if step else "click the author's Download button")

    def _follow(self, mod, url: str, html: str) -> None:
        if not self._still(mod, url):
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

    # ---- following a site's own buttons -----------------------------------------------------------------------
    def _still(self, mod, url: str) -> bool:
        """A page callback may act only if nothing changed meanwhile: same mod, same page, no download yet."""
        return mod is self.current and not self._downloading and self._url() == url

    def _seconds_on_page(self, url: str) -> float:
        if self._page[0] != url:
            self._page = (url, time.monotonic())
        return time.monotonic() - self._page[1]

    def _may_click(self, url: str) -> bool:
        last = self._clicked.get(url)
        return last is None or time.monotonic() - last > self.reclick_after

    def _click(self, mod, url: str, script: str, done_text: str, missing_text: str) -> None:
        def after(value, mod=mod, url=url):
            if not self._still(mod, url):
                return
            try:
                res = json.loads(value) if isinstance(value, str) and value else {}
            except ValueError:
                res = {}
            if res.get("clicked"):
                self._clicked[url] = time.monotonic()
                self._say(done_text)
            else:
                self._say(missing_text)
        self._run(script, after)

    def _go(self, mod, url: str, target: str, what: str) -> None:
        """Go to ``target`` from the current page (the site sees the page as Referer), once per mod."""
        if target in self._followed or self._login_wait:
            return
        self._followed.add(target)
        self._clicked[url] = time.monotonic()
        self.mod_status.emit(mod.id, what)
        self.status.emit(f"{mod.name}: {what}")
        self._run(H.navigate_script(target), lambda _r: None)

    def _same_site_download(self, page_url: str, href: str | None) -> bool:
        if not href:
            return False
        a, b = QUrl(page_url), QUrl(href)
        return a.host() == b.host() and a.port() == b.port() and "/download/" in b.path()

    def _look_gta5mods(self, mod, url: str, hint) -> None:
        step = hint.step_for(url)
        if step is not None and step.starts_by_itself:  # a /download/<id> page
            waited = self._seconds_on_page(url)
            if waited < self.countdown_grace:
                self._say(f"waiting through gta5-mods' countdown ({self.countdown_grace - waited:.0f} s)")
            elif self._may_click(url):
                self._click(mod, url, H.click_script(step.selector),
                            "clicked the download link the page shows after the countdown; waiting for the file",
                            "waiting for the download (it starts by itself, or a link appears)")
            else:
                self._say("waiting for the download to start")
            return
        if not self._may_click(url):
            return
        if mod.pick:
            def done(value, mod=mod, url=url):
                try:
                    res = {"found": False, "label": "", "labels": [], "href": None, **json.loads(value)}
                except (TypeError, ValueError):
                    res = {"found": False, "label": "", "labels": [], "href": None}
                if not self._still(mod, url):
                    return
                if res["found"] and self._same_site_download(url, res.get("href")):
                    self._go(mod, url, res["href"], f"opening version '{res['label']}' (its countdown comes next)")
                else:
                    seen = ", ".join(res["labels"]) or "none"
                    self._say(f"no version here matches the pick hint (versions: {seen}); choose the Enhanced one")
            self._run(H.pick_version_script(mod.pick), done)
        else:
            self._click(mod, url, H.click_script('a.btn-download[href*="/download/"]'),
                        "pressed Download (its countdown comes next)", "waiting for the Download button")

    def _look_mediafire(self, mod, url: str, hint) -> None:
        step = hint.step_for(url)
        if step is None:
            self._say("click the author's Download button")
            return
        if step.css_class == "foldername":  # a folder: find the file for this mod's version
            def found(value, mod=mod, url=url, step=step):
                if not self._still(mod, url):
                    return
                files, end = H.parse_scan_result(value, step)
                f, why = H.choose_host_file(files, mod.archive, mod.pick, mod.version)
                ends = self._scan[1] + 1 if end and self._scan[0] == url else int(end)
                self._scan = (url, ends)
                known = H.version_number(mod.version) is not None  # then a fitting file can't be another one
                if f is not None and (end or known) and step.accepts(f.url):
                    self._go(mod, url, f.url, f"opening {f.name}")
                elif ends >= 2:  # the whole list has been read (twice at its end, so a late chunk counts too)
                    self._fail(f"the author's MediaFire folder: {why}; get it yourself from {mod.page}")
                else:
                    self._say(f"reading the folder's file list ({len(files)} files so far)")
            self._run(H.folder_scan_script(), found)
            return
        if self._may_click(url):  # the file page: the site's own Download button
            self._click(mod, url, H.click_script(step.selector),
                        "pressed MediaFire's Download button; waiting for the file",
                        "waiting for MediaFire's Download button")
        else:
            self._say("waiting for the file")

    def _look_nexus(self, mod, url: str, hint) -> None:
        step = hint.step_for(url)
        if step is not None and step.json_attr:  # the files tab
            def pick(html, mod=mod, url=url, step=step):
                if not self._still(mod, url):
                    return
                f = H.choose_nexus_file(H.nexus_files(html, step.accepts), mod.archive)
                if f is None:
                    self._say("waiting for the file list")
                    return
                self._run(H.highlight_script(url, f.download_url, hint),
                          lambda v, f=f: self._nexus_file(mod, url, f, v))
            self.browser.page.toHtml(pick)
            return
        if step is not None and step.label == "Files tab":  # the mod page: on to its files tab
            self._go(mod, url, self._start_url(mod), "opening the files tab")
            return
        # the file's download page: sign-in check, then the site's own "Slow download" button
        def check(value, mod=mod, url=url):
            if not self._still(mod, url):
                return
            try:
                res = json.loads(value) if isinstance(value, str) and value else {}
            except ValueError:
                res = {}
            if res.get("found"):  # "Log in to download" / "Register to download"
                self._ask_login("nexusmods.com")
                return
            self._login_wait = False
            if self._may_click(url):
                self._click(mod, url, H.click_script(texts=["slow download"]),
                            "pressed 'Slow download'; waiting for Nexus's timer and the file",
                            "waiting for the 'Slow download' button")
            else:
                self._say("waiting for Nexus's timer and the file")
        self._run(text_button_script(list(hint.login_texts)), check)

    def _nexus_file(self, mod, url: str, f, value) -> None:
        if not self._still(mod, url):
            return
        res = H.parse_highlight_result(value)
        hint = self.hints(self._url())
        if res["found"] and hint is not None and hint.needs_login(res["text"]):
            self._ask_login("nexusmods.com")
        elif res["found"]:  # signed in: the file's own download page, from the files tab
            self._login_wait = False  # the user is back on Nexus and signed in
            self._go(mod, url, f.download_url, f"opening the download page of '{f.name}' ({f.kind} file)")
        else:
            self._say("waiting for the file's Download button")

    def _ask_login(self, site: str) -> None:
        if not self._login_wait:
            self._login_wait = True
            self._followed.clear()  # after the sign-in the same pages may be opened again
            self._clicked.clear()
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
