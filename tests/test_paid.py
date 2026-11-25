"""Paid mods, the legit way (leonida/paid.py, docs/PAID-MODS.md): the authors' own buy pages, the buyer's own file
recognised (a wrong package refused, a renamed one assigned), what to do next in `leonida check`, `leonida paid`."""

from __future__ import annotations

from conftest import make_zip

from leonida import cli
from leonida import paid as P
from leonida.manifest import load_manifest
from leonida.session import Session

AUTHORS = ("patreon.com/razedmods", "patreon.com/livelyworldexpansion", "patreon.com/cw/u10507693",
           "patreon.com/ChromatiXGTA", "patreon.com/centralmods")


def test_every_paid_mod_has_the_authors_buy_page():
    m = load_manifest()
    paid = [x for x in m.mods.values() if x.tier == "paid"]
    assert {x.id for x in paid} == {"nve", "lwe", "jasonlucia", "chromatix", "centralmods"}
    for x in paid:
        b = P.buy_info(x.id)
        assert set(b) == P.BUY_KEYS and all(b.values()), x.id
        assert b["url"].startswith("https://www.patreon.com/") and any(a in b["url"] for a in AUTHORS), x.id
        assert (x.free_route or {}).get("type") in ("none", "freeEdition"), x.id     # never a stand-in mod


def _session(tmp_path, game, downloads):
    s = Session(tmp_path / "st", None, download_dir=str(downloads), game_dir=str(game))
    s.choose_pack("owner-pick")
    return s


def test_your_own_download_is_recognised_and_a_wrong_one_refused(tmp_path, game, downloads):
    make_zip(downloads / "ChromatiX - Enhanced Main Package.oiv", {"assembly.xml": "<package/>", "content/a": "x"})
    make_zip(downloads / "NaturalVision Enhanced.zip", {"readme.txt": "a repack without the author's layout"})
    s = _session(tmp_path, game, downloads)
    rows = {r.id: r for r in P.paid_list(s)}
    assert rows["chromatix"].status == "downloaded" and rows["chromatix"].file.startswith("ChromatiX")
    assert rows["nve"].status == "wrong file" and "main package" in rows["nve"].reason.lower()
    assert rows["lwe"].status == "not bought" and rows["lwe"].buy_url.endswith("livelyworldexpansion/membership")
    # what turns it on in the owner's pick, and what it takes the place of
    assert rows["nve"].addons[0] == "NaturalVision Enhanced (paid)"
    assert "GTA V Remastered: Enhanced" in rows["lwe"].replaces
    found = {f.code: f for f in s.findings() if f.code.startswith("paid-")}
    assert "test place" in found["paid-downloaded"].message and found["paid-downloaded"].mod == "chromatix"
    assert found["paid-wrong-file"].level == "warning" and "patreon.com/razedmods" in found["paid-wrong-file"].message


def test_a_renamed_download_is_assigned(tmp_path, game, downloads):
    make_zip(downloads / "my-purchase.zip", {"NaturalVision Enhanced - Single Player Package/Main Package/x.asi": "x"})
    s = _session(tmp_path, game, downloads)
    assert {r.id: r.status for r in P.paid_list(s)}["nve"] == "not bought"
    s.config.assignments["my-purchase.zip"] = "nve"              # what `leonida assign my-purchase.zip nve` does
    s.save()
    s = _session(tmp_path, game, downloads)
    assert {r.id: r.status for r in P.paid_list(s)}["nve"] == "downloaded"


def test_cli_paid_list(tmp_path, game, downloads, monkeypatch, capsys):
    monkeypatch.setenv("LEONIDA_STATE_DIR", str(tmp_path / "st"))
    assert cli.main(["--game-dir", str(game), "--download-dir", str(downloads), "paid"]) == 0
    out = capsys.readouterr().out
    assert "https://www.patreon.com/razedmods/membership" in out and "not bought" in out
    assert "never buys, signs in or uses re-uploads" in out
