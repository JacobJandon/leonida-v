"""Failures of an unexpected kind half-way through an install, a mod update or a self-update must never leave a
half-done state: whatever was placed is logged and undone, or the previous version is put back."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import AutoUI, make_zip
from test_cov_updates import _assert_alpha_v1_intact, _inst, _step, make_kit, mod
from test_modpack import current_files, pack_for, v2_zip

from leonida import installer as installer_mod
from leonida import modupdate as mu
from leonida import updater
from leonida.manifest import FileSpec
from leonida.snapshot import diff, take_snapshot
from leonida.updater import UpdateError, UpdateInfo


@pytest.fixture
def kit(tmp_path, game, downloads):
    return make_kit(tmp_path, game, downloads)


# ------------------------------------------------------------------------------------------------ installer
def test_partial_copy_is_undone(manifest, game, state, log, downloads, monkeypatch):
    z = make_zip(downloads / "cov-1.zip", {"a.asi": "a" * 1000})
    real = installer_mod.shutil.copy2

    def half_then_fail(src, dst, *a, **k):
        Path(dst).write_bytes(Path(src).read_bytes()[:10])  # half a file reaches the game folder
        raise OSError("disk full")

    before = take_snapshot(game)
    monkeypatch.setattr(installer_mod.shutil, "copy2", half_then_fail)
    inst = _inst(manifest, game, state, log)
    with pytest.raises(OSError, match="disk full"):
        inst.install(mod(files=(FileSpec("a.asi"),)), z)
    monkeypatch.setattr(installer_mod.shutil, "copy2", real)
    step = log.steps[-1]
    assert step.status == "failed" and [a.path for a in step.actions] == ["a.asi"]
    warnings = inst.rollback(step.id)
    assert not (game / "a.asi").exists() and diff(before, take_snapshot(game)).empty
    assert len(warnings) == 1 and "moved to" in warnings[0]  # the partial bytes are kept aside, not deleted


class ExplodingUI(AutoUI):
    """The user changes the game folder, then the UI fails (window closed, crash, Ctrl+C)."""

    def __init__(self, game: Path, exc: BaseException):
        super().__init__()
        self.game, self.exc = game, exc

    def wait_done(self, title, steps, folder):
        (self.game / "scripts" / "Thing").mkdir(parents=True)
        (self.game / "scripts" / "Thing" / "thing.dll").write_text("x")
        (self.game / "bink2w64.dll").write_bytes(b"changed")
        raise self.exc


@pytest.mark.parametrize("exc", [RuntimeError("window closed"), KeyboardInterrupt()])
def test_interrupted_guided_step_is_logged_and_undone(manifest, game, state, log, downloads, exc):
    z = make_zip(downloads / "cov-guide.zip", {"readme.txt": "r"})
    before = take_snapshot(game)
    inst = _inst(manifest, game, state, log, ExplodingUI(game, exc))
    with pytest.raises(type(exc)):
        inst.install(mod(method="guided"), z)
    step = log.steps[-1]
    assert step.status == "failed" and any("interrupted" in n for n in step.notes)
    assert {a.path for a in step.actions} == {"scripts/Thing/thing.dll", "bink2w64.dll"}
    assert inst.rollback(step.id) == []
    assert diff(before, take_snapshot(game)).empty and (game / "bink2w64.dll").read_bytes() == b"original bink"


# ------------------------------------------------------------------------------------------------ modupdate
def test_dependent_reinstall_failure_restores_everything(kit, game, downloads, monkeypatch):
    real = installer_mod.shutil.copy2
    hits = []

    def fail_gamma_once(src, dst, *a, **k):
        if Path(src).read_bytes() == b"gamma v1" and not hits:
            hits.append(1)
            raise OSError("disk full")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(installer_mod.shutil, "copy2", fail_gamma_once)
    with pytest.raises(mu.ModUpdateError, match="previous version \\(alpha-1.0.zip\\) was reinstalled"):
        mu.replace_mod(kit, kit.installer(AutoUI()), kit.manifest.mod("alpha"), v2_zip(downloads),
                       downloads / "alpha-1.0.zip")
    assert hits
    _assert_alpha_v1_intact(kit, game)
    assert [s.mod for s in kit.log.active_steps()] == ["beta", "alpha", "gamma"]


def test_rollback_failure_puts_dependents_back(kit, game, downloads, monkeypatch):
    alpha_id = _step(kit, "alpha").id
    real = installer_mod.Installer.rollback

    def rollback(self, step_id):
        if step_id == alpha_id:
            raise PermissionError("alpha.asi is locked")
        return real(self, step_id)

    monkeypatch.setattr(installer_mod.Installer, "rollback", rollback)
    with pytest.raises(mu.ModUpdateError, match="Couldn't roll back Alpha to update it: alpha.asi is locked"):
        mu.replace_mod(kit, kit.installer(AutoUI()), kit.manifest.mod("alpha"), v2_zip(downloads),
                       downloads / "alpha-1.0.zip")
    _assert_alpha_v1_intact(kit, game)  # gamma was taken out first and is back
    assert {s.mod for s in kit.log.active_steps()} == {"alpha", "beta", "gamma"}


def test_run_updates_survives_record_failures(kit, game, downloads, monkeypatch):
    pack = pack_for(kit, {"alpha": v2_zip(downloads), **current_files(downloads)})
    plan = mu.plan_updates(kit, pack)

    def broken(*a, **k):
        raise OSError("lockfile is read-only")

    monkeypatch.setattr(mu, "_record_lock", broken)
    report = mu.run_updates(kit, plan, AutoUI())
    assert report[0].startswith("Alpha: updated to 2.0")
    assert any("couldn't update the lockfile" in r for r in report)
    assert (game / "alpha.asi").read_text() == "alpha v2"


def test_run_updates_download_oserror_is_reported(tmp_path, game, downloads, monkeypatch):
    import copy

    from test_modpack import MODS

    mods = copy.deepcopy(MODS)
    mods[0]["download"] = {"type": "direct", "url": "https://alpha.example/a.zip", "file": "alpha-2.0.zip"}
    s = make_kit(tmp_path, game, downloads, mods)
    v2 = make_zip(tmp_path / "srv" / "alpha-2.0.zip", {"alpha.asi": "alpha v2", "alpha.ini": "a=2"})
    plan = mu.plan_updates(s, pack_for(s, {"alpha": v2, **current_files(downloads)}))

    def fail(*a, **k):
        raise PermissionError("Downloads is read-only")

    monkeypatch.setattr(mu.downloader, "download", fail)
    report = mu.run_updates(s, plan, AutoUI())
    assert len(report) == 1 and "download failed (Downloads is read-only)" in report[0]
    _assert_alpha_v1_intact(s, game)


# --------------------------------------------------------------------------------------------------- updater
INFO = UpdateInfo("1.0.0", "9.9.9", True, "", "https://example.invalid", "https://x.example/leonida-v-9.9.9.zip",
                  "https://x.example/LeonidaV-9.9.9-win64.zip", {})


def test_apply_oserror_becomes_update_error(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise PermissionError("State is read-only")

    monkeypatch.setattr(updater, "_fetch_verified", boom)
    (tmp_path / "leonida-v").mkdir()
    with pytest.raises(UpdateError, match="Updating Leonida V failed: State is read-only. Nothing was switched over"):
        updater.apply(INFO, tmp_path / "leonida-v", tmp_path / "State")


def test_exe_helper_write_failure_removes_staged_folder(tmp_path, monkeypatch):
    import io
    import sys
    import zipfile

    app = tmp_path / "LeonidaV"
    app.mkdir()
    (app / "LeonidaV.exe").write_bytes(b"MZ old")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("LeonidaV/LeonidaV.exe", b"MZ new")
    z = tmp_path / "dl" / "LeonidaV-9.9.9-win64.zip"
    z.parent.mkdir()
    z.write_bytes(buf.getvalue())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_current_exe", lambda: app / "LeonidaV.exe")
    monkeypatch.setattr(updater, "_fetch_verified", lambda *a, **k: (z, ""))

    def no_helper(*a, **k):
        raise OSError("no space left")

    monkeypatch.setattr(updater, "write_helper", no_helper)
    with pytest.raises(UpdateError, match="no space left"):
        updater.apply(INFO, tmp_path, tmp_path / "State")
    assert not (tmp_path / "LeonidaV.new").exists() and (app / "LeonidaV.exe").read_bytes() == b"MZ old"
