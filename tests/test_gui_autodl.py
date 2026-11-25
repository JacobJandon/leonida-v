"""AutoDownloader on the real QtWebEngine, offscreen, against local pages that mimic each site as seen on the owner's
PC (served by the test HTTP server). Leonida follows each site's own Download buttons; the test only plays the user
where a user is needed: signing in."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402

if QCoreApplication.instance() is None:
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
pytest.importorskip("PySide6.QtWebEngineWidgets")

from conftest import flush_deletes, make_zip  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from test_downloader import Server  # noqa: E402

from leonida import pagehints as H  # noqa: E402
from leonida.pagehints import PageHint, Step  # noqa: E402
from leonida.session import Session  # noqa: E402

pytestmark = pytest.mark.webengine


LAST: list = []  # the current Recorder's events, shown when a wait times out
BROWSER: list = []


def wait_until(cond, timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.005)
    QApplication.processEvents()
    url = BROWSER[0].view.url().toString() if BROWSER else None
    assert cond(), f"timed out at {url}; events: {LAST[-1].events[-12:] if LAST else None}"


@pytest.fixture(scope="module")
def server():
    s = Server()
    yield s
    s.close()


@pytest.fixture(scope="module")
def browser(qt_app, tmp_path_factory):
    from leonida.gui.browser import BrowserWindow

    root = tmp_path_factory.mktemp("autodl-browser")
    win = BrowserWindow(root / "state", root / "downloads")
    BROWSER.append(win)
    yield win
    win.close()
    win.deleteLater()
    flush_deletes()


# ------------------------------------------------------------------------------------------------ fake sites
def zip_bytes(tmp: Path, name: str, members: dict) -> bytes:
    return make_zip(tmp / "srv" / name, members).read_bytes()


def serve_file(server, path: str, data: bytes) -> None:
    name = path.rsplit("/", 1)[-1]
    server.add(path, body=data, ctype="application/zip",
               headers={"Content-Disposition": f'attachment; filename="{name}"'})


def html(server, path: str, body: str) -> str:
    return server.add(path, body=f"<!doctype html><html><body>{body}</body></html>".encode(), ctype="text/html",
                      headers={"Cache-Control": "no-store"})


NEXUS_ELEMENT = """<script>customElements.define('mod-download-modal', class extends HTMLElement {
  connectedCallback() { const r = this.attachShadow({mode: 'open'}); const a = document.createElement('a');
    a.className = 'nxm-button'; a.textContent = this.dataset.text; a.href = this.dataset.href; r.appendChild(a); } });
</script>"""


def nexus_files_tab(text: str, base: str = "") -> str:
    def modal(name, cat, uid, href):
        data = json.dumps({"name": name, "category": cat, "fileName": f"{name.replace(' ', '_')}.zip",
                           "downloadUrl": f"{base}/api/files/{uid}/download"})
        return (f"<mod-download-modal file='{data}' data-text='{text}' data-href='{href}'></mod-download-modal>")
    return (NEXUS_ELEMENT + "<header>" + modal("Header", 1, "hdr", "/nowhere") + "</header><dl>"
            "<dt class='file-expander-header'>Old</dt><dd>" + modal("DriveV Old", 4, "old", "/nowhere") + "</dd>"
            "<dt class='file-expander-header'>Main</dt><dd>"
            + modal("DriveV NVE", 1, "nve", "/gta5enhanced/mods/1093?tab=files&file_id=7") + "</dd></dl>")


# Nexus's download page: a premium button and the free "Slow download" button, which starts a short timer
NEXUS_DOWNLOAD_PAGE = ('<a class="premium" href="/premium">Fast download</a>'
                       '<button id="slow" onclick="this.textContent = \'Your download starts in 1 s\'; setTimeout('
                       'function () { location.href = \'/files/DriveV_NVE_2.1.zip\'; }, 300);">Slow download</button>')


def local_hints(base: str):
    b = re.escape(base)
    devc = PageHint("dev-c.com", ("127.0.0.1",), (
        Step(r"^/devc/gtav/[^/]+/?$", 'a[href^="/devc/files/"]', "Download", link_pattern=rf"^{b}/devc/files/[^/]+\.zip$"),),
        auto_follow=True)
    gh = PageHint("github.com", ("127.0.0.1",), (
        Step(r"^/gh/[^/]+/[^/]+/releases/latest$", 'a[href*="/releases/download/"]', "asset",
             link_pattern=rf"^{b}/gh/[^/]+/[^/]+/releases/download/"),),
        auto_follow=True, start=(r"^/gh/([^/]+)/([^/]+)/?$", r"/gh/\1/\2/releases/latest"))
    g5 = H.hint_for("https://www.gta5-mods.com/maps/x")    # the real site descriptions
    nx_real = H.hint_for("https://www.nexusmods.com/x/mods/1")
    nx = dataclasses.replace(nx_real, steps=tuple(  # the files' downloadUrl lives on the local server here
        dataclasses.replace(st, link_pattern=rf"^{b}/api/files/[^/?#]+/download") if st.json_attr else st
        for st in nx_real.steps))

    def resolve(url: str):
        path = urllib.parse.urlsplit(url).path
        for prefix, hint in (("/devc/", devc), ("/gh/", gh), ("/maps/", g5), ("/gta5enhanced/", nx),
                             ("/api/files/", nx)):
            if path.startswith(prefix):
                return hint
        return None
    return resolve


def mod(mid, order, page, archive, **extra):
    return {"id": mid, "order": order, "tier": extra.pop("tier", "core"), "layer": "t", "name": mid.title(),
            "version": "1", "source": extra.pop("source", "direct"), "page": page, "archive": archive,
            "install": {"method": "guided", "steps": ["x"]}, **extra}


@pytest.fixture
def kit(tmp_path, server, browser, game):
    base = server.base
    mods = [
        mod("shv", 1, f"{base}/devc/gtav/scripthookv/", ["ScriptHookV_*.zip"]),
        mod("hud", 2, f"{base}/gh/o/hud", ["HUD-*.zip"]),
        mod("mapfixes", 3, f"{base}/maps/map-fixes", ["*Map*Fixes*"], requireMembers=["*spmapfixes_gen9/*"],
            rejectMembers=["*spmapfixes/*"], pick={"versionMatch": "(?i)\\benhanced\\b"}),
        mod("drivev", 4, f"{base}/gta5enhanced/mods/1093", ["DriveV_NVE*"]),
        mod("paidthing", 5, f"{base}/paid", ["Paid*"], tier="paid", source="patreon"),
        mod("patreonthing", 6, f"{base}/pat", ["Pat*"], source="patreon"),
        mod("idle", 7, f"{base}/static/nothing", ["Idle*"]),
        mod("mapfixes_main", 8, f"{base}/maps/map-fixes", ["*Map*Fixes*"], requireMembers=["*spmapfixes_gen9/*"],
            rejectMembers=["*spmapfixes/*"]),  # no pick hint: the main (current = Legacy) button
    ]
    d = tmp_path / "manifest"
    d.mkdir()
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "1", "mods": mods}))
    (d / "profiles.json").write_text(json.dumps({"default": "all", "profiles": [
        {"id": "all", "name": "All", "include": [m["id"] for m in mods]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    downloads = tmp_path / "dl"
    s = Session(tmp_path / "st", d, download_dir=str(downloads), game_dir=str(game), game_build="1.0.1013.20")
    browser.download_dir = downloads
    # pages
    html(server, "/devc/gtav/scripthookv/", '<a href="/devc/files/ScriptHookV_1.0.zip">Download</a>'
                                           '<a href="/devc/files/ScriptHookV_SDK.zip">SDK</a>')
    serve_file(server, "/devc/files/ScriptHookV_1.0.zip", zip_bytes(tmp_path, "s.zip", {"bin/ScriptHookV.dll": "x"}))
    html(server, "/gh/o/hud/releases/latest", '<a href="/gh/o/hud/releases/download/v1/HUD-Legacy.zip">L</a>'
                                             '<a href="/gh/o/hud/releases/download/v1/HUD-Enhanced.zip">E</a>'
                                             '<a href="/gh/o/hud/archive/v1.zip">source</a>')
    serve_file(server, "/gh/o/hud/releases/download/v1/HUD-Enhanced.zip", zip_bytes(tmp_path, "h.zip", {"hud.oiv": "x"}))
    rows = "".join(
        f'<div class="well pull-left file-version-container"><div class="pull-left">{label}<p>1 MB</p></div>'
        f'<div class="pull-right"><a target="_blank" href="/maps/map-fixes/download/{vid}">dl</a></div></div>'
        for label, vid in (("21.8.2 Enhanced", 204370), ("21.8.2 Legacy <span>(current)</span>", 204369)))
    html(server, "/maps/map-fixes", f'<a class="btn btn-download" href="/maps/map-fixes/download/204369">Download</a>{rows}')
    # the current version (Legacy here) starts by itself after the countdown ...
    html(server, "/maps/map-fixes/download/204369", "<p>Your download starts in 1 second</p><script>setTimeout("
                 "function () { location.href = '/files/MapFixes_v21.8.2_NG.zip'; }, 300);</script>")
    # ... an older one (Enhanced) only shows a direct link after the countdown, as on the real site
    enh = "/files.gta5-mods.com/uploads/map-fixes/5e056b-MapFixes_v21.8.2_Enhanced.zip"
    html(server, "/maps/map-fixes/download/204370", "<p id=c>Please wait 1 second</p><script>setTimeout(function () "
                 f"{{ var a = document.createElement('a'); a.href = '{enh}'; a.textContent = 'MapFixes_v21.8.2_Enhanced.zip'; "
                 "document.body.appendChild(a); }, 300);</script>")
    serve_file(server, enh, zip_bytes(tmp_path, "e.zip", {"Enhanced/SPMapFixes_gen9/dlc.rpf": "e"}))
    serve_file(server, "/files/MapFixes_v21.8.2_NG.zip", zip_bytes(tmp_path, "l.zip", {"Legacy/SPMapFixes/dlc.rpf": "l"}))
    html(server, "/gta5enhanced/mods/1093?tab=files", nexus_files_tab("Log in to download", base))
    html(server, "/api/files/nve/download", NEXUS_DOWNLOAD_PAGE)
    html(server, "/premium", "<p>premium page: must never be opened</p>")
    serve_file(server, "/files/DriveV_NVE_2.1.zip", zip_bytes(tmp_path, "d.zip", {"DriveV/onigiri/x.ytd": "d"}))
    html(server, "/static/nothing", "<p>no hint for this site</p>")
    return s, browser, local_hints(base)


class Recorder:
    def __init__(self, dl):
        self.events = []
        LAST.append(self)
        for name in ("status", "need_login", "mod_status", "mod_done", "mod_failed", "finished"):
            getattr(dl, name).connect(lambda *a, name=name: self.events.append((name, *a)))

    def __repr__(self):
        return f"Recorder({self.events[-14:]})"

    def of(self, kind):
        return [e[1:] for e in self.events if e[0] == kind]

    def said(self, mod_id, text):
        return any(m == mod_id and text in t for m, t in self.of("mod_status"))


def make_dl(kit, ids, **kw):
    from leonida.gui.autodl import AutoDownloader

    s, browser, hints = kit
    mods = [s.manifest.mod(i) for i in ids]
    dl = AutoDownloader(browser, s, mods, hints=hints, poll_ms=kw.pop("poll_ms", 150), **kw)
    return dl, Recorder(dl)


def js(browser, code):
    browser.page.runJavaScript(code)


# ------------------------------------------------------------------------------------------------------- tests
def test_devc_and_github_are_followed_by_themselves(kit):
    s, browser, _ = kit
    dl, rec = make_dl(kit, ["shv", "hud"])
    dl.start()
    wait_until(lambda: rec.of("finished"), 60)
    done = dict(rec.of("mod_done"))
    assert Path(done["shv"]).name == "ScriptHookV_1.0.zip"
    assert Path(done["hud"]).name == "HUD-Enhanced.zip"        # Enhanced chosen over Legacy, no source zip
    assert rec.of("mod_failed") == [] and rec.said("shv", "following the download link")
    assert not (s.config.downloads() / "ScriptHookV_SDK.zip").exists()


def requested(server, path_part: str) -> list[dict]:
    return [h for p, h in server.requests if path_part in p]


def test_gta5mods_older_version_after_the_countdown(kit, server):
    s, browser, _ = kit
    page = s.manifest.mod("mapfixes").page
    dl, rec = make_dl(kit, ["mapfixes"], countdown_grace=1.5)
    dl.start()
    wait_until(lambda: rec.said("mapfixes", "opening version '21.8.2 Enhanced'"))
    wait_until(lambda: rec.said("mapfixes", "waiting through gta5-mods' countdown"))
    (hdr,) = requested(server, "/maps/map-fixes/download/204370")[-1:]
    assert hdr.get("Referer") == page                     # reached from the mod page, like a click
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.9:                    # the link is there after 0.3 s, but the countdown is respected
        QApplication.processEvents()
        time.sleep(0.01)
    assert not requested(server, "5e056b-MapFixes") and rec.of("finished") == []
    wait_until(lambda: rec.of("finished"), 60)
    assert rec.said("mapfixes", "clicked the download link the page shows after the countdown")
    (done,) = rec.of("mod_done")
    assert Path(done[1]).name == "5e056b-MapFixes_v21.8.2_Enhanced.zip"  # gta5-mods keeps its hash prefix
    assert not requested(server, "/download/204369")      # the Legacy (current) version was never opened


def test_gta5mods_current_version_starts_by_itself_and_legacy_is_rejected(kit, server):
    s, browser, _ = kit
    dl, rec = make_dl(kit, ["mapfixes_main"], countdown_grace=3.0)
    dl.start()
    wait_until(lambda: rec.of("finished"), 60)
    assert rec.said("mapfixes_main", "pressed Download (its countdown comes next)")
    assert not rec.said("mapfixes_main", "clicked the download link")  # it started by itself: nothing clicked
    (failed,) = rec.of("mod_failed")
    assert failed[0] == "mapfixes_main" and "wrong edition/version of Mapfixes_Main" in failed[1] and "kept" in failed[1]
    assert (s.config.downloads() / "MapFixes_v21.8.2_NG.zip").exists() and rec.of("mod_done") == []


def test_nexus_waits_for_sign_in_then_downloads(kit, server):
    s, browser, _ = kit
    files_tab = s.manifest.mod("drivev").page + "?tab=files"
    dl, rec = make_dl(kit, ["drivev"])
    dl.start()
    wait_until(lambda: rec.of("need_login"))
    assert rec.of("need_login") == [("nexusmods.com",)] and rec.said("drivev", "sign in to nexusmods.com")
    assert any("never types your password" in st[0] for st in rec.of("status"))
    time.sleep(0.5)
    QApplication.processEvents()
    assert dl.current is not None and rec.of("mod_failed") == [] and not requested(server, "/api/files/")
    # the user signs in themselves; Nexus sends them back to the files tab
    html(server, "/gta5enhanced/mods/1093?tab=files", nexus_files_tab("Download", server.base))
    browser.view.load(browser.view.url())
    wait_until(lambda: rec.of("finished"), 60)
    assert rec.said("drivev", "opening the download page of 'DriveV NVE' (main file)")
    assert rec.said("drivev", "pressed 'Slow download'; waiting for Nexus's timer and the file")
    assert Path(rec.of("mod_done")[0][1]).name == "DriveV_NVE_2.1.zip"
    (hdr,) = requested(server, "/api/files/nve/download")[-1:]
    assert hdr.get("Referer") == files_tab               # the Main file's own link, from the files tab
    assert not requested(server, "/premium") and not requested(server, "/api/files/old/")  # never premium / Old


def test_nexus_bounce_to_sign_in_resumes(kit, server):
    s, browser, _ = kit
    # the button says Download, but the session has expired: Nexus bounces to its sign-in page
    html(server, "/gta5enhanced/mods/1093?tab=files", nexus_files_tab("Download", server.base))
    server.add("/api/files/nve/download", status=302, headers={"Location": "/users.nexusmods.com/auth/sign_in"})
    html(server, "/users.nexusmods.com/auth/sign_in", "<form><input name=user><input type=password></form>")
    dl, rec = make_dl(kit, ["drivev"])
    dl.start()
    urls = []
    browser.view.urlChanged.connect(lambda u: urls.append(u.toString()))
    wait_until(lambda: rec.of("need_login"))
    assert rec.said("drivev", "sign in to nexusmods.com")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1.5:                   # while the user signs in, Leonida stays put
        QApplication.processEvents()
        time.sleep(0.01)
    assert sum("/api/files/nve/download" in u for u in urls) <= 1 and "users.nexusmods.com" in browser.view.url().toString()
    # nothing is ever typed into the sign-in form
    wait_until(lambda: "users.nexusmods.com" in browser.view.url().toString())
    loaded = []
    browser.view.loadFinished.connect(loaded.append)
    wait_until(lambda: loaded or browser.page.title() != "", 10)
    out = []
    browser.page.runJavaScript("Array.from(document.querySelectorAll('input')).map(i => i.value).join('|')", 0,
                               out.append)
    wait_until(lambda: out)
    assert out == ["|"]
    # the user signs in; Nexus sends them back to the file's download page
    html(server, "/api/files/nve/download", NEXUS_DOWNLOAD_PAGE)
    from PySide6.QtCore import QUrl

    browser.view.load(QUrl(server.base + "/api/files/nve/download"))
    wait_until(lambda: rec.of("finished"), 60)
    assert Path(rec.of("mod_done")[0][1]).name == "DriveV_NVE_2.1.zip" and not requested(server, "/premium")


def test_paid_and_patreon_mods_are_left_alone(kit):
    dl, rec = make_dl(kit, ["paidthing", "patreonthing"])
    dl.start()
    wait_until(lambda: rec.of("finished"))
    reasons = dict(rec.of("mod_failed"))
    assert "is paid" in reasons["paidthing"] and "never uses re-uploaded copies" in reasons["paidthing"]
    assert "comes from patreon" in reasons["patreonthing"]


def test_idle_timeout_skip_and_stop(kit):
    dl, rec = make_dl(kit, ["idle"], idle_timeout=0.5)
    dl.start()
    wait_until(lambda: rec.of("finished"), 20)
    assert "no download started" in dict(rec.of("mod_failed"))["idle"]
    dl, rec = make_dl(kit, ["idle", "paidthing"])
    dl.start()
    wait_until(lambda: rec.said("idle", "click the author's Download button"))
    dl.skip()
    wait_until(lambda: rec.of("finished"))
    assert dict(rec.of("mod_failed"))["idle"] == "skipped"
    dl, rec = make_dl(kit, ["idle"])
    dl.start()
    wait_until(lambda: rec.said("idle", "click"))
    dl.stop()
    assert rec.of("finished") and not dl.running and dl.current is None


def test_failed_download_and_existing_file(kit):
    s, browser, _ = kit
    dl, rec = make_dl(kit, ["idle"])
    dl.start()
    wait_until(lambda: rec.said("idle", "click"))
    browser.file_failed.emit("Idle.zip", "network error")
    wait_until(lambda: rec.of("finished"))
    assert dict(rec.of("mod_failed"))["idle"] == "the download of Idle.zip failed: network error"
    make_zip(s.config.downloads() / "ScriptHookV_2.0.zip", {"x": "y"})
    dl, rec = make_dl(kit, ["shv"])
    dl.start()
    wait_until(lambda: rec.of("finished"))
    assert Path(dict(rec.of("mod_done"))["shv"]).name == "ScriptHookV_2.0.zip"  # already there: not downloaded again


def test_finished_downloader_lets_go_of_the_browser(kit):
    _s, browser, _ = kit
    dl, rec = make_dl(kit, ["paidthing"])
    dl.start()
    wait_until(lambda: rec.of("finished"))
    assert dl._links == []
    browser.file_saved.emit("x")  # nothing happens: no longer connected
    assert len(rec.events) == len(rec.events)


def test_text_button_script_never_clicks():
    from leonida.gui.autodl import text_button_script

    js_text = text_button_script(["Slow download"])
    assert '["slow download"]' in js_text and ".click(" not in js_text and "shadowRoot" in js_text



# ------------------------------------------------------------------------------------------- GetPage wiring
def test_get_page_download_everything(qt_app, tmp_path, game, monkeypatch):
    from PySide6.QtCore import QObject, Signal

    from leonida.gui import app as A
    from leonida.gui import autodl

    monkeypatch.setenv("LEONIDA_NO_NET", "1")       # no automatic downloads: straight to the browser part
    monkeypatch.setenv("LEONIDA_NO_UPDATE_CHECK", "1")
    made = []

    class FakeAuto(QObject):
        status, need_login, finished = Signal(str), Signal(str), Signal()
        mod_status, mod_done, mod_failed = Signal(str, str), Signal(str, str), Signal(str, str)

        def __init__(self, browser, session, mods, parent=None, sites=None):
            super().__init__(parent)
            self.browser, self.mods, self.results, self.started = browser, mods, {}, False
            self.sites = sites
            made.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.finished.emit()

    monkeypatch.setattr(autodl, "AutoDownloader", FakeAuto)
    s = Session(tmp_path / "st", download_dir=str(tmp_path / "dl"), game_dir=str(game), game_build="1.0.1013.20")
    win = A.MainWindow(s)
    fake_browser = types_ns(raise_=lambda: None, activateWindow=lambda: None)
    monkeypatch.setattr(win, "browser_window", lambda: fake_browser)
    win.browser = fake_browser
    page = win.pages[3]
    page.refresh()
    assert page.browse_btn.text() == "Download everything" and page.browse_btn.isEnabled()
    page.browse_btn.click()
    (auto,) = made
    assert auto.sites["nexusmods.com"] is False and auto.sites["gta5-mods.com"] is True   # Settings' defaults
    assert auto.started and auto.browser is fake_browser and [m.id for m in auto.mods] == [m.id for m in page.mods]
    assert not page.browse_btn.isEnabled() and page.cancel_btn.text() == "Stop" and not page.cancel_btn.isHidden()
    first, second = page.mods[0].id, page.mods[1].id
    auto.mod_status.emit(first, "sign in to nexusmods.com")
    assert page.table.item(0, page.STATUS).text() == "sign in to nexusmods.com"
    auto.need_login.emit("nexusmods.com")
    assert "Sign in to nexusmods.com" in page.auto_status.text() and "never types your password" in page.auto_status.text()
    auto.mod_failed.emit(second, "skipped")
    auto.mod_status.emit(second, "failed: skipped")
    auto.status.emit("Mod: downloading")
    assert page.auto_status.text() == "Mod: downloading"
    page.cancel_btn.click()                      # Stop -> the downloader finishes
    assert page.autodl is None and page.cancel_btn.isHidden() and page.cancel_btn.text() == "Cancel download"
    assert page.table.item(1, page.STATUS).text() == "needs you: skipped"
    assert "Still needed:" in page.auto_status.text() and "skipped" in page.auto_status.text()
    win.close()
    win.deleteLater()
    flush_deletes()


def types_ns(**kw):
    import types

    return types.SimpleNamespace(**kw)


def test_get_page_falls_back_to_pages_without_the_browser(qt_app, tmp_path, game, monkeypatch):
    from leonida.gui import app as A

    monkeypatch.setenv("LEONIDA_NO_NET", "1")
    monkeypatch.setenv("LEONIDA_NO_OPEN", "1")      # browser_window() -> None
    monkeypatch.setenv("LEONIDA_NO_UPDATE_CHECK", "1")
    s = Session(tmp_path / "st", download_dir=str(tmp_path / "dl"), game_dir=str(game), game_build="1.0.1013.20")
    win = A.MainWindow(s)
    opened = []
    monkeypatch.setattr(win, "open_page", lambda mod, queue=None: opened.append((mod.id, [m.id for m in queue or []])))
    page = win.pages[3]
    page.refresh()
    page.download_everything()
    assert opened and page.autodl is None
    win.close()
    win.deleteLater()
    flush_deletes()


def test_never_acts_on_the_previous_mods_page(kit):
    """The window is shared: right after opening a mod it may still show the previous mod's page (here a
    GitHub-like page with a download link). Polling then must not follow that page's link for the new mod."""
    from PySide6.QtCore import QUrl

    s, browser, _ = kit
    browser.view.load(QUrl(s.manifest.mod("hud").page + "/releases/latest"))
    wait_until(lambda: browser.view.url().toString().endswith("/releases/latest"))
    wait_until(lambda: browser.page is not None and not browser.view.url().isEmpty())
    QApplication.processEvents()
    dl, rec = make_dl(kit, ["idle"], idle_timeout=60)
    dl.start()
    dl._tick()                      # an immediate poll, before the new page has committed
    dl._loaded(True)                # and a late loadFinished of the old page
    wait_until(lambda: rec.said("idle", "click the author's Download button"))
    assert not rec.said("idle", "following") and not any(s.config.downloads().glob("HUD-*"))
    dl.stop()


def test_a_site_switched_off_in_settings_is_only_pointed_at(kit, server):
    """Settings > Downloads: with Nexus off (its default), Leonida outlines the button and waits for your own click:
    no file page is opened for you."""
    before = len(requested(server, "/api/files/"))         # the module's server also served earlier tests
    dl, rec = make_dl(kit, ["drivev"], sites={"nexusmods.com": False})
    dl.start()
    wait_until(lambda: rec.said("drivev", "automatic clicks are off for nexusmods.com"))
    time.sleep(0.3)
    QApplication.processEvents()
    assert len(requested(server, "/api/files/")) == before and rec.of("need_login") == []
    dl.stop()
