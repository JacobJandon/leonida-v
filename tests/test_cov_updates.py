"""Coverage for modupdate.py, downloader.py and installer.py branches the main test files don't reach.

No network: a local http.server (tests/test_downloader.py) or fake responses via a monkeypatched ``_open``.
Everything happens in tmp_path (fake game folder, state, downloads).
"""

from __future__ import annotations

import copy
import email.message
import json
import urllib.error
import zipfile
from pathlib import Path

import pytest
from conftest import AutoUI, make_zip
from test_downloader import BODY, Server, gh_plan, make_mod
from test_modpack import BUILD, MODS, current_files, pack_for, v2_zip, write_manifest

from leonida import downloader as dl
from leonida import installer as installer_mod
from leonida import log as L
from leonida import modupdate as mu
from leonida.downloader import DownloadError, DownloadPlan, download, fetch_image, page_image, resolve
from leonida.installer import Installer, InstallError
from leonida.manifest import FileSpec, Mod
from leonida.matcher import build_lock, sha256_file, write_lock
from leonida.modpack import Change
from leonida.paths import EXTRACT_DIR, LOCK_NAME
from leonida.session import Session
from leonida.snapshot import diff, take_snapshot


# =============================================================================================== fixtures
@pytest.fixture
def server(monkeypatch):
    s = Server()
    monkeypatch.setattr(dl, "GITHUB_API", s.base + "/gh")
    yield s
    s.close()


def make_kit(tmp_path: Path, game: Path, downloads: Path, mods=None) -> Session:
    """alpha 1.0, beta, gamma installed (gamma overwrites alpha.ini, so it depends on alpha); lockfile written."""
    mdir = write_manifest(tmp_path, mods)
    state = tmp_path / "kit-state"
    files = {
        "alpha": make_zip(downloads / "alpha-1.0.zip", {"alpha/alpha.asi": "alpha v1", "alpha/alpha.ini": "a=1"}),
        "beta": make_zip(downloads / "beta-1.0.zip", {"beta.asi": "beta v1"}),
        "gamma": make_zip(downloads / "gamma-1.0.zip", {"gamma.asi": "gamma v1", "alpha.ini": "a=gamma"}),
    }
    s = Session(state, mdir, download_dir=str(downloads), game_dir=str(game), game_build=BUILD)
    inst = s.installer(AutoUI())
    for mid in ("alpha", "beta", "gamma"):
        inst.install(s.manifest.mod(mid), files[mid])
    write_lock(state / LOCK_NAME, build_lock("Leonida V", "9", files))
    return s


@pytest.fixture
def kit(tmp_path, game, downloads):
    return make_kit(tmp_path, game, downloads)


def _step(s: Session, mod_id: str) -> L.Step:
    return next(st for st in s.log.active_steps() if st.mod == mod_id)


def _assert_alpha_v1_intact(s: Session, game: Path):
    assert (game / "alpha.asi").read_text() == "alpha v1"
    assert (game / "alpha.ini").read_text() == "a=gamma"  # gamma (installed later) still wins
    assert (game / "gamma.asi").read_text() == "gamma v1"


# ============================================================================================ modupdate
def test_skips_file_robustness(tmp_path):
    state = tmp_path / "nested" / "state"
    assert mu.load_skips(state) == {}                       # missing
    mu.skip_version(state, "alpha", "2.0")                   # creates the folder
    mu.skip_version(state, "beta", "1.1")
    assert mu.load_skips(state) == {"alpha": "2.0", "beta": "1.1"}
    mu.skip_version(state, "gamma", None)                    # forgetting an unknown skip is harmless
    assert mu.load_skips(state) == {"alpha": "2.0", "beta": "1.1"}
    (state / mu.SKIP_FILE).write_text("[1, 2]", encoding="utf-8")
    assert mu.load_skips(state) == {}                       # not a dict
    (state / mu.SKIP_FILE).write_text("{broken", encoding="utf-8")
    assert mu.load_skips(state) == {}                       # not JSON


def test_plan_summary_and_pending_when_held():
    ch = Change("alpha", "updated", "alpha-1.0.zip", None, {"version": "2.0", "file": "alpha-2.0.zip"})
    items = [mu.ModUpdate("alpha", "Alpha", ch, mu.READY),
             mu.ModUpdate("beta", "Beta", Change("beta", "same"), mu.CURRENT),
             mu.ModUpdate("gamma", "Gamma", Change("gamma", "removed"), mu.GONE, "left installed")]
    plan = mu.UpdatePlan("1.0.1013.20", "1.0.1013.20", items, held="not today")
    assert plan.pending == [] and items[0].pending
    assert plan.summary() == ["HELD: not today", "[update] Alpha -> 2.0", "[removed] Gamma: left installed"]
    plan.held = None
    assert plan.pending == [items[0]]
    assert mu.UpdatePlan(None, None).summary() == ["Every installed mod is the modpack's tested version."]


def test_plan_held_without_game_build(kit, downloads, monkeypatch):
    pack = pack_for(kit, {"alpha": v2_zip(downloads), **current_files(downloads)})
    monkeypatch.setattr(kit, "game_version", lambda: None)
    plan = mu.plan_updates(kit, pack)
    assert plan.build is None and plan.items == [] and "Can't read the game build" in plan.held
    with pytest.raises(mu.ModUpdateError, match="Can't read the game build"):
        mu.run_updates(kit, plan, AutoUI())


def test_installed_state_without_lockfile(kit, downloads):
    (kit.state / LOCK_NAME).unlink()
    (downloads / "beta-1.0.zip").unlink()                     # installed, but its download is gone
    ghost = kit.log.new_step("ghost", "copy")                 # installed, no longer in the manifest
    ghost.status = "done"
    entries = {e["mod"]: e for e in mu.installed_state(kit)["entries"]}
    assert set(entries) == {"alpha", "beta", "gamma", "ghost"}
    alpha = downloads / "alpha-1.0.zip"
    assert entries["alpha"] == {"mod": "alpha", "file": alpha.name, "sha256": sha256_file(alpha),
                                "size": alpha.stat().st_size}
    assert entries["beta"] == {"mod": "beta", "file": None, "sha256": None, "size": None}
    assert entries["ghost"] == {"mod": "ghost", "file": None, "sha256": None, "size": None}


def test_plan_gone_new_and_refused(kit, game, downloads):
    gamma = _step(kit, "gamma")
    kit.installer(AutoUI()).rollback(gamma.id)                # gamma no longer installed
    pack = pack_for(kit, {"alpha": v2_zip(downloads), "gamma": downloads / "gamma-1.0.zip"})  # beta dropped
    pack["builds"][BUILD]["mods"]["alpha"]["source"]["page"] = "https://mirror.example/alpha"
    plan = mu.plan_updates(kit, pack)
    acts = {i.mod_id: (i.action, i.message) for i in plan.items}
    assert acts["alpha"][0] == mu.REFUSED and "isn't the author's page" in acts["alpha"][1]
    assert acts["beta"] == (mu.GONE, "no longer in the modpack; left installed")
    assert acts["gamma"][0] == mu.NEW and "leonida install" in acts["gamma"][1]
    assert plan.pending == [] and not plan.held
    assert mu.run_updates(kit, plan, AutoUI()) == []
    assert (game / "alpha.asi").read_text() == "alpha v1" and (game / "beta.asi").exists()


def test_plan_held_when_pack_was_tested_on_other_variant(tmp_path, game, downloads):
    mods = copy.deepcopy(MODS)
    mods[0]["minGameBuild"] = "1.0.1013.17"
    mods[0]["gameBuilds"] = [{"min": "1.0.1000.0", "max": "1.0.1013.16", "version": "1.5",
                              "archive": ["alpha-*.zip"]}]
    s = make_kit(tmp_path, game, downloads, mods)
    old_build = "1.0.1013.10"                                  # older than the game's BUILD, other alpha variant
    pack = pack_for(s, {"alpha": v2_zip(downloads), **current_files(downloads)}, build=old_build)
    plan = mu.plan_updates(s, pack)
    assert plan.modpack_build == old_build and plan.build == BUILD
    assert plan.held and f"tested on game build {old_build}" in plan.held and plan.pending == []
    with pytest.raises(mu.ModUpdateError, match="different version"):
        mu.run_updates(s, plan, AutoUI())


def test_replace_mod_not_installed(kit, downloads):
    inst = kit.installer(AutoUI())
    inst.rollback(_step(kit, "gamma").id)
    with pytest.raises(mu.ModUpdateError, match="Gamma isn't installed"):
        mu.replace_mod(kit, inst, kit.manifest.mod("gamma"), downloads / "gamma-1.0.zip")


def test_replace_mod_needs_dependent_download(kit, game, downloads):
    (downloads / "gamma-1.0.zip").unlink()
    before = [(s.id, s.status) for s in kit.log.steps]
    with pytest.raises(mu.ModUpdateError, match="gamma was installed later and shares files"):
        mu.replace_mod(kit, kit.installer(AutoUI()), kit.manifest.mod("alpha"), v2_zip(downloads))
    assert [(s.id, s.status) for s in kit.log.steps] == before  # nothing rolled back
    _assert_alpha_v1_intact(kit, game)


def test_replace_mod_bad_new_file_restores_previous(kit, game, downloads):
    bad = make_zip(downloads / "alpha-2.0.zip", {"alpha.asi": "alpha v2"})  # alpha.ini missing -> plan problem
    with pytest.raises(mu.ModUpdateError) as err:
        mu.replace_mod(kit, kit.installer(AutoUI()), kit.manifest.mod("alpha"), bad, downloads / "alpha-1.0.zip")
    msg = str(err.value)
    assert "Updating Alpha failed" in msg and "alpha.ini not found" in msg
    assert "The previous version (alpha-1.0.zip) was reinstalled." in msg
    _assert_alpha_v1_intact(kit, game)
    assert [s.mod for s in kit.log.active_steps()] == ["beta", "alpha", "gamma"]


def _flaky_copy2(monkeypatch, poison: set[bytes], once: bool):
    """installer.shutil.copy2 raising OSError for sources with the given content (once, or every time)."""
    real = installer_mod.shutil.copy2
    hits = []

    def copy2(src, dst, *a, **k):
        if Path(src).is_file() and Path(src).read_bytes() in poison and not (once and hits):
            hits.append(Path(src).read_bytes())
            raise OSError("disk full")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(installer_mod.shutil, "copy2", copy2)
    return hits


def test_replace_mod_copy_error_rolls_back_failed_step(kit, game, downloads, monkeypatch):
    new = v2_zip(downloads)
    hits = _flaky_copy2(monkeypatch, {b"a=2"}, once=True)  # alpha.asi v2 is copied, then alpha.ini fails
    with pytest.raises(mu.ModUpdateError, match="disk full.*previous version \\(alpha-1.0.zip\\) was reinstalled"):
        mu.replace_mod(kit, kit.installer(AutoUI()), kit.manifest.mod("alpha"), new, downloads / "alpha-1.0.zip")
    assert hits == [b"a=2"]
    failed = [s for s in kit.log.steps if s.status == "rolled-back" and s.mod == "alpha" and s.notes
              and any("failed part-way" in n for n in s.notes)]
    assert failed, "the half-done step must have been rolled back"
    _assert_alpha_v1_intact(kit, game)


def test_replace_mod_restore_also_fails(kit, game, downloads, monkeypatch):
    new = v2_zip(downloads)
    _flaky_copy2(monkeypatch, {b"alpha v2", b"alpha v1"}, once=False)
    with pytest.raises(mu.ModUpdateError) as err:
        mu.replace_mod(kit, kit.installer(AutoUI()), kit.manifest.mod("alpha"), new, downloads / "alpha-1.0.zip")
    msg = str(err.value)
    assert "Alpha is now uninstalled" in msg and "Restoring didn't finish: reinstalling alpha-1.0.zip (disk full)" in msg
    assert not (game / "alpha.asi").exists() and not (game / "gamma.asi").exists()
    assert not any(s.mod == "alpha" for s in kit.log.active_steps())  # the half-done v1 attempt was rolled back


def _corrupt_zip_data(z: Path, marker: bytes) -> Path:
    """Flip a byte of a member's stored data: the zip still lists fine, extraction fails (Bad CRC-32)."""
    data = bytearray(z.read_bytes())
    data[data.index(marker)] ^= 0xFF
    z.write_bytes(bytes(data))
    return z


def test_replace_mod_unextractable_new_file_restores_previous(kit, game, downloads):
    new = _corrupt_zip_data(make_zip(downloads / "alpha-2.0.zip", {"alpha.asi": "v2" * 100, "alpha.ini": "a=2"}),
                            b"v2" * 20)
    with pytest.raises(mu.ModUpdateError, match="previous version"):
        mu.replace_mod(kit, kit.installer(AutoUI()), kit.manifest.mod("alpha"), new, downloads / "alpha-1.0.zip")
    _assert_alpha_v1_intact(kit, game)


def test_run_updates_reports_replace_error(kit, game, downloads):
    pack = pack_for(kit, {"alpha": v2_zip(downloads), **current_files(downloads)})
    plan = mu.plan_updates(kit, pack)
    assert [i.mod_id for i in plan.pending] == ["alpha"]
    (downloads / "gamma-1.0.zip").unlink()
    report = mu.run_updates(kit, plan, AutoUI())
    assert len(report) == 1 and report[0].startswith("Alpha: Can't update Alpha: gamma was installed later")
    _assert_alpha_v1_intact(kit, game)
    assert json.loads((kit.state / LOCK_NAME).read_text())["entries"][0]["file"] == "alpha-1.0.zip"


# ---- DOWNLOAD action (alpha has a direct link from its author) ---------------------------------------------
DIRECT = {"type": "direct", "url": "https://alpha.example/files/alpha-2.0.zip", "file": "alpha-2.0.zip"}


@pytest.fixture
def auto_kit(tmp_path, game, downloads):
    mods = copy.deepcopy(MODS)
    mods[0]["download"] = DIRECT
    s = make_kit(tmp_path, game, downloads, mods)
    v2 = make_zip(tmp_path / "srv" / "alpha-2.0.zip", {"alpha.asi": "alpha v2", "alpha.ini": "a=2"})
    pack = pack_for(s, {"alpha": v2, **current_files(downloads)})
    plan = mu.plan_updates(s, pack)
    assert {i.mod_id: i.action for i in plan.items}["alpha"] == mu.DOWNLOAD
    return s, plan, v2


def test_run_updates_download_failed(auto_kit, game, downloads, monkeypatch):
    s, plan, _ = auto_kit
    seen = []

    def fail(plan_, dest, progress=None, cancel=None, timeout=30):
        seen.append((plan_.url, plan_.filename, Path(dest)))
        raise DownloadError("offline")

    monkeypatch.setattr(mu.downloader, "download", fail)
    report = mu.run_updates(s, plan, AutoUI())
    assert seen == [(DIRECT["url"], "alpha-2.0.zip", downloads)]
    assert len(report) == 1 and "not updated, download failed (offline)" in report[0]
    assert "https://alpha.example/page" in report[0]
    _assert_alpha_v1_intact(s, game)


def test_run_updates_downloaded_file_fails_verification(auto_kit, game, downloads, monkeypatch):
    s, plan, _ = auto_kit

    def tampered(plan_, dest, progress=None, cancel=None, timeout=30):
        return make_zip(Path(dest) / plan_.filename, {"alpha.asi": "evil", "alpha.ini": "a=evil"})

    monkeypatch.setattr(mu.downloader, "download", tampered)
    report = mu.run_updates(s, plan, AutoUI())
    assert len(report) == 1 and report[0].startswith("Alpha: not updated.")
    assert "SHA-256" in report[0] or "bytes" in report[0]
    _assert_alpha_v1_intact(s, game)


def test_run_updates_direct_download_from_local_server(auto_kit, game, downloads, monkeypatch):
    s, plan, v2 = auto_kit
    srv = Server()
    try:
        url = srv.add("/files/alpha-2.0.zip", body=v2.read_bytes())
        real_plan_for = mu.downloader.plan_for

        def local_plan(mod):  # same plan, but served by the local test server instead of the author's host
            p = real_plan_for(mod)
            assert p.url == DIRECT["url"]
            p.url = url
            return p

        monkeypatch.setattr(mu.downloader, "plan_for", local_plan)
        s.config.assignments["alpha-2.0.zip"] = "alpha"         # already assigned: config left as is
        progress = []
        report = mu.run_updates(s, plan, AutoUI(), progress=lambda d, t: progress.append((d, t)))
    finally:
        srv.close()
    assert report[0] == "Alpha: updated to 2.0 (alpha-2.0.zip). Test the game before playing on."
    assert progress[-1] == (v2.stat().st_size, v2.stat().st_size)
    assert (downloads / "alpha-2.0.zip").read_bytes() == v2.read_bytes()
    assert (game / "alpha.asi").read_text() == "alpha v2" and (game / "alpha.ini").read_text() == "a=gamma"
    lock = {e["mod"]: e for e in json.loads((s.state / LOCK_NAME).read_text())["entries"]}
    assert lock["alpha"]["sha256"] == sha256_file(v2)


# ============================================================================================ downloader
@pytest.mark.parametrize("url, ok", [
    ("http://[::1", False),              # urlsplit raises ValueError
    ("https:///no-host", False),
    ("ftp://example.com/a.zip", False),
    ("http://example.com/a.zip", False),
    ("http://localhost:8080/a.zip", True),
    ("https://example.com/a.zip", True),
])
def test_allowed(url, ok):
    assert dl._allowed(url) is ok


def test_safe_redirect_to_allowed_url(server, tmp_path):
    server.add("/files/real.zip", body=b"payload")
    server.add("/go", status=302, headers={"Location": "/files/real.zip"})  # relative redirect
    out = download(DownloadPlan("m", "auto", "https://example.invalid", url=server.base + "/go"), tmp_path)
    assert out == tmp_path / "real.zip" and out.read_bytes() == b"payload"


def test_github_server_error(server):
    server.add("/gh/repos/owner/repo/releases/latest", status=500, body=b"oops")
    with pytest.raises(DownloadError, match="GitHub API error 500 for owner/repo"):
        resolve(gh_plan())


def test_github_429_without_reset(server):
    server.add("/gh/repos/owner/repo/releases/latest", status=429, body=b"slow down")
    with pytest.raises(DownloadError, match=r"rate limit reached .*Try again, or download it yourself"):
        resolve(gh_plan())


def test_github_not_json(server):
    server.add("/gh/repos/owner/repo/releases/latest", body=b"<html>not json</html>", ctype="text/html")
    with pytest.raises(DownloadError, match="Could not reach GitHub for owner/repo"):
        resolve(gh_plan())


def test_github_api_must_be_https(monkeypatch):
    monkeypatch.setattr(dl, "GITHUB_API", "http://api.example.com")
    with pytest.raises(DownloadError, match="only https:// links are allowed"):
        resolve(gh_plan())


def test_github_unreachable(monkeypatch):
    def offline(url, timeout, headers=None):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(dl, "_open", offline)
    with pytest.raises(DownloadError, match="Could not reach GitHub for owner/repo: no route to host"):
        resolve(gh_plan())


@pytest.mark.parametrize("spec", [
    {"type": "github", "repo": "not a repo", "asset": "*.zip"},
    {"type": "github", "repo": "owner/repo", "asset": ""},
])
def test_resolve_bad_spec(spec):
    with pytest.raises(DownloadError, match="bad GitHub download spec"):
        resolve(dl.plan_for(make_mod(download=spec)))


def test_resolve_no_published_release(server):
    server.add("/gh/repos/owner/repo/releases?per_page=10", ctype="application/json",
               body=json.dumps([{"draft": True, "assets": []}]).encode())
    with pytest.raises(DownloadError, match="owner/repo has no published GitHub release"):
        resolve(gh_plan())
    server.httpd.routes.pop("/gh/repos/owner/repo/releases?per_page=10")  # listing 404 too
    with pytest.raises(DownloadError, match="no published GitHub release"):
        resolve(gh_plan())


def test_resolve_asset_without_url(server):
    server.add("/gh/repos/owner/repo/releases/latest", ctype="application/json", body=json.dumps(
        {"tag_name": "v1", "assets": [{"name": "mod-1.zip", "size": "12"}]}).encode())
    p = gh_plan()
    with pytest.raises(DownloadError, match=r"No asset matching 'mod-\*.zip' in owner/repo release v1 \(assets: mod-1.zip\)"):
        resolve(p)
    assert p.size is None  # non-integer size ignored


def test_safe_name_long_and_fallback():
    long = dl._safe_name("a" * 300 + ".zip")
    assert len(long) == 180 and long.endswith(".zip")
    assert dl._safe_name("", "fallback.bin") == "fallback.bin"


class _Headers(email.message.Message):
    def __init__(self, values=None, bad_filename=False):
        super().__init__()
        for k, v in (values or {}).items():
            self[k] = v
        self._bad = bad_filename

    def get_filename(self, failobj=None):
        if self._bad:
            raise ValueError("malformed Content-Disposition")
        return super().get_filename(failobj)


class _Resp:
    def __init__(self, body=b"", headers=None, status=200, url="https://x.example/files/f.zip", read_error=None,
                 bad_filename=False):
        self.body, self.status, self.url, self.read_error = body, status, url, read_error
        self.headers = _Headers(headers, bad_filename)
        self.closed = False

    def read(self, n=-1):
        if self.read_error and not self.body:
            raise self.read_error
        n = len(self.body) if n < 0 else n
        chunk, self.body = self.body[:n], self.body[n:]
        return chunk

    def geturl(self):
        return self.url

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _serve(monkeypatch, *responses):
    """dl._open returning the given fake responses in order; records (url, headers)."""
    queue, calls = list(responses), []

    def fake_open(url, timeout, headers=None):
        calls.append((url, dict(headers or {})))
        r = queue.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(dl, "_open", fake_open)
    return calls


def test_name_from_response_fallbacks():
    r = _Resp(url="https://x.example/dl/Real%20Name.zip", bad_filename=True)
    assert dl._name_from_response(r, "https://x.example/ignored", "fb.bin") == "Real Name.zip"
    r = _Resp(url="", headers={"Content-Disposition": "attachment"})
    assert dl._name_from_response(r, "https://x.example/", "fb.bin") == "fb.bin"


def test_reason():
    assert dl._reason(urllib.error.URLError("refused")) == "refused"
    assert dl._reason(ValueError("plain")) == "plain"


def test_download_auto_plan_without_url(tmp_path):
    plan = DownloadPlan("m", "auto", "https://example.invalid", source={"type": "direct"})
    with pytest.raises(DownloadError, match="m: no download URL"):
        download(plan, tmp_path)


@pytest.mark.parametrize("exc, match", [
    (urllib.error.URLError("connection refused"), "could not download .*connection refused"),
    (ValueError("bad url"), "could not download .*bad url"),
    (urllib.error.HTTPError("https://x.example/f.zip", 416, "Range Not Satisfiable", None, None),
     "server answered 416"),  # 416 without a .part to resume is an error
])
def test_download_request_errors(monkeypatch, tmp_path, exc, match):
    _serve(monkeypatch, exc)
    with pytest.raises(DownloadError, match=match):
        download(DownloadPlan("m", "auto", "https://p", url="https://x.example/f.zip", filename="f.zip"), tmp_path)


def test_416_with_wrong_size_restarts(server, tmp_path):
    url = server.add("/f.zip", body=BODY, ranges=True)
    (tmp_path / "f.zip.part").write_bytes(BODY + b"extra")  # longer than the file: server answers 416
    plan = DownloadPlan("m", "auto", "https://p", url=url, filename="f.zip", size=None)
    assert download(plan, tmp_path).read_bytes() == BODY
    ranges = [h.get("Range") for _, h in server.requests]
    assert ranges == [f"bytes={len(BODY) + 5}-", None]


def test_name_from_response_with_stale_part_restarts(server, tmp_path):
    url = server.add("/get?id=1", body=BODY, ranges=True,
                     headers={"Content-Disposition": 'attachment; filename="Named.zip"'})
    (tmp_path / "Named.zip.part").write_bytes(BODY + b"stale")  # bigger than the file -> 416 on resume
    out = download(DownloadPlan("m", "auto", "https://p", url=url), tmp_path)
    assert out == tmp_path / "Named.zip" and out.read_bytes() == BODY
    assert [h.get("Range") for _, h in server.requests] == [None, f"bytes={len(BODY) + 5}-", None]
    assert not (tmp_path / "Named.zip.part").exists()


def test_name_from_response_part_without_range_support(server, tmp_path):
    url = server.add("/get?id=2", body=BODY, headers={"Content-Disposition": "attachment; filename=N2.zip"})
    (tmp_path / "N2.zip.part").write_bytes(b"old partial")
    out = download(DownloadPlan("m", "auto", "https://p", url=url), tmp_path)
    assert out.read_bytes() == BODY and len(server.requests) == 1  # restarted from 0 on the same response


def test_unexpected_range_is_refused(monkeypatch, tmp_path):
    (tmp_path / "f.zip.part").write_bytes(b"x" * 100)
    _serve(monkeypatch, _Resp(b"0123456789", {"Content-Range": "bytes 0-9/10", "Content-Length": "10"}, status=206))
    with pytest.raises(DownloadError, match="unexpected range; delete f.zip.part"):
        download(DownloadPlan("m", "auto", "https://p", url="https://x.example/f.zip", filename="f.zip"), tmp_path)
    assert (tmp_path / "f.zip.part").read_bytes() == b"x" * 100


def test_resume_with_unknown_total(monkeypatch, tmp_path):
    (tmp_path / "f.zip.part").write_bytes(b"A" * 10)
    calls = _serve(monkeypatch, _Resp(b"B" * 10, {"Content-Range": "bytes 10-19/*", "Content-Length": "10"},
                                      status=206))
    progress = []
    out = download(DownloadPlan("m", "auto", "https://p", url="https://x.example/f.zip", filename="f.zip"), tmp_path,
                   progress=lambda d, t: progress.append((d, t)))
    assert out.read_bytes() == b"A" * 10 + b"B" * 10
    assert calls[0][1]["Range"] == "bytes=10-" and progress[0] == (10, 20) and progress[-1] == (20, 20)


def test_total_from_plan_when_no_length(monkeypatch, tmp_path):
    _serve(monkeypatch, _Resp(b"Z" * 7))
    progress = []
    plan = DownloadPlan("m", "auto", "https://p", url="https://x.example/f.zip", filename="f.zip", size=7)
    download(plan, tmp_path, progress=lambda d, t: progress.append((d, t)))
    assert progress == [(0, 7), (7, 7)]


def test_connection_lost_keeps_part(monkeypatch, tmp_path):
    _serve(monkeypatch, _Resp(b"", {"Content-Length": "100"}, read_error=OSError("connection reset")))
    with pytest.raises(DownloadError, match=r"connection lost \(connection reset\); run again to resume"):
        download(DownloadPlan("m", "auto", "https://p", url="https://x.example/f.zip", filename="f.zip"), tmp_path)
    assert (tmp_path / "f.zip.part").exists() and not (tmp_path / "f.zip").exists()


def test_incomplete_download(monkeypatch, tmp_path):
    resp = _Resp(b"q" * 50, {"Content-Length": "100"})
    _serve(monkeypatch, resp)
    with pytest.raises(DownloadError, match=r"incomplete download \(50 of 100 bytes\)"):
        download(DownloadPlan("m", "auto", "https://p", url="https://x.example/f.zip", filename="f.zip"), tmp_path)
    assert resp.closed and (tmp_path / "f.zip.part").stat().st_size == 50


def test_finish_never_overwrites(tmp_path):
    part, final = tmp_path / "f.zip.part", tmp_path / "f.zip"
    part.write_bytes(b"new")
    final.write_bytes(b"mine")
    plan = DownloadPlan("m", "auto", "https://p")
    assert dl._finish(part, final, plan, "f.zip") == final
    assert final.read_bytes() == b"mine" and not part.exists() and plan.filename == "f.zip" and plan.size is None


def test_fetch_image_empty_and_unknown_type(server, tmp_path):
    assert fetch_image(server.add("/empty.png", body=b"", ctype="image/png"), tmp_path / "c") is None
    out = fetch_image(server.add("/x.img", body=b"IMG", ctype="image/x-Fancy+Fmt"), tmp_path / "c")
    assert out is not None and out.suffix == ".xfancyfm" and out.read_bytes() == b"IMG"


def test_page_image_unknown_charset(server):
    url = server.add("/p", body=b'<meta property="og:image" content="https://cdn.example/c.png">',
                     ctype="text/html; charset=no-such-charset")
    assert page_image(url) == "https://cdn.example/c.png"


# ============================================================================================ installer
def mod(**kw) -> Mod:
    base = dict(id="cov", order=1, tier="core", layer="x", name="Cov Mod", author="a", version="1", source="direct",
                page="https://example.invalid/cov", archive=("cov*.zip",), method="copy")
    base.update(kw)
    return Mod(**base)


def _inst(manifest, game, state, log, ui=None, **kw):
    return Installer(manifest, game, state, log, ui or AutoUI(), **kw)


def test_plan_problems(manifest, game, state, log, downloads):
    inst = _inst(manifest, game, state, log)
    copy_mod = mod(files=(FileSpec("x.asi"),))
    assert "No downloaded file matched" in inst.plan(copy_mod, None).problems[0]
    with pytest.raises(InstallError, match="Cov Mod: No downloaded file matched"):
        inst.install(copy_mod, None)

    exe = downloads / "Setup.exe"
    exe.write_bytes(b"MZ")
    assert inst.plan(copy_mod, exe).problems == ["Setup.exe is not a .zip/.7z/.rar archive."]

    broken = downloads / "cov-broken.zip"
    broken.write_bytes(b"not a zip at all")
    assert "not a valid zip" in inst.plan(copy_mod, broken).problems[0]

    readme = make_zip(downloads / "cov-readme.zip", {"docs/readme.txt": "r", "x.ini": "orphan ini"})
    generic = mod(method="generic")
    assert inst.plan(generic, readme).copies == []
    with pytest.raises(InstallError, match="Nothing recognisable"):
        inst.install(generic, readme)

    run = mod(method="run", run="Setup.exe")
    assert inst.plan(run, readme).problems == ["Setup.exe not found in cov-readme.zip."]
    assert inst.plan(mod(method="run", run="Setup.exe"), downloads / "cov.oiv").run_target is None
    assert log.steps == [] and not (state / "baseline-snapshot.json").exists()


def test_dir_and_optional_specs(manifest, game, state, log, downloads):
    z = make_zip(downloads / "cov-1.zip", {"pkg/x.asi": "x"})
    inst = _inst(manifest, game, state, log)
    p = inst.plan(mod(files=(FileSpec("x.asi"), FileSpec("Data", type="dir"))), z)
    assert p.problems == ["Folder Data not found in the archive."]
    p = inst.plan(mod(files=(FileSpec("x.asi"), FileSpec("opt.ini", optional=True),
                             FileSpec("Data", type="dir", optional=True))), z)
    assert p.problems == [] and [(c.src, c.dest) for c in p.copies] == [("pkg/x.asi", "x.asi")]


def test_describe_run_and_guided(manifest, game, state, log, downloads):
    exe = downloads / "Setup.exe"
    exe.write_bytes(b"MZ")
    inst = _inst(manifest, game, state, log)
    lines = inst.plan(mod(method="run", run="Setup.exe"), exe).describe()
    assert lines == ["Cov Mod [run] from Setup.exe", "  run Setup.exe"]
    z = make_zip(downloads / "cov-guide.zip", {"readme.txt": "r"})
    lines = inst.plan(mod(method="guided", steps=("Open the folder", "Copy the files")), z).describe()
    assert lines == ["Cov Mod [guided] from cov-guide.zip", "  step: Open the folder", "  step: Copy the files"]
    assert inst.plan(mod(), None).describe()[0] == "Cov Mod [copy] from (no file)"


def test_identical_file_is_left_alone(manifest, game, state, log, downloads):
    (game / "x.asi").write_text("same")
    z = make_zip(downloads / "cov-1.zip", {"x.asi": "same"})
    inst = _inst(manifest, game, state, log)
    step = inst.install(mod(files=(FileSpec("x.asi"),)), z)
    assert step.actions == [] and step.notes == ["x.asi already identical; left as is"]
    assert inst.rollback(step.id) == [] and (game / "x.asi").read_text() == "same"


def test_run_exe_outside_archive_with_pre_backup(manifest, game, state, log, downloads):
    (game / "scripts").mkdir()
    (game / "scripts" / "old.dll").write_text("old helper")
    exe = downloads / "Setup.exe"
    exe.write_bytes(b"MZ")
    launched, folders = [], []

    def run(path):
        launched.append(path)
        (game / "scripts" / "old.dll").unlink()
        (game / "scripts" / "new.dll").write_text("new helper")

    before = take_snapshot(game)
    inst = _inst(manifest, game, state, log, AutoUI(on_launch=run, on_wait=folders.append))
    step = inst.install(mod(method="run", run="Setup.exe"), exe)
    assert launched == [exe] and folders == [downloads]
    ops = {(a.op, a.path): a for a in step.actions}
    assert set(ops) == {(L.EXT_REMOVE, "scripts/old.dll"), (L.EXT_ADD, "scripts/new.dll")}
    backup = ops[(L.EXT_REMOVE, "scripts/old.dll")].backup
    assert backup and (state / backup).read_text() == "old helper"
    # pre-backups nobody needs (top-level files) were dropped again
    kept = [p for p in (state / "backups").rglob("*") if p.is_file()]
    assert kept == [state / backup]
    assert inst.rollback(step.id) == []
    assert diff(before, take_snapshot(game)).empty


def test_guided_reextracts_and_records_dirs(manifest, game, state, log, downloads):
    stale = state / EXTRACT_DIR / "cov"
    stale.mkdir(parents=True)
    (stale / "stale.txt").write_text("old run")
    (game / "onigiri").mkdir()
    (game / "onigiri" / "keep.txt").write_text("k")
    (game / "onigiri" / "pre.txt").write_text("p")
    z = make_zip(downloads / "cov-guide.zip", {"Guide/readme.txt": "r"})

    def user(folder):
        assert folder == stale and not (folder / "stale.txt").exists()
        assert (folder / "Guide" / "readme.txt").read_text() == "r"
        (game / "onigiri" / "pre.txt").unlink()               # managed folder, no pre-backup
        (game / "onigiri" / "EmptyDir").mkdir()               # empty folder inside a managed folder
        (game / "NewTop").mkdir()                             # new unmanaged top-level folder
        (game / "NewTop" / "inner.bin").write_bytes(b"i")

    inst = _inst(manifest, game, state, log, AutoUI(on_wait=user))
    step = inst.install(mod(method="guided", steps=("Do it",)), z)
    ops = [(a.op, a.path, a.backup) for a in step.actions]
    assert (L.EXT_ADD, "onigiri/EmptyDir/", None) in ops
    assert (L.EXT_REMOVE, "onigiri/pre.txt", None) in ops
    assert (L.EXT_ADD, "NewTop/", None) in ops
    assert any("top-level folders +1/-0" in n for n in step.notes)
    warnings = inst.rollback(step.id)
    assert warnings == ["onigiri/pre.txt: no backup (file was too big); restore it by verifying game files"]
    assert not (game / "NewTop").exists() and not (game / "onigiri" / "EmptyDir").exists()
    assert (game / "onigiri" / "keep.txt").exists()


def test_guided_nested_empty_dir_uninstall_matches_baseline(manifest, game, state, log, downloads):
    z = make_zip(downloads / "cov-guide.zip", {"readme.txt": "r"})

    def user(folder):
        (game / "scripts" / "SomeMod").mkdir(parents=True)

    before = take_snapshot(game)
    inst = _inst(manifest, game, state, log, AutoUI(on_wait=user))
    inst.install(mod(method="guided"), z)
    warnings, residual = inst.uninstall()
    assert warnings == [] and residual.empty, residual.summary()
    assert diff(before, take_snapshot(game)).empty


def test_mkdir_not_empty_warns(manifest, game, state, log, downloads):
    z = make_zip(downloads / "cov-1.zip", {"x.asi": "x"})
    inst = _inst(manifest, game, state, log)
    step = inst.install(mod(create_dirs=("scripts",), files=(FileSpec("x.asi", to="scripts"),)), z)
    assert [a.op for a in step.actions] == [L.MKDIR, L.ADD]
    (game / "scripts" / "user.txt").write_text("mine")
    assert inst.rollback(step.id) == ["scripts: folder not empty, left in place"]
    assert (game / "scripts" / "user.txt").read_text() == "mine" and not (game / "scripts" / "x.asi").exists()


def test_rollback_keeps_baseline_top_folder(manifest, game, state, log, downloads):
    z = make_zip(downloads / "cov-1.zip", {"x.dll": "x"})
    inst = _inst(manifest, game, state, log)
    step = inst.install(mod(files=(FileSpec("x.dll", to="update/sub/deeper"),)), z)
    assert (game / "update" / "sub" / "deeper" / "x.dll").exists()
    inst.rollback(step.id)
    assert not (game / "update" / "sub").exists()
    assert (game / "update" / "update.rpf").exists()  # the game's own folder stays


def test_rollback_twice_and_missing_target(manifest, game, state, log, downloads):
    z = make_zip(downloads / "cov-1.zip", {"x.asi": "x"})
    inst = _inst(manifest, game, state, log)
    step = inst.install(mod(files=(FileSpec("x.asi"),)), z)
    (game / "x.asi").unlink()                                  # the user deleted it already
    assert inst.rollback(step.id) == [] and step.status == "rolled-back"
    assert inst.rollback(step.id) == [f"Step {step.id} is already rolled back."]


def test_dry_run_rollback_only_reports(manifest, game, state, log, downloads):
    z = make_zip(downloads / "cov-1.zip", {"x.asi": "x"})
    step = _inst(manifest, game, state, log).install(mod(files=(FileSpec("x.asi"),)), z)
    ui = AutoUI()
    assert _inst(manifest, game, state, log, ui, dry_run=True).rollback(step.id) == []
    assert ui.lines == ["undo add x.asi"]
    assert (game / "x.asi").exists() and step.status == "done"


def test_install_failure_mid_copy_is_logged(manifest, game, state, log, downloads, monkeypatch):
    z = make_zip(downloads / "cov-1.zip", {"a.asi": "a", "b.asi": "b"})
    _flaky_copy2(monkeypatch, {b"b"}, once=True)
    inst = _inst(manifest, game, state, log)
    with pytest.raises(OSError, match="disk full"):
        inst.install(mod(files=(FileSpec("a.asi"), FileSpec("b.asi"))), z)
    step = log.steps[-1]
    # the failed copy is logged before it starts, so a partly written file would be undone too
    assert step.status == "failed" and step.finished and [a.path for a in step.actions] == ["a.asi", "b.asi"]
    assert inst.rollback(step.id) == [] and not (game / "a.asi").exists() and not (game / "b.asi").exists()


def test_zip_members_listed_but_unreadable(manifest, game, state, log, downloads):
    z = _corrupt_zip_data(make_zip(downloads / "cov-1.zip", {"x.asi": "x" * 200}), b"x" * 50)
    inst = _inst(manifest, game, state, log)
    assert inst.plan(mod(files=(FileSpec("x.asi"),)), z).problems == []
    with pytest.raises(zipfile.BadZipFile):
        inst.install(mod(files=(FileSpec("x.asi"),)), z)
    assert log.steps[-1].status == "failed" and not (game / "x.asi").exists()
