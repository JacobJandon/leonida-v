"""leonida/cleanup.py: the automatic clean-up and the kinds that ask first, on fake folders only (a fake Recycle Bin:
tests/conftest.py makes the real one refuse, and GTA's real CrashLogs are never looked at)."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from conftest import make_zip

from leonida import cleanup as C
from leonida.log import InstallLog
from leonida.matcher import write_lock
from leonida.paths import BACKUPS_DIR, LOCK_NAME
from leonida.session import Session

DAY = 24 * 3600
NOW = time.time()


def aged(p: Path, days: float) -> Path:
    t = NOW - days * DAY
    os.utime(p, (t, t))
    return p


def write(p: Path, data: bytes | str = b"x", days: float = 0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data.encode() if isinstance(data, str) else data)
    return aged(p, days)


def make_session(tmp_path, game, downloads) -> Session:
    return Session(state=tmp_path / "state", download_dir=str(downloads), game_dir=str(game),
                   game_build="1.0.1013.20")


def by_cat(items) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for i in items:
        out.setdefault(i.category, set()).add(Path(i.path).name)
    return out


def a_free_mod_not_in_the_pack(s: Session):
    mine = {m.id for m in s.mods()}
    for m in s.manifest.mods.values():
        if (m.id not in mine and m.tier in ("optional", "alternative") and m.archive and not m.require_members
                and m.archive[0].endswith(".zip")):
            return m, m.archive[0].replace("*", "") or f"{m.id}.zip"
    pytest.skip("no free mod outside the default pack")


# ------------------------------------------------------------------------------------------------- automatic
@pytest.fixture
def fake(tmp_path, game, downloads):
    s = make_session(tmp_path, game, downloads)
    st = s.state
    shv = make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "shv"})
    copy = downloads / "ScriptHookV_1.0 (1).zip"
    copy.write_bytes(shv.read_bytes())
    aged(copy, 3)                                           # older, but the lockfile names it: it stays
    write_lock(st / LOCK_NAME, {"entries": [{"mod": "scripthookv", "file": copy.name, "size": copy.stat().st_size,
                                             "sha256": "x"}]})
    write(downloads / "big.zip.part", b"p" * 10, days=2)
    write(downloads / "fresh.zip.crdownload", b"p", days=0.1)
    write(downloads / "LeonidaMenu-1.0.zip", b"menu one")
    write(downloads / "LeonidaMenu-1.2.zip", b"menu one-two")
    for i, days in enumerate((9, 1, 5)):                    # 3 x 400 bytes with a 1000-byte cap: the least recent goes
        write(st / "images" / f"pic{i}.jpg", b"i" * 400, days=days)
    write(st / "images" / "index.json", "{}")
    logs = st / "logs"
    write(logs / "leonida.log.4", "kept")
    write(logs / "leonida.log.5", "past rotation")
    for i in range(12):
        write(logs / f"session-{i:02d}.log", "s", days=20 - i)
    write(logs / "playtest" / "run-old.csv", "a,b", days=40)
    write(logs / "playtest" / "run-new.csv", "a,b", days=2)
    write(logs / "playtest" / "series-old.json", "{}", days=31)
    write(logs / "playtest" / "crash-old" / "dump.txt", "c")
    aged(logs / "playtest" / "crash-old", 45)
    crash = tmp_path / "Rockstar Games" / "GTAV Enhanced" / "CrashLogs"
    write(crash / "old.dmp", b"d" * 50, days=40)
    write(crash / "new.dmp", b"d", days=3)
    write(st / "updates" / "0.0.1" / "LeonidaV.exe", b"old update")
    write(st / "updates" / "99.0" / "LeonidaV.exe", b"a newer one, not installed yet")
    return s, crash


def test_the_automatic_kinds(fake):
    s, crash = fake
    items = C.Scanner(s, now=NOW, image_cap=1000, crash_dirs=[crash]).auto()
    got = by_cat(items)
    assert got["duplicates"] == {"ScriptHookV_1.0.zip"}                     # the lockfile's copy stays
    assert got["partial"] == {"big.zip.part"}                               # the fresh one may still be running
    assert got["old-packages"] == {"LeonidaMenu-1.0.zip"}
    assert got["image-cache"] == {"pic0.jpg"}                               # the least recently used; never index.json
    assert got["old-logs"] == {"leonida.log.5", "session-00.log", "session-01.log"}
    assert got["playtest"] == {"run-old.csv", "series-old.json", "crash-old"}
    assert got["crash-dumps"] == {"old.dmp"}
    assert got["updates"] == {"0.0.1"}
    assert set(got) == set(C.AUTO)
    assert C.summary(items)["image-cache"] == (1, 400)


def test_clean_moves_them_to_the_bin_and_logs_where(fake, tmp_path):
    s, crash = fake
    items = C.Scanner(s, now=NOW, image_cap=1000, crash_dirs=[crash]).auto()
    dry = C.clean(s, items, dry_run=True, trash=C.move_to(tmp_path / "bin"))
    assert dry.dry_run and len(dry.moved) == len(items) and all(Path(i.path).exists() for i in items)
    assert "Would move" in dry.lines()[0] and not (s.state / "logs" / C.LOG_NAME).exists()
    report = C.clean(s, items, trash=C.move_to(tmp_path / "bin"))
    assert len(report.moved) == len(items) and not report.failed
    assert not any(Path(i.path).exists() for i in items)
    assert report.freed == sum(i.size for i in items) and len(list((tmp_path / "bin").iterdir())) == len(items)
    kept = [s.config.downloads() / "ScriptHookV_1.0 (1).zip", s.config.downloads() / "LeonidaMenu-1.2.zip",
            s.state / "logs" / "leonida.log.4", s.state / "updates" / "99.0", crash / "new.dmp"]
    assert all(p.exists() for p in kept)
    log = (s.state / "logs" / C.LOG_NAME).read_text(encoding="utf-8")
    assert "ScriptHookV_1.0.zip" in log and str(tmp_path / "bin") in log and "duplicates" in log


def test_the_real_recycle_bin_is_never_used_in_tests(fake):
    s, crash = fake
    items = C.Scanner(s, now=NOW, crash_dirs=[crash]).duplicates()
    report = C.clean(s, items)                         # no trash given: the Recycle Bin, which conftest refuses
    assert not report.moved and "never use the Recycle Bin" in report.failed[0][1]
    assert all(Path(i.path).exists() for i in items)
    assert C.Scanner(s, now=NOW).crash_dumps() == []   # GTA's real CrashLogs aren't looked at in tests


def test_auto_clean_uses_the_automatic_kinds_only(fake, tmp_path):
    s, crash = fake
    report = C.auto_clean(s, trash=C.move_to(tmp_path / "bin"), now=NOW, crash_dirs=[crash])
    assert {i.category for i, _w in report.moved} <= set(C.AUTO) and report.moved


# ------------------------------------------------------------------------------------------------- ask first
def test_the_kinds_that_ask_first_and_paid_files_need_a_yes(tmp_path, game, downloads):
    s = make_session(tmp_path, game, downloads)
    mod, name = a_free_mod_not_in_the_pack(s)
    free = write(downloads / name, b"a free mod outside the pack")
    nve = make_zip(downloads / "NaturalVision Enhanced 1.0.zip", {"Main Package/x.dll": "x"})       # paid, bought
    wrong = make_zip(downloads / "NaturalVision Enhanced reupload.zip", {"stuff/x.dll": "x"})       # repacked
    write(downloads / C.WRONG_DIR / "old.zip", b"set aside")
    shv = make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "shv"})              # in the pack
    log = InstallLog(s.state / "install-log.json")
    active, undone = log.new_step("scripthookv", "copy"), log.new_step("hud", "copy")
    active.status, undone.status = "done", "rolled-back"
    log.save()
    s.log = InstallLog(s.state / "install-log.json")
    write(s.state / BACKUPS_DIR / f"step-{active.id}" / "x.dll", b"needed by Undo")
    write(s.state / BACKUPS_DIR / f"step-{undone.id}" / "y.dll", b"undone")
    write(s.state / BACKUPS_DIR / "step-99" / "z.dll", b"no such step")
    old_state, old_dl = tmp_path / "AppData" / "LeonidaV", tmp_path / "Home" / "Downloads" / "LeonidaV"
    write(old_state / "moved-to.txt", str(s.state))         # it points here: its pointer stays
    write(old_state / "images" / "a.jpg", b"old picture")
    write(old_dl / "NaturalVision Enhanced 1.0.zip", nve.read_bytes())
    write(old_dl / "something.zip", b"old download")
    items = C.Scanner(s, now=NOW, home_state=old_state, home_downloads=old_dl).ask()
    got = by_cat(items)
    assert got["not-in-pack"] == {free.name, nve.name}
    assert got["wrong-edition"] == {wrong.name, C.WRONG_DIR}
    assert got["rolled-back-backups"] == {f"step-{undone.id}", "step-99"}          # never the installed step's
    assert got["stray-folders"] == {"images", "NaturalVision Enhanced 1.0.zip", "something.zip"}
    paid = {Path(i.path).name for i in items if i.paid}
    assert paid == {nve.name, wrong.name, "NaturalVision Enhanced 1.0.zip"}
    assert shv.name not in {Path(i.path).name for i in items}

    report = C.clean(s, items, trash=C.move_to(tmp_path / "bin"))                   # no yes for paid files
    assert {Path(i.path).name for i, why in report.failed if "paid" in why} == paid
    assert nve.exists() and wrong.exists() and (old_dl / "NaturalVision Enhanced 1.0.zip").exists()
    assert not free.exists() and not (s.state / BACKUPS_DIR / f"step-{undone.id}").exists()
    assert (s.state / BACKUPS_DIR / f"step-{active.id}" / "x.dll").exists() and (old_state / "moved-to.txt").exists()
    again = C.clean(s, [i for i, _w in report.failed], paid=True, trash=C.move_to(tmp_path / "bin"))
    assert not nve.exists() and not wrong.exists() and not again.failed


def test_the_guard_refuses_the_game_folder_state_files_and_undo_backups(tmp_path, game, downloads):
    s = make_session(tmp_path, game, downloads)
    log = InstallLog(s.state / "install-log.json")
    st = log.new_step("scripthookv", "copy")
    st.status = "done"
    log.save()
    s.log = InstallLog(s.state / "install-log.json")
    s.save()
    backup = write(s.state / BACKUPS_DIR / f"step-{st.id}" / "x.dll", b"x")
    items = [C.Item(game / "bink2w64.dll", 1, "duplicates", "test"),
             C.Item(s.state / "config.json", 1, "old-logs", "test"),
             C.Item(s.state, 1, "stray-folders", "test"),
             C.Item(Path(s.config.downloads()), 1, "stray-folders", "test"),
             C.Item(backup.parent, 1, "rolled-back-backups", "test"),
             C.Item(tmp_path / "gone.zip", 1, "partial", "test")]
    report = C.clean(s, items, paid=True, trash=C.move_to(tmp_path / "bin"))
    assert not report.moved
    whys = [why for _i, why in report.failed]
    assert whys[0] == "it is in the game folder" and "Leonida's own" in whys[1] and "Leonida uses" in whys[2]
    assert "Leonida uses" in whys[3] and "Undo needs it" in whys[4] and "gone" in whys[5]
    assert (game / "bink2w64.dll").exists() and backup.exists()


def test_a_working_state_folder_of_another_copy_is_left_alone(tmp_path, game, downloads):
    s = make_session(tmp_path, game, downloads)
    other = tmp_path / "Other" / "LeonidaV"
    write(other / "moved-to.txt", str(tmp_path / "somewhere else"))          # points to another folder
    write(other / "x.txt", "x")
    assert C.Scanner(s, home_state=other).stray_folders() == []
    busy = tmp_path / "Busy" / "LeonidaV"
    log = InstallLog(busy / "install-log.json")
    log.new_step("scripthookv", "copy").status = "done"
    log.save()
    assert C.Scanner(s, home_state=busy).stray_folders() == []                # its installed steps need it
    inside = s.state / "sub"
    write(inside / "x.txt", "x")
    assert C.Scanner(s, home_state=s.state, home_downloads=Path(s.config.downloads())).stray_folders() == []


def test_without_injected_folders_an_explicit_state_folder_skips_the_stray_kind(tmp_path, game, downloads):
    s = make_session(tmp_path, game, downloads)
    assert os.environ.get("LEONIDA_STATE_DIR")                               # conftest sets it
    assert C.Scanner(s).stray_folders() == []


def test_sizes_in_words():
    assert C.size_text(512) == "512 B" and C.size_text(2048) == "2 KB" and C.size_text(5 * 2**20) == "5 MB"
    assert C.size_text(3 * 2**30) == "3.0 GB"


# ------------------------------------------------------------------------------------------------- the CLI
def test_cli_clean_dry_run_and_all(tmp_path, game, downloads, capsys, monkeypatch):
    from leonida import cli

    s = make_session(tmp_path, game, downloads)
    s.save()
    shv = make_zip(downloads / "ScriptHookV_1.0.zip", {"bin/ScriptHookV.dll": "shv"})
    dup = downloads / "ScriptHookV copy.zip"
    dup.write_bytes(shv.read_bytes())
    aged(dup, 0.5)
    mod, name = a_free_mod_not_in_the_pack(s)
    free = write(downloads / name, b"outside the pack")
    base = ["--state-dir", str(s.state), "--download-dir", str(downloads), "--game-dir", str(game)]
    assert cli.main(base + ["clean", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Duplicate downloads: 1" in out and "Would move 1 item(s)" in out and dup.exists()
    monkeypatch.setattr(C, "recycle", C.move_to(tmp_path / "bin"))
    assert cli.main(base + ["clean", "--all", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Moved 2 item(s)" in out and not dup.exists() and not free.exists() and shv.exists()
    assert C.LOG_NAME in out
    assert cli.main(base + ["clean"]) == 0 and "Nothing to clean." in capsys.readouterr().out
