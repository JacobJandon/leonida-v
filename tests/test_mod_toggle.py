"""Per-mod on/off (for A/B tests in the game): Disable rolls back an installed mod's steps and keeps its download;
Enable installs it again. A mod whose files later steps share is only switched off together with them."""

from __future__ import annotations

from conftest import AutoUI, make_zip
from test_settings import MENYOO_INI, install_all, kit  # noqa: F401  (fixture)

from leonida.cli import main
from leonida.manifest import FileSpec, Mod
from leonida.snapshot import diff, take_snapshot


def _ids(s):
    return {m.id for m in s.mods()}


def test_disable_and_enable_a_mod(kit, game):  # noqa: F811
    install_all(kit)
    before = take_snapshot(game)
    assert kit.log.installed_mods() == {"shvdne", "menyoo"}
    report, others = kit.disable_mod("menyoo", AutoUI())
    assert others == [] and any("menyoo: rolled back" in line for line in report)
    assert not (game / "Menyoo.asi").exists()
    assert (game / "menyooStuff" / "menyooConfig.ini").read_text() == MENYOO_INI.replace("119", "120")  # user's own
    assert kit.config.disabled == ["menyoo"] and "menyoo" not in _ids(kit) and "shvdne" in _ids(kit)
    assert kit.log.installed_mods() == {"shvdne"} and (game / "ScriptHookVDotNet.ini").exists()
    lines = kit.enable_mod("menyoo", AutoUI())
    assert lines[0].startswith("MENYOO: installed again") and kit.config.disabled == []
    assert (game / "Menyoo.asi").exists() and kit.settings_drift() == []        # locked values written again
    assert diff(before, take_snapshot(game)).empty
    assert kit.enable_mod("menyoo", AutoUI()) == ["menyoo isn't disabled."]
    assert kit.disable_mod("nothere", AutoUI()) == (["nothere isn't installed."], [])


def test_a_mod_whose_files_a_later_step_shares(kit, game, downloads):  # noqa: F811
    inst = install_all(kit)
    later = Mod(id="later", order=9, tier="core", layer="x", name="Later", author="a", version="1", source="direct",
                page="https://x", archive=("later*.zip",), method="copy", files=(FileSpec("Menyoo.asi"),))
    inst.install(later, make_zip(downloads / "later-1.zip", {"Menyoo.asi": "patched"}))
    report, others = kit.disable_mod("menyoo", AutoUI())
    assert report == [] and others == ["later"] and (game / "Menyoo.asi").read_text() == "patched"  # nothing changed
    report, others = kit.disable_mod("menyoo", AutoUI(), with_dependents=True)
    assert others == ["later"] and not (game / "Menyoo.asi").exists()
    assert set(kit.config.disabled) == {"menyoo", "later"}


def test_cli_disable_enable(kit, game, tmp_path, downloads, capsys):  # noqa: F811
    install_all(kit)
    base = ["--state-dir", str(kit.state), "--manifest-dir", str(tmp_path / "manifest"), "--game-dir", str(game),
            "--download-dir", str(downloads)]
    assert main(base + ["disable", "nope"]) == 2
    assert main(base + ["disable", "menyoo"]) == 0
    assert "menyoo is off. `leonida enable menyoo` installs it again" in capsys.readouterr().out
    assert main(base + ["enable", "menyoo"]) == 0
    assert "installed again" in capsys.readouterr().out and (game / "Menyoo.asi").exists()


def test_the_mods_tab_switches_a_mod(kit, game, qt_app, monkeypatch):  # noqa: F811
    import leonida.gui.app as A
    from leonida.gui import launcher as L

    monkeypatch.setenv("LEONIDA_NO_OPEN", "1")
    monkeypatch.setattr(A.QMessageBox, "question", staticmethod(lambda *a, **k: A.QMessageBox.StandardButton.Yes))
    install_all(kit)
    kit.choose_pack("plus")
    win = A.MainWindow(kit)
    try:
        win.open_pack("plus")
        win.pack_page.tabs.setCurrentIndex(1)                       # the Mods tab
        row = next(r for r in win.pack_page.mod_rows if r.mod.id == "menyoo")
        (btn,) = [b for b in row.findChildren(A.QPushButton) if b.text() == "Disable"]
        btn.click()
        assert not (game / "Menyoo.asi").exists() and "is off" in win.notifications.items[0].text
        row = next(r for r in win.pack_page.mod_rows if r.mod.id == "menyoo")   # still listed, now with Enable
        assert [b.text() for b in row.findChildren(A.QPushButton) if b.text() in ("Enable", "Disable")] == ["Enable"]
        assert L.set_mod_enabled(win, kit.manifest.mods["menyoo"], True)[0].startswith("MENYOO: installed again")
        assert (game / "Menyoo.asi").exists()
    finally:
        win.close()
        win.deleteLater()
