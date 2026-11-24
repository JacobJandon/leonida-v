"""Self-updater tests: local http server for GitHub, temp git repos, no real network."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from test_downloader import Server  # same tests/ folder (pytest puts it on sys.path)

from leonida import __version__, updater
from leonida.updater import UpdateError, UpdateInfo, apply, check, install_kind, is_newer, parse_version

LATEST = "/gh/repos/JacobJandon/leonida-v/releases/latest"


@pytest.fixture
def server(monkeypatch):
    from leonida import downloader

    s = Server()
    monkeypatch.setattr(downloader, "GITHUB_API", s.base + "/gh")
    yield s
    s.close()


def release_zip(top: str | None = "leonida-v") -> bytes:
    buf = io.BytesIO()
    prefix = f"{top}/" if top else ""
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(prefix + "pyproject.toml", "[project]\nname = 'leonida-v'\n")
        zf.writestr(prefix + "leonida/__init__.py", "__version__ = '9.9.9'\n")
        zf.writestr(prefix + "Start-Leonida.bat", "@echo off\r\n")
    return buf.getvalue()


def publish(server, tag="v9.9.9", files: dict[str, bytes] | None = None, sums: str | None = None) -> None:
    assets = []
    for name, body in (files or {}).items():
        assets.append({"name": name, "browser_download_url": server.add(f"/dl/{name}", body=body), "size": len(body)})
    if sums is not None:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": server.add("/dl/SHA256SUMS.txt", body=sums.encode())})
    server.add(LATEST, ctype="application/json", body=json.dumps({
        "tag_name": tag, "body": "Release notes " * 400, "html_url": "https://github.com/JacobJandon/leonida-v/releases/tag/" + tag,
        "assets": assets,
    }).encode())


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --------------------------------------------------------------------------------------------- versions
@pytest.mark.parametrize("older, newer", [
    ("1.0.0.dev1", "1.0.0"),
    ("1.0.0.dev1", "1.0.0.dev2"),
    ("1.0.0.dev9", "1.0.0a1"),
    ("1.0.0a1", "1.0.0b1"),
    ("1.0.0b2", "1.0.0rc1"),
    ("1.0.0rc1", "1.0.0"),
    ("1.0.0", "1.0.0.post1"),
    ("1.0.0", "1.0.1"),
    ("1.0.9", "1.0.10"),
    ("1.9", "1.10.0"),
    ("1.0.0a1.dev1", "1.0.0a1"),
    ("v1.2.0", "V1.3"),
])
def test_version_order(older, newer):
    assert parse_version(older) < parse_version(newer)
    assert is_newer(newer, older) and not is_newer(older, newer)


def test_version_equal_and_bad():
    assert parse_version("1.0") == parse_version("1.0.0") == parse_version("v1.0.0")
    assert parse_version("1.0.0+local") == parse_version("1.0.0")
    assert parse_version("latest") is None and parse_version(None) is None
    assert not is_newer("nightly", "1.0.0") and not is_newer("1.0.0", "1.0.0")
    assert parse_version(__version__) is not None


# ------------------------------------------------------------------------------------------------- check
def test_check_no_release(server):
    info = check()
    assert (info.latest, info.newer, info.zip_url, info.exe_url) == (None, False, None, None)
    assert info.current == __version__


def test_check_newer_with_assets_and_sums(server):
    z, e = release_zip(), folder_zip()
    publish(server, "v9.9.9", {"Source.zip": b"x", "leonida-v-9.9.9.zip": z, "LeonidaV-9.9.9-win64.zip": e},
            sums=f"{sha(z)}  leonida-v-9.9.9.zip\n{sha(e)} *dist/LeonidaV-9.9.9-win64.zip\nnot a sum line\n")
    info = check()
    assert info.latest == "9.9.9" and info.newer
    assert info.zip_url.endswith("/dl/leonida-v-9.9.9.zip") and info.exe_url.endswith("/dl/LeonidaV-9.9.9-win64.zip")
    assert info.sha256 == {"leonida-v-9.9.9.zip": sha(z), "LeonidaV-9.9.9-win64.zip": sha(e)}
    assert len(info.notes) == updater.MAX_NOTES and info.page.endswith("/tag/v9.9.9")


def test_check_older_release(server):
    publish(server, "v0.1.0", {"leonida-v-0.1.0.zip": b"z"})
    info = check()
    assert info.latest == "0.1.0" and not info.newer and info.sha256 == {}
    assert apply(info, Path("unused"), Path("unused")).endswith("is up to date.")


# -------------------------------------------------------------------------------------------------- kind
def test_install_kind(tmp_path, monkeypatch):
    assert install_kind(tmp_path) == "zip"
    (tmp_path / ".git").mkdir()
    assert install_kind(tmp_path) == "git"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert install_kind(tmp_path) == "exe"


# --------------------------------------------------------------------------------------------------- zip
@pytest.fixture
def kit(tmp_path):
    k = tmp_path / "Leonida"
    (k / "leonida-v" / "leonida").mkdir(parents=True)
    (k / "leonida-v" / "pyproject.toml").write_text("old")
    (k / "State").mkdir()
    (k / "Downloads").mkdir()
    (k / "Downloads" / "mod.zip").write_bytes(b"keep")
    return k


@pytest.mark.parametrize("top", ["leonida-v", "leonida-v-9.9.9", None])
def test_zip_staging(server, kit, top):
    z = release_zip(top)
    publish(server, files={"leonida-v-9.9.9.zip": z}, sums=f"{sha(z)}  leonida-v-9.9.9.zip\n")
    msg = apply(check(), kit / "leonida-v", kit / "State")
    staged = kit / "leonida-v.new"
    assert (staged / "pyproject.toml").is_file() and (staged / "leonida" / "__init__.py").is_file()
    assert (staged / updater.READY_MARKER).read_text().strip() == "9.9.9"
    assert "Start-Leonida.bat" in msg and "Warning" not in msg
    assert (kit / "leonida-v" / "pyproject.toml").read_text() == "old"  # current copy untouched
    assert (kit / "Downloads" / "mod.zip").read_bytes() == b"keep"
    assert (kit / "State" / "updates" / "9.9.9" / "leonida-v-9.9.9.zip").is_file()


def test_zip_without_sum_warns(server, kit):
    publish(server, files={"leonida-v-9.9.9.zip": release_zip()})
    msg = apply(check(), kit / "leonida-v", kit / "State")
    assert msg.startswith("Warning") and (kit / "leonida-v.new" / updater.READY_MARKER).exists()


def test_zip_sha_mismatch_refused(server, kit):
    publish(server, files={"leonida-v-9.9.9.zip": release_zip()}, sums=f"{'0' * 64}  leonida-v-9.9.9.zip\n")
    with pytest.raises(UpdateError, match="SHA-256"):
        apply(check(), kit / "leonida-v", kit / "State")
    assert not (kit / "leonida-v.new").exists()
    assert not (kit / "State" / "updates" / "9.9.9" / "leonida-v-9.9.9.zip").exists()  # bad file deleted


def test_zip_not_a_release_refused(server, kit):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "hi")
    publish(server, files={"leonida-v-9.9.9.zip": buf.getvalue()})
    with pytest.raises(UpdateError, match="does not look like"):
        apply(check(), kit / "leonida-v", kit / "State")
    assert not (kit / "leonida-v.new").exists()


def test_zip_missing_asset(server, kit):
    publish(server, files={"other.7z": b"x"})
    with pytest.raises(UpdateError, match="no leonida-v"):
        apply(check(), kit / "leonida-v", kit / "State")


# --------------------------------------------------------------------------------------------------- exe
def folder_zip(top: str | None = "LeonidaV", exe: bytes = b"MZ new gui") -> bytes:
    buf = io.BytesIO()
    prefix = f"{top}/" if top else ""
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(prefix + "LeonidaV.exe", exe)
        zf.writestr(prefix + "leonida.exe", b"MZ new cli")
        zf.writestr(prefix + "_internal/base_library.zip", b"libs")
    return buf.getvalue()


@pytest.fixture
def frozen_install(tmp_path, monkeypatch):
    app = tmp_path / "Programs" / "LeonidaV"
    (app / "_internal").mkdir(parents=True)
    (app / "LeonidaV.exe").write_bytes(b"MZ old gui")
    (app / "_internal" / "old.dll").write_bytes(b"old")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_current_exe", lambda: app / "LeonidaV.exe")
    monkeypatch.setenv("LEONIDA_NO_OPEN", "1")
    return app


def test_check_picks_folder_zip(server):
    z = folder_zip()
    publish(server, files={"leonida-v-9.9.9-win64.zip": b"x", "leonida-v-9.9.9.zip": release_zip(),
                           "LeonidaV-9.9.9-win64.zip": z, "LeonidaV.exe": b"MZ"},
            sums=f"{sha(z)}  LeonidaV-9.9.9-win64.zip\n")
    info = check()
    assert info.exe_url.endswith("/dl/LeonidaV-9.9.9-win64.zip")
    assert info.zip_url.endswith("/dl/leonida-v-9.9.9.zip")  # the portable zip, never a win64 one
    assert info.sha256 == {"LeonidaV-9.9.9-win64.zip": sha(z)}


@pytest.mark.parametrize("top", ["LeonidaV", None])
def test_exe_update_stages_folder(server, tmp_path, frozen_install, top):
    z = folder_zip(top)
    publish(server, files={"LeonidaV-9.9.9-win64.zip": z}, sums=f"{sha(z)}  LeonidaV-9.9.9-win64.zip\n")
    msg = apply(check(), tmp_path / "unused", tmp_path / "state")
    staged = frozen_install.with_name("LeonidaV.new")
    assert (staged / "LeonidaV.exe").read_bytes() == b"MZ new gui"
    assert (staged / "_internal" / "base_library.zip").is_file()
    assert (frozen_install / "LeonidaV.exe").read_bytes() == b"MZ old gui"  # swapped only after exit
    helper = tmp_path / "state" / "updates" / "apply-update.bat"
    raw = helper.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    for part in (str(frozen_install), str(staged), str(frozen_install) + ".old", str(os.getpid())):
        assert part.encode() in raw
    assert b'start "" "%DIR%\\LeonidaV.exe"' in raw
    assert b'"IMAGENAME eq LeonidaV.exe"' in raw and b'"IMAGENAME eq leonida.exe"' in raw  # waits for every Leonida
    assert "Close Leonida V" in msg and "Warning" not in msg


def test_exe_update_refuses_bad_zip(server, tmp_path, frozen_install):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no exe here")
    publish(server, files={"LeonidaV-9.9.9-win64.zip": buf.getvalue()})
    with pytest.raises(UpdateError, match="LeonidaV.exe"):
        apply(check(), tmp_path, tmp_path / "state")
    assert not frozen_install.with_name("LeonidaV.new").exists()


def test_exe_sha_mismatch(server, tmp_path, frozen_install):
    publish(server, files={"LeonidaV-9.9.9-win64.zip": folder_zip()}, sums=f"{'a' * 64}  LeonidaV-9.9.9-win64.zip\n")
    with pytest.raises(UpdateError, match="SHA-256"):
        apply(check(), tmp_path, tmp_path / "state")
    assert not frozen_install.with_name("LeonidaV.new").exists()


def test_exe_missing_asset(server, tmp_path, frozen_install):
    publish(server, files={"leonida-v-9.9.9.zip": release_zip()})
    with pytest.raises(UpdateError, match="win64"):
        apply(check(), tmp_path, tmp_path / "state")


# The helper .bat itself, run for real (Windows only), waiting on a PID that doesn't exist.
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="runs a .bat")
DEAD_PID = 999_999_999
# the helper waits while Leonida runs; a real leonida.exe on this PC (e.g. `leonida playtest`) must not block the tests
NO_SUCH_EXES = ("LeonidaV-test-not-running.exe",)


def _install_pair(tmp_path):
    install = tmp_path / "LeonidaV"
    (install / "_internal").mkdir(parents=True)
    (install / "LeonidaV.exe").write_text("old")
    staged = tmp_path / "LeonidaV.new"
    (staged / "_internal").mkdir(parents=True)
    (staged / "LeonidaV.exe").write_text("new")
    (staged / updater.READY_MARKER).write_text("9.9.9")
    return install, staged


def _run(helper: Path) -> int:
    return subprocess.run(["cmd", "/c", str(helper)], cwd=str(helper.parent), capture_output=True, timeout=60).returncode


@windows_only
def test_helper_swaps_folders(tmp_path):
    install, staged = _install_pair(tmp_path)
    old = tmp_path / "LeonidaV.old"
    old.mkdir()
    (old / "ancient.txt").write_text("older .old is replaced")
    helper = updater.write_helper(install, staged, tmp_path / "upd" / "apply-update.bat", DEAD_PID,
                                  restart=False, wait=2, tries=2, exes=NO_SUCH_EXES)
    assert _run(helper) == 0
    assert (install / "LeonidaV.exe").read_text() == "new"
    assert not (install / updater.READY_MARKER).exists()
    assert (old / "LeonidaV.exe").read_text() == "old" and not (old / "ancient.txt").exists()
    assert not staged.exists() and not helper.exists()


@windows_only
def test_helper_rolls_back_when_new_folder_is_locked(tmp_path):
    install, staged = _install_pair(tmp_path)
    helper = updater.write_helper(install, staged, tmp_path / "upd" / "apply-update.bat", DEAD_PID,
                                  restart=False, wait=2, tries=2, exes=NO_SUCH_EXES)
    with open(staged / "_internal" / "locked.bin", "wb"):  # an open file blocks renaming its folder
        rc = _run(helper)
    assert rc == 1
    assert (install / "LeonidaV.exe").read_text() == "old"  # rolled back
    assert not (tmp_path / "LeonidaV.old").exists()
    assert (staged / "LeonidaV.exe").read_text() == "new"
    assert (helper.parent / "apply-update.log").is_file()


# --------------------------------------------------------------------------------------------------- git
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    (origin / "pyproject.toml").write_text("v1\n")
    (origin / "readme.txt").write_text("a\n")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "one")
    kit = tmp_path / "Leonida"
    kit.mkdir()
    git(tmp_path, "clone", "-q", str(origin), str(kit / "leonida-v"))
    (kit / ".venv").mkdir()
    (kit / ".venv" / updater.INSTALLED_MARKER).write_text("ok")
    return origin, kit / "leonida-v"


INFO = UpdateInfo("1.0.0", "9.9.9", True, "", "https://example.invalid", None, None, {})


@needs_git
def test_git_refuses_dirty_tree(repos):
    origin, clone = repos
    (clone / "readme.txt").write_text("local edit\n")
    with pytest.raises(UpdateError, match="local changes"):
        apply(INFO, clone, clone.parent / "State")
    assert (clone / "readme.txt").read_text() == "local edit\n"  # never stashed or reset
    assert "readme.txt" in git(clone, "status", "--porcelain")


@needs_git
def test_git_pull_and_reinstall_marker(repos):
    origin, clone = repos
    (origin / "readme.txt").write_text("b\n")
    git(origin, "commit", "-q", "-am", "two")
    msg = apply(INFO, clone, clone.parent / "State")
    assert "Restart" in msg and (clone / "readme.txt").read_text() == "b\n"
    assert (clone.parent / ".venv" / updater.INSTALLED_MARKER).exists()

    (origin / "pyproject.toml").write_text("v2\n")
    git(origin, "commit", "-q", "-am", "deps")
    msg = apply(INFO, clone, clone.parent / "State")
    assert "Start-Leonida.bat" in msg
    assert not (clone.parent / ".venv" / updater.INSTALLED_MARKER).exists()

    assert apply(INFO, clone, clone.parent / "State").startswith("Already up to date")


# ------------------------------------------------------------------------------------- force / repair / cache
SAME = UpdateInfo(__version__, __version__, False, "", "https://example.invalid", None, None, {})


def test_force_without_release_is_an_error(tmp_path):
    none = UpdateInfo(__version__, None, False, "", "https://example.invalid", None, None, {})
    assert apply(none, tmp_path, tmp_path).endswith("is up to date.")
    with pytest.raises(UpdateError, match="No Leonida V release has been published yet"):
        apply(none, tmp_path, tmp_path, force=True)


def test_force_zip_same_version_redownloads(server, kit):
    z = release_zip()
    publish(server, f"v{__version__}", {f"leonida-v-{__version__}.zip": z})
    info = check()
    assert not info.newer
    assert apply(info, kit / "leonida-v", kit / "State").endswith("is up to date.")
    assert not (kit / "leonida-v.new").exists()
    cached = kit / "State" / "updates" / __version__ / f"leonida-v-{__version__}.zip"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"broken earlier download")  # no SHA in this release: force must not trust it
    msg = apply(info, kit / "leonida-v", kit / "State", force=True)
    assert cached.read_bytes() == z
    assert (kit / "leonida-v.new" / updater.READY_MARKER).read_text().strip() == __version__
    assert "Start-Leonida.bat" in msg


def test_force_exe_same_version(server, tmp_path, frozen_install):
    z = folder_zip()
    publish(server, f"v{__version__}", {f"LeonidaV-{__version__}-win64.zip": z},
            sums=f"{sha(z)}  LeonidaV-{__version__}-win64.zip\n")
    info = check()
    assert not info.newer
    apply(info, tmp_path, tmp_path / "state", force=True)
    assert (frozen_install.with_name("LeonidaV.new") / "LeonidaV.exe").read_bytes() == b"MZ new gui"
    assert (tmp_path / "state" / "updates" / "apply-update.bat").is_file()


def test_force_older_release_notes_downgrade(server, kit):
    publish(server, "v0.0.1", {"leonida-v-0.0.1.zip": release_zip()})
    msg = apply(check(), kit / "leonida-v", kit / "State", force=True)
    assert msg.startswith(f"Note: this replaces your newer {__version__}")


@needs_git
def test_force_git_reinstalls(repos):
    origin, clone = repos
    msg = apply(SAME, clone, clone.parent / "State", force=True)
    assert "Already at the latest commit (forced)" in msg and "reinstalls" in msg
    assert not (clone.parent / ".venv" / updater.INSTALLED_MARKER).exists()
    (origin / "readme.txt").write_text("c\n")
    git(origin, "commit", "-q", "-am", "three")
    assert "Updated the git clone" in apply(SAME, clone, clone.parent / "State", force=True)
    assert (clone / "readme.txt").read_text() == "c\n"


@needs_git
def test_force_git_still_refuses_local_changes(repos):
    origin, clone = repos
    (clone / "readme.txt").write_text("mine\n")
    with pytest.raises(UpdateError, match="local changes"):
        apply(SAME, clone, clone.parent / "State", force=True)
    assert (clone / "readme.txt").read_text() == "mine\n"
    assert (clone.parent / ".venv" / updater.INSTALLED_MARKER).exists()


def test_request_reinstall(kit, monkeypatch):
    project = kit / "leonida-v"
    assert "nothing to reset" in updater.request_reinstall(project)
    (kit / ".venv").mkdir()
    (kit / ".venv" / updater.INSTALLED_MARKER).write_text("ok")
    assert "reinstalls the package" in updater.request_reinstall(project)
    assert not (kit / ".venv" / updater.INSTALLED_MARKER).exists()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(UpdateError, match="Force update"):
        updater.request_reinstall(project)


def test_check_cache(server, tmp_path, monkeypatch):
    publish(server, "v9.9.9", {"leonida-v-9.9.9.zip": release_zip()})
    state = tmp_path / "State"
    assert updater.cached_check(state) is None
    first = check(cache_dir=state, max_age=0)
    assert not first.from_cache and first.checked_at and (state / updater.CACHE_NAME).is_file()
    n = len(server.requests)
    again = check(cache_dir=state, max_age=updater.DAY)
    assert again.from_cache and again.latest == "9.9.9" and again.newer and again.zip_url == first.zip_url
    assert len(server.requests) == n  # no network
    assert again.age is not None and again.age < 60
    check(cache_dir=state, max_age=0)
    assert len(server.requests) > n  # "Check now" always asks

    data = json.loads((state / updater.CACHE_NAME).read_text())
    data["checked_at"] -= 2 * updater.DAY
    data["current"] = "0.0.1"
    (state / updater.CACHE_NAME).write_text(json.dumps(data))
    old = updater.cached_check(state)
    assert old.age > updater.DAY and old.current == __version__  # recomputed for the running version
    n = len(server.requests)
    assert not check(cache_dir=state, max_age=updater.DAY).from_cache and len(server.requests) > n  # stale
    (state / updater.CACHE_NAME).write_text("{broken")
    assert updater.cached_check(state) is None


def test_cli_self_update_force_check_reinstall(server, kit, monkeypatch, capsys):
    from leonida.cli import main

    monkeypatch.setattr(updater, "project_dir", lambda: kit / "leonida-v")
    base = ["--state-dir", str(kit / "State")]
    assert main(base + ["self-update", "--force"]) == 1
    assert "No Leonida V release has been published yet" in capsys.readouterr().out

    publish(server, f"v{__version__}", {f"leonida-v-{__version__}.zip": release_zip()})
    assert main(base + ["self-update", "--check"]) == 0
    out = capsys.readouterr().out
    assert "Last check: just now" in out and "--force" in out
    assert main(base + ["self-update", "--force"]) == 0
    assert (kit / "leonida-v.new" / updater.READY_MARKER).exists()
    capsys.readouterr()

    (kit / ".venv").mkdir()
    (kit / ".venv" / updater.INSTALLED_MARKER).write_text("ok")
    assert main(base + ["self-update", "--reinstall"]) == 0
    assert not (kit / ".venv" / updater.INSTALLED_MARKER).exists()
