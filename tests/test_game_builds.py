"""Game-build compatibility: schema, resolution, checks, session and CLI (test-local manifests only)."""

from __future__ import annotations

import copy
import json
from importlib import resources
from pathlib import Path

import pytest

from leonida import session as session_mod
from leonida.checks import ERROR, INFO, WARNING, run_checks
from leonida.cli import main
from leonida.manifest import ManifestError, build_key, in_build_range, load_manifest
from leonida.session import Session

BUNDLED = {n: json.loads(resources.files("leonida.manifest").joinpath(n).read_text(encoding="utf-8"))
           for n in ("mods.json", "profiles.json", "hotkeys.json")}

SHV_BUILDS = {
    "minGameBuild": "1.0.1013.17",
    "gameBuilds": [
        {"min": "1.0.889.0", "max": "1.0.1013.16", "version": "1.0.3411.0", "page": "https://example.invalid/shv-old",
         "archive": ["ScriptHookV_1.0.3411.0*.zip"], "notes": "older Script Hook V",
         "download": {"type": "github", "repo": "o/r", "asset": "*.zip", "tag": "v1.0.3411.0"}},
        {"min": "1.0.800.0", "max": "1.0.1000.0", "version": "shadowed-for-889-1000", "archive": ["x*.zip"]},
        {"min": "1.0.700.0", "max": "1.0.799.99", "unsupported": "No Script Hook V exists for these builds."},
    ],
}


def write_manifest(tmp_path: Path, mods: dict[str, dict] | None = None, top: dict | None = None) -> Path:
    """Copy the bundled manifest into tmp_path, merging extra fields into the given mods / top level."""
    data = copy.deepcopy(BUNDLED)
    for raw in data["mods.json"]["mods"]:
        raw.pop("minGameBuild", None), raw.pop("maxGameBuild", None), raw.pop("gameBuilds", None)
        raw.update((mods or {}).get(raw["id"], {}))
    data["mods.json"].pop("testedGameBuilds", None)
    data["mods.json"]["testedGameBuild"] = "1.0.1158.13"
    data["mods.json"].update(top or {})
    d = tmp_path / "manifest"
    d.mkdir(exist_ok=True)
    for name, content in data.items():
        (d / name).write_text(json.dumps(content), encoding="utf-8")
    return d


@pytest.fixture
def mdir(tmp_path):
    return write_manifest(tmp_path, {"scripthookv": SHV_BUILDS},
                          top={"testedGameBuilds": ["1.0.1013.20", "1.0.1158.13"]})


@pytest.fixture
def shv(mdir):
    return load_manifest(mdir).mod("scripthookv")


# ------------------------------------------------------------------------------------------- helpers
def test_build_key_and_range():
    assert build_key("1.0.1013.20") == (1, 0, 1013, 20)
    assert build_key("1.0.1013") == (1, 0, 1013, 0)
    assert build_key("1.0.1013.9") < build_key("1.0.1013.10")
    assert build_key(None) is None and build_key("unknown") is None
    assert in_build_range("1.0.1013.20", "1.0.1013.20", "1.0.1013.20")
    assert in_build_range("1.0.5", None, None) and not in_build_range(None, None, None)


# ---------------------------------------------------------------------------------------- resolution
@pytest.mark.parametrize("build, version, variant", [
    ("1.0.1013.17", "top", None),
    ("1.0.1013.20", "top", None),
    ("1.0.1158.13", "top", None),
    ("1.0.1013.16", "1.0.3411.0", 0),
    ("1.0.950.0", "1.0.3411.0", 0),        # in entries 0 and 1: the first wins
    ("1.0.850.0", "shadowed-for-889-1000", 1),
])
def test_resolution_order(shv, build, version, variant):
    m = shv.for_build(build)
    assert m.unsupported is None and m.variant == variant
    assert m.version == (shv.version if version == "top" else version)


def test_top_level_is_returned_as_is(shv):
    assert shv.for_build("1.0.1013.20") is shv
    assert shv.for_build(None) is shv and shv.for_build("garbage") is shv


def test_unsupported_reasons(shv):
    m = shv.for_build("1.0.750.0")
    assert m.unsupported == "No Script Hook V exists for these builds." and m.variant == 2
    m = shv.for_build("1.0.600.0")
    assert "needs game build 1.0.1013.17 or newer" in m.unsupported and "1.0.600.0" in m.unsupported
    assert m.variant is None


def test_max_reason(tmp_path):
    d = write_manifest(tmp_path, {"menyoo": {"minGameBuild": "1.0.1013.0", "maxGameBuild": "1.0.1158.99"}})
    m = load_manifest(d).mod("menyoo")
    assert m.for_build("1.0.1158.50").unsupported is None
    assert "up to 1.0.1158.99" in m.for_build("1.0.1200.0").unsupported
    assert m.supported_builds == "1.0.1013.0 to 1.0.1158.99"


def test_overrides_applied(shv):
    m = shv.for_build("1.0.1013.10")
    assert m.page == "https://example.invalid/shv-old"
    assert m.archive == ("ScriptHookV_1.0.3411.0*.zip",)
    assert m.download["tag"] == "v1.0.3411.0" and m.notes == "older Script Hook V"
    assert (m.id, m.order, m.files, m.method, m.name) == (shv.id, shv.order, shv.files, shv.method, shv.name)
    assert m.base is shv


def test_resolving_again_starts_from_the_original(shv):
    old = shv.for_build("1.0.1013.10")
    assert old.for_build("1.0.1013.20") is shv
    assert old.for_build("1.0.1013.10") == old
    assert shv.for_build("1.0.600.0").for_build("1.0.1013.12").variant == 0


def test_manifest_for_build(mdir):
    base = load_manifest(mdir)
    res = base.for_build("1.0.1013.10")
    assert res.game_build == "1.0.1013.10" and base.game_build is None
    assert res.mod("scripthookv").variant == 0 and base.mod("scripthookv").variant is None
    assert res.mod("menyoo") is base.mod("menyoo")  # mods without build data are unchanged
    assert [m.id for m in res.resolve("core")] == [m.id for m in base.resolve("core")]  # profiles unchanged
    assert res.for_build("1.0.1013.20").mod("scripthookv") is base.mod("scripthookv")


def test_tested_builds(mdir, tmp_path):
    m = load_manifest(mdir)
    assert m.tested_builds == ("1.0.1013.20", "1.0.1158.13") and m.tested_build == "1.0.1158.13"
    assert m.is_tested("1.0.1013.20") and not m.is_tested("1.0.1013.21") and not m.is_tested(None)
    assert m.newer_than_tested("1.0.1200.0") and not m.newer_than_tested("1.0.1100.0")
    (tmp_path / "legacy").mkdir()
    legacy = load_manifest(write_manifest(tmp_path / "legacy"))  # only the old single testedGameBuild
    assert legacy.tested_builds == ("1.0.1158.13",)


# ----------------------------------------------------------------------------------------- validation
@pytest.mark.parametrize("fields, message", [
    ({"minGameBuild": "latest"}, "must look like"),
    ({"maxGameBuild": 1013}, "must look like"),
    ({"minGameBuild": "1.0.1013.20", "maxGameBuild": "1.0.1013.0"}, "greater than max"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": {"min": "1.0"}}, "must be a list"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": ["x"]}, "must be an object"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"max": "1.0.1013.0", "verison": "1"}]}, "unknown key"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"min": "1.0.900.0", "max": "1.0.800.0", "version": "1"}]},
     "greater than max"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"max": "1.0.1013.0"}]}, "give the values"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"max": "1.0.1013.0", "unsupported": " "}]}, "non-empty reason"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"max": "1.0.1013.0", "unsupported": "no", "page": "https://x"}]},
     "can't also override"),
    ({"gameBuilds": [{"max": "1.0.1013.0", "version": "1"}]}, "never be used"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"min": "1.0.1013.20", "version": "1"}]}, "never be used"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"max": "1.0.1013.0", "page": "http://x"}]}, "https"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"max": "1.0.1013.0", "archive": []}]}, "can't be empty"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"max": "1.0.1013.0", "files": []}]}, "needs a 'files' list"),
    ({"minGameBuild": "1.0.1013.17", "gameBuilds": [{"max": "1.0.1013.0", "method": "magic"}]}, "unknown install"),
    ({"minGameBuild": "1.0.1013.17",
      "gameBuilds": [{"max": "1.0.1013.0", "download": {"type": "github", "repo": "o/r"}}]}, "needs 'repo' and 'asset'"),
    ({"download": {"type": "github", "repo": "o/r", "asset": "*.zip", "tag": ""}}, "'tag' must be"),
])
def test_schema_errors(tmp_path, fields, message):
    d = write_manifest(tmp_path, {"scripthookv": fields})
    with pytest.raises(ManifestError, match=message):
        load_manifest(d)


def test_tested_builds_must_be_a_list(tmp_path):
    with pytest.raises(ManifestError, match="testedGameBuilds"):
        load_manifest(write_manifest(tmp_path, top={"testedGameBuilds": "1.0.1013.20"}))
    with pytest.raises(ManifestError, match="must look like"):
        load_manifest(write_manifest(tmp_path, top={"testedGameBuilds": ["new"]}))


def test_bundled_manifest_build_data_is_valid(manifest):
    for m in manifest.mods.values():  # whatever mod-sources adds must resolve on the owner's build
        assert m.for_build("1.0.1013.20").id == m.id


# ---------------------------------------------------------------------------------------------- checks
def codes(findings, level=None):
    return [x.code for x in findings if level is None or x.level == level]


def test_checks_unsupported_is_error(mdir, game):
    m = load_manifest(mdir)
    f = run_checks(m, m.resolve("core"), game, game_version="1.0.750.0")
    err = [x for x in f if x.code == "build-unsupported"]
    assert len(err) == 1 and err[0].level == ERROR and err[0].mod == "scripthookv"
    assert "No Script Hook V exists" in err[0].message and "Pick another profile" in err[0].message


def test_checks_variant_is_info(mdir, game):
    m = load_manifest(mdir)
    f = run_checks(m, m.resolve("core"), game, game_version="1.0.1013.10")
    assert "build-unsupported" not in codes(f)
    info = next(x for x in f if x.code == "build-variant")
    assert info.level == INFO and "Script Hook V" in info.message and "1.0.3411.0" in info.message
    assert "version-newer" not in codes(f) and "version-untested" in codes(f, INFO)


def test_checks_tested_build_is_quiet(mdir, game):
    m = load_manifest(mdir)
    f = run_checks(m, m.resolve("core"), game, game_version="1.0.1013.20")
    assert not {"build-unsupported", "build-variant", "version-newer", "version-untested"} & set(codes(f))


def test_checks_newer_than_tested_warns(mdir, game):
    m = load_manifest(mdir)
    f = run_checks(m, m.resolve("core"), game, game_version="1.0.1300.0")
    assert "version-newer" in codes(f, WARNING) and "build-unsupported" not in codes(f)


def test_checks_unknown_version(mdir, game):
    m = load_manifest(mdir)
    f = run_checks(m, m.resolve("core"), game, game_version=None)
    assert "version-unknown" in codes(f, INFO) and "build-unsupported" not in codes(f)


def test_checks_suggest_slot_alternative(tmp_path, game):
    d = write_manifest(tmp_path, {"hud-geckomacabre": {"minGameBuild": "1.0.1100.0"}})
    m = load_manifest(d)
    f = run_checks(m, m.resolve("core"), game, game_version="1.0.1013.20")
    err = next(x for x in f if x.code == "build-unsupported")
    assert "leonida swap hud-geckomacabre" in err.message and "needs game build 1.0.1100.0" in err.message


# --------------------------------------------------------------------------------------------- session
def test_session_uses_detected_build(mdir, game, state, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1013.10")
    calls = []
    real = session_mod.exe_version
    monkeypatch.setattr(session_mod, "exe_version", lambda exe: calls.append(exe) or real(exe))
    s = Session(state, mdir, game_dir=str(game))
    shv = next(m for m in s.mods() if m.id == "scripthookv")
    assert shv.variant == 0 and shv.archive == ("ScriptHookV_1.0.3411.0*.zip",)
    assert s.manifest.game_build == "1.0.1013.10" and s.base_manifest.mod("scripthookv").variant is None
    assert s.manifest.mod("scripthookv").version == "1.0.3411.0"
    s.findings(), s.mods(), s.manifest
    assert len(calls) == 1  # the exe is read once
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1013.20")
    assert s.manifest.mod("scripthookv").variant is None  # follows the build


def test_session_override_wins(mdir, game, state, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1013.20")
    s = Session(state, mdir, game_dir=str(game), game_build="1.0.750.0")
    assert s.game_version() == "1.0.750.0"
    assert "build-unsupported" in codes(s.findings(), ERROR)


def test_session_matches_use_variant_archive(mdir, game, state, downloads, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1013.10")
    (downloads / "ScriptHookV_1.0.3411.0_x64.zip").write_bytes(b"zip")
    s = Session(state, mdir, download_dir=str(downloads), game_dir=str(game))
    assert s.matches().matched["scripthookv"].name == "ScriptHookV_1.0.3411.0_x64.zip"


# ------------------------------------------------------------------------------------------------- CLI
def test_cli_game_build_flag(mdir, game, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LEONIDA_FAKE_GAME_VERSION", "1.0.1158.13")
    base = ["--state-dir", str(tmp_path / "st"), "--manifest-dir", str(mdir), "--game-dir", str(game)]
    assert main(base + ["--game-build", "1.0.750.0", "check"]) == 1
    out = capsys.readouterr().out
    assert "No Script Hook V exists" in out

    main(base + ["--game-build", "1.0.1013.10", "doctor"])
    out = capsys.readouterr().out
    assert "1.0.1013.10 (from --game-build)" in out and "not a tested build" in out
    assert "Script Hook V 1.0.3411.0" in out

    main(base + ["detect", "--set", str(game)])
    out = capsys.readouterr().out
    assert "Game build:    1.0.1158.13" in out and "(tested build)" in out
