"""What the smoke walk of the real app on the owner's state (a copy, 2026-11-25) found, fixed: add-on cards that the
pack already contains, numbering that differed between the Install list and "Next step", raw step ids and status words
on Manage, "[ok]" for logs not written yet, a long game path cut off, the window not fitting a 1280x720 screen, a
guided step with no change counted as installed."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from conftest import AutoUI, flush_deletes, make_zip  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from test_gui_pages import dialogs, make_win, qapp  # noqa: E402,F401  (fixtures)

from leonida.installer import Installer, InstallError  # noqa: E402
from leonida.log import InstallLog  # noqa: E402
from leonida.manifest import Mod, load_manifest  # noqa: E402


def labels(widget) -> list[str]:
    return [" ".join(lab.text().split()) for lab in widget.findChildren(QLabel) if lab.text().strip()]


def test_addon_cards_the_pack_already_has_are_ticked_and_locked(make_win):  # noqa: F811
    win = make_win()
    s = win.session
    s.choose_pack("video-setup", None, "balanced")
    page = win.pages[2]
    page.edition_changed()
    QApplication.processEvents()
    cards = page.addon_cards
    food = cards["street-food"]                  # in Showcase's base: part of the pack either way
    assert food.included and food.control.isChecked() and not food.control.isEnabled()
    assert "In this pack" in labels(food)
    visualv = cards["visualv"]                   # a default add-on, not in the base: the user's choice
    assert not visualv.included and visualv.control.isChecked() and visualv.control.isEnabled()
    prime = cards["prime-realism"]
    assert not prime.included and not prime.control.isChecked() and prime.control.isEnabled()


def test_install_next_and_get_rows_use_the_same_numbers(make_win, downloads):  # noqa: F811
    win = make_win()
    s = win.session
    s.choose_pack("video-setup", None, "balanced")
    mods = s.mods()
    install = win.pages[5]
    install.refresh()
    assert install.next_title.text() == f"1. {mods[0].name}"
    s.log.new_step(mods[0].id, "copy").status = "done"   # the first one is installed: the next is row 2
    install.refresh()
    assert install.next_title.text() == f"2. {mods[1].name}"
    get = win.pages[3]
    get.refresh()
    assert [get.table.item(r, 0).text() for r in range(3)] == ["1", "2", "3"]
    gap = next(i for i, m in enumerate(mods) if m.order != i + 1)  # where the manifest's own numbers skip
    assert get.table.item(gap, 0).text() == str(gap + 1)
    assert f"{gap + 1}. {mods[gap].name}" in labels(get.rows[mods[gap].id])


def test_manage_names_settings_steps_and_says_mods_not_steps(make_win, game):  # noqa: F811
    win = make_win()
    s = win.session
    for mid, method in (("scripthookv", "copy"), ("settings:scripthookv", "settings")):
        s.log.new_step(mid, method).status = "done"
    page = win.pages[6]
    page.refresh()
    assert page.state.text() == "1 mod installed in 2 steps · none in the game"
    rows = labels(page)
    assert "Locked settings: Script Hook V" in rows and "settings:scripthookv" not in rows


def test_long_game_paths_are_shortened_in_the_middle(qapp):  # noqa: F811
    from leonida.gui.widgets import EditionPicker, ElidedLabel

    path = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\" + "Very Long Folder\\" * 6 + "Grand Theft Auto V"
    picker = EditionPicker([("Enhanced", path, "1.0.1013.20"), ("Legacy", None, None)])
    picker.resize(700, 140)
    picker.show()
    QApplication.processEvents()
    (lab,) = [x for x in picker.findChildren(ElidedLabel)]
    assert lab.toolTip() == path and lab.text() != path and "…" in lab.text()
    assert lab.text().startswith("C:\\Program") and lab.text().endswith("Auto V")
    picker.close()
    picker.deleteLater()
    flush_deletes()


def test_the_window_fits_a_1280x720_screen(make_win):  # noqa: F811
    win = make_win()
    assert win.minimumSize().height() <= 640 and win.minimumSize().width() <= 1200


def _guided(mid="g"):
    return Mod(id=mid, order=1, tier="core", layer="x", name="Guided", author="a", version="1", source="direct",
               page="https://x", archive=("g*.zip",), method="guided", steps=("Do it",))


def test_a_guided_step_that_changed_nothing_asks_before_counting(tmp_path, game, state, downloads):
    z = make_zip(downloads / "g-1.zip", {"readme.txt": "r"})
    no = Installer(load_manifest(), game, state, InstallLog(state / "log.json"), AutoUI(confirm=False))
    with pytest.raises(InstallError, match="no change seen in the game folder"):
        no.install(_guided(), z)
    assert no.log.installed_mods() == set()
    yes = Installer(load_manifest(), game, state, InstallLog(state / "log2.json"), AutoUI(confirm=True))
    assert yes.install(_guided(), z).status == "done"     # done somewhere Leonida doesn't watch: the user says so
    changed = Installer(load_manifest(), game, state, InstallLog(state / "log3.json"),
                        AutoUI(confirm=False, on_wait=lambda f: (game / "mods").mkdir()
                               or (game / "mods" / "x.rpf").write_text("x")))
    assert changed.install(_guided(), z).status == "done"  # a change was seen: no question


def _strings_without_docstrings(path):
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_no_key_names_are_typed_into_the_gui():
    """Key hints come from hotkeys.json and the locked settings (mods.json), never from text in the GUI code: the
    old preview said "Menyoo moves to F8" while ActionsV is locked at F7 and F10 reloads the HUD."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    files = sorted((root / "leonida" / "gui").glob("*.py")) + [root / "build" / "design_preview.py"]
    key = re.compile(r"(?<![\w-])F(?:[1-9]|1[0-2])(?![\w])")
    typed = [(f.name, line, text) for f in files for line, text in _strings_without_docstrings(f) if key.search(text)]
    assert typed == []


def test_the_preview_key_example_comes_from_the_data():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build"))
    import design_preview as D

    m = load_manifest()
    wanted, key, mine, other = D.key_clash_sample(m)
    assert mine in m.hotkeys and other in m.hotkeys and not other["rebindable"]
    assert str(wanted.value) == mine["key"] and key == other["key"] and key in wanted.why
