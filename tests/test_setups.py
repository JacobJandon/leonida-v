"""Ready-made setups (plan F8, leonida/setups.py, leonida/manifest/setups.json)."""

from __future__ import annotations

import json

import pytest

from leonida import cli
from leonida import gamesettings as G
from leonida import setups as SU
from leonida.manifest import load_manifest
from leonida.session import Session

OWNER = G.PC(15.8, 8.0, ("NVIDIA GeForce GTX 1070",))


@pytest.mark.parametrize("edition", ["enhanced", "legacy"])
def test_every_setup_fits_its_manifest(edition):
    assert SU.problems(load_manifest(edition=edition)) == []
    assert SU.load(edition)


def test_best_setup_for_a_pc():
    assert SU.best_for(OWNER).id == "owner-16gb"
    assert SU.best_for(G.PC(31.9, 16.0, ("NVIDIA GeForce RTX 4080",))).id == "owner-32gb"
    assert SU.best_for(G.PC(7.9, 4.0, ("NVIDIA GeForce GTX 1650",))).id == "core-laptop"
    ok, why = SU.fits(SU.get("showcase-rtx"), OWNER)
    assert not ok and "needs an NVIDIA RTX card" in why and any("RAM" in w for w in why)
    assert SU.fits(SU.get("owner-16gb"), G.PC())[0]                          # unknown facts don't block
    assert SU.best_for(OWNER, "legacy").id == "legacy-core"


def _session(tmp_path, game, downloads):
    return Session(tmp_path / "st", None, download_dir=str(downloads), game_dir=str(game), game_build="1.0.1013.20")


def test_choose_export_import_and_build(tmp_path, game, downloads):
    s = _session(tmp_path, game, downloads)
    SU.choose(s, "owner-16gb")
    c = s.pack_choice()
    assert (c.pack, c.variant, tuple(c.addons)) == ("owner-pick", "ram16", ("owner-gun-sounds",))
    assert SU.chosen(s) == "owner-16gb"
    shared = SU.export(s, "Mine")
    assert shared == {"kind": "leonida-setup", "schema": 1, "edition": "enhanced", "name": "Mine",
                      "pack": "owner-pick", "variant": "ram16", "addons": ["owner-gun-sounds"]}
    s.choose_pack("core")
    assert SU.chosen(s) is None                                               # changed: not the setup any more
    SU.import_setup(s, shared)
    assert s.pack_choice().variant == "ram16"
    with pytest.raises(ValueError, match="doesn't fit"):
        SU.import_setup(s, {**shared, "addons": ["visualv"]})                 # not offered by the owner's pick
    with pytest.raises(ValueError, match="legacy"):
        SU.import_setup(s, {**shared, "edition": "legacy"})
    lock = SU.build_lock(s, "core-laptop")
    assert lock["setup"]["id"] == "core-laptop" and list(lock["builds"]) == ["1.0.1013.20"]


def test_cli_setup_list_and_choose(tmp_path, game, downloads, monkeypatch, capsys):
    monkeypatch.setenv("LEONIDA_STATE_DIR", str(tmp_path / "st"))
    monkeypatch.setattr(Session, "pc_specs", lambda self: OWNER)
    base = ["--game-dir", str(game), "--download-dir", str(downloads), "--game-build", "1.0.1013.20"]
    assert cli.main([*base, "setup", "list"]) == 0
    out = capsys.readouterr().out
    assert "Owner's pick · 16 GB" in out and "best for this PC" in out and "needs an NVIDIA RTX card" in out
    assert cli.main([*base, "setup", "choose", "core-laptop"]) == 0
    assert cli.main([*base, "setup", "export", str(tmp_path / "mine.json")]) == 0
    assert json.loads((tmp_path / "mine.json").read_text(encoding="utf-8"))["pack"] == "core"
    assert cli.main([*base, "setup", "build", str(tmp_path / "out"), "--name", "core-laptop"]) == 0
    assert (tmp_path / "out" / "core-laptop.modpack.json").is_file()
