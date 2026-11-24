"""Download engine tests against a local http.server (no real internet)."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from leonida import downloader as dl
from leonida.downloader import DownloadError, DownloadPlan, download, fetch_image, page_image, plan_for, resolve
from leonida.manifest import Mod


# ------------------------------------------------------------------------------------------------ server
@dataclass
class Route:
    body: bytes = b""
    ctype: str = "application/octet-stream"
    status: int = 200
    headers: dict = field(default_factory=dict)
    ranges: bool = False


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep pytest output clean
        pass

    def do_GET(self):
        srv = self.server
        srv.requests.append((self.path, dict(self.headers)))
        route = srv.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body, status = route.body, route.status
        extra = dict(route.headers)
        rng = self.headers.get("Range")
        if route.ranges and rng and status == 200:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(body):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(body)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            extra["Content-Range"] = f"bytes {start}-{len(body) - 1}/{len(body)}"
            body, status = body[start:], 206
        self.send_response(status)
        self.send_header("Content-Type", route.ctype)
        self.send_header("Content-Length", str(len(body)))
        if route.ranges:
            self.send_header("Accept-Ranges", "bytes")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


class Server:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.routes = {}
        self.httpd.requests = []
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def add(self, path: str, **kw) -> str:
        self.httpd.routes[path] = Route(**kw)
        return self.base + path

    @property
    def requests(self) -> list:
        return self.httpd.requests

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(monkeypatch):
    s = Server()
    monkeypatch.setattr(dl, "GITHUB_API", s.base + "/gh")
    yield s
    s.close()


def make_mod(**kw) -> Mod:
    base = dict(id="testmod", order=1, tier="core", layer="x", name="Test Mod", author="a", version="1",
                source="direct", page="https://example.invalid/mod", archive=("testmod*.zip",), method="copy")
    base.update(kw)
    return Mod(**base)


def gh_plan(asset="mod-*.zip") -> DownloadPlan:
    return plan_for(make_mod(download={"type": "github", "repo": "owner/repo", "asset": asset}))


BODY = bytes(range(256)) * 1200  # 307200 bytes, several chunks


# ---------------------------------------------------------------------------------------------- plan modes
def test_plan_modes():
    p = gh_plan()
    assert (p.mode, p.url, p.filename) == ("auto", None, None)
    p = plan_for(make_mod(download={"type": "direct", "url": "https://x.example/f.zip", "file": "f.zip"}))
    assert (p.mode, p.url, p.filename) == ("auto", "https://x.example/f.zip", "f.zip")
    assert plan_for(make_mod(source="patreon")).mode == "manual"
    assert plan_for(make_mod(source="discord")).mode == "manual"
    p = plan_for(make_mod())
    assert (p.mode, p.page, p.url) == ("browser", "https://example.invalid/mod", None)


def test_real_manifest_plans(manifest):
    for m in manifest.mods.values():
        p = plan_for(m)
        assert p.mode in ("auto", "browser", "manual")
        if m.manual_download and not m.download:
            assert p.mode == "manual"


# ------------------------------------------------------------------------------------------- github resolve
def _release(server, assets, status=200, headers=None, path="/gh/repos/owner/repo/releases/latest"):
    server.add(path, body=json.dumps({"tag_name": "v2", "assets": assets}).encode(),
               ctype="application/json", status=status, headers=headers or {})


def test_github_resolve_match(server):
    _release(server, [
        {"name": "Source.txt", "browser_download_url": "https://x/1", "size": 1},
        {"name": "Mod-v2.ZIP", "browser_download_url": "https://github.com/o/r/Mod-v2.ZIP", "size": 1234},
    ])
    p = gh_plan()
    assert resolve(p) is p
    assert (p.url, p.filename, p.size) == ("https://github.com/o/r/Mod-v2.ZIP", "Mod-v2.ZIP", 1234)
    path, headers = server.requests[0]
    assert headers["User-Agent"].startswith("LeonidaV/")
    assert "Authorization" not in headers and "Cookie" not in headers


def test_github_resolve_no_match(server):
    _release(server, [{"name": "other.7z", "browser_download_url": "https://x/1", "size": 1}])
    with pytest.raises(DownloadError, match="No asset matching"):
        resolve(gh_plan())


def test_github_resolve_rate_limit(server):
    server.add("/gh/repos/owner/repo/releases/latest", body=b'{"message":"API rate limit exceeded"}',
               ctype="application/json", status=403,
               headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"})
    with pytest.raises(DownloadError, match="rate limit"):
        resolve(gh_plan())


def test_github_resolve_falls_back_to_prerelease(server):
    server.add("/gh/repos/owner/repo/releases?per_page=10", ctype="application/json", body=json.dumps([
        {"draft": True, "assets": [{"name": "mod-draft.zip", "browser_download_url": "https://x/d"}]},
        {"draft": False, "prerelease": True, "tag_name": "v3-beta",
         "assets": [{"name": "mod-3.zip", "browser_download_url": "https://x/3", "size": 9}]},
    ]).encode())
    p = resolve(gh_plan())
    assert (p.url, p.filename) == ("https://x/3", "mod-3.zip")


def test_resolve_leaves_other_plans_alone():
    p = plan_for(make_mod())
    assert resolve(p) is p and p.url is None


def test_download_resolves_github_then_downloads(server, tmp_path):
    url = server.add("/files/mod-2.zip", body=BODY)
    _release(server, [{"name": "mod-2.zip", "browser_download_url": url, "size": len(BODY)}])
    out = download(gh_plan(), tmp_path)
    assert out == tmp_path / "mod-2.zip" and out.read_bytes() == BODY


# ------------------------------------------------------------------------------------------------ download
def direct(url: str, filename: str | None = "f.zip") -> DownloadPlan:
    return DownloadPlan("testmod", "auto", "https://example.invalid/mod", url=url, filename=filename)


def test_progress(server, tmp_path):
    url = server.add("/f.zip", body=BODY)
    calls = []
    out = download(direct(url), tmp_path, progress=lambda d, t: calls.append((d, t)))
    assert out.read_bytes() == BODY
    assert calls[0] == (0, len(BODY)) and calls[-1] == (len(BODY), len(BODY))
    assert [d for d, _ in calls] == sorted(d for d, _ in calls)
    assert not (tmp_path / "f.zip.part").exists()


def test_cancel_keeps_part(server, tmp_path):
    url = server.add("/f.zip", body=BODY)
    seen = []
    with pytest.raises(DownloadError, match="cancelled"):
        download(direct(url), tmp_path, progress=lambda d, t: seen.append(d), cancel=lambda: len(seen) > 2)
    assert not (tmp_path / "f.zip").exists()
    assert 0 < (tmp_path / "f.zip.part").stat().st_size < len(BODY)


def test_resume_with_range(server, tmp_path):
    url = server.add("/f.zip", body=BODY, ranges=True)
    (tmp_path / "f.zip.part").write_bytes(BODY[:100_000])
    calls = []
    out = download(direct(url), tmp_path, progress=lambda d, t: calls.append((d, t)))
    assert out.read_bytes() == BODY
    assert server.requests[-1][1]["Range"] == "bytes=100000-"
    assert calls[0] == (100_000, len(BODY))


def test_resume_restarts_when_server_ignores_range(server, tmp_path):
    url = server.add("/f.zip", body=BODY)  # no range support -> 200 with full body
    (tmp_path / "f.zip.part").write_bytes(b"garbage" * 1000)
    assert download(direct(url), tmp_path).read_bytes() == BODY


def test_resume_complete_part_416(server, tmp_path):
    url = server.add("/f.zip", body=BODY, ranges=True)
    (tmp_path / "f.zip.part").write_bytes(BODY)
    plan = direct(url)
    plan.size = len(BODY)
    assert download(plan, tmp_path).read_bytes() == BODY


def test_resume_with_content_disposition_name(server, tmp_path):
    url = server.add("/dl?id=7", body=BODY, ranges=True,
                     headers={"Content-Disposition": 'attachment; filename="Named.zip"'})
    (tmp_path / "Named.zip.part").write_bytes(BODY[:5000])
    out = download(direct(url, filename=None), tmp_path)
    assert out.name == "Named.zip" and out.read_bytes() == BODY
    assert server.requests[-1][1].get("Range") == "bytes=5000-"


def test_never_overwrites_existing(server, tmp_path):
    url = server.add("/f.zip", body=BODY)
    (tmp_path / "f.zip").write_bytes(b"mine")
    assert download(direct(url), tmp_path).read_bytes() == b"mine"
    assert server.requests == []  # known name: no request at all

    # name only known from the response: still returned untouched
    url = server.add("/get", body=BODY, headers={"Content-Disposition": "attachment; filename=f.zip"})
    assert download(direct(url, filename=None), tmp_path).read_bytes() == b"mine"


@pytest.mark.parametrize("raw, expected", [
    ("../../evil.zip", "evil.zip"),
    ("..\\..\\Windows\\evil.zip", "evil.zip"),
    ("/etc/passwd", "passwd"),
    ("..", ""),
    ("a<b>c:d|e?.zip", "a_b_c_d_e_.zip"),
    ("CON.zip", "_CON.zip"),
    ("My%20Mod%20v1.zip", "My Mod v1.zip"),
    ("  .hidden. ", "hidden"),
])
def test_safe_name(raw, expected):
    assert dl._safe_name(raw) == expected


def test_filename_from_header_is_sanitised(server, tmp_path):
    url = server.add("/x", body=b"data", headers={"Content-Disposition": 'attachment; filename="../../evil.zip"'})
    out = download(direct(url, filename=None), tmp_path / "dl")
    assert out == tmp_path / "dl" / "evil.zip"
    assert not (tmp_path / "evil.zip").exists()


def test_filename_from_url_path(server, tmp_path):
    url = server.add("/files/Some%20Mod.7z", body=b"data")
    assert download(direct(url, filename=None), tmp_path).name == "Some Mod.7z"


def test_rejects_plain_http_and_bad_modes(server, tmp_path):
    with pytest.raises(DownloadError, match="https"):
        download(direct("http://example.com/f.zip"), tmp_path)
    with pytest.raises(DownloadError):
        download(plan_for(make_mod()), tmp_path)  # browser mode
    # a redirect to plain http is refused before connecting anywhere
    server.add("/redir", status=302, headers={"Location": "http://example.com/f.zip"})
    with pytest.raises(DownloadError, match="https"):
        download(direct(server.base + "/redir"), tmp_path)
    assert list(tmp_path.iterdir()) == [] or all(p.suffix == ".part" for p in tmp_path.iterdir())


def test_http_error_is_download_error(server, tmp_path):
    with pytest.raises(DownloadError, match="404"):
        download(direct(server.base + "/missing.zip"), tmp_path)


# -------------------------------------------------------------------------------------------------- images
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


def test_fetch_image_and_cache(server, tmp_path):
    url = server.add("/p.png", body=PNG, ctype="image/png")
    out = fetch_image(url, tmp_path / "cache")
    assert out is not None and out.suffix == ".png" and out.read_bytes() == PNG
    n = len(server.requests)
    assert fetch_image(url, tmp_path / "cache") == out
    assert len(server.requests) == n  # served from cache


def test_fetch_image_rejects_non_images(server, tmp_path, monkeypatch):
    assert fetch_image(server.add("/a.png", body=b"<html>", ctype="text/html"), tmp_path) is None
    assert fetch_image(server.base + "/nothing.png", tmp_path) is None
    assert fetch_image("http://example.com/a.png", tmp_path) is None
    monkeypatch.setattr(dl, "MAX_IMAGE_BYTES", 32)
    assert fetch_image(server.add("/big.jpg", body=PNG, ctype="image/jpeg"), tmp_path) is None
    assert not any(tmp_path.iterdir())


def _page(server, head: str) -> str:
    return server.add("/page", body=f"<html><head>{head}</head><body>x</body></html>".encode(),
                      ctype="text/html; charset=utf-8")


def test_page_image_og(server):
    url = _page(server, '<meta property="og:image" content="/img/cover.png?a=1&amp;b=2">'
                        '<meta name="twitter:image" content="https://cdn.example/t.jpg">')
    assert page_image(url) == server.base + "/img/cover.png?a=1&b=2"


def test_page_image_twitter_only(server):
    url = _page(server, '<meta name="twitter:image" content="https://cdn.example/t.jpg"/>')
    assert page_image(url) == "https://cdn.example/t.jpg"


def test_page_image_none(server):
    assert page_image(_page(server, "<title>no image</title>")) is None
    assert page_image(_page(server, '<meta property="og:image" content="http://cdn.example/a.png">')) is None
    assert page_image(server.base + "/404") is None
    assert page_image("http://example.com/") is None


# ------------------------------------------------------------------------------------------------------ CLI
def test_cli_get_auto(tmp_path, downloads, monkeypatch, capsys):
    from leonida.cli import main

    fetched = []

    def fake_download(plan, dest, progress=None, cancel=None, timeout=30):
        fetched.append(plan.mod_id)
        if progress:
            progress(5, 10)
            progress(10, 10)
        raise DownloadError("offline in tests")

    def fake_plan(mod):
        return DownloadPlan(mod.id, "auto" if mod.order % 2 else "browser", mod.page)

    monkeypatch.setattr(dl, "download", fake_download)
    monkeypatch.setattr(dl, "plan_for", fake_plan)
    rc = main(["--state-dir", str(tmp_path / "st"), "--download-dir", str(downloads), "get", "--auto"])
    out = capsys.readouterr().out
    assert rc == 2 and fetched
    assert "offline in tests" in out and "author's page" in out
    assert not any(Path(downloads).iterdir())


def test_github_resolve_pinned_tag(server):
    _release(server, [{"name": "mod-1.0.zip", "browser_download_url": "https://x/old", "size": 5}],
             path="/gh/repos/owner/repo/releases/tags/v1.0%2Bold")
    _release(server, [{"name": "mod-2.0.zip", "browser_download_url": "https://x/new", "size": 6}])
    p = plan_for(make_mod(download={"type": "github", "repo": "owner/repo", "asset": "mod-*.zip", "tag": "v1.0+old"}))
    assert resolve(p).url == "https://x/old"
    assert all("/latest" not in path for path, _ in server.requests)


def test_github_resolve_missing_tag(server):
    p = plan_for(make_mod(download={"type": "github", "repo": "owner/repo", "asset": "*.zip", "tag": "v9"}))
    with pytest.raises(DownloadError, match="no release tagged 'v9'"):
        resolve(p)
