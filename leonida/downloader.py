"""Fetch mod files and preview images at runtime, only from the author's own source (stdlib only).

Three modes per mod (see ``plan_for``):
  * "auto"    - ``mod.download`` is set: a GitHub release asset or a direct link the author publishes.
                The kit downloads it into the user's download folder.
  * "browser" - no ``download``: the author's page opens inside the app and the user clicks Download there.
  * "manual"  - Discord / Patreon / shop / login-gated: the user gets it themselves.

Nothing here scrapes around download gates, logins or ads, and no personal data is sent: requests carry a
generic User-Agent and nothing else. Only https URLs are accepted (plain http only for localhost, for tests).
"""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from . import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"LeonidaV/{__version__} (+https://github.com/JacobJandon/leonida-v)"
CHUNK = 64 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PAGE_BYTES = 512 * 1024
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _github_api() -> str:
    """api.github.com, or LEONIDA_GITHUB_API when it's a local test server (the release end-to-end checks run the
    frozen exe against a fake GitHub on 127.0.0.1). Any other host is ignored: it can't redirect real updates."""
    override = os.environ.get("LEONIDA_GITHUB_API", "").strip()
    if override and urllib.parse.urlsplit(override).hostname in _LOCAL_HOSTS:
        return override.rstrip("/")
    return "https://api.github.com"


GITHUB_API = _github_api()  # tests point this at a local server
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_IMAGE_EXT = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/pjpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "image/bmp": ".bmp", "image/avif": ".avif", "image/svg+xml": ".svg",
    "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
}


class DownloadError(RuntimeError):
    """A download could not be planned, resolved or completed. The message is shown to the user."""


@dataclass
class DownloadPlan:
    mod_id: str
    mode: str            # "auto" (mod.download set) | "browser" (open mod.page in the app) | "manual"
    page: str
    url: str | None = None       # filled for "direct" at plan time, for "github" by resolve()
    filename: str | None = None
    size: int | None = None
    # Copy of mod.download ({"type": "github"|"direct", ...}) so resolve() needs no manifest.
    source: dict | None = field(default=None, repr=False)


# ------------------------------------------------------------------------------------------- network basics
def _allowed(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if not parts.hostname:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS


def _check_url(url: str) -> None:
    if not _allowed(url):
        raise DownloadError(f"Refusing to fetch {url!r}: only https:// links are allowed")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to allowed (https) URLs."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect())


def _open(url: str, timeout: float, headers: dict[str, str] | None = None):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})})
    return _OPENER.open(req, timeout=timeout)


# ---------------------------------------------------------------------------------------------------- plan
def plan_for(mod) -> DownloadPlan:
    """How this mod's file can be fetched. No network."""
    dl = getattr(mod, "download", None)
    if dl:
        plan = DownloadPlan(mod.id, "auto", mod.page, source=dict(dl))
        if dl.get("type") == "direct":
            plan.url = dl.get("url")
            plan.filename = _safe_name(dl.get("file") or "") or None
        return plan
    if getattr(mod, "manual_download", False):
        return DownloadPlan(mod.id, "manual", mod.page)
    return DownloadPlan(mod.id, "browser", mod.page)


def _github_json(url: str, repo: str, timeout: float):
    try:
        with _open(url, timeout, {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
        if exc.code == 429 or (exc.code == 403 and remaining == "0"):
            reset = exc.headers.get("X-RateLimit-Reset") if exc.headers else None
            when = ""
            if reset and reset.isdigit():
                when = " after " + datetime.fromtimestamp(int(reset)).strftime("%H:%M")
            raise DownloadError(
                f"GitHub API rate limit reached (60 requests per hour without sign-in). Try again{when}, "
                f"or download it yourself from https://github.com/{repo}/releases"
            ) from None
        if exc.code == 404:
            return None
        raise DownloadError(f"GitHub API error {exc.code} for {repo}: {exc.reason}") from None
    except DownloadError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DownloadError(f"Could not reach GitHub for {repo}: {_reason(exc)}") from None


def resolve(plan: DownloadPlan, timeout: float = 20) -> DownloadPlan:
    """Fill url/filename/size for a GitHub release plan (latest release, or ``tag`` if given; asset matched by glob).

    The plan is updated in place and returned. Non-GitHub plans are returned unchanged.
    """
    src = plan.source or {}
    if plan.mode != "auto" or src.get("type") != "github":
        return plan
    repo = str(src.get("repo", "")).strip("/")
    pattern = str(src.get("asset", "")).lower()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not pattern:
        raise DownloadError(f"{plan.mod_id}: bad GitHub download spec {src!r}")
    base = GITHUB_API.rstrip("/")
    tag = str(src.get("tag") or "").strip()
    if tag:  # a pinned release (e.g. the last version that supports an older game build)
        release = _github_json(f"{base}/repos/{repo}/releases/tags/{urllib.parse.quote(tag, safe='')}", repo, timeout)
        if release is None:
            raise DownloadError(f"{repo} has no release tagged {tag!r}. Get it from {plan.page}")
    else:
        release = _github_json(f"{base}/repos/{repo}/releases/latest", repo, timeout)
    if release is None:  # no "latest" (e.g. only pre-releases): take the newest published one
        listing = _github_json(f"{base}/repos/{repo}/releases?per_page=10", repo, timeout) or []
        release = next((r for r in listing if not r.get("draft")), None)
        if release is None:
            raise DownloadError(f"{repo} has no published GitHub release. Get it from {plan.page}")
    assets = release.get("assets") or []
    for asset in assets:
        name = str(asset.get("name", ""))
        if fnmatch.fnmatchcase(name.lower(), pattern):
            plan.url = asset.get("browser_download_url")
            plan.filename = _safe_name(name) or None
            plan.size = asset.get("size") if isinstance(asset.get("size"), int) else None
            if not plan.url:
                break
            return plan
    names = ", ".join(str(a.get("name")) for a in assets) or "none"
    raise DownloadError(
        f"No asset matching {src.get('asset')!r} in {repo} release {release.get('tag_name', '?')} "
        f"(assets: {names}). Get it from {plan.page}"
    )


# ------------------------------------------------------------------------------------------------ download
def _safe_name(name: str, fallback: str = "") -> str:
    """A plain file name: no directories, no '..', no characters Windows rejects."""
    name = urllib.parse.unquote(str(name or "")).replace("\\", "/").split("/")[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(" .")
    if not name or set(name) <= {"."}:
        return fallback
    stem = name.split(".")[0].upper()
    if stem in _WIN_RESERVED:
        name = "_" + name
    if len(name) > 180:
        root, ext = os.path.splitext(name)
        name = root[: 180 - len(ext)] + ext[:20]
    return name


def _name_from_response(resp, url: str, fallback: str) -> str:
    try:
        cd = resp.headers.get_filename()
    except Exception:  # malformed header
        cd = None
    name = _safe_name(cd or "")
    if not name:
        name = _safe_name(urllib.parse.urlsplit(resp.geturl() or url).path)
    return name or fallback


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "reason", None) or exc)


def download(plan: DownloadPlan, dest_dir: Path, progress: Callable[[int, int | None], None] | None = None,
             cancel: Callable[[], bool] | None = None, timeout: float = 30) -> Path:
    """Download an "auto" plan into ``dest_dir`` and return the file.

    Writes ``<name>.part`` and renames it when complete; resumes an existing ``.part`` with a Range request when
    the server allows it; never overwrites an existing file with the same name (it is returned instead).
    ``progress(done, total_or_None)`` is called as bytes arrive; ``cancel()`` returning True aborts with
    ``DownloadError("cancelled")`` and keeps the ``.part`` for a later resume.
    """
    if plan.mode != "auto":
        raise DownloadError(f"{plan.mod_id}: no automatic download; get it from {plan.page}")
    if (plan.source or {}).get("type") == "leonida":  # Leonida's own files (the in-game menu): made here, no network
        from .menu import make_zip

        path = make_zip(Path(dest_dir))
        if progress:
            progress(path.stat().st_size, path.stat().st_size)
        log.info("made %s for %s (Leonida's own files)", path.name, plan.mod_id)
        return path
    if not plan.url:
        resolve(plan, timeout=min(timeout, 20))
    if not plan.url:
        raise DownloadError(f"{plan.mod_id}: no download URL")
    url = plan.url
    _check_url(url)
    log.info("download %s from %s", plan.mod_id, _host_of(url))
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    fallback = _safe_name(plan.mod_id) + ".download"

    name = _safe_name(plan.filename or "") or None
    if name and (dest / name).is_file():
        return dest / name

    def part_size(n: str | None) -> int:
        p = dest / f"{n}.part" if n else None
        return p.stat().st_size if p and p.is_file() else 0

    def request(offset: int):
        headers = {"Range": f"bytes={offset}-", "Accept-Encoding": "identity"} if offset else {}
        try:
            return _open(url, timeout, headers)
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and offset:
                return exc  # caller decides: complete .part or restart
            raise DownloadError(f"{plan.mod_id}: server answered {exc.code} {exc.reason} for {url}") from None
        except DownloadError:
            raise
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise DownloadError(f"{plan.mod_id}: could not download {url}: {_reason(exc)}") from None

    offset = part_size(name)
    resp = request(offset)
    try:
        if isinstance(resp, urllib.error.HTTPError):  # 416: the .part may already hold the whole file
            resp.close()
            part = dest / f"{name}.part"
            if plan.size is not None and offset == plan.size:
                return _finish(part, dest / name, plan, name)
            part.unlink(missing_ok=True)
            offset = 0
            resp = request(0)
        if name is None:
            name = _name_from_response(resp, url, fallback)
            if (dest / name).is_file():
                return dest / name
            offset = part_size(name)
            if offset and resp.headers.get("Accept-Ranges", "").lower() == "bytes":
                resp.close()
                resp = request(offset)
                if isinstance(resp, urllib.error.HTTPError):
                    resp.close()
                    (dest / f"{name}.part").unlink(missing_ok=True)
                    offset = 0
                    resp = request(0)
            else:
                offset = 0
        part = dest / f"{name}.part"

        status = getattr(resp, "status", 200)
        length = resp.headers.get("Content-Length")
        length = int(length) if length and length.isdigit() else None
        total: int | None
        if offset and status == 206:
            m = re.match(r"bytes (\d+)-\d+/(\d+|\*)", resp.headers.get("Content-Range", ""))
            if not m or int(m.group(1)) != offset:
                raise DownloadError(f"{plan.mod_id}: server sent an unexpected range; delete {part.name} and retry")
            total = int(m.group(2)) if m.group(2) != "*" else (offset + length if length is not None else None)
            mode, done = "ab", offset
        else:
            total, mode, done = length, "wb", 0
        if total is None:
            total = plan.size

        if progress:
            progress(done, total)
        with open(part, mode) as fh:
            while True:
                if cancel and cancel():
                    raise DownloadError("cancelled")
                try:
                    block = resp.read(CHUNK)
                except (OSError, ValueError) as exc:
                    raise DownloadError(f"{plan.mod_id}: connection lost ({_reason(exc)}); run again to resume") from None
                if not block:
                    break
                fh.write(block)
                done += len(block)
                if progress:
                    progress(done, total)
        if total is not None and done != total:
            raise DownloadError(f"{plan.mod_id}: incomplete download ({done} of {total} bytes); run again to resume")
        return _finish(part, dest / name, plan, name)
    finally:
        resp.close()


def _host_of(url: str | None) -> str:
    from .logs import host

    return host(url)


def _finish(part: Path, final: Path, plan: DownloadPlan, name: str) -> Path:
    log.info("downloaded %s: %s", plan.mod_id, name)
    plan.filename = name
    if final.exists():  # appeared meanwhile: never overwrite it
        part.unlink(missing_ok=True)
        return final
    os.replace(part, final)
    if plan.size is None:
        plan.size = final.stat().st_size
    return final


# -------------------------------------------------------------------------------------------------- images
def fetch_image(url: str, cache_dir: Path, timeout: float = 15) -> Path | None:
    """Download a preview image into ``cache_dir`` (cached by URL). None on any failure."""
    try:
        if not _allowed(url):
            return None
        cache = Path(cache_dir)
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        if cache.is_dir():
            for hit in cache.glob(key + ".*"):
                if hit.is_file() and hit.suffix != ".tmp" and hit.stat().st_size > 0:
                    return hit
        with _open(url, timeout, {"Accept": "image/*"}) as resp:
            ctype = resp.headers.get_content_type().lower()
            if not ctype.startswith("image/"):
                return None
            length = resp.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > MAX_IMAGE_BYTES:
                return None
            data = resp.read(MAX_IMAGE_BYTES + 1)
        if not data or len(data) > MAX_IMAGE_BYTES:
            return None
        ext = _IMAGE_EXT.get(ctype) or "." + re.sub(r"[^a-z0-9]", "", ctype.split("/", 1)[1])[:8]
        cache.mkdir(parents=True, exist_ok=True)
        out = cache / (key + ext)
        tmp = cache / (key + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, out)
        return out
    except Exception:
        return None


class _MetaImage(HTMLParser):
    KEYS = ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        key = (a.get("property") or a.get("name") or "").strip().lower()
        content = a.get("content", "").strip()
        if key in self.KEYS and content and key not in self.found:
            self.found[key] = content

    handle_startendtag = handle_starttag


def page_image(page_url: str, timeout: float = 15) -> str | None:
    """The page's og:image / twitter:image as an absolute https URL, or None."""
    try:
        with _open(page_url, timeout, {"Accept": "text/html,application/xhtml+xml"}) as resp:
            final_url = resp.geturl() or page_url
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read(MAX_PAGE_BYTES)
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        parser = _MetaImage()
        with contextlib.suppress(Exception):  # truncated / broken HTML: keep what was found
            parser.feed(text)
        for key in _MetaImage.KEYS:
            if key in parser.found:
                img = urllib.parse.urljoin(final_url, parser.found[key])
                if _allowed(img):
                    return img
        return None
    except Exception:
        return None
