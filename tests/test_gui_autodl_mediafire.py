"""AutoDownloader on MediaFire (real QtWebEngine, offscreen, local pages that mimic the real folder and file pages):
the folder lists files in chunks that load as it scrolls; Leonida reads the list, opens the file for the mod's version
and presses the site's own Download button. A folder without that version fails at once, with the reason."""

from __future__ import annotations

import dataclasses
import json
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("PySide6.QtWebEngineWidgets")

import test_gui_autodl as G  # noqa: E402
from test_mediafire import row  # noqa: E402

from leonida import pagehints as H  # noqa: E402
from leonida.session import Session  # noqa: E402

pytestmark = pytest.mark.webengine
server, browser = G.server, G.browser  # the module's fixtures (one test server and browser window)
Recorder, html, serve_file, wait_until, zip_bytes = G.Recorder, G.html, G.serve_file, G.wait_until, G.zip_bytes


def folder_page(base: str, first: list[str], later: list[str]) -> str:
    """Like the real folder: the first chunk is in the page, the next one is added when the list is scrolled down."""
    rows1 = "".join(row(f"a{i}", n, base) for i, n in enumerate(first))
    rows2 = json.dumps("".join(row(f"b{i}", n, base, chunk=2) for i, n in enumerate(later)))
    return (f'<div style="height:30px">VisualV</div><ul id="main_list">{rows1}</ul><div style="height:2400px"></div>'
            f"<script>var more = {rows2}, added = false; window.addEventListener('scroll', function () {{"
            "  if (!added && window.scrollY + window.innerHeight > document.body.scrollHeight - 1500) {"
            "    added = true; document.getElementById('main_list').insertAdjacentHTML('beforeend', more); } });"
            "</script>")


def file_page(target: str) -> str:
    return (f'<a href="/ads/download-now">Download now (ad)</a><a class="input popsok" id="downloadButton" '
            f'href="{target}">DOWNLOAD (1 KB)</a>')


@pytest.fixture
def kit(tmp_path, server, browser, game):
    base = server.base
    mf = H.hint_for("https://www.mediafire.com/folder/x")
    b = re.escape(base)
    local = dataclasses.replace(mf, hosts=("127.0.0.1",), steps=tuple(  # the real steps, with local link patterns
        dataclasses.replace(st, link_pattern=st.link_pattern.replace(r"^https://(www\.)?mediafire\.com", f"^{b}")
                            .replace(r"^https://download\d*\.mediafire\.com/", f"^{b}/dl/"),
                            selector=st.selector.replace('[href*=".mediafire.com/"]', ""))
        for st in mf.steps))
    mods = [{"id": mid, "order": i, "tier": "optional", "layer": "t", "name": mid.title(), "version": version,
             "source": "direct", "page": f"{base}{page}", "archive": ["*VisualV*.zip", "*VisualV*.rar"],
             "pick": {"versionMatch": "(?i)enhanced"}, "install": {"method": "guided", "steps": ["x"]}}
            for i, (mid, version, page) in enumerate((("visualv", "2.0.630 (Enhanced)", "/folder/vv/VisualV"),
                                                       ("visualvold", "2.0.630 (Enhanced)", "/folder/old/VisualV")), 1)]
    d = tmp_path / "manifest"
    d.mkdir()
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "1", "mods": mods}))
    (d / "profiles.json").write_text(json.dumps({"default": "all", "profiles": [
        {"id": "all", "name": "All", "include": [m["id"] for m in mods]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    downloads = tmp_path / "dl"
    s = Session(tmp_path / "st", d, download_dir=str(downloads), game_dir=str(game), game_build="1.0.1013.20")
    browser.download_dir = downloads
    first = [f"VisualV 1.0.{n:03d}.rar" for n in range(10, 300, 10)]          # 29 old builds in the first chunk
    later = ["VisualV 2.0.630 Legacy.rar", "VisualV 2.0.630 Enhanced.zip", "VisualV 2.0.640 Enhanced.zip"]
    html(server, "/folder/vv/VisualV", folder_page(base, first, later))
    html(server, "/folder/old/VisualV", folder_page(base, first, ["VisualV 1.0.380.rar"]))
    for name in later:
        u = name.replace(" ", "_")
        html(server, f"/file/b{later.index(name)}/{u}/file", file_page(f"/dl/x/{u}"))
        serve_file(server, f"/dl/x/{u}", zip_bytes(tmp_path, u, {"VisualV/manual installation/x.xml": "x"}))
    html(server, "/ads/download-now", "<p>an ad: must never be opened</p>")
    return s, browser, lambda url: local if url.startswith(base) else None


def make_dl(kit, ids, **kw):
    from leonida.gui.autodl import AutoDownloader

    s, win, hints = kit
    dl = AutoDownloader(win, s, [s.manifest.mod(i) for i in ids], hints=hints, poll_ms=150, **kw)
    return dl, Recorder(dl)


def test_mediafire_folder_file_for_the_version_then_the_sites_button(kit, server):
    dl, rec = make_dl(kit, ["visualv"])
    dl.start()
    wait_until(lambda: rec.of("finished"), 60)
    assert rec.of("mod_failed") == [], rec
    (done,) = rec.of("mod_done")
    assert Path(done[1]).name == "VisualV_2.0.630_Enhanced.zip"              # from the second chunk, Enhanced
    assert rec.said("visualv", "opening VisualV_2.0.630_Enhanced.zip")
    assert rec.said("visualv", "pressed MediaFire's Download button")
    (hdr,) = [h for p, h in server.requests if "/file/b1/" in p][-1:]
    assert hdr.get("Referer", "").endswith("/folder/vv/VisualV")             # opened from the folder, like a click
    assert not [p for p, _ in server.requests if "/ads/" in p or "/file/a" in p or "Legacy" in p]


def test_mediafire_folder_without_the_version_fails_at_once(kit):
    dl, rec = make_dl(kit, ["visualvold"], idle_timeout=900)
    t0 = time.monotonic()
    dl.start()
    wait_until(lambda: rec.of("finished"), 60)
    assert time.monotonic() - t0 < 30                                        # not the 15-minute idle timeout
    ((mid, why),) = rec.of("mod_failed")
    assert mid == "visualvold" and "no file for version 2.0.630" in why and "30 files" in why
    assert "VisualV_1.0.380.rar" in why and rec.of("mod_done") == []
