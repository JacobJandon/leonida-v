"""Leonida's own menu package matches only the running version's zip, so an update reinstalls the new menu."""
from __future__ import annotations

from leonida import __version__
from leonida.manifest import load_manifest
from leonida.menu import zip_name


def test_menu_matches_only_this_versions_zip():
    m = load_manifest()
    menu = m.mods["leonidamenu"]
    assert menu.archive == (zip_name(),) == (f"LeonidaMenu-{__version__}.zip",)
    assert "LeonidaMenu-1.0.1.zip" not in menu.archive or __version__ == "1.0.1"
