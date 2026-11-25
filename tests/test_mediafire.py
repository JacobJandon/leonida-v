"""MediaFire (an author's own chosen host, e.g. VisualV's folder): the page hints, picking the file for the mod's
version from a folder, and the site's own Download button. The HTML mimics the real pages as read on 2026-11-25
(https://www.mediafire.com/folder/vrv4z3navwafa/VisualV and one of its file pages); no files are re-hosted."""

from __future__ import annotations

from leonida import pagehints as H

FOLDER = "https://www.mediafire.com/folder/vrv4z3navwafa/VisualV"
# the 35 files the real VisualV folder lists (2016-2018 builds, all .rar)
REAL_VERSIONS = ["1.0.010", "1.0.015", "1.0.020", "1.0.050", "1.0.050a", "1.0.075", "1.0.085", "1.0.090", "1.0.091",
                 "1.0.100", "1.0.110", "1.0.120", "1.0.130", "1.0.145", "1.0.150", "1.0.160", "1.0.200", "1.0.210",
                 "1.0.220", "1.0.230", "1.0.240", "1.0.250", "1.0.270", "1.0.280", "1.0.290", "1.0.295", "1.0.300",
                 "1.0.310", "1.0.320", "1.0.330", "1.0.340", "1.0.350", "1.0.360", "1.0.370", "1.0.380"]


def row(key: str, name: str, base: str = "https://www.mediafire.com", chunk: int = 1) -> str:
    """One file row as the real folder page renders it (li.mf_filecontainer, three links to the file page)."""
    href = f"{base}/file/{key}/{name.replace(' ', '_')}/file"
    click = f"window.MYF_DirectDownload({{files: ['{key}']}}); return false;"
    return (f'<li id="file-{key}" data-key="{key}" data-chunk="{chunk}" class="row_container mf_filecontainer file '
            f'archive public"><a href="{href}" onclick="{click}" class="thumbnailClickArea" title="{name}"></a>'
            f'<a class="filetype_column" href="{href}" onclick="{click}"><span><em>rar</em></span></a>'
            f'<div class="btns_column"><a href="javascript:void(0);" class="fileoptions">menu</a></div>'
            f'<div class="filename_outer cf"><a class="foldername" href="{href}">{name}</a></div>'
            f'<div class="file_maindetails"><span class="size">85 MB</span></div></li>')


def folder_html(names: list[str], base: str = "https://www.mediafire.com") -> str:
    rows = "".join(row(f"k{i:03d}", n, base) for i, n in enumerate(names))
    return (f'<div class="breadcrumb"><a href="{FOLDER}#myfiles">Shared Files</a></div><ul id="main_list">{rows}</ul>'
            '<a href="https://www.mediafire.com/help/">Help</a><div class="ad"><a href="https://ads.example/x">ad</a>'
            "</div><button>I Accept</button>")


FILE_PAGE = ('<div class="dl-btn-label">VisualV 2.0.630 Enhanced</div>'
             '<a class="input popsok" aria-label="Download file" href="https://download1511.mediafire.com/p33vv/k1/'
             'VisualV_2.0.630_Enhanced.zip" id="downloadButton" rel="nofollow">DOWNLOAD (85.44MB)</a>'
             '<a class="retry" href="https://www.mediafire.com/download_repair.php?qkey=k1">Repair your download</a>'
             '<a href="https://ads.example/download-now">Download now (ad)</a>')


def real_names() -> list[str]:
    return [f"VisualV {v}.rar" for v in REAL_VERSIONS]


def test_mediafire_hint_and_links():
    hint = H.hint_for(FOLDER)
    assert hint is not None and hint.site == "mediafire.com" and not hint.login_required and hint.wait_seconds == 0
    assert H.hint_for("https://mediafire.com/folder/x") is hint
    links = H.find_links(FOLDER, folder_html(real_names()[:3]))
    assert [u for _, u in links] == [f"https://www.mediafire.com/file/k00{i}/VisualV_{v}.rar/file"
                                     for i, v in enumerate(REAL_VERSIONS[:3])]   # one per file, no menus or ads
    file_url = "https://www.mediafire.com/file/k1/VisualV_2.0.630_Enhanced.zip/file"
    (step, target), = H.find_links(file_url, FILE_PAGE)
    assert target.startswith("https://download1511.mediafire.com/") and step.selector.startswith("a#downloadButton")
    assert hint.step_for(file_url) is step and step.wait_seconds == 0             # no countdown on MediaFire
    assert not step.accepts("https://ads.example/download-now")
    assert not hint.may_auto_follow(FOLDER)        # the folder needs a choice: the AutoDownloader makes it, not the page


def test_mediafire_files_from_a_folder():
    files = H.mediafire_files(FOLDER, folder_html(["VisualV 1.0.380.rar", "Readme v2.txt"]))
    assert files == [H.HostFile("VisualV_1.0.380.rar", "https://www.mediafire.com/file/k000/VisualV_1.0.380.rar/file"),
                     H.HostFile("Readme_v2.txt", "https://www.mediafire.com/file/k001/Readme_v2.txt/file")]


ARCHIVE = ("*VisualV*.zip", "*VisualV*.rar", "*VisualV*.7z")


def pick(names, version="", pick=None, archive=ARCHIVE):
    files = [H.HostFile(n.replace(" ", "_"), f"https://www.mediafire.com/file/k{i}/{n.replace(' ', '_')}/file")
             for i, n in enumerate(names)]
    f, why = H.choose_host_file(files, archive, pick, version)
    return (f.name if f else None), why


def test_the_real_visualv_folder_has_no_enhanced_2_0_630():
    """The real folder only holds the 2016-2018 builds: Leonida must not take one of those for 2.0.630 (Enhanced)."""
    name, why = pick(real_names(), "2.0.630 (Enhanced)", {"versionMatch": "(?i)enhanced"})
    assert name is None
    assert "no file for version 2.0.630" in why and "35 files" in why and "VisualV_1.0.380.rar" in why


def test_choosing_a_folder_file():
    names = real_names() + ["VisualV 2.0.630 Legacy.rar", "VisualV 2.0.630 Enhanced.zip", "VisualV 2.0.640.zip"]
    assert pick(names, "2.0.630 (Enhanced)", {"versionMatch": "(?i)enhanced"})[0] == "VisualV_2.0.630_Enhanced.zip"
    assert pick(names, "2.0.630")[0] == "VisualV_2.0.630_Enhanced.zip"     # Enhanced over Legacy
    assert pick(names, "1.0.38")[0] is None                                   # 1.0.380 is another version
    assert pick(names, "1.0.380")[0] == "VisualV_1.0.380.rar"
    assert pick(["VisualV.rar"], "2.0.630")[0] == "VisualV.rar"            # one file, no version in its name
    name, why = pick(["VisualV a.rar", "VisualV b.rar"], "")
    assert name is None and "2 files fit" in why                             # never a guess between several
    assert pick(["Other 2.0.630.zip"], "2.0.630")[0] is None                 # not the mod's archive name
    assert pick(names, "2.0.630", {"versionLabel": "visualv 2.0.630 legacy.rar"})[0] == "VisualV_2.0.630_Legacy.rar"
    assert pick([], "1")[1] == "no files"
