"""Where the real Download button is on each mod site, so the in-app browser can point at it (pure data + helpers).

This never bypasses anything. The GUI highlights the button and shows the hints. It follows a link by itself only
where ``PageHint.auto_follow`` is true: dev-c.com and github.com, plain author pages with no login, ads or countdown.
On every other site the user clicks; countdowns are shown and waited out, never skipped; login sites are only
pointed at.

Each ``Step`` is one page of a site's download flow:
  * ``match``         regex searched in the page's path + query, saying which page the step is for
  * ``selector``      CSS selector for ``document.querySelector`` in the browser (the element to highlight)
  * ``link_attr``     attribute holding the target URL ("href", or "data-dl-href" for razedmods' mirror buttons);
                      "" = the element opens a dialog and has no URL of its own
  * ``link_pattern``  regex the (absolute) target URL must match; used by ``find_links`` and as a safety check
  * ``wait_seconds``  countdown on that page before the link works (shown to the user, never skipped)
  * ``shadow_selector`` the real button inside the element's open shadow root (Nexus' ``a.nxm-button``)
  * ``starts_by_itself`` the site starts the download on its own (after its countdown): nothing to click

How the hints were made: the HTML of real mod pages was read on 2026-11-24 (dev-c.com, gta5-mods.com,
razedmods.com, github.com). nexusmods.com and patreon.com refuse non-browser clients (HTTP 403). The Nexus hints
were checked in Leonida's own browser the same day. Patreon's hints come from how the site is known to work and
are marked ``verified=""``.

gta5-mods "All Versions" list (mod page, read 2026-11-24): one ``div.file-version-container`` per version, whose
``div.pull-left`` text is the label ("21.8.2 Enhanced"; the main Download button's version also has
``<span>(current)</span>``) and whose ``div.pull-right a[href*="/download/"]`` (icon ``i.download-version``) opens
that version's /download/<id> page. The main Download button serves the "(current)" version, which for several
mods is the Legacy build: for a mod with a ``pick`` hint, use ``gta5mods_versions`` + ``pick_version`` or
``pick_version_script`` instead of the main button.

Nexus files tab: every file is a ``<mod-download-modal file='{json}'>`` inside ``dt.file-expander-header + dd``
(the first ``mod-download-modal`` on the page is the header button, not a file). The JSON has the file's
``name``, ``category`` (1 Main, 2 Update, 3 Optional, 4 Old, ...) and ``downloadUrl``. The buttons are
``a.nxm-button`` in the element's open shadow root; signed out they read "Log in to download" / "Register to
download". ``nexus_files`` + ``choose_nexus_file`` pick the right file, ``highlight_script`` points at its button
and reports whether the user has to sign in first.

MediaFire (read 2026-11-25: VisualV's folder https://www.mediafire.com/folder/vrv4z3navwafa/VisualV and a file page):
an author may keep a folder there. A folder page lists one ``li.mf_filecontainer`` per file whose ``a.foldername``
(text = the name) links to the file page ``https://www.mediafire.com/file/<key>/<name>/file``; the list is loaded in
chunks as it is scrolled (28 rows first, 35 in all for VisualV). The file page's own button is ``a#downloadButton``,
whose href is the direct ``https://download<n>.mediafire.com/...`` link; no countdown, no sign-in. ``mediafire_files``
+ ``choose_host_file`` pick the file for the mod's version (never a guess between several).
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

VERIFIED = "2026-11-24"


@dataclass(frozen=True)
class Step:
    match: str
    selector: str
    label: str
    link_attr: str = "href"
    link_pattern: str = ""
    css_class: str = ""          # extra check for find_links: the element must have this class
    wait_seconds: int = 0
    shadow_selector: str = ""    # the button inside the element's open shadow root
    json_attr: str = ""          # attribute holding JSON with the target (Nexus: "file")
    json_key: str = ""           # key of the target URL in that JSON (Nexus: "downloadUrl")
    starts_by_itself: bool = False  # the site starts the download itself (after its countdown)

    def applies(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        return re.search(self.match, parts.path + (f"?{parts.query}" if parts.query else "")) is not None

    def accepts(self, target: str) -> bool:
        return bool(self.link_pattern) and re.search(self.link_pattern, target) is not None


@dataclass(frozen=True)
class PageHint:
    site: str
    hosts: tuple[str, ...]
    steps: tuple[Step, ...]
    login_required: bool = False
    auto_follow: bool = False     # the GUI may open the found link itself (only plain pages without gates)
    verified: str = ""            # date the selectors were checked against the real site ("" = not checked)
    notes: str = ""
    start: tuple[str, str] | None = None  # (regex, replacement) on the path: a better page to start on
    login_texts: tuple[str, ...] = field(default=())  # button texts that mean "sign in first"

    def needs_login(self, button_text: str | None) -> bool:
        """True when a button's text says the user must sign in first (e.g. Nexus' "Log in to download")."""
        low = (button_text or "").strip().lower()
        return bool(low) and any(t.lower() in low for t in self.login_texts)

    @property
    def wait_seconds(self) -> int:
        return max((s.wait_seconds for s in self.steps), default=0)

    def steps_for(self, url: str) -> list[Step]:
        return [s for s in self.steps if s.applies(url)]

    def step_for(self, url: str) -> Step | None:
        steps = self.steps_for(url)
        return steps[0] if steps else None

    def start_url(self, url: str) -> str:
        """Where to open the browser for ``url`` (e.g. a GitHub repo -> its latest release)."""
        if not self.start:
            return url
        parts = urllib.parse.urlsplit(url)
        path, n = re.subn(self.start[0], self.start[1], parts.path)
        return urllib.parse.urlunsplit(parts._replace(path=path, query="", fragment="")) if n else url

    def may_auto_follow(self, url: str) -> bool:
        """True only where Leonida may follow the found link by itself on this page."""
        step = self.step_for(url)
        return bool(self.auto_follow and not self.login_required and step and step.link_attr and not step.wait_seconds)


HINTS: tuple[PageHint, ...] = (
    PageHint(
        site="dev-c.com",
        hosts=("dev-c.com", "www.dev-c.com"),
        steps=(Step(match=r"^/gtav/[^/]+/?$",
                    selector='a[href^="/files/"][href$=".zip"]:not([href*="SDK"])',
                    label="Download (the plain zip; skip 'Download SDK')",
                    link_pattern=r"^https://(www\.)?dev-c\.com/files/(?![^/]*SDK)[^/]+\.zip$"),),
        auto_follow=True,
        verified=VERIFIED,
        notes="Alexander Blade's page: one plain link per file, no login, ads or countdown.",
    ),
    PageHint(
        site="gta5-mods.com",
        hosts=("gta5-mods.com", "www.gta5-mods.com"),
        steps=(
            Step(match=r"/download/\d+/?$",
                 selector='a[href*="files.gta5-mods.com/uploads/"]',
                 label="The current version's download starts by itself after the page's countdown; an older "
                       "version shows a direct link after the countdown instead: click it "
                       "(by downloading you accept the GTA5-Mods.com Terms of Use)",
                 link_pattern=r"^https://files\.gta5-mods\.com/uploads/",
                 starts_by_itself=True),
            Step(match=r"^/(?:[a-z]{2}/)?[a-z-]+/[^/]+/?$",
                 selector='a.btn-download[href*="/download/"]',
                 label="Download (newest version; opens the download page)",
                 link_pattern=r"^https://(www\.)?gta5-mods\.com/(?:[a-z]{2}/)?[a-z-]+/[^/]+/download/\d+$",
                 css_class="btn-download"),
        ),
        verified=VERIFIED,
        notes="Two pages: the mod page's Download button opens /download/<id>. For the current version that page "
              "shows a countdown and then starts the download by itself (seen in Leonida's browser, 22 files). "
              "A non-current version from 'All Versions' shows a direct link a[href*=\"files.gta5-mods.com/uploads/\"] "
              "after the countdown instead, which has to be clicked. A /download/<id> page loaded directly (without "
              "the mod page as Referer) starts nothing: reach it from the mod page.",
    ),
    PageHint(
        site="razedmods.com",
        hosts=("razedmods.com", "www.razedmods.com"),
        steps=(
            Step(match=r"^/",
                 selector="a.mod-hero_dl[data-dl-modal]",
                 label="Download (opens the list of mirrors)",
                 link_attr=""),
            Step(match=r"^/",
                 selector="a.rm-mirror_opt[data-dl-href]",
                 label="Pick a mirror (gofile or pixeldrain), then press Download on the mirror's page",
                 link_attr="data-dl-href",
                 link_pattern=r"^https://(gofile\.io|pixeldrain\.com)/",
                 css_class="rm-mirror_opt"),
        ),
        verified=VERIFIED,
        notes="The page is built by JavaScript (its body comes from /_pages/<hash>.html). The hero Download button "
              "opens a dialog with mirror buttons whose data-dl-href is the file host's page. Older NVE builds "
              "are on Razed's Patreon.",
    ),
    PageHint(
        site="github.com",
        hosts=("github.com", "www.github.com"),
        steps=(Step(match=r"^/[^/]+/[^/]+/releases(/latest|/tag/[^/]+)?/?$",
                    selector='a[href*="/releases/download/"]',
                    label="Release asset (the .zip/.7z under Assets)",
                    link_pattern=r"^https://github\.com/[^/]+/[^/]+/releases/download/[^/]+/[^/]+$"),),
        auto_follow=True,
        verified=VERIFIED,
        notes="Assets load after the page (an include-fragment from /releases/expanded_assets/<tag>), so wait for "
              "the selector to appear. Source-code zips are not release assets and don't match. Mods with a "
              "'download' spec in mods.json are fetched through the GitHub API instead.",
        start=(r"^/([^/]+)/([^/]+)/?$", r"/\1/\2/releases/latest"),
    ),
    PageHint(
        site="nexusmods.com",
        hosts=("nexusmods.com", "www.nexusmods.com"),
        steps=(
            Step(match=r"[?&]file_id=\d+",
                 selector="#slowDownloadButton, button[data-download-type='slow']",
                 label="Slow download (free account; Nexus may show a short wait)",
                 link_attr=""),
            Step(match=r"[?&]tab=files",
                 selector="dt.file-expander-header + dd mod-download-modal",
                 label="Download the Main file (sign in to Nexus first)",
                 link_attr="",
                 link_pattern=r"^https://(www\.)?nexusmods\.com/api/files/[^/?#]+/download",
                 shadow_selector="a.nxm-button",
                 json_attr="file",
                 json_key="downloadUrl"),
            Step(match=r"^/[^/]+/mods/\d+/?$",
                 selector='a[href*="tab=files"]',
                 label="Files tab",
                 link_pattern=r"[?&]tab=files"),
        ),
        login_required=True,
        login_texts=("Log in to download", "Register to download"),
        verified=VERIFIED,
        notes="Needs a (free) Nexus account and the user's own sign-in in the browser. Never click for the user. "
              "Files tab: pick the file with nexus_files()/choose_nexus_file() and point at it with "
              "highlight_script(); its result says when the button reads 'Log in to download'.",
    ),
    PageHint(
        site="mediafire.com",
        hosts=("mediafire.com", "www.mediafire.com"),
        steps=(
            Step(match=r"^/file/[a-z0-9]+/",
                 selector='a#downloadButton[href*=".mediafire.com/"]',
                 label="Download (the site's own button; no countdown)",
                 link_pattern=r"^https://download\d*\.mediafire\.com/"),
            Step(match=r"^/folder/[a-z0-9]+",
                 selector='li.mf_filecontainer a.foldername[href*="/file/"]',
                 label="Pick the file for your game build (the folder lists every version), then press Download",
                 link_pattern=r"^https://(www\.)?mediafire\.com/file/[a-z0-9]+/[^/]+(/file)?/?$",
                 css_class="foldername"),
        ),
        verified="2026-11-25",
        notes="An author's own file host (e.g. VisualV's 'Previous versions' folder). Folder: one row per file, "
              "loaded in chunks while scrolling; the file page's a#downloadButton links straight to "
              "download<n>.mediafire.com. No sign-in, no countdown; the page's ads are left alone.",
    ),
    PageHint(
        site="patreon.com",
        hosts=("patreon.com", "www.patreon.com"),
        steps=(Step(match=r"/posts/",
                    selector='a[href*="patreon.com/file?"], a[href^="/file?"]',
                    label="Post attachment (needs the creator's membership)",
                    link_pattern=r"^https://(www\.)?patreon\.com/file\?"),),
        login_required=True,
        notes="Attachments only show to signed-in members (paid tiers for most files). Never click for the user. "
              "Selectors not verified: patreon.com refuses non-browser clients.",
    ),
)


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def hint_for(url: str) -> PageHint | None:
    """The hint for the site ``url`` is on, or None for a site without one."""
    host = _host(url)
    return next((h for h in HINTS if host in h.hosts), None)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("a", "button"):
            self.elements.append({k.lower(): (v or "") for k, v in attrs})


def find_links(url: str, html: str, hint: PageHint | None = None) -> list[tuple[Step, str]]:
    """Download targets on this page per the site's hint: [(step, absolute URL)], in page order, no duplicates.

    Pure Python, for tests and as a fallback when the GUI only has the HTML. Steps without a URL (dialogs,
    buttons) aren't returned; use ``Step.selector`` in the browser for those. ``hint`` overrides the lookup by host."""
    hint = hint or hint_for(url)
    if hint is None:
        return []
    parser = _Links()
    with contextlib.suppress(Exception):  # broken HTML: keep what was parsed
        parser.feed(html)
    out: list[tuple[Step, str]] = []
    seen: set[str] = set()
    for step in hint.steps_for(url):
        if step.json_attr:
            for f in nexus_files(html):
                if step.accepts(f.download_url) and f.download_url not in seen:
                    seen.add(f.download_url)
                    out.append((step, f.download_url))
            continue
        if not step.link_attr:
            continue
        for attrs in parser.elements:
            raw = attrs.get(step.link_attr)
            if not raw:
                continue
            if step.css_class and step.css_class not in attrs.get("class", "").split():
                continue
            target = urllib.parse.urljoin(url, raw)
            if step.accepts(target) and target not in seen:
                seen.add(target)
                out.append((step, target))
    return out


def choose(links: list[tuple[Step, str]], archive: tuple[str, ...] | list[str] = ()) -> str | None:
    """The best target for a mod: one whose file name matches the mod's ``archive`` patterns if any do, preferring
    Enhanced over Legacy builds; else the first link. None when there are no links."""
    urls = [u for _, u in links]
    if not urls:
        return None

    def name(u: str) -> str:
        return urllib.parse.unquote(urllib.parse.urlsplit(u).path.rsplit("/", 1)[-1]).lower()

    hits = [u for u in urls if any(fnmatch.fnmatchcase(name(u), p.lower()) for p in archive)] or urls
    return min(hits, key=lambda u: (("legacy" in name(u)) - ("enhanced" in name(u)), hits.index(u)))


# --------------------------------------------------------------------------------- file hosts (MediaFire folders)
@dataclass(frozen=True)
class HostFile:
    name: str   # the file name (from the file page URL: "VisualV_1.0.380.rar")
    url: str    # its file page


def _host_file_name(url: str) -> str:
    parts = [p for p in urllib.parse.urlsplit(url).path.split("/") if p]
    # /file/<key>/<name>/file
    return urllib.parse.unquote(parts[2]) if len(parts) >= 3 and parts[0] == "file" else ""


def mediafire_files(page_url: str, html: str) -> list[HostFile]:
    """The files a MediaFire folder page lists (the rows rendered so far), in page order."""
    out = []
    for _step, url in find_links(page_url, html):
        name = _host_file_name(url)
        if name:
            out.append(HostFile(name, url))
    return out


_VERSION_RX = re.compile(r"\d+(?:\.\d+)+[a-z]?")


def version_number(version: str) -> str | None:
    """The first version number in a manifest version ("2.0.630" of "2.0.630 (Enhanced)"), lower case, or None."""
    m = _VERSION_RX.search(version or "")
    return m.group(0).lower() if m else None


def choose_host_file(files: list[HostFile], archive: tuple[str, ...] | list[str] = (), pick: dict | None = None,
                     version: str = "") -> tuple[HostFile | None, str]:
    """The file to download from a host folder for a mod: (file, "") or (None, why).

    Only files whose name fits the mod's ``archive`` patterns count. A ``pick`` hint ({"versionLabel"} / {"versionMatch"},
    as for gta5-mods) narrows them when it matches any name. The mod's ``version`` (its first number, "2.0.630" of
    "2.0.630 (Enhanced)") must be in the name, unless a single file fits and no fitting name carries a version at all.
    Enhanced beats Legacy between files of the same version. Several files left without a version to tell them
    apart: None (never a guess)."""
    if not files:
        return None, "no files"

    def spaced(n: str) -> str:
        return n.replace("_", " ").lower()

    cands = [f for f in files if not archive or any(fnmatch.fnmatchcase(f.name.lower(), p.lower()) or
                                                    fnmatch.fnmatchcase(spaced(f.name), p.lower()) for p in archive)]
    if pick and cands:
        if "versionLabel" in pick:
            want = " ".join(str(pick["versionLabel"]).split()).lower()
            hit = [f for f in cands if spaced(f.name) == want]
        else:
            try:
                rx = re.compile(str(pick.get("versionMatch", "")))
            except re.error:
                rx = None
            hit = [f for f in cands if rx and rx.search(spaced(f.name))]
        cands = hit or cands
    names = [f.name for f in files]
    listing = f"it has {len(files)} files: " + (", ".join(names) if len(names) <= 4 else
                                                 f"{names[0]}, {names[1]} ... {names[-1]}")
    v = version_number(version)
    m = v is not None
    if m:
        rx = re.compile(rf"(?<![\d.]){re.escape(v)}(?![\d])")
        with_v = [f for f in cands if rx.search(f.name.lower())]
        if not with_v and len(cands) == 1 and not _VERSION_RX.search(cands[0].name.lower()):
            with_v = cands
        if not with_v:
            return None, f"no file for version {v} ({listing})"
        cands = with_v
    if not cands:
        return None, f"no file that fits the mod's file names ({listing})"
    cands.sort(key=lambda f: ("legacy" in f.name.lower()) - ("enhanced" in f.name.lower()))
    if len(cands) > 1 and not m:
        best = [f for f in cands if (("legacy" in f.name.lower()) - ("enhanced" in f.name.lower())) ==
                (("legacy" in cands[0].name.lower()) - ("enhanced" in cands[0].name.lower()))]
        if len(best) > 1:
            return None, f"{len(best)} files fit and nothing tells them apart: " + ", ".join(f.name for f in best)
    return cands[0], ""


# Collect the rows a MediaFire folder page has rendered (kept across calls in window.__leonidaFiles), then scroll one
# screen further so the next chunk loads, as a person scrolling the list would. Evaluates to JSON {files, end}.
_SCAN_JS = r"""(function (rowSel, linkSel) {
  var seen = window.__leonidaFiles || (window.__leonidaFiles = []);
  document.querySelectorAll(rowSel).forEach(function (row) {
    var a = row.querySelector(linkSel);
    if (a && seen.indexOf(a.href) === -1) { seen.push(a.href); }
  });
  var before = window.scrollY;
  window.scrollBy(0, Math.max(400, window.innerHeight - 100));
  var end = window.scrollY === before;
  return JSON.stringify({files: seen, end: end});
})"""


def folder_scan_script(row_selector: str = "li.mf_filecontainer", link_selector: str = 'a.foldername[href*="/file/"]') -> str:
    """JavaScript for ``runJavaScript`` on a MediaFire folder page (see ``_SCAN_JS``); never clicks."""
    return _SCAN_JS + "(" + json.dumps(row_selector) + ", " + json.dumps(link_selector) + ");"


def parse_scan_result(value, step: Step | None = None) -> tuple[list[HostFile], bool]:
    """The ``runJavaScript`` value of ``folder_scan_script``: (files whose links ``step`` accepts, at the end)."""
    try:
        data = json.loads(value) if isinstance(value, str) and value else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return [], False
    out = []
    for url in data.get("files") or []:
        if isinstance(url, str) and (step is None or step.accepts(url)) and _host_file_name(url):
            out.append(HostFile(_host_file_name(url), url))
    return out, bool(data.get("end"))


# ------------------------------------------------------------------------------------------------- Nexus files
NEXUS_CATEGORIES = {1: "main", 2: "update", 3: "optional", 4: "old", 5: "miscellaneous", 6: "deleted", 7: "archived"}


@dataclass(frozen=True)
class NexusFile:
    name: str
    category: int | None
    download_url: str
    data: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def kind(self) -> str:
        return NEXUS_CATEGORIES.get(self.category or 0, "unknown")

    def names(self) -> list[str]:
        """Every name the JSON gives (display name, file name) for matching against archive patterns."""
        keys = ("name", "fileName", "file_name", "uri")
        return [str(self.data[k]) for k in keys if isinstance(self.data.get(k), str) and self.data[k]]


class _NexusFiles(HTMLParser):
    """``mod-download-modal`` elements inside ``dt.file-expander-header + dd`` (not the header button)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.after_header = False   # the last <dt> closed was a file header
        self.dd_depth = 0           # >0 while inside the <dd> that follows it
        self.files: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "dt":
            self.after_header = "file-expander-header" in a.get("class", "").split()
        elif tag == "dd":
            if self.dd_depth:
                self.dd_depth += 1
            elif self.after_header:
                self.dd_depth = 1
            self.after_header = False
        elif tag == "mod-download-modal" and self.dd_depth and a.get("file"):
            try:
                data = json.loads(a["file"])
            except ValueError:
                return
            if isinstance(data, dict):
                self.files.append(data)

    def handle_endtag(self, tag):
        if tag == "dd" and self.dd_depth:
            self.dd_depth -= 1


def nexus_files(html: str, url_ok=None) -> list[NexusFile]:
    """The files listed on a Nexus files tab, in page order (the header button is not a file)."""
    parser = _NexusFiles()
    with contextlib.suppress(Exception):
        parser.feed(html)
    out = []
    for d in parser.files:
        url = d.get("downloadUrl")
        ok = url_ok(url) if url_ok and isinstance(url, str) else (
            isinstance(url, str) and re.match(r"^https://(www\.)?nexusmods\.com/", url))
        if not isinstance(url, str) or not ok:
            continue
        cat = d.get("category")
        try:
            cat = int(cat) if cat is not None else None
        except (TypeError, ValueError):
            cat = None
        out.append(NexusFile(str(d.get("name") or ""), cat, url, d))
    return out


def choose_nexus_file(files: list[NexusFile], archive: tuple[str, ...] | list[str] = ()) -> NexusFile | None:
    """The file to download for a mod: a Main file (category 1) whose name matches the mod's archive patterns,
    else the first Main file, else any file matching the patterns. Old/archived files are never picked unless
    nothing else exists. None when there are no files."""
    def matches(f: NexusFile) -> bool:
        return any(fnmatch.fnmatchcase(n.lower(), p.lower()) for n in f.names() for p in archive)

    main = [f for f in files if f.category == 1]
    current = [f for f in files if f.kind not in ("old", "deleted", "archived")]
    for group in ([f for f in main if matches(f)], main, [f for f in current if matches(f)], current,
                  [f for f in files if matches(f)], files):
        if group:
            return group[0]
    return None


# -------------------------------------------------------------------------------------------- browser script
_HIGHLIGHT_JS = r"""(function (sel, inner, jsonAttr, jsonKey, target, loginTexts) {
  function deep(root, s) {
    var out = Array.prototype.slice.call(root.querySelectorAll(s));
    root.querySelectorAll('*').forEach(function (e) { if (e.shadowRoot) { out = out.concat(deep(e.shadowRoot, s)); } });
    return out;
  }
  function targetOf(e) {
    if (jsonAttr) {
      try { return JSON.parse(e.getAttribute(jsonAttr) || '{}')[jsonKey] || null; } catch (err) { return null; }
    }
    var h = e.getAttribute('href') || e.getAttribute('data-dl-href');
    return h ? new URL(h, location.href).href : null;
  }
  var els = deep(document, sel);
  if (target) { els = els.filter(function (e) { return targetOf(e) === target; }); }
  if (!els.length) { return JSON.stringify({found: false, text: '', login: false, target: null}); }
  var el = els[0], btn = el;
  if (inner) {
    var root = el.shadowRoot;
    var b = root ? root.querySelector(inner) : el.querySelector(inner);
    if (b) { btn = b; }
  }
  btn.style.outline = '3px solid #ff2d95';
  btn.style.outlineOffset = '3px';
  btn.style.borderRadius = '4px';
  btn.scrollIntoView({block: 'center', behavior: 'smooth'});
  var text = (btn.innerText || btn.textContent || '').trim();
  var low = text.toLowerCase();
  var login = loginTexts.some(function (t) { return low.indexOf(t.toLowerCase()) !== -1; });
  return JSON.stringify({found: true, text: text, login: login, target: targetOf(el)});
})"""


def highlight_script(url: str, target: str | None = None, hint: PageHint | None = None) -> str | None:
    """JavaScript for ``QWebEnginePage.runJavaScript`` on ``url``: outlines the download button of the page's
    first step (searching open shadow roots too, e.g. Nexus' ``a.nxm-button``). It evaluates to a JSON string
    (PySide6 drops plain JS objects): pass the callback's value to ``parse_highlight_result`` to get
    ``{found, text, login, target}``. ``login`` is true when the button says to sign in first. ``target`` (a URL
    from ``find_links``/``choose_nexus_file``) picks which of several buttons. It never clicks.
    None when there is no hint for this page."""
    hint = hint or hint_for(url)
    step = hint.step_for(url) if hint else None
    if step is None:
        return None
    args = [step.selector, step.shadow_selector, step.json_attr, step.json_key, target, list(hint.login_texts)]
    return _HIGHLIGHT_JS + "(" + ", ".join(json.dumps(a) for a in args) + ");"


def parse_highlight_result(value) -> dict:
    """The ``runJavaScript`` callback value of ``highlight_script`` as {found, text, login, target}
    (a failed or missing result counts as not found)."""
    empty = {"found": False, "text": "", "login": False, "target": None}
    if isinstance(value, dict):
        data = value
    else:
        try:
            data = json.loads(value) if isinstance(value, str) and value else {}
        except ValueError:
            data = {}
    if not isinstance(data, dict):
        return empty
    return {**empty, **{k: data[k] for k in empty if k in data}}


# ------------------------------------------------------------------------------------ gta5-mods "All Versions"
VERSION_ROW = "div.file-version-container"
VERSION_LABEL = "div.pull-left"
VERSION_LINK = 'div.pull-right a[href*="/download/"]'


@dataclass(frozen=True)
class ModVersion:
    label: str        # "21.8.2 Enhanced" (without "(current)")
    url: str          # absolute https://www.gta5-mods.com/.../download/<id>
    current: bool     # the version the main Download button serves


class _Versions(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.depth = 0          # div depth inside the current row (0 = not in a row)
        self.label_depth = 0    # div depth of the row's div.pull-left while reading its label
        self.in_p = False
        self.row: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        classes = a.get("class", "").split()
        if tag == "div":
            if self.depth:
                self.depth += 1
                if "pull-left" in classes and self.row is not None and not self.row["label_done"]:
                    self.label_depth = self.depth
            elif "file-version-container" in classes:
                self.depth = 1
                self.row = {"label": "", "current": False, "url": None, "label_done": False}
                self.rows.append(self.row)
        elif tag == "p" and self.label_depth:
            self.in_p = True
        elif tag == "a" and self.depth and self.row is not None and self.row["url"] is None:
            href = a.get("href", "")
            if "/download/" in href:
                self.row["url"] = href

    def handle_endtag(self, tag):
        if tag == "p":
            self.in_p = False
        elif tag == "div" and self.depth:
            if self.label_depth == self.depth:
                self.label_depth = 0
                if self.row is not None:
                    self.row["label_done"] = True
            self.depth -= 1
            if self.depth == 0:
                self.row = None

    def handle_data(self, data):
        if self.label_depth and not self.in_p and self.row is not None:
            self.row["label"] += data


def gta5mods_versions(page_url: str, html: str) -> list[ModVersion]:
    """The entries of a gta5-mods mod page's "All Versions" list, in page order (duplicates removed)."""
    parser = _Versions()
    with contextlib.suppress(Exception):
        parser.feed(html)
    out, seen = [], set()
    for r in parser.rows:
        if not r["url"]:
            continue
        url = urllib.parse.urljoin(page_url, r["url"])
        if url in seen or not re.match(r"^https://(www\.)?gta5-mods\.com/.+/download/\d+$", url):
            continue
        seen.add(url)
        text = " ".join(r["label"].split())
        current = "(current)" in text.lower()
        label = re.sub(r"\s*\(current\)\s*", " ", text, flags=re.I).strip()
        out.append(ModVersion(label, url, current))
    return out


def pick_version(versions: list[ModVersion], pick: dict | None) -> ModVersion | None:
    """The version a mod's ``pick`` hint names: {"versionLabel": exact label, case-insensitive} or
    {"versionMatch": regex searched in the label} (first hit). None when nothing fits or there's no hint."""
    if not pick:
        return None
    if "versionLabel" in pick:
        want = " ".join(str(pick["versionLabel"]).split()).lower()
        return next((v for v in versions if v.label.lower() == want), None)
    try:
        rx = re.compile(str(pick.get("versionMatch", "")))
    except re.error:
        return None
    return next((v for v in versions if rx.search(v.label)), None)


_PICK_JS = r"""(function (rowSel, labelSel, linkSel, label, pattern) {
  var rx = null;
  if (pattern !== null) {
    var flags = '';
    if (pattern.indexOf('(?i)') === 0) { pattern = pattern.slice(4); flags = 'i'; }
    try { rx = new RegExp(pattern, flags); } catch (e) { return JSON.stringify({found: false, error: String(e)}); }
  }
  function labelOf(box) {
    var text = '';
    box.childNodes.forEach(function (n) {
      if (n.nodeType === 3 || (n.nodeType === 1 && n.tagName !== 'P')) { text += ' ' + n.textContent; }
    });
    return text.replace(/\(current\)/i, ' ').replace(/\s+/g, ' ').trim();
  }
  var rows = Array.prototype.slice.call(document.querySelectorAll(rowSel)), labels = [];
  for (var i = 0; i < rows.length; i++) {
    var box = rows[i].querySelector(labelSel), link = rows[i].querySelector(linkSel);
    if (!box || !link) { continue; }
    var text = labelOf(box);
    if (labels.indexOf(text) === -1) { labels.push(text); }
    if (rx ? rx.test(text) : text.toLowerCase() === label.toLowerCase()) {
      link.style.outline = '3px solid #ff2d95';
      link.style.outlineOffset = '3px';
      rows[i].scrollIntoView({block: 'center', behavior: 'smooth'});
      return JSON.stringify({found: true, label: text, href: link.href, labels: labels});
    }
  }
  return JSON.stringify({found: false, label: '', href: null, labels: labels});
})"""


def pick_version_script(pick: dict | None) -> str | None:
    """JavaScript for ``runJavaScript`` on a gta5-mods mod page: finds the "All Versions" entry the ``pick`` hint
    names, outlines its download icon and evaluates to a JSON string {found, label, href, labels} (``href`` = that
    version's /download/<id> page; ``labels`` = every label seen, for "no matching version" messages). Python's
    "(?i)" prefix is turned into a JS "i" flag. It never clicks. None without a hint."""
    if not pick:
        return None
    label = pick.get("versionLabel")
    pattern = pick.get("versionMatch")
    args = [VERSION_ROW, VERSION_LABEL, VERSION_LINK, label or "", pattern if label is None else None]
    return _PICK_JS + "(" + ", ".join(json.dumps(a) for a in args) + ");"


def parse_pick_result(value) -> dict:
    """The ``runJavaScript`` value of ``pick_version_script`` as {found, label, href, labels}."""
    empty = {"found": False, "label": "", "href": None, "labels": []}
    try:
        data = value if isinstance(value, dict) else json.loads(value) if isinstance(value, str) and value else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return empty
    out = {**empty, **{k: data[k] for k in empty if k in data}}
    href = out["href"]
    if href and not re.match(r"^https://(www\.)?gta5-mods\.com/.+/download/\d+$", str(href)):
        out.update(found=False, href=None)  # never follow anything but a gta5-mods version download page
    return out


# ------------------------------------------------------------------------------- following a site's own buttons
_CLICK_JS = r"""(function (selector, texts, visibleOnly) {
  function deep(root, sel) {
    var out = Array.prototype.slice.call(root.querySelectorAll(sel));
    root.querySelectorAll('*').forEach(function (e) { if (e.shadowRoot) { out = out.concat(deep(e.shadowRoot, sel)); } });
    return out;
  }
  var els = deep(document, selector || 'a, button, [role="button"]');
  for (var i = 0; i < els.length; i++) {
    var el = els[i], t = (el.innerText || el.textContent || '').trim();
    if (texts.length && !texts.some(function (x) { return t.toLowerCase().indexOf(x) !== -1; })) { continue; }
    if (visibleOnly && el.getClientRects().length === 0) { continue; }
    el.style.outline = '3px solid #ff2d95';
    el.click();
    return JSON.stringify({clicked: true, text: t, href: el.href || null});
  }
  return JSON.stringify({clicked: false, text: '', href: null});
})"""


def click_script(selector: str | None = None, texts: list[str] | None = None, visible_only: bool = True) -> str:
    """JavaScript that clicks the site's own first visible button/link matching ``selector`` and/or containing one
    of ``texts`` (open shadow roots included), and evaluates to a JSON string {clicked, text, href}. Used only where
    the owner allows Leonida to follow a site's Download buttons for the user (see CLAUDE.md)."""
    args = [selector, [t.lower() for t in (texts or [])], visible_only]
    return _CLICK_JS + "(" + ", ".join(json.dumps(a) for a in args) + ");"


def navigate_script(url: str) -> str:
    """JavaScript that goes to ``url`` from the current page (so the site sees it as the Referer, like a click)."""
    return "location.href = " + json.dumps(url) + ";"
