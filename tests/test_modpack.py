"""Modpack lockfile + mod auto-updater: format, diff, verification, redistribution, the full update flow."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from conftest import AutoUI, make_zip
from test_downloader import Server

from leonida import downloader
from leonida import modpack as mp
from leonida import modupdate as mu
from leonida.cli import main
from leonida.manifest import ManifestError, load_manifest
from leonida.matcher import build_lock, write_lock
from leonida.paths import LOCK_NAME
from leonida.session import Session
from leonida.snapshot import diff as snap_diff
from leonida.snapshot import load_snapshot, take_snapshot

BUILD = "1.0.1013.20"


def _mod(mid, order, files, version, **extra):
    return {"id": mid, "order": order, "tier": "core", "layer": "test", "name": mid.title(), "version": version,
            "source": "direct", "page": f"https://{mid}.example/page", "archive": [f"{mid}-*.zip"],
            "install": {"method": "copy", "files": [{"match": f} for f in files]}, **extra}


MODS = [
    _mod("alpha", 1, ["alpha.asi", "alpha.ini"], "2.0"),
    _mod("beta", 2, ["beta.asi"], "1.0"),
    _mod("gamma", 3, ["gamma.asi", "alpha.ini"], "1.0"),  # overwrites alpha.ini -> depends on alpha
]


def write_manifest(root: Path, mods=None) -> Path:
    d = root / "manifest"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "9", "testedGameBuilds": [BUILD],
                                             "gameExeNames": ["GTA5_Enhanced.exe"], "mods": mods or MODS}))
    (d / "profiles.json").write_text(json.dumps({"default": "all", "profiles": [
        {"id": "all", "name": "All", "include": [m["id"] for m in (mods or MODS)]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    return d


@pytest.fixture
def kit(tmp_path, game, downloads):
    """Fake game with alpha 1.0, beta, gamma installed (lockfile written), alpha 2.0 not downloaded yet."""
    mdir = write_manifest(tmp_path)
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


def v2_zip(downloads: Path, alpha_asi: str = "alpha v2") -> Path:
    return make_zip(downloads / "alpha-2.0.zip", {"alpha.asi": alpha_asi, "alpha.ini": "a=2"})


def pack_for(s: Session, files: dict[str, Path], build: str = BUILD) -> dict:
    mods = {mid: mp.entry_for(s.manifest.mod(mid), p) for mid, p in files.items()}
    return mp.validate({"schema": 1, "pack": "Leonida V", "version": "9", "builds": {build: {"mods": mods}}})


def current_files(downloads: Path) -> dict[str, Path]:
    return {"beta": downloads / "beta-1.0.zip", "gamma": downloads / "gamma-1.0.zip"}


# ---------------------------------------------------------------------------------------------- format
def test_build_round_trip_and_merge(tmp_path, kit, downloads):
    data = mp.build_modpack(kit)
    assert data["schema"] == 1 and list(data["builds"]) == [BUILD]
    entries = data["builds"][BUILD]["mods"]
    assert set(entries) == {"alpha", "beta", "gamma"}
    e = entries["beta"]
    assert e["file"] == "beta-1.0.zip" and e["sha256"] == hashlib.sha256((downloads / "beta-1.0.zip").read_bytes()).hexdigest()
    assert e["source"] == {"page": "https://beta.example/page", "download": None} and e["redistributable"] is False
    out = mp.write_file(tmp_path / "modpack.json", data)
    assert mp.load_file(out) == data

    other = copy.deepcopy(data)
    other["builds"] = {"1.0.1158.13": other["builds"].pop(BUILD)}
    merged = mp.merge(mp.load_file(out), other)
    assert list(merged["builds"]) == [BUILD, "1.0.1158.13"]
    assert mp.merge(merged, data)["builds"][BUILD] == data["builds"][BUILD]


def test_build_needs_a_game_build(tmp_path, downloads):
    s = Session(tmp_path / "st", write_manifest(tmp_path), download_dir=str(downloads))
    with pytest.raises(mp.ModpackError, match="game build"):
        mp.build_modpack(s)


GOOD = {"version": "1", "file": "a.zip", "size": 1, "sha256": "a" * 64,
        "source": {"page": "https://a.example/", "download": None}, "redistributable": False}


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(schema=2), "schema"),
    (lambda d: d.update(builds={}), "no 'builds'"),
    (lambda d: d["builds"].update({"latest": {"mods": {}}}), "not a game build"),
    (lambda d: d["builds"][BUILD]["mods"]["a"].update(sha256="XYZ"), "sha256"),
    (lambda d: d["builds"][BUILD]["mods"]["a"].update(file="../evil.zip"), "plain file name"),
    (lambda d: d["builds"][BUILD]["mods"]["a"].update(size="1"), "size"),
    (lambda d: d["builds"][BUILD]["mods"]["a"]["source"].update(page="http://a.example/"), "https page"),
    (lambda d: d["builds"][BUILD]["mods"]["a"].update(mirror="https://m.example/a.zip"), "mirror"),
    (lambda d: d["builds"][BUILD]["mods"]["a"]["source"].update(download={"type": "ftp"}), "download type"),
])
def test_validate_errors(mutate, message):
    d = {"schema": 1, "builds": {BUILD: {"mods": {"a": copy.deepcopy(GOOD)}}}}
    mp.validate(copy.deepcopy(d))
    mutate(d)
    with pytest.raises(mp.ModpackError, match=message):
        mp.validate(d)


# ------------------------------------------------------------------------------------------------ diff
def test_diff_cases():
    lock = {"entries": [{"mod": "a", "file": "a1.zip", "sha256": "1" * 64}, {"mod": "b", "file": "b.zip", "sha256": "2" * 64},
                        {"mod": "gone", "file": "g.zip", "sha256": "3" * 64}]}
    entry = lambda f, h: dict(GOOD, file=f, sha256=h)  # noqa: E731
    pack = {"schema": 1, "builds": {BUILD: {"mods": {"a": entry("a2.zip", "4" * 64), "b": entry("b.zip", "2" * 64),
                                                       "new": entry("n.zip", "5" * 64)}}}}
    kinds = {c.mod: c.kind for c in mp.diff(lock, pack, BUILD)}
    assert kinds == {"a": "updated", "b": "same", "gone": "removed", "new": "added"}
    a = next(c for c in mp.diff(lock, pack, BUILD) if c.mod == "a")
    assert (a.old_file, a.new_file, a.new_version) == ("a1.zip", "a2.zip", "1")
    assert {c.kind for c in mp.diff(None, pack, BUILD)} == {"added"}
    assert mp.section_for(pack, "1.0.1013.25")[0] == BUILD          # newest older section
    assert mp.section_for(pack, "1.0.1013.19") == (None, None)
    with pytest.raises(mp.ModpackError, match="no tested set for game build 1.0.900.0"):
        mp.diff(lock, pack, "1.0.900.0")


def test_verify_file(tmp_path):
    f = tmp_path / "a.zip"
    f.write_bytes(b"hello")
    e = dict(GOOD, size=5, sha256=hashlib.sha256(b"hello").hexdigest())
    assert mp.verify_file(f, e) is None
    assert "bytes" in mp.verify_file(f, dict(e, size=6))
    assert "SHA-256" in mp.verify_file(f, dict(e, sha256="0" * 64)) and f.read_bytes() == b"hello"
    assert "not in the download folder" in mp.verify_file(tmp_path / "x.zip", e)


# ------------------------------------------------------------------------------------- redistribution
@pytest.mark.parametrize("value, message", [
    ({"allowed": "yes"}, "redistribution must be"),
    ({"allowed": True}, "proof"),
    ({"allowed": True, "proof": "http://x"}, "proof"),
    ({"allowed": False, "licence": "x"}, "unknown key"),
])
def test_redistribution_schema(tmp_path, value, message):
    with pytest.raises(ManifestError, match=message):
        load_manifest(write_manifest(tmp_path, [_mod("alpha", 1, ["a.asi"], "1", redistribution=value)]))


def test_redistribution_rule(tmp_path):
    ok = {"allowed": True, "proof": "https://alpha.example/licence"}
    m = load_manifest(write_manifest(tmp_path, [_mod("alpha", 1, ["a.asi"], "1", redistribution=ok),
                                                _mod("beta", 2, ["b.asi"], "1", redistribution={"allowed": False}),
                                                _mod("gamma", 3, ["g.asi"], "1",
                                                     download={"type": "github", "repo": "auth/gamma", "asset": "*.zip"})]))
    assert m.mod("alpha").redistributable and not m.mod("beta").redistributable
    page = lambda mid: {"page": f"https://{mid}.example/page", "download": None}  # noqa: E731
    assert mp.entry_problem("alpha", dict(GOOD, source=page("alpha"), redistributable=True), m, BUILD) is None
    assert "no redistribution permission" in mp.entry_problem(
        "beta", dict(GOOD, source=page("beta"), redistributable=True), m, BUILD)
    assert "no redistribution permission" in mp.entry_problem(
        "beta", dict(GOOD, source=page("beta"), mirror="https://ours.example/b.zip"), m, BUILD)
    assert "isn't the author's page" in mp.entry_problem(
        "beta", dict(GOOD, source={"page": "https://mirror.example/b", "download": None}), m, BUILD)
    evil = {"page": "https://gamma.example/page", "download": {"type": "github", "repo": "evil/gamma", "asset": "*.zip"}}
    assert "author's source" in mp.entry_problem("gamma", dict(GOOD, source=evil), m, BUILD)
    assert "update Leonida" in mp.entry_problem("nope", GOOD, m, BUILD)


# ---------------------------------------------------------------------------------------- update flow
def test_update_flow_v1_to_v2_rollback_uninstall(kit, game, downloads):
    baseline = load_snapshot(kit.state / "baseline-snapshot.json")
    v2 = v2_zip(downloads)
    pack = pack_for(kit, {"alpha": v2, **current_files(downloads)})
    plan = mu.plan_updates(kit, pack)
    acts = {i.mod_id: i.action for i in plan.items}
    assert acts == {"alpha": mu.READY, "beta": mu.CURRENT, "gamma": mu.CURRENT} and not plan.held

    beta_step = next(s for s in kit.log.active_steps() if s.mod == "beta")
    report = mu.run_updates(kit, plan, AutoUI())
    assert any("updated to 2.0" in r for r in report) and any("Reinstalled after Alpha" in r for r in report)
    assert (game / "alpha.asi").read_text() == "alpha v2"
    assert (game / "alpha.ini").read_text() == "a=gamma"  # gamma (installed later) still wins
    assert beta_step.status == "done"                     # independent step left alone
    active = [s.mod for s in kit.log.active_steps()]
    assert active == ["beta", "alpha", "gamma"]
    assert {e["mod"]: e["file"] for e in json.loads((kit.state / LOCK_NAME).read_text())["entries"]}["alpha"] == "alpha-2.0.zip"
    assert mu.plan_updates(kit, pack).pending == []       # now current

    inst = kit.installer(AutoUI())
    inst.rollback(kit.log.last_active().id)               # roll back gamma's reinstall
    assert (game / "alpha.ini").read_text() == "a=2" and not (game / "gamma.asi").exists()
    warnings, residual = inst.uninstall()
    assert not warnings and residual.empty, residual.summary()
    assert snap_diff(baseline, take_snapshot(game)).empty


def test_sha_mismatch_is_refused_and_kept(kit, game, downloads):
    good = v2_zip(downloads)
    pack = pack_for(kit, {"alpha": good, **current_files(downloads)})
    good.unlink()
    bad = v2_zip(downloads, alpha_asi="tampered!")  # same name, different bytes
    plan = mu.plan_updates(kit, pack)
    item = next(i for i in plan.items if i.mod_id == "alpha")
    assert item.action == mu.REFUSED and ("SHA-256" in item.message or "bytes" in item.message)
    assert mu.run_updates(kit, plan, AutoUI()) == []
    assert bad.exists() and (game / "alpha.asi").read_text() == "alpha v1"


def test_update_held_on_unsupported_build(tmp_path, kit, downloads):
    pack = pack_for(kit, {"alpha": v2_zip(downloads), **current_files(downloads)})
    mods = copy.deepcopy(MODS)
    mods[0]["minGameBuild"] = "1.0.1013.30"
    kit.manifest = load_manifest(write_manifest(tmp_path / "newer", mods))
    plan = mu.plan_updates(kit, pack)
    assert plan.held and "doesn't support game build 1.0.1013.20" in plan.held and plan.pending == []
    with pytest.raises(mu.ModUpdateError, match="doesn't support"):
        mu.run_updates(kit, plan, AutoUI())


def test_update_held_without_section(kit, downloads):
    pack = pack_for(kit, {"alpha": v2_zip(downloads)}, build="1.0.1200.0")
    plan = mu.plan_updates(kit, pack)
    assert "no tested set for game build 1.0.1013.20" in plan.held


def test_version_mismatch_refused(kit, downloads):
    pack = pack_for(kit, {"alpha": v2_zip(downloads), **current_files(downloads)})
    pack["builds"][BUILD]["mods"]["alpha"]["version"] = "3.0"
    item = next(i for i in mu.plan_updates(kit, pack).items if i.mod_id == "alpha")
    assert item.action == mu.REFUSED and "self-update" in item.message


def test_skip_version_and_only(kit, downloads):
    pack = pack_for(kit, {"alpha": v2_zip(downloads), **current_files(downloads)})
    mu.skip_version(kit.state, "alpha", "2.0")
    assert next(i for i in mu.plan_updates(kit, pack).items if i.mod_id == "alpha").action == mu.SKIPPED
    mu.skip_version(kit.state, "alpha", None)
    assert [i.mod_id for i in mu.plan_updates(kit, pack, only="beta").items] == ["beta"]
    assert [i.mod_id for i in mu.plan_updates(kit, pack, only="alpha").pending] == ["alpha"]


def test_browser_mod_needs_manual_download(kit, downloads):
    v2 = v2_zip(downloads)
    pack = pack_for(kit, {"alpha": v2, **current_files(downloads)})
    v2.unlink()
    item = next(i for i in mu.plan_updates(kit, pack).items if i.mod_id == "alpha")
    assert item.action == mu.GET_MANUALLY and "https://alpha.example/page" in item.message


def test_auto_mod_downloads_exact_tested_asset(tmp_path, game, downloads, monkeypatch):
    srv = Server()
    try:
        monkeypatch.setattr(downloader, "GITHUB_API", srv.base + "/gh")
        mods = copy.deepcopy(MODS)
        mods[0]["download"] = {"type": "github", "repo": "auth/alpha", "asset": "alpha-*.zip"}
        mdir = write_manifest(tmp_path, mods)
        state = tmp_path / "st"
        v1 = make_zip(downloads / "alpha-1.0.zip", {"alpha.asi": "alpha v1", "alpha.ini": "a=1"})
        s = Session(state, mdir, download_dir=str(downloads), game_dir=str(game), game_build=BUILD)
        s.installer(AutoUI()).install(s.manifest.mod("alpha"), v1)
        write_lock(state / LOCK_NAME, build_lock("Leonida V", "9", {"alpha": v1}))
        v2 = make_zip(tmp_path / "srv" / "alpha-2.0.zip", {"alpha.asi": "alpha v2", "alpha.ini": "a=2"})
        pack = pack_for(s, {"alpha": v2})
        url = srv.add("/files/alpha-2.0.zip", body=v2.read_bytes())
        srv.add("/gh/repos/auth/alpha/releases/latest", ctype="application/json", body=json.dumps({"tag_name": "v2", "assets": [
            {"name": "alpha-2.1-beta.zip", "browser_download_url": srv.base + "/nope", "size": 1},  # newer, untested
            {"name": "alpha-2.0.zip", "browser_download_url": url, "size": v2.stat().st_size}]}).encode())
        plan = mu.plan_updates(s, pack)
        assert [i.action for i in plan.items] == [mu.DOWNLOAD]
        report = mu.run_updates(s, plan, AutoUI())
        assert "updated to 2.0" in report[0]
        assert (downloads / "alpha-2.0.zip").read_bytes() == v2.read_bytes() and (game / "alpha.asi").read_text() == "alpha v2"
    finally:
        srv.close()


# ------------------------------------------------------------------------------------------ fetch_latest
def test_fetch_latest(monkeypatch, tmp_path):
    srv = Server()
    try:
        monkeypatch.setattr(downloader, "GITHUB_API", srv.base + "/gh")
        assert mp.fetch_latest() is None  # no release
        body = json.dumps({"schema": 1, "builds": {BUILD: {"mods": {"a": GOOD}}}}).encode()
        latest = "/gh/repos/JacobJandon/leonida-v/releases/latest"

        def publish(sums: str | None, with_pack=True):
            assets = [{"name": "modpack.json", "browser_download_url": srv.add("/dl/modpack.json", body=body)}] if with_pack else []
            if sums is not None:
                assets.append({"name": "SHA256SUMS.txt", "browser_download_url": srv.add("/dl/sums", body=sums.encode())})
            srv.add(latest, ctype="application/json", body=json.dumps(
                {"tag_name": "v1.2.0", "html_url": "https://example.invalid/r", "assets": assets}).encode())

        publish(None, with_pack=False)
        assert mp.fetch_latest() is None  # release without a modpack
        publish(f"{hashlib.sha256(body).hexdigest()}  modpack.json\n")
        data = mp.fetch_latest()
        assert data["_release"] == {"tag": "v1.2.0", "page": "https://example.invalid/r", "verified": True}
        assert data["builds"][BUILD]["mods"]["a"]["file"] == "a.zip"
        publish(None)
        assert mp.fetch_latest()["_release"]["verified"] is False
        publish(f"{'0' * 64}  modpack.json\n")
        with pytest.raises(mp.ModpackError, match="tampered"):
            mp.fetch_latest()
    finally:
        srv.close()


# --------------------------------------------------------------------------------------------------- CLI
def test_cli_modpack_and_update(kit, game, downloads, tmp_path, capsys):
    base = ["--state-dir", str(kit.state), "--manifest-dir", str(tmp_path / "manifest"),
            "--download-dir", str(downloads), "--game-dir", str(game), "--game-build", BUILD]
    out = tmp_path / "release" / "modpack.json"
    assert main(base + ["modpack", "build", "--out", str(out)]) == 0
    assert "Recorded 3 mod file(s) for game build 1.0.1013.20" in capsys.readouterr().out
    assert set(mp.load_file(out)["builds"][BUILD]["mods"]) == {"alpha", "beta", "gamma"}

    pack = pack_for(kit, {"alpha": v2_zip(downloads), **current_files(downloads)})
    pf = mp.write_file(tmp_path / "pack.json", pack)
    assert main(base + ["update", "--modpack", str(pf), "--check"]) == 0
    text = capsys.readouterr().out
    assert "[update] Alpha -> 2.0" in text and "1 update(s) available" in text
    assert (game / "alpha.asi").read_text() == "alpha v1"

    assert main(base + ["update", "--skip", "alpha@2.0"]) == 0
    main(base + ["update", "--modpack", str(pf), "--check"])
    assert "[skipped] Alpha" in capsys.readouterr().out
    main(base + ["update", "--skip", "alpha"])
    assert main(base + ["update", "--modpack", str(pf), "--yes"]) == 0
    assert "updated to 2.0" in capsys.readouterr().out and (game / "alpha.asi").read_text() == "alpha v2"
