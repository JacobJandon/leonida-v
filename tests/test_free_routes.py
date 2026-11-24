"""freeRoute: schema, the publicSince switch, checks, the 'now free' notice and doctor (test-local manifests)."""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from leonida import downloader
from leonida import manifest as manifest_mod
from leonida.checks import INFO, run_checks
from leonida.cli import main
from leonida.manifest import ManifestError, load_manifest
from leonida.session import PAID_STATE, Session


def _mod(mid, order, tier="optional", **extra):
    return {"id": mid, "order": order, "tier": tier, "layer": "t", "name": mid.title(), "version": "1",
            "source": extra.pop("source", "direct"), "page": f"https://{mid}.example/", "archive": [f"{mid}*.zip"],
            "install": {"method": "guided", "steps": ["do it"]}, **extra}


PUBLIC = {"type": "publicSince", "date": "2026-12-01", "page": "https://author.example/public",
          "download": {"type": "github", "repo": "author/paidgfx", "asset": "PaidGfx-*.zip"},
          "version": "2.0-public", "archive": ["PaidGfx-*.zip"]}
MODS = [
    _mod("freegfx", 1),
    _mod("paidgfx", 2, tier="paid", source="patreon", freeRoute=PUBLIC,
         minGameBuild="1.0.1013.17",
         gameBuilds=[{"max": "1.0.1013.16", "version": "0.9-old", "page": "https://paidgfx.example/old"}]),
    _mod("paidmodels", 3, tier="paid", source="shop", freeRoute={"type": "alternative", "mod": "freegfx"}),
    _mod("paidworld", 4, tier="paid", source="patreon",
         freeRoute={"type": "freeEdition", "version": "Lite 1.2", "page": "https://paidworld.example/lite"}),
    _mod("paidx", 5, tier="paid", source="patreon", freeRoute={"type": "none", "reason": "author said no"}),
    _mod("paidnone", 6, tier="paid", source="shop"),
]


def write_manifest(root: Path, mods=None) -> Path:
    mods = mods if mods is not None else MODS
    d = root / "manifest"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mods.json").write_text(json.dumps({"pack": "Leonida V", "version": "1", "testedGameBuilds": ["1.0.1013.20"],
                                             "mods": mods}))
    (d / "profiles.json").write_text(json.dumps({"default": "all", "profiles": [
        {"id": "all", "name": "All", "include": [m["id"] for m in mods]},
        {"id": "free", "name": "Free", "include": ["freegfx"]},
        {"id": "paid", "name": "Paid", "include": ["@tier:paid"]}]}))
    (d / "hotkeys.json").write_text(json.dumps({"keys": []}))
    return d


@pytest.fixture
def mdir(tmp_path):
    return write_manifest(tmp_path)


@pytest.fixture
def clock(monkeypatch):
    """Set today's date for the manifest: clock("2026-12-05")."""
    def set_date(day: str):
        monkeypatch.setattr(manifest_mod, "_today", lambda: dt.date.fromisoformat(day))
    set_date("2026-11-24")
    return set_date


# ------------------------------------------------------------------------------------------------- schema
@pytest.mark.parametrize("route, message", [
    ({"type": "leak"}, "type must be one of"),
    ("free", "type must be one of"),
    ({"type": "alternative"}, "needs mod"),
    ({"type": "publicSince", "date": "2026-12-01"}, "needs page"),
    ({"type": "freeEdition", "page": "https://x.example/"}, "needs version"),
    ({"type": "none"}, "needs reason"),
    ({"type": "none", "reason": "x", "page": "https://x"}, "unknown key"),
    ({"type": "alternative", "mod": "freegfx", "download": {}}, "unknown key"),
    ({"type": "publicSince", "date": "1.12.2026", "page": "https://x.example/"}, "YYYY-MM-DD"),
    ({"type": "publicSince", "date": "2026-02-30", "page": "https://x.example/"}, "not a real date"),
    ({"type": "publicSince", "date": "2026-12-01", "page": "http://x.example/"}, "https"),
    ({"type": "publicSince", "date": "2026-12-01", "page": "https://x.example/", "archive": []}, "non-empty list"),
    ({"type": "publicSince", "date": "2026-12-01", "page": "https://x.example/", "download": {"type": "ftp"}},
     "download type"),
    ({"type": "none", "reason": " "}, "non-empty string"),
    ({"type": "alternative", "mod": "paidnone"}, "can't be its own"),
    ({"type": "alternative", "mod": "ghost"}, "unknown alternative"),
    ({"type": "alternative", "mod": "paidx"}, "is paid too"),
])
def test_schema_errors(tmp_path, route, message):
    mods = copy.deepcopy(MODS)
    mods[5]["freeRoute"] = route
    with pytest.raises(ManifestError, match=message):
        load_manifest(write_manifest(tmp_path, mods))


def test_free_route_is_optional_and_kept(mdir, clock):
    m = load_manifest(mdir)
    assert m.mod("paidnone").free_route is None
    assert m.mod("paidmodels").free_route == {"type": "alternative", "mod": "freegfx"}
    assert m.mod("paidgfx").is_paid and not m.mod("freegfx").is_paid


# --------------------------------------------------------------------------------------------- resolution
def test_public_since_switches_on_its_date(mdir, clock):
    base = load_manifest(mdir).mod("paidgfx")
    before = base.for_build("1.0.1013.20")
    assert before is base and before.is_paid and before.source == "patreon" and before.download is None
    clock("2026-12-01")  # the day itself counts
    after = base.for_build("1.0.1013.20")
    assert not after.is_paid and after.free_since == "2026-12-01" and after.tier == "paid"
    assert (after.page, after.source, after.version, after.archive) == (
        "https://author.example/public", "direct", "2.0-public", ("PaidGfx-*.zip",))
    assert after.download["repo"] == "author/paidgfx" and not after.manual_download
    assert downloader.plan_for(after).mode == "auto"
    assert after.for_build("1.0.1013.20") == after and after.for_build(None).free_since == "2026-12-01"
    assert after.for_selection({"paidgfx"}).free_since == "2026-12-01"


def test_public_since_leaves_build_variants_alone(mdir, clock):
    clock("2027-01-01")
    old = load_manifest(mdir).mod("paidgfx").for_build("1.0.1013.10")
    assert old.variant == 0 and old.version == "0.9-old" and old.page == "https://paidgfx.example/old"
    assert old.free_since is None and old.is_paid


def test_only_public_since_changes_the_mod(mdir, clock):
    clock("2030-01-01")
    m = load_manifest(mdir).for_build("1.0.1013.20")
    for mid in ("paidmodels", "paidworld", "paidx", "paidnone"):
        assert m.mod(mid).is_paid and m.mod(mid).free_since is None


def test_free_route_text(mdir, clock):
    m = load_manifest(mdir)
    assert m.free_route_text("paidmodels") == "use the free Freegfx instead"
    assert m.free_route_text("paidgfx").startswith("goes public on 2026-12-01 (https://author.example/public)")
    assert m.free_route_text("paidworld") == "official free edition Lite 1.2: https://paidworld.example/lite"
    assert m.free_route_text("paidx") == "none (author said no)"
    assert m.free_route_text("paidnone") == "no free route recorded yet"
    clock("2026-12-02")
    assert m.for_build(None).free_route_text("paidgfx") == "free since 2026-12-01 (the author's public release)"


def test_profiles_keep_tier_tokens(mdir, clock):
    clock("2027-01-01")
    m = load_manifest(mdir).for_build("1.0.1013.20")
    assert "paidgfx" in {x.id for x in m.resolve("paid")}  # @tier:paid still includes it


# ------------------------------------------------------------------------------------------------- checks
def test_paid_infos(mdir, game, clock):
    m = load_manifest(mdir)
    f = run_checks(m, m.resolve("all"), game, game_version="1.0.1013.20")
    paid = {x.mod: x.message for x in f if x.code == "paid"}
    assert set(paid) == {"paidgfx", "paidmodels", "paidworld", "paidx", "paidnone"}
    assert paid["paidmodels"] == "Paidmodels is paid; free route: use the free Freegfx instead."
    assert all(x.level == INFO for x in f if x.code == "paid")
    clock("2026-12-03")
    f = run_checks(m.for_build("1.0.1013.20"), m.resolve("all"), game, game_version="1.0.1013.20")
    assert "paidgfx" not in {x.mod for x in f if x.code in ("paid", "manual-source")}
    assert "paidx" in {x.mod for x in f if x.code == "paid"}


def test_now_free_notice_once(tmp_path, mdir, game, clock):
    s = Session(tmp_path / "st", mdir, game_dir=str(game), game_build="1.0.1013.20")
    assert s.turned_free() == []                      # first run only records
    state = json.loads((tmp_path / "st" / PAID_STATE).read_text())
    assert state["paidgfx"] == "paid" and set(state) == {"paidgfx", "paidmodels", "paidworld", "paidx", "paidnone"}
    assert s.manifest.mod("paidgfx").is_paid
    clock("2026-12-01")
    assert not s.manifest.mod("paidgfx").is_paid      # the session follows the date
    notes = [x for x in s.findings() if x.code == "now-free"]
    assert len(notes) == 1 and notes[0].level == INFO and notes[0].mod == "paidgfx"
    assert "public release came out on 2026-12-01" in notes[0].message and "author.example/public" in notes[0].message
    assert [x for x in s.findings() if x.code == "now-free"] == []  # said once
    assert json.loads((tmp_path / "st" / PAID_STATE).read_text())["paidgfx"] == "free"


def test_turned_free_without_recording_and_broken_state(tmp_path, mdir, clock):
    s = Session(tmp_path / "st", mdir, game_build="1.0.1013.20")
    s.turned_free()
    clock("2026-12-05")
    assert [m.id for m in s.turned_free(record=False)] == ["paidgfx"]
    assert [m.id for m in s.turned_free(record=False)] == ["paidgfx"]  # not recorded: still new
    (tmp_path / "st" / PAID_STATE).write_text("{broken")
    assert s.turned_free() == []                      # unreadable state counts as a first run
    assert json.loads((tmp_path / "st" / PAID_STATE).read_text())["paidgfx"] == "free"


# --------------------------------------------------------------------------------------------------- doctor
def test_doctor_lists_paid_mods(tmp_path, mdir, clock, capsys):
    clock("2026-12-02")
    main(["--state-dir", str(tmp_path / "st"), "--manifest-dir", str(mdir), "--game-build", "1.0.1013.20", "doctor"])
    out = capsys.readouterr().out
    assert "Paid mods (optional add-ons; Leonida never uses leaked or re-uploaded copies):" in out
    assert "Paidgfx: free now; free route: free since 2026-12-01" in out
    assert "Paidmodels: paid; free route: use the free Freegfx instead" in out
    assert "Paidnone: paid; free route: no free route recorded yet" in out
    assert not (tmp_path / "st" / PAID_STATE).exists()  # doctor only reads
