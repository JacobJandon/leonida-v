"""Google Drive (an author's own file host, e.g. Forza Horizon 6 Roads): the page hints and helpers, and the
AutoDownloader on local pages that mimic the real ones (read 2026-11-25): a file page whose Download buttons have no
link, Drive's "can't scan this file for viruses" page with its own "Download anyway" form, a shared folder."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from leonida import pagehints as H

FILE_ID = "1Fs2OC5UA13zey3L3TnUhxtx8G27bIrqw"
REAL_FILE = f"https://drive.google.com/file/d/{FILE_ID}/view"


def confirm_page(file_id: str, name: str, action: str = "https://drive.usercontent.google.com/download") -> str:
    """Drive's virus-scan warning page, as the real one is built (title, caption, the form and its button)."""
    return ("<title>Google Drive - Virus scan warning</title><div class='uc-main'><div id='uc-text'>"
            "<p class='uc-warning-caption'>Google Drive can't scan this file for viruses.</p>"
            f"<p class='uc-warning-subcaption'><span class='uc-name-size'><a href='/open?id={file_id}'>{name}</a> "
            "(2.4G)</span> is too large for Google to scan for viruses. Would you still like to download this file?"
            f"</p><form id='download-form' action='{action}' method='get'>"
            "<input type='submit' id='uc-download-link' class='goog-inline-block jfk-button jfk-button-action' "
            f"value='Download anyway'/><input type='hidden' name='id' value='{file_id}'>"
            "<input type='hidden' name='export' value='download'><input type='hidden' name='confirm' value='t'>"
            "</form></div></div>")


# Drive's file viewer: Download buttons labelled in the viewer's language, with no link of their own
FILE_PAGE = ("<div role='button' aria-label='Изтегляне' data-tooltip='Изтегляне'>Изтегляне</div>"
             "<button aria-label='Изтегляне' jsaction='click:h5M12e'></button><p>This file is too large to preview</p>")


def test_drive_hint_and_helpers():
    h = H.hint_for(REAL_FILE)
    assert h is not None and h.site == "drive.google.com" and not h.login_required and h.wait_seconds == 0
    assert h.step_for(REAL_FILE).css_class == "drive-file"
    assert H.drive_file_id(REAL_FILE) == FILE_ID
    url = H.drive_download_url(REAL_FILE)
    assert url == f"https://drive.google.com/uc?export=download&id={FILE_ID}" and h.step_for(REAL_FILE).accepts(url)
    confirm = f"https://drive.usercontent.google.com/download?id={FILE_ID}&export=download"
    assert H.hint_for(confirm) is h and h.step_for(confirm).css_class == "drive-confirm"
    assert H.drive_file_id(confirm) == FILE_ID
    folder = "https://drive.google.com/drive/folders/0B1abcDEFghiJKL"
    assert h.step_for(folder).css_class == "drive-folder"
    assert H.drive_download_url(folder) is None and H.drive_file_id("https://drive.google.com/?id=bad id") is None
    assert not h.may_auto_follow(REAL_FILE)          # the AutoDownloader decides, not the page


def test_drive_folder_files_and_choice():
    value = json.dumps([["FALK FH6 ROAD - GTA V LEGACY.rar", "1LegacyFileIdXYZ"],
                        ["FALK FH6 ROAD - GTA V ENHANCED.rar", "1EnhancedFileIdXYZ"], ["bad", "x y"], "junk"])
    files = H.parse_drive_folder(value, "https://drive.google.com/drive/folders/0Bfolder")
    assert files == [H.HostFile("FALK FH6 ROAD - GTA V LEGACY.rar", "https://drive.google.com/file/d/1LegacyFileIdXYZ/view"),
                     H.HostFile("FALK FH6 ROAD - GTA V ENHANCED.rar",
                                "https://drive.google.com/file/d/1EnhancedFileIdXYZ/view")]
    f, why = H.choose_host_file(files, ("*FH6*Road*.rar",), {"versionMatch": "(?i)enhanced"}, "1.0 (Enhanced)")
    assert why == "" and f.name.endswith("ENHANCED.rar")
    assert H.parse_drive_folder("not json", "https://drive.google.com/x") == []


# --------------------------------------------------------------------------------------- the AutoDownloader
pytest.importorskip("PySide6")
pytest.importorskip("PySide6.QtWebEngineWidgets")

import test_gui_autodl as G  # noqa: E402

from leonida.session import Session  # noqa: E402

server, browser = G.server, G.browser  # the module fixtures: one test server and browser window
html, serve_file, wait_until, zip_bytes = G.html, G.serve_file, G.wait_until, G.zip_bytes


def _local_drive(base: str):
    real = H.hint_for(REAL_FILE)
    b = re.escape(base)
    return dataclasses.replace(real, hosts=("127.0.0.1",), steps=tuple(
        dataclasses.replace(st, link_pattern=st.link_pattern.replace(r"^https://drive\.google\.com", f"^{b}"))
        for st in real.steps))


@pytest.fixture
def kit(tmp_path, server, browser, game):
    base = server.base
    mods = [{"id": mid, "order": i, "tier": "optional", "layer": "t", "name": mid.title(), "version": "1.0 (Enhanced)",
             "source": "direct", "page": f"{base}{page}", "archive": ["*FH6*Road*.zip"],
             "pick": {"versionMatch": "(?i)enhanced"}, "install": {"method": "guided", "steps": ["x"]}}
            for i, (mid, page) in enumerate((("bigfile", "/file/d/1BigFileIdABCDEF/view"),
                                             ("smallfile", "/file/d/1SmallFileIdABCD/view"),
                                             ("infolder", "/drive/folders/1FolderIdABCDEF")), 1)]
    d = tmp_path / "manifest"
    d.mkdir()
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "1", "mods": mods}))
    (d / "profiles.json").write_text(json.dumps({"default": "all", "profiles": [
        {"id": "all", "name": "All", "include": [m["id"] for m in mods]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    downloads = tmp_path / "dl"
    s = Session(tmp_path / "st", d, download_dir=str(downloads), game_dir=str(game), game_build="1.0.1013.20")
    browser.download_dir = downloads
    data = zip_bytes(tmp_path, "fh6.zip", {"FALK_FH6Roads/dlc.rpf": "rpf"})
    # a big file: the viewer, then Drive's "can't scan" page, then the file
    html(server, "/file/d/1BigFileIdABCDEF/view", FILE_PAGE)
    html(server, "/uc?export=download&id=1BigFileIdABCDEF",
         confirm_page("1BigFileIdABCDEF", "FALK FH6 ROAD - GTA V ENHANCED.zip", action="/download"))
    serve_file(server, "/download?id=1BigFileIdABCDEF&export=download&confirm=t", data)
    server.httpd.routes["/download?id=1BigFileIdABCDEF&export=download&confirm=t"].headers[
        "Content-Disposition"] = 'attachment; filename="FALK FH6 ROAD - GTA V ENHANCED.zip"'
    # a small file: the download link gives the file at once
    html(server, "/file/d/1SmallFileIdABCD/view", FILE_PAGE)
    serve_file(server, "/uc?export=download&id=1SmallFileIdABCD", data)
    server.httpd.routes["/uc?export=download&id=1SmallFileIdABCD"].headers[
        "Content-Disposition"] = 'attachment; filename="FH6 Roads small.zip"'
    # a shared folder with the Legacy and the Enhanced file
    rows = "".join(f"<div data-id='{fid}' role='row'><div data-tooltip='{name}'>{name}</div></div>"
                   for name, fid in (("FALK FH6 ROAD - GTA V LEGACY.zip", "1LegacyFileIdXYZ"),
                                     ("FALK FH6 ROAD - GTA V ENHANCED.zip", "1BigFileIdABCDEF")))
    html(server, "/drive/folders/1FolderIdABCDEF", rows)
    local = _local_drive(base)
    return s, browser, lambda url: local if url.startswith(base) else None


def _dl(kit, ids):
    from leonida.gui.autodl import AutoDownloader

    s, win, hints = kit
    dl = AutoDownloader(win, s, [s.manifest.mod(i) for i in ids], hints=hints, poll_ms=150)
    return dl, G.Recorder(dl)


def _requested(server, part):
    return [p for p, _ in server.requests if part in p]


def test_big_drive_file_through_download_anyway(kit, server):
    dl, rec = _dl(kit, ["bigfile"])
    dl.start()
    wait_until(lambda: rec.of("finished"), 60)
    assert rec.of("mod_failed") == [], rec
    ((mid, path),) = rec.of("mod_done")
    assert mid == "bigfile" and Path(path).name == "FALK FH6 ROAD - GTA V ENHANCED.zip"
    assert rec.said("bigfile", "opening Google Drive's download for this file")
    assert rec.said("bigfile", "pressed Google Drive's 'Download anyway'")


def test_small_drive_file_downloads_at_once(kit):
    dl, rec = _dl(kit, ["smallfile"])
    dl.start()
    wait_until(lambda: rec.of("finished"), 60)
    ((_mid, path),) = rec.of("mod_done")
    assert Path(path).name == "FH6 Roads small.zip" and not rec.said("smallfile", "Download anyway")


def test_drive_folder_picks_the_enhanced_file(kit, server):
    dl, rec = _dl(kit, ["infolder"])
    dl.start()
    wait_until(lambda: rec.of("finished"), 60)
    assert rec.said("infolder", "opening FALK FH6 ROAD - GTA V ENHANCED.zip"), rec
    assert rec.of("mod_done") and not _requested(server, "1LegacyFileIdXYZ")


def test_from_gta5mods_version_to_the_authors_drive(tmp_path, server, browser, game):
    """The real route (Forza Horizon 6 Roads): gta5-mods' "All Versions" entry '1.0 (Enhanced)' opens its download
    page, which sends you on to the author's Drive file; Leonida carries on there."""
    base = server.base
    mod = {"id": "fh6roads", "order": 1, "tier": "optional", "layer": "t", "name": "FH6 Roads", "version": "1.0",
           "source": "direct", "page": f"{base}/maps/fh6roads", "archive": ["*FH6*Road*.zip"],
           "pick": {"versionLabel": "1.0 (Enhanced)"}, "install": {"method": "guided", "steps": ["x"]}}
    d = tmp_path / "manifest"
    d.mkdir()
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "1", "mods": [mod]}))
    (d / "profiles.json").write_text(json.dumps({"default": "all", "profiles": [
        {"id": "all", "name": "All", "include": ["fh6roads"]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    s = Session(tmp_path / "st", d, download_dir=str(tmp_path / "dl"), game_dir=str(game), game_build="1.0.1013.20")
    browser.download_dir = tmp_path / "dl"
    rows = "".join(
        f'<div class="well pull-left file-version-container"><div class="pull-left">{label}<p>1 MB</p></div>'
        f'<div class="pull-right"><a href="/maps/fh6roads/download/{vid}">dl</a></div></div>'
        for label, vid in (("1.0 (Legacy) <span>(current)</span>", 2), ("1.0 (Enhanced)", 3)))
    html(server, "/maps/fh6roads", f'<a class="btn btn-download" href="/maps/fh6roads/download/2">Download</a>{rows}')
    html(server, "/maps/fh6roads/download/3", "<p>Your download starts in 1 second</p><script>setTimeout("
                 "function () { location.href = '/file/d/1RouteFileIdABCD/view'; }, 300);</script>")
    html(server, "/file/d/1RouteFileIdABCD/view", FILE_PAGE)
    serve_file(server, "/uc?export=download&id=1RouteFileIdABCD", zip_bytes(tmp_path, "r.zip", {"FALK_FH6Roads/x": "x"}))
    server.httpd.routes["/uc?export=download&id=1RouteFileIdABCD"].headers[
        "Content-Disposition"] = 'attachment; filename="FALK FH6 ROAD - GTA V ENHANCED.zip"'
    g5 = H.hint_for("https://www.gta5-mods.com/maps/x")
    drive = _local_drive(base)
    from leonida.gui.autodl import AutoDownloader

    dl = AutoDownloader(browser, s, [s.manifest.mod("fh6roads")], poll_ms=150, countdown_grace=1.0,
                        hints=lambda url: (g5 if "/maps/" in url else drive) if url.startswith(base) else None)
    rec = G.Recorder(dl)
    dl.start()
    wait_until(lambda: rec.of("finished"), 60)
    assert rec.said("fh6roads", "opening version '1.0 (Enhanced)'")
    assert rec.said("fh6roads", "opening Google Drive's download for this file")
    ((_mid, path),) = rec.of("mod_done")
    assert Path(path).name == "FALK FH6 ROAD - GTA V ENHANCED.zip"
    assert not _requested(server, "/maps/fh6roads/download/2")       # never the Legacy (current) file
