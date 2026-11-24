"""Page hints: per-site download-button descriptions, checked against small hand-written HTML fixtures that only
reproduce each site's structure (no copied pages)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from leonida.pagehints import (
    HINTS,
    NexusFile,
    choose,
    choose_nexus_file,
    find_links,
    highlight_script,
    hint_for,
    nexus_files,
    parse_highlight_result,
)

DEVC = """<html><body><h1>Script Hook V</h1>
<a href="/files/ScriptHookV_3889.0_1158.13.zip" target="_blank">Download</a>
<a href="/files/ScriptHookV_SDK_1.0.617.1a.zip" target="_blank">Download SDK</a>
<a href="/gtav/">Back</a></body></html>"""

GTA5MODS_MOD = """<div class="file-actions">
<a href="/maps/map-fixes/download/204369" class="btn btn-primary btn-download"><span class="fa fa-download"></span>Download</a>
</div><table class="versions">
<tr><td><a target="_blank" href="/maps/map-fixes/download/204370">21.8.1</a></td></tr>
<tr><td><a target="_blank" href="/maps/map-fixes/download/204369">21.8.2</a></td></tr></table>
<a href="/all/most-downloaded">Most Downloaded Files</a>"""

GTA5MODS_DOWNLOAD = """<h4>Click here to begin your download</h4><div class="panel-body"><p>
<a class="btn btn-primary btn-download" href="https://files.gta5-mods.com/uploads/map-fixes/abc123-MapFixes_v1.rar">Download</a>
</p><p>By downloading you agree to the <a href="/terms">Terms of Use</a>.</p>
<a href="/register?r=/maps/map-fixes/download/204369">Register here.</a>
<a href="/maps/map-fixes">Back to Map Fixes</a></div>"""

RAZED = """<a class="mod-hero_dl" role="button" tabindex="0" data-dl-modal="" data-dl-mod="gtavenhanced">DOWNLOAD</a>
<a href="https://patreon.com/razedmods" target="_blank">PATREON</a>
<div class="rm-mirrors">
<a class="rm-mirror_opt" role="button" data-dl-href="https://gofile.io/d/AAAA" data-dl-mirror="gofile">Gofile</a>
<a class="rm-mirror_opt" role="button" data-dl-href="https://pixeldrain.com/d/BBBB" data-dl-mirror="pixeldrain">Pixeldrain</a>
<a class="rm-mirror_opt" role="button" data-dl-href="https://evil.example/x">Elsewhere</a></div>"""

GITHUB_ASSETS = """<ul>
<li><a href="/o/r/releases/download/v2.8.2/Mod-2.8.2-Enhanced.oiv" rel="nofollow">Mod-2.8.2-Enhanced.oiv</a></li>
<li><a href="/o/r/releases/download/v2.8.2/Mod-2.8.2-Legacy.oiv" rel="nofollow">Mod-2.8.2-Legacy.oiv</a></li>
<li><a href="/o/r/archive/refs/tags/v2.8.2.zip" rel="nofollow">Source code (zip)</a></li></ul>"""

def _modal(name, category, uid, file_name=None):
    data = {"name": name, "category": category, "downloadUrl": f"https://www.nexusmods.com/api/files/{uid}/download"}
    if file_name:
        data["fileName"] = file_name
    return "<mod-download-modal file='" + json.dumps(data).replace("'", "&#39;") + "'></mod-download-modal>"


# The real files tab: a header button first (not a file), then one dt.file-expander-header + dd per file.
NEXUS_FILES = (
    '<header><div class="mod-actions">' + _modal("Drive V Main", 1, "hdr") + "</div></header>"
    '<div class="files-tabs"><h2>Main files</h2><dl class="accordion">'
    '<dt class="file-expander-header clearfix"><p>Drive V NVE</p></dt>'
    '<dd><div class="files-description">For NVE</div><div class="tabbed-block">'
    + _modal("Drive V NVE", 1, "uid-nve", "DriveV_NVE_2.1.7z") + "</div></dd>"
    '<dt class="file-expander-header clearfix"><p>Drive V Vanilla</p></dt>'
    "<dd><div><dd-inner></dd-inner>" + _modal("Drive V Vanilla", 1, "uid-vanilla", "DriveV_Vanilla_2.1.7z") + "</div></dd>"
    "</dl><h2>Optional files</h2><dl>"
    '<dt class="file-expander-header"><p>Extra sounds</p></dt><dd>' + _modal("Extra sounds", 3, "uid-opt") + "</dd>"
    "</dl><h2>Old files</h2><dl>"
    '<dt class="file-expander-header"><p>Drive V 1.0</p></dt><dd>' + _modal("Drive V 1.0", 4, "uid-old") + "</dd>"
    '<dt class="not-a-file"><p>x</p></dt><dd>' + _modal("Stray", 1, "uid-stray") + "</dd>"
    "</dl></div>")


def urls(links):
    return [u for _, u in links]


def test_hint_for_hosts():
    assert hint_for("https://www.dev-c.com/gtav/scripthookv/").site == "dev-c.com"
    assert hint_for("https://gta5-mods.com/scripts/x").site == "gta5-mods.com"
    assert hint_for("https://www.patreon.com/razedmods/posts/x-1").site == "patreon.com"
    assert hint_for("https://example.com/x") is None and hint_for("not a url") is None


def test_dev_c():
    url = "https://www.dev-c.com/gtav/scripthookv/"
    h = hint_for(url)
    assert urls(find_links(url, DEVC)) == ["https://www.dev-c.com/files/ScriptHookV_3889.0_1158.13.zip"]  # not the SDK
    assert h.may_auto_follow(url) and not h.login_required and h.wait_seconds == 0 and h.verified


def test_gta5mods_two_pages():
    mod = "https://www.gta5-mods.com/maps/map-fixes"
    h = hint_for(mod)
    first = find_links(mod, GTA5MODS_MOD)
    assert urls(first) == ["https://www.gta5-mods.com/maps/map-fixes/download/204369"]  # the main button, not the version list
    page2 = urls(first)[0]
    assert urls(find_links(page2, GTA5MODS_DOWNLOAD)) == ["https://files.gta5-mods.com/uploads/map-fixes/abc123-MapFixes_v1.rar"]
    assert "Terms of Use" in h.step_for(page2).label
    assert h.step_for(page2).starts_by_itself and "starts by itself" in h.step_for(page2).label
    # an older version's page shows a plain direct link (no btn-download class) after the countdown
    older = ('<p>Please wait</p><a href="https://files.gta5-mods.com/uploads/street-food-vendors-enhanced/'
             '51cc88-StreetFoodVenders.1.2.1.0-Enhanced.rar">StreetFoodVenders.rar</a>')
    assert urls(find_links(page2, older)) == ["https://files.gta5-mods.com/uploads/street-food-vendors-enhanced/"
                                              "51cc88-StreetFoodVenders.1.2.1.0-Enhanced.rar"]
    assert "older version shows a direct link" in h.step_for(page2).label
    assert not h.step_for(mod).starts_by_itself
    assert not h.may_auto_follow(mod) and not h.may_auto_follow(page2)  # Leonida never clicks here
    assert find_links("https://www.gta5-mods.com/de/maps/map-fixes", GTA5MODS_MOD.replace("/maps/", "/de/maps/"))


def test_razedmods_dialog_and_mirrors():
    url = "https://razedmods.com/gtavenhanced"
    h = hint_for(url)
    steps = h.steps_for(url)
    assert steps[0].selector == "a.mod-hero_dl[data-dl-modal]" and steps[0].link_attr == ""  # opens the dialog
    assert urls(find_links(url, RAZED)) == ["https://gofile.io/d/AAAA", "https://pixeldrain.com/d/BBBB"]  # not evil.example
    assert not h.may_auto_follow(url)


def test_github_release_assets_and_start_url():
    h = hint_for("https://github.com/o/r")
    assert h.start_url("https://github.com/o/r") == "https://github.com/o/r/releases/latest"
    assert h.start_url("https://github.com/o/r/releases/tag/v1") == "https://github.com/o/r/releases/tag/v1"
    rel = "https://github.com/o/r/releases/tag/v2.8.2"
    links = find_links(rel, GITHUB_ASSETS)
    assert urls(links) == ["https://github.com/o/r/releases/download/v2.8.2/Mod-2.8.2-Enhanced.oiv",
                           "https://github.com/o/r/releases/download/v2.8.2/Mod-2.8.2-Legacy.oiv"]  # no source zip
    assert h.may_auto_follow(rel) and not h.may_auto_follow("https://github.com/o/r/issues")
    assert choose(links, ["*-Legacy.oiv"]).endswith("Legacy.oiv")
    assert choose(links, ["*.oiv"]).endswith("Enhanced.oiv")    # prefers Enhanced when both match
    assert choose(links, ["nomatch*"]).endswith("Enhanced.oiv") and choose([], ["*"]) is None


def test_login_sites_are_never_automatic():
    for url in ("https://www.nexusmods.com/gta5enhanced/mods/1093", "https://www.nexusmods.com/gta5enhanced/mods/1093?tab=files",
                "https://www.patreon.com/razedmods/posts/naturalvision-147045704"):
        h = hint_for(url)
        assert h.login_required and not h.auto_follow and not h.may_auto_follow(url)
    assert hint_for("https://www.patreon.com/x/posts/y").verified == ""
    assert hint_for("https://www.nexusmods.com/x").verified  # checked in Leonida's browser
    mod = "https://www.nexusmods.com/gta5enhanced/mods/1093"
    assert hint_for(mod).step_for(mod).label == "Files tab"


FILES_TAB = "https://www.nexusmods.com/gta5enhanced/mods/1093?tab=files"


def test_nexus_files_skip_header_and_strays():
    files = nexus_files(NEXUS_FILES)
    assert [f.name for f in files] == ["Drive V NVE", "Drive V Vanilla", "Extra sounds", "Drive V 1.0"]
    assert [f.kind for f in files] == ["main", "main", "optional", "old"]
    assert files[0].download_url == "https://www.nexusmods.com/api/files/uid-nve/download"
    assert files[0].names() == ["Drive V NVE", "DriveV_NVE_2.1.7z"]
    step = hint_for(FILES_TAB).step_for(FILES_TAB)
    assert step.selector == "dt.file-expander-header + dd mod-download-modal" and step.shadow_selector == "a.nxm-button"
    assert urls(find_links(FILES_TAB, NEXUS_FILES)) == [f.download_url for f in files]


def test_nexus_files_ignore_bad_json_and_foreign_urls():
    bad = ('<dt class="file-expander-header"></dt><dd><mod-download-modal file="{not json"></mod-download-modal>'
           "<mod-download-modal file='[1, 2]'></mod-download-modal>"
           "<mod-download-modal file='{\"name\": \"x\", \"category\": \"main\", "
           "\"downloadUrl\": \"https://evil.example/x\"}'></mod-download-modal>"
           "<mod-download-modal file='{\"name\": \"ok\", \"category\": \"1\", "
           "\"downloadUrl\": \"https://www.nexusmods.com/api/files/u/download\"}'></mod-download-modal></dd>")
    files = nexus_files(bad)
    assert [(f.name, f.category) for f in files] == [("ok", 1)]
    assert nexus_files("") == [] and nexus_files("<dd><mod-download-modal file='{}'>") == []


def test_choose_nexus_file():
    files = nexus_files(NEXUS_FILES)
    assert choose_nexus_file(files, ["DriveV_Vanilla*"]).name == "Drive V Vanilla"
    assert choose_nexus_file(files, ["*NVE*"]).name == "Drive V NVE"
    assert choose_nexus_file(files, ["nomatch*"]).name == "Drive V NVE"          # first Main file
    assert choose_nexus_file(files).name == "Drive V NVE"
    only_extra = [f for f in files if f.category != 1]
    assert choose_nexus_file(only_extra, ["Extra*"]).name == "Extra sounds"
    assert choose_nexus_file(only_extra).name == "Extra sounds"                   # never an Old file first
    old = [f for f in files if f.kind == "old"]
    assert choose_nexus_file(old).name == "Drive V 1.0" and choose_nexus_file([]) is None
    assert NexusFile("x", None, "https://www.nexusmods.com/").kind == "unknown"


def test_needs_login():
    h = hint_for(FILES_TAB)
    assert h.needs_login("Log in to download") and h.needs_login("  register to download ")
    assert not h.needs_login("Manual download") and not h.needs_login("") and not h.needs_login(None)
    assert not hint_for("https://www.dev-c.com/gtav/scripthookv/").needs_login("Log in to download")


def test_highlight_script():
    target = "https://www.nexusmods.com/api/files/uid-vanilla/download"
    js = highlight_script(FILES_TAB, target)
    assert js.startswith("(function (sel, inner, jsonAttr, jsonKey, target, loginTexts)")
    args = json.loads("[" + js[js.rindex("})(") + 3:-2] + "]")
    assert args == ["dt.file-expander-header + dd mod-download-modal", "a.nxm-button", "file", "downloadUrl", target,
                    ["Log in to download", "Register to download"]]
    assert "shadowRoot" in js and ".click(" not in js  # points, never clicks
    dev = highlight_script("https://www.dev-c.com/gtav/scripthookv/")
    assert '"a[href^=\\"/files/\\"]' in dev and dev.endswith(", null, []);")
    assert highlight_script("https://example.com/") is None
    assert "JSON.stringify({found: true" in js  # PySide6 only passes strings/plain values back


def test_parse_highlight_result():
    ok = '{"found": true, "text": "Log in to download", "login": true, "target": "https://x", "extra": 1}'
    assert parse_highlight_result(ok) == {"found": True, "text": "Log in to download", "login": True, "target": "https://x"}
    assert parse_highlight_result({"found": True, "text": "Download"})["text"] == "Download"
    for bad in (None, "", "not json", "[1]", 3):
        assert parse_highlight_result(bad) == {"found": False, "text": "", "login": False, "target": None}
    assert highlight_script("https://www.nexusmods.com/users/1") is None  # no step for that page


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_highlight_script_is_valid_javascript(tmp_path):
    for url in (FILES_TAB, "https://www.dev-c.com/gtav/scripthookv/", "https://razedmods.com/gtavenhanced"):
        f = tmp_path / "h.js"
        f.write_text(highlight_script(url, "https://x/\"'</script>"), encoding="utf-8")
        res = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, timeout=60)
        assert res.returncode == 0, res.stderr


def test_hint_table_is_consistent():
    auto = {h.site for h in HINTS if h.auto_follow}
    assert auto == {"dev-c.com", "github.com"}
    for h in HINTS:
        assert not (h.auto_follow and h.login_required)
        for s in h.steps:
            re.compile(s.match)
            if s.link_pattern:
                re.compile(s.link_pattern)
                assert s.link_pattern.startswith("^https://") or s.link_pattern.startswith("[?&]"), s
            assert s.selector and s.label


@pytest.mark.parametrize("html", ["", "<a href=", "<<<>>>", "<a class='btn-download'>no href</a>"])
def test_broken_html(html):
    assert find_links("https://www.gta5-mods.com/maps/map-fixes", html) == []
