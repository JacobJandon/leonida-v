"""Memory sampling, crash collection, `playtest --repeat` and the pre-flight RAM check. Fakes only: never the real
game, never the real %LOCALAPPDATA% (the Windows sampler is only tried on this Python process)."""

from __future__ import annotations

import csv
import json
import os
import struct
import sys
import time
from pathlib import Path

import pytest

from leonida import diagnostics
from leonida import memwatch as M
from leonida import playtest as P
from leonida.cli import main
from leonida.minidump import read_minidump
from tests.test_playtest import NORMAL, FakeGame, make_session, run

GB = 1024.0
REAL_GRACEFUL_CLOSE = M.graceful_close           # the autouse fixture replaces it; one test checks its guard


def _real_memory_step():
    from leonida import cli

    return cli.memory_step


REAL_MEMORY_STEP = _real_memory_step()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))

    def refuse(*a, **k):
        raise AssertionError("a test tried to start or kill a real process")

    monkeypatch.setattr(P.ProcessOps, "start", refuse)
    monkeypatch.setattr(P.ProcessOps, "kill", refuse)
    monkeypatch.setattr(M, "graceful_close", refuse)
    monkeypatch.setattr("leonida.cli.memory_step", lambda: True)  # the CLI's low-memory prompt: tested on its own


class FakeMemory(M.NullMemory):
    """Memory on the fake game's clock: the game's private bytes grow 100 MB a second, free RAM shrinks."""

    def __init__(self, fake: FakeGame, free_before: float = 8 * GB, top=(("chrome.exe", 2100.0),
                                                                          ("Discord.exe", 600.0))):
        self.fake, self.free_before, self.top = fake, free_before, list(top)
        self.process_calls: list[int] = []
        self.closed = False

    def _t(self) -> float:
        return 0.0 if self.fake.started_at is None else self.fake.t - self.fake.started_at

    def system(self) -> dict:
        free = max(self.free_before - 50 * self._t(), 300.0)
        return {"sys_free_mb": free, "sys_total_mb": 16 * GB, "mem_load_pct": 100 - free / (16 * GB) * 100,
                "commit_used_mb": 12 * GB + 80 * self._t(), "commit_limit_mb": 32 * GB}

    def process(self, pid: int) -> dict:
        self.process_calls.append(pid)
        return {"game_ws_mb": 60 * self._t(), "game_private_mb": 100 * self._t()}

    def pagefile(self) -> dict:
        return {"pagefile_used_mb": 1000 + 10 * self._t(), "pagefile_total_mb": 16 * GB}

    def gpu(self, pid) -> dict:
        out = {"gpu_used_mb": 1500 + 40 * self._t()}
        if pid:
            out["game_gpu_mb"] = 30 * self._t()
        return out

    def top_users(self, n: int = 8):
        return self.top[:n]

    def close(self) -> None:
        self.closed = True


def playdir(tmp_path) -> Path:
    return tmp_path / "st" / "logs" / "playtest"


# ------------------------------------------------------------------------------------------------ minidump
def make_minidump(path: Path, code=0xC0000005, address=0x7FF6_0000_0000 + 0xBCC6AD, params=(0, 0x18),
                  modules=(("C:\\Games\\GTA\\GTA5_Enhanced.exe", 0x7FF6_0000_0000, 0x4000000),
                           ("C:\\Games\\GTA\\ScriptHookV.dll", 0x7FFA_0000_0000, 0x100000),
                           ("C:\\Games\\GTA\\ViMinimap.asi", 0x7FFB_0000_0000, 0x10000),
                           ("C:\\Games\\GTA\\plugins\\ViPreload.asi", 0x7FFB_1000_0000, 0x10000),
                           ("C:\\Games\\GTA\\VIMINIMAP.ASI", 0x7FFB_2000_0000, 0x10000))) -> Path:
    """A minimal valid minidump: header, a directory with an exception stream and a module list."""
    names = b""
    name_rvas = []
    exc_rva, mods_rva = 32 + 24, 32 + 24 + 168
    names_rva = mods_rva + 4 + 108 * len(modules)
    for name, _b, _s in modules:
        enc = name.encode("utf-16-le")
        name_rvas.append(names_rva + len(names))
        names += struct.pack("<I", len(enc)) + enc
    head = b"MDMP" + struct.pack("<IIIIIQ", 0xA793, 2, 32, 0, 0, 0)
    directory = struct.pack("<III", 6, 168, exc_rva) + struct.pack("<III", 4, 4 + 108 * len(modules), mods_rva)
    info = list(params) + [0] * (15 - len(params))
    exc = struct.pack("<II", 1234, 0) + struct.pack("<IIQQII", code, 0, 0, address, len(params), 0)
    exc += struct.pack("<15Q", *info) + struct.pack("<II", 0, 0)
    mods = struct.pack("<I", len(modules))
    for (_n, base, size), rva in zip(modules, name_rvas, strict=True):
        mods += struct.pack("<QIIII", base, size, 0, 0, rva) + b"\0" * (108 - 24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(head + directory + exc + mods + names)
    return path


def test_minidump_access_violation(tmp_path):
    info = read_minidump(make_minidump(tmp_path / "a.dmp"))
    assert info.code == 0xC0000005 and info.thread_id == 1234
    assert info.module == "GTA5_Enhanced.exe" and info.offset == 0xBCC6AD
    assert info.describe() == "EXCEPTION_ACCESS_VIOLATION (0xC0000005) in GTA5_Enhanced.exe+0xBCC6AD reading 0x18"
    assert info.modules[:2] == ["GTA5_Enhanced.exe", "ScriptHookV.dll"]
    assert info.site == "GTA5_Enhanced.exe+0xBCC6AD" and info.asis == ["ViMinimap.asi", "ViPreload.asi"]


def test_minidump_other_cases(tmp_path):
    info = read_minidump(make_minidump(tmp_path / "b.dmp", code=0xE06D7363, address=0x7FFA_0000_0010, params=()))
    assert info.describe() == "C++ exception (0xE06D7363) in ScriptHookV.dll+0x10"
    outside = read_minidump(make_minidump(tmp_path / "c.dmp", address=0x1234, params=(1, 0x0)))
    assert "at 0x1234 (outside the loaded modules) writing 0x0" in outside.describe() and outside.site == "0x1234"
    (tmp_path / "x.dmp").write_bytes(b"not a dump at all, just text")
    assert read_minidump(tmp_path / "x.dmp") is None and read_minidump(tmp_path / "missing.dmp") is None
    whole = (tmp_path / "a.dmp").read_bytes() if (tmp_path / "a.dmp").exists() else make_minidump(
        tmp_path / "a.dmp").read_bytes()
    (tmp_path / "cut.dmp").write_bytes(whole[:60])  # cut inside the exception stream: no crash, no exception
    cut = read_minidump(tmp_path / "cut.dmp")
    assert cut is None or cut.code is None


# ------------------------------------------------------------------------------------------------- memwatch
def test_parse_top_users():
    text = ('"chrome.exe","1","Console","1","1,200,000 K"\r\n"chrome.exe","2","Console","1","800.000 K"\r\n'
            '"Discord.exe","3","Console","1","500 000 K"\r\n"System Idle Process","0","Services","0","8 K"\r\n'
            '"broken"\r\n')
    top = M.parse_top_users(text, 2)
    assert [n for n, _ in top] == ["chrome.exe", "Discord.exe"] and round(top[0][1]) == round(2_000_000 / 1024)


def test_watch_interval_csv_and_peaks(tmp_path):
    class Steps(M.NullMemory):
        def __init__(self):
            self.n = 0

        def system(self):
            self.n += 1
            return {"sys_free_mb": 5000 - 1000 * self.n, "commit_used_mb": 100.0 * self.n}

        def process(self, pid):
            return {"game_private_mb": 10.0 * self.n} if pid else {}

    w = M.MemWatch(Steps(), tmp_path / "logs" / "run.csv", every=2.0)
    assert w.tick(0.0, None) is not None and w.tick(1.0, 7) is None   # within 2 s: skipped
    w.tick(2.0, 7)
    w.tick(4.1, None)                                                  # the game's gone
    w.close()
    rows = list(csv.reader((tmp_path / "logs" / "run.csv").open(encoding="utf-8")))
    assert rows[0] == M.COLUMNS and len(rows) == 4
    assert rows[1][M.COLUMNS.index("game_private_mb")] == ""          # empty, never a guess
    peak = w.peak()
    assert peak["sys_free_mb"] == 2000 and peak["commit_used_mb"] == 300 and peak["game_private_mb"] == 20
    assert w.last_with_game().t == 2.0                                  # the values just before the game closed
    assert w.summary()["samples"] == 3


def test_null_memory_writes_nothing(tmp_path):
    w = M.MemWatch(M.NullMemory(), tmp_path / "run.csv")
    assert w.tick(0, 1) is None and w.summary() == {} and not (tmp_path / "run.csv").exists()


def test_describe_and_prune(tmp_path):
    text = M.describe({"game_private_mb": 9 * GB, "game_ws_mb": 6.5 * GB, "sys_free_mb": 1.2 * GB,
                       "commit_used_mb": 31 * GB, "commit_limit_mb": 32 * GB, "gpu_used_mb": 7 * GB,
                       "game_gpu_mb": 6 * GB})
    assert text == ("game 9.0 GB private / 6.5 GB in RAM, free RAM 1.2 GB, commit 31.0 GB of 32.0 GB, "
                    "GPU 7.0 GB (game 6.0 GB)")
    assert M.describe({}) == "no memory values"
    for i in range(5):
        p = tmp_path / f"run-{i}.csv"
        p.write_text("x")
        os.utime(p, (1000 + i, 1000 + i))
    M.prune(tmp_path, "run-*.csv", 2)
    assert sorted(p.name for p in tmp_path.glob("run-*.csv")) == ["run-3.csv", "run-4.csv"]


def test_preflight():
    class Low(M.NullMemory):
        def __init__(self, free, commit_free=20 * GB):
            self.free, self.commit_free = free, commit_free

        def system(self):
            return {"sys_free_mb": self.free, "commit_limit_mb": 32 * GB, "commit_used_mb": 32 * GB - self.commit_free}

        def top_users(self, n=8):
            return [("chrome.exe", 2100.0), ("svchost.exe", 1500.0), ("Discord.exe", 600.0), ("LeonidaV.exe", 300.0)]

    free, msg = M.preflight(Low(4.6 * GB))
    assert free == 4.6 * GB and msg.startswith("GTA may crash while loading: free memory is low: 4.6 GB of RAM free "
                                               "(under 6.0 GB).")
    assert "Using the most memory now: chrome.exe (2.1 GB), svchost.exe (1.5 GB), Discord.exe (0.6 GB)" in msg
    assert M.preflight(Low(8 * GB)) == (8 * GB, None)
    assert M.preflight(M.NullMemory()) == (None, None)
    # free commit counts too: 6 GB free RAM is fine, 9.8 GB free commit isn't
    chk = M.check_memory(Low(6.5 * GB, commit_free=9.8 * GB))
    assert chk.low and chk.reasons == ["9.8 GB of commit free (under 12.0 GB)"] and chk.free_commit_mb == 9.8 * GB
    both = M.check_memory(Low(4.6 * GB, commit_free=9.8 * GB))
    assert both.text().startswith("GTA may crash while loading: free memory is low: 4.6 GB of RAM free (under "
                                  "6.0 GB) and 9.8 GB of commit free (under 12.0 GB).")
    # only apps the user may close are offered: never Windows, security, the game or Leonida
    assert [a.name for a in both.closeable] == ["chrome.exe", "Discord.exe"]
    assert not M.check_memory(Low(8 * GB)).low and M.check_memory(Low(8 * GB)).apps == []


def test_close_apps_is_graceful_and_never_touches_windows_or_leonida():
    alive = {"chrome.exe", "Discord.exe"}
    asked = []
    t = {"now": 0.0}

    def close(name):
        asked.append(name)
        if name == "chrome.exe":
            alive.discard(name)        # closes; Discord only hides in the tray

    def sleep(s):
        t["now"] += s

    closed, left = M.close_apps(["chrome.exe", "Discord.exe", "svchost.exe", "explorer.exe", "LeonidaV.exe",
                                 "GTA5_Enhanced.exe", "chrome.exe"], timeout=5, close=close,
                                running=lambda n: n in alive, sleep=sleep, clock=lambda: t["now"])
    assert asked == ["chrome.exe", "Discord.exe"] and closed == ["chrome.exe"] and left == ["Discord.exe"]
    assert t["now"] >= 5
    assert REAL_GRACEFUL_CLOSE("svchost.exe") == "svchost.exe is never closed by Leonida."  # never runs taskkill


@pytest.mark.skipif(sys.platform != "win32", reason="Windows memory APIs")
def test_windows_sampler_on_this_process():
    mem = M.default_ops()
    try:
        sysv = mem.system()
        assert sysv["sys_total_mb"] > 0 and 0 <= sysv["sys_free_mb"] <= sysv["sys_total_mb"]
        assert sysv["commit_limit_mb"] >= sysv["commit_used_mb"] > 0
        proc = mem.process(os.getpid())
        assert proc["game_private_mb"] > 0 and proc["game_ws_mb"] > 0
        assert isinstance(mem.pagefile(), dict) and isinstance(mem.gpu(os.getpid()), dict)
    finally:
        mem.close()


# ------------------------------------------------------------------------------------------- in the play test
def test_passed_run_samples_memory(tmp_path, game):
    s = make_session(tmp_path, game)
    fake = FakeGame(game, NORMAL)
    mem = FakeMemory(fake)
    rep = run(s, fake, mem=mem)
    assert rep.ok and mem.closed
    assert rep.free_ram_before_mb == 8 * GB and not any("RAM is free" in n for n in rep.notes)
    csvs = list(playdir(tmp_path).glob("run-*.csv"))
    assert len(csvs) == 1 and rep.memory["csv"] == str(csvs[0])
    rows = list(csv.DictReader(csvs[0].open(encoding="utf-8")))
    assert len(rows) == rep.memory["samples"] >= 35                      # every 2 s from launch to closing
    assert rows[0]["game_private_mb"] == "" and rows[-5]["game_private_mb"] != ""  # no game yet / the game
    assert set(mem.process_calls) == {4242}
    peak = rep.memory["peak"]
    assert peak["game_private_mb"] >= 7000 and peak["sys_free_mb"] < 8 * GB
    lines = rep.summary()
    assert any(ln.startswith("memory peak: game ") for ln in lines) and any("memory samples" in ln for ln in lines)
    saved = json.loads((tmp_path / "st" / "playtest" / "last-report.json").read_text())
    assert saved["memory"]["peak"]["game_private_mb"] == peak["game_private_mb"]


def test_low_ram_warning_before_the_launch(tmp_path, game):
    s = make_session(tmp_path, game)
    fake = FakeGame(game, NORMAL)
    seen = []
    rep = run(s, fake, mem=FakeMemory(fake, free_before=4.6 * GB), progress=seen.append)
    assert rep.ok  # a warning, never a stop
    note = next(n for n in rep.notes if "free memory is low" in n)
    assert "4.6 GB of RAM free" in note and "chrome.exe (2.1 GB), Discord.exe (0.6 GB)" in note
    assert any(m.startswith("Warning: GTA may crash while loading") for m in seen)
    assert "Free before the launch: RAM 4.6 GB, commit 20.0 GB" in seen
    assert rep.free_commit_before_mb == 20 * GB
    assert seen.index(next(m for m in seen if m.startswith("Warning"))) < seen.index("Started PlayGTAV.exe")


CONTEXT = """###### DEBUG INFO ######

============ SYSTEM INFO ============
Game State : Game Running
System Time (0h 1m 5s)
Raw System Time (22697754ms)
System Memory :
  Memory Load       : (        91%)
  Physical Free     : (      1307Mb)
  PageFile Total    : (     32351Mb)
  PageFile Free     : (      7011Mb)
============ MISC INFO ============
Version : 1013.20-dev_gen9_sga_live
Loading : 7
============ STREAMING INFO ============
Is Out of memory      : No : 0
============ SCALEFORM INFO ============
Last Movie : HUD
Last ActionScript Method : HUD.SHOW
"""


def test_crash_collects_dump_rockstar_log_events_and_memory(tmp_path, game):
    s = make_session(tmp_path, game)
    local = tmp_path / "localappdata"
    rockstar = local / "Rockstar Games" / "GTAV Enhanced" / "CrashLogs"

    def crash(fake):
        fake.procs.discard(P.GAME_EXE)
        make_minidump(rockstar / "8533541a.dmp")
        (rockstar / "crashcontext.log").write_text(CONTEXT)
        (local / "CrashDumps").mkdir(parents=True, exist_ok=True)
        (local / "CrashDumps" / "Discord.exe.77.dmp").write_bytes(b"MDMP-ish")
        (game / "asiloader.log").write_text("Loaded ViMinimap.asi\nLoaded ViPreload.asi")  # this run's logs
        (game / "menyooLog.txt").write_text("menyoo started")
    event = "Source: Application Error | Faulting application name: GTA5_Enhanced.exe | Exception code: 0xc0000005"
    fake = FakeGame(game, [(3, "game"), (12, "shv"), (25, "shvdn"), (76, crash)], events=[event])
    rep = run(s, fake, mem=FakeMemory(fake))
    assert rep.status == P.CRASHED and 75 <= rep.ended_after <= 80
    assert rep.crash_reason == "EXCEPTION_ACCESS_VIOLATION (0xC0000005) in GTA5_Enhanced.exe+0xBCC6AD reading 0x18"
    assert rep.crash_site == "GTA5_Enhanced.exe+0xBCC6AD" and rep.crash_asis == ["ViMinimap.asi", "ViPreload.asi"]
    assert rep.crash_memory_load == "91%"                     # from Rockstar's crashcontext.log
    assert rep.evidence[0] == ("crash summary: EXCEPTION_ACCESS_VIOLATION (0xC0000005) in GTA5_Enhanced.exe+0xBCC6AD "
                               "reading 0x18 | memory load 91% | ASIs: ViMinimap.asi, ViPreload.asi (8533541a.dmp)")
    saved = json.loads((tmp_path / "st" / "playtest" / "last-report.json").read_text())
    assert saved["crash_site"] == rep.crash_site and saved["crash_asis"] == rep.crash_asis
    ev = "\n".join(rep.evidence)
    assert "crash summary: EXCEPTION_ACCESS_VIOLATION" in ev and "Discord.exe.77.dmp" in ev
    assert ("Rockstar crash log: Game State : Game Running; System Time 0h 1m 5s; Memory Load : 91%; "
            "Physical Free : 1307Mb; PageFile Total : 32351Mb; PageFile Free : 7011Mb") in ev
    assert "Is Out of memory : No : 0" in ev and "Last ActionScript Method : HUD.SHOW" in ev
    assert "Faulting application name: GTA5_Enhanced.exe" in ev
    assert "asiloader.log: Loaded ViPreload.asi" in ev and "menyooLog.txt: menyoo started" in ev
    assert "memory at 7" in ev and "(the last sample before the end): game 7." in ev
    folder = Path(rep.crash_dir)
    assert folder.parent == playdir(tmp_path) and folder.name.startswith("crash-")
    assert (folder / "rockstar-crashcontext.log").read_text() == CONTEXT
    assert "GTA5_Enhanced.exe+0xBCC6AD" in (folder / "dumps.txt").read_text()
    assert "Faulting application name" in (folder / "events.txt").read_text()
    assert (folder / "mod-logs" / "ScriptHookV.log").is_file() and (folder / "mod-logs" / "asiloader.log").is_file()
    summary = (folder / "summary.txt").read_text()
    assert "using the most memory at the end: chrome.exe (2.1 GB), Discord.exe (0.6 GB)" in summary
    assert not list(folder.rglob("*.dmp"))                     # dumps are listed, never copied
    lines = rep.summary()
    assert any(ln.startswith("memory at 7") and "just before the end" in ln for ln in lines)


def test_hang_also_keeps_evidence(tmp_path, game):
    s = make_session(tmp_path, game)
    fake = FakeGame(game, [(3, "game"), (12, "shv")])
    rep = run(s, fake, timeout=60, mem=FakeMemory(fake))
    assert rep.status == P.HANG and rep.crash_dir and 58 <= rep.ended_after <= 64 and rep.crash_reason is None
    assert "summary.txt" in os.listdir(rep.crash_dir)


def test_crash_folders_are_pruned(tmp_path, game):
    s = make_session(tmp_path, game)
    folder = playdir(tmp_path)
    for i in range(P.KEEP_CRASH_DIRS + 3):
        d = folder / f"crash-2026010{i:02d}"
        d.mkdir(parents=True)
        os.utime(d, (1000 + i, 1000 + i))
    ev, info, made = P.collect_crash(s, game, since=0, events=[])
    assert made.is_dir() and len(list(folder.glob("crash-*"))) == P.KEEP_CRASH_DIRS
    assert not (folder / "crash-202601000").exists()


# ------------------------------------------------------------------------------------------------- series
class SeriesGame(FakeGame):
    """A new script for each launch."""

    def __init__(self, game, scripts, **kw):
        super().__init__(game, [], **kw)
        self.scripts = list(scripts)
        self.pauses: list[float] = []

    def start(self, exe, cwd):
        self.script, self.done = sorted(self.scripts.pop(0), key=lambda x: x[0]), set()
        super().start(exe, cwd)

    def sleep(self, s):
        if s >= 15:
            self.pauses.append(s)
        super().sleep(s)


def test_series_summary(tmp_path, game):
    s = make_session(tmp_path, game)
    rockstar = tmp_path / "localappdata" / "Rockstar Games" / "GTAV Enhanced" / "CrashLogs"

    def crash(fake):
        fake.procs.discard(P.GAME_EXE)
        make_minidump(rockstar / f"{len(fake.starts)}.dmp")

    crash_run = [(3, "game"), (12, "shv"), (25, "shvdn"), (74, crash)]
    fake = SeriesGame(game, [NORMAL, crash_run, NORMAL, crash_run])
    seen = []
    series = P.playtest_series(s, 4, progress=seen.append, pause=20, ops=fake, sleep=fake.sleep, clock=fake.clock,
                               poll=2, settle=10, timeout=300, mem=FakeMemory(fake))
    assert [r.status for r in series.runs] == [P.PASSED, P.CRASHED, P.PASSED, P.CRASHED] and not series.ok
    assert fake.pauses == [20, 20, 20] and len(fake.starts) == 4
    assert "--- Run 2 of 4 ---" in seen
    lines = series.lines()
    assert lines[0] == "4 run(s): 2 passed, 0 failed, 2 crashed, 0 hang"
    assert lines[1] == "Story mode after 70 s (median 70 s)."
    assert lines[2] == "Free before the launch:"
    assert lines[3].startswith("  passed run(s) (2): RAM ") and ", commit " in lines[3]
    assert lines[4].startswith("  crashed run(s) (2): RAM ")
    lines = lines[:2] + lines[5:]
    assert lines[2].startswith("Crashes at 7") and lines[2].endswith(" s after the launch.")
    assert lines[3] == "  2× GTA5_Enhanced.exe+0xBCC6AD  EXCEPTION_ACCESS_VIOLATION (0xC0000005)  (memory load 72%, 72%)"
    text = "\n".join(lines)
    assert "Run  1  PASSED   story mode 7" in text and "Run  2  CRASHED  ended at 7" in text
    assert "free before: RAM 8.0 GB, commit 20.0 GB" in text and "just before: game 7." in text and "crash details:" in text
    assert "loaded ASIs: ViMinimap.asi, ViPreload.asi" in text and "| memory load 72%" in text
    assert len(list(playdir(tmp_path).glob("run-*.csv"))) == 4
    saved = series.saved
    assert saved.read_text().startswith("4 run(s): 2 passed")
    data = json.loads(saved.with_suffix(".json").read_text())
    assert [r["status"] for r in data["runs"]] == ["passed", "crashed", "passed", "crashed"]
    assert data["runs"][1]["crash_reason"].startswith("EXCEPTION_ACCESS_VIOLATION")


def test_series_stops_when_blocked_and_on_ctrl_c(tmp_path, game):
    s = make_session(tmp_path, game)
    fake = SeriesGame(game, [NORMAL], running=(P.GAME_EXE,), deny_kill=True)
    series = P.playtest_series(s, 5, ops=fake, sleep=fake.sleep, clock=fake.clock, poll=2, settle=10)
    assert [r.status for r in series.runs] == [P.BLOCKED] and series.lines()[0].startswith("1 of 5 run(s)")

    fake = SeriesGame(game, [NORMAL, NORMAL, NORMAL])
    calls = []

    def sleepy(sec):
        calls.append(sec)
        if sec == 20:
            raise KeyboardInterrupt
        fake.sleep(sec)

    series = P.playtest_series(s, 3, ops=fake, sleep=sleepy, clock=fake.clock, poll=2, settle=10)
    assert len(series.runs) == 1 and series.interrupted and not series.ok
    assert series.lines()[0] == "1 of 3 run(s): 1 passed, 0 failed, 0 crashed, 0 hang (stopped early)"


# ---------------------------------------------------------------------------------------------------- CLI
def test_cli_repeat(tmp_path, game, monkeypatch, capsys):
    calls = []

    def fake_series(session, repeat, progress, pause, timeout):
        calls.append((repeat, pause, timeout))
        progress("--- Run 1 of 3 ---")
        rep = P.PlaytestReport(P.CRASHED, "The game closed", ended_after=76.0, crash_site="GTA5_Enhanced.exe+0xBCC6AD",
                               crash_reason="EXCEPTION_ACCESS_VIOLATION (0xC0000005) in GTA5_Enhanced.exe+0xBCC6AD")
        return P.SeriesReport(runs=[rep], planned=3, saved=tmp_path / "series.txt")

    monkeypatch.setattr(P, "playtest_series", fake_series)
    st = ["--state-dir", str(tmp_path / "st"), "--game-dir", str(game)]
    rc = main([*st, "playtest", "--repeat", "3", "--pause", "5", "--timeout", "200"])
    out = capsys.readouterr().out
    assert rc == 1 and calls == [(3, 5.0, 200.0)]
    assert "1 of 3 run(s): 0 passed, 0 failed, 1 crashed, 0 hang" in out and "Crashes at 76 s" in out and "Summary saved:" in out
    assert out.rstrip().splitlines()[-1] == ("VERDICT: 1 of 3 run(s): 0 passed, 0 failed, 1 crashed, 0 hang; "
                                             "1× GTA5_Enhanced.exe+0xBCC6AD")
    assert main([*st, "playtest", "--repeat", "2", "--keep-running"]) == 2
    with pytest.raises(SystemExit):
        main([*st, "playtest", "--repeat", "0"])


def test_cli_single_run_prints_memory(tmp_path, game, monkeypatch, capsys):
    def fake_playtest(session, timeout, keep_running, progress):
        return P.PlaytestReport(P.PASSED, "Story mode loaded after 87 s",
                                memory={"csv": "run.csv", "samples": 50, "peak": {"game_private_mb": 9216.0}})

    monkeypatch.setattr(P, "playtest", fake_playtest)
    assert main(["--state-dir", str(tmp_path / "st"), "--game-dir", str(game), "playtest"]) == 0
    out = capsys.readouterr().out
    assert "memory peak: game 9.0 GB private" in out and "memory samples (50, every 2 s): run.csv" in out
    assert out.rstrip().splitlines()[-1] == "VERDICT: PASSED"   # the last line, after the verify lines


def test_verdicts():
    R = P.PlaytestReport
    assert R(P.PASSED, "", story_mode_after=87.2).verdict() == "VERDICT: PASSED (story mode after 87 s)"
    assert R(P.FAILED, "", story_mode_after=80).verdict() == "VERDICT: FAILED (story mode after 80 s)"
    assert (R(P.CRASHED, "", ended_after=76.4, crash_site="GTA5_Enhanced.exe+0x1516B9").verdict()
            == "VERDICT: CRASHED GTA5_Enhanced.exe+0x1516B9 (at 76 s)")
    assert R(P.CRASHED, "", ended_after=70).verdict() == "VERDICT: CRASHED no-crash-dump (at 70 s)"
    assert R(P.HANG, "", ended_after=300).verdict() == "VERDICT: HANG (at 300 s)"
    assert R(P.BLOCKED, "x").verdict() == "VERDICT: BLOCKED"
    assert R(P.PASSED, "ok").summary()[-1] == "VERDICT: PASSED"


# ------------------------------------------------------------------------------- waiting for exits and dumps
def test_a_dump_still_being_written_is_waited_for_before_any_kill(tmp_path, game):
    s = make_session(tmp_path, game)
    rockstar = tmp_path / "localappdata" / "Rockstar Games" / "GTAV Enhanced" / "CrashLogs"
    full = make_minidump(tmp_path / "full.dmp").read_bytes()
    dump = rockstar / "8533541a.dmp"

    def crash(fake):          # the game's gone, its crash handler is still writing the dump
        fake.procs.discard(P.GAME_EXE)
        fake.procs.add("WerFault.exe")
        rockstar.mkdir(parents=True, exist_ok=True)
        dump.write_bytes(b"")

    def half(fake):
        dump.write_bytes(full[:100])

    def done(fake):
        dump.write_bytes(full)

    def handler_exits(fake):
        fake.procs.discard("WerFault.exe")

    fake = FakeGame(game, [(3, "game"), (12, "shv"), (25, "shvdn"), (60, crash), (66, half), (72, done),
                           (90, handler_exits)])
    killed_at = []
    real_kill = fake.kill

    def kill(name):
        killed_at.append((name, fake.t - fake.started_at, dump.stat().st_size if dump.exists() else None))
        return real_kill(name)

    fake.kill = kill
    seen = []
    rep = run(s, fake, progress=seen.append)
    assert rep.status == P.CRASHED and rep.crash_site == "GTA5_Enhanced.exe+0xBCC6AD"  # read once it was complete
    assert killed_at and all(t >= 72 and size == len(full) for _n, t, size in killed_at)
    assert "WerFault.exe" not in [n for n, _t, _s in killed_at]                       # waited for, never killed
    assert any(m.startswith("A crash dump is being written (8533541a.dmp)") for m in seen)
    assert seen[-1] == "Everything has exited (waited 10 s more)" and "WerFault.exe" not in fake.procs
    assert fake.t - fake.started_at >= 100                                             # handler exit + 10 s quiet


def test_an_old_empty_dump_does_not_hold_anything_up(tmp_path):
    rockstar = tmp_path / "localappdata" / "Rockstar Games" / "GTAV Enhanced" / "CrashLogs"
    rockstar.mkdir(parents=True)
    old = rockstar / "abandoned.dmp"
    old.write_bytes(b"")
    stamp = time.time() - 120
    os.utime(old, (stamp, stamp))
    clock = {"t": 0.0}
    sleeps = []

    def sleep(sec):
        sleeps.append(sec)
        clock["t"] += sec

    assert P.wait_for_dumps(time.time() - 600, sleep, lambda: clock["t"], poll=2) is True
    assert sleeps == []                                    # empty but abandoned long ago: no wait at all
    assert P.wait_for_dumps(time.time(), sleep, lambda: clock["t"]) is True and sleeps == []  # not new: ignored
    # a fresh 0-byte dump (being written right now) is waited for, up to the timeout
    fresh = rockstar / "fresh.dmp"
    fresh.write_bytes(b"")
    said = []
    assert P.wait_for_dumps(time.time() - 600, sleep, lambda: clock["t"], poll=2, timeout=10, say=said.append) is False
    assert sum(sleeps) >= 10 and said[0].startswith("A crash dump is being written (")
    assert said[-1].startswith("A crash dump may still be incomplete after 10 s")


def test_series_waits_for_the_previous_game_to_exit(tmp_path, game):
    s = make_session(tmp_path, game)

    def slow_exit(fake):  # PlayGTAV.exe ignores the first kill and lingers for 15 s
        fake.lingering = fake.t + 15

    fake = SeriesGame(game, [NORMAL, NORMAL])
    fake.lingering = 0.0
    real_running = fake.running

    def running(name):
        if name == P.LAUNCHER and fake.t < fake.lingering:
            return [4243]
        return real_running(name)

    real_kill = fake.kill

    def kill(name):
        if name == P.LAUNCHER and not fake.lingering:
            slow_exit(fake)
        return real_kill(name)

    fake.running, fake.kill = running, kill
    seen = []
    series = P.playtest_series(s, 2, progress=seen.append, pause=20, ops=fake, sleep=fake.sleep, clock=fake.clock,
                               poll=2, settle=10, timeout=300)
    assert [r.status for r in series.runs] == [P.PASSED, P.PASSED]
    closed = seen.index("Everything has exited (waited 10 s more)")
    assert closed < seen.index("--- Run 2 of 2 ---")
    assert "Run 1 VERDICT: PASSED (story mode after 70 s)" in seen and "Run 2 VERDICT: PASSED (story mode after 70 s)" in seen
    assert series.verdict() == "VERDICT: 2 run(s): 2 passed, 0 failed, 0 crashed, 0 hang"


# ------------------------------------------------------------------------------------------- debug report
def test_report_has_playtest_files_but_no_dumps(tmp_path, game):
    s = make_session(tmp_path, game)
    folder = playdir(tmp_path)
    folder.mkdir(parents=True)
    for i in range(7):
        p = folder / f"run-2026112{i}.csv"
        p.write_text("time,t\n")
        os.utime(p, (1000 + i, 1000 + i))
    (folder / "series-1.txt").write_text("4 run(s)")
    (folder / "series-1.json").write_text("{}")
    crash = folder / "crash-1"
    (crash / "mod-logs").mkdir(parents=True)
    (crash / "summary.txt").write_text("crash: x")
    (crash / "rockstar-crashcontext.log").write_text(CONTEXT)
    (crash / "mod-logs" / "ScriptHookV.log").write_text("x")
    (crash / "stray.dmp").write_bytes(b"MDMP")
    names = [n for n, _ in diagnostics._playtest_files(s)]
    assert len([n for n in names if n.endswith(".csv")]) == 5 and "playtest/run-20261126.csv" in names
    assert {"playtest/series-1.txt", "playtest/series-1.json", "playtest/crash-1/summary.txt",
            "playtest/crash-1/rockstar-crashcontext.log", "playtest/crash-1/mod-logs/ScriptHookV.log"} <= set(names)
    assert not any(n.endswith(".dmp") for n in names)


def test_report_crash_dumps_grouped_by_site_and_redacted(tmp_path, game, monkeypatch):
    local = tmp_path / "localappdata"
    rockstar = local / "Rockstar Games" / "GTAV Enhanced" / "CrashLogs"
    for i, addr in enumerate((0xBCC6AD, 0xBCC6AD, 0x1516B9)):
        d = make_minidump(rockstar / f"dump{i}.dmp", address=0x7FF6_0000_0000 + addr)
        os.utime(d, (1000 + i, 1000 + i))
    (rockstar / "crashcontext.log").write_text(CONTEXT.replace("Version :", f"Path : {Path.home() / 'x'}\nVersion :"))
    (local / "CrashDumps").mkdir(parents=True)
    make_minidump(local / "CrashDumps" / "GTA5_Enhanced.exe.4242.dmp")
    make_minidump(local / "CrashDumps" / "python.exe.1.dmp")          # not the game: left out
    text = diagnostics._crash_dumps_text()
    assert text.startswith("The game's newest crash dumps (4, newest first)")
    assert "  3\u00d7 GTA5_Enhanced.exe+0xBCC6AD  EXCEPTION_ACCESS_VIOLATION (0xC0000005)" in text
    assert "  1\u00d7 GTA5_Enhanced.exe+0x1516B9" in text and "python.exe.1.dmp" not in text
    assert "dump2.dmp  EXCEPTION_ACCESS_VIOLATION (0xC0000005) in GTA5_Enhanced.exe+0x1516B9 reading 0x18 | ASIs: " \
           "ViMinimap.asi, ViPreload.asi" in text
    assert "Memory Load : 91%" in text and "Last ActionScript Method : HUD.SHOW" in text
    s = make_session(tmp_path, game)
    report = dict(diagnostics.collect(s))
    assert report["results/crash-dumps.txt"].count("\u00d7") == 2
    assert str(Path.home()) not in report["results/crash-dumps.txt"]   # redacted like everything else


# ------------------------------------------------------------------------------------- the CLI's memory step
class LowMem(M.NullMemory):
    def __init__(self):
        self.free, self.commit_used = 4.6 * GB, 22 * GB

    def system(self):
        return {"sys_free_mb": self.free, "commit_limit_mb": 32 * GB, "commit_used_mb": self.commit_used}

    def top_users(self, n=8):
        return [("firefox.exe", 1500.0), ("svchost.exe", 1300.0), ("Discord.exe", 900.0)]


def test_cli_memory_step_choices(monkeypatch, capsys):
    memory_step = REAL_MEMORY_STEP
    picked = []

    def fake_close(names, **kw):
        picked.append(list(names))
        return names[:1], names[1:]

    monkeypatch.setattr(M, "close_apps", fake_close)
    mem = LowMem()
    # Enter: play anyway, nothing closed
    assert memory_step(mem, ask=lambda q: "", interactive=True) is True and picked == []
    out = capsys.readouterr().out
    assert "GTA may crash while loading: free memory is low: 4.6 GB of RAM free" in out
    assert "  1. firefox.exe (1.5 GB)" in out and "  2. Discord.exe (0.9 GB)" in out and "svchost" not in out.split(
        "Close apps first?")[1]
    # q: cancel
    assert memory_step(mem, ask=lambda q: "q", interactive=True) is False and picked == []
    # numbers: close just those (gracefully, through close_apps)
    assert memory_step(mem, ask=lambda q: "2", interactive=True) is True and picked == [["Discord.exe"]]
    assert memory_step(mem, ask=lambda q: "all", interactive=True) is True
    assert picked[-1] == ["firefox.exe", "Discord.exe"]
    out = capsys.readouterr().out
    assert "Closed: firefox.exe" in out and "Still running: Discord.exe (some apps only hide in the tray" in out
    # no terminal (a script): a warning only, never a close
    picked.clear()
    assert memory_step(mem, ask=lambda q: pytest.fail("no prompt"), interactive=False) is True and picked == []
    assert "Playing anyway (nothing was closed)." in capsys.readouterr().out
    # enough memory: silent
    mem.free, mem.commit_used = 8 * GB, 12 * GB
    assert memory_step(mem, ask=lambda q: pytest.fail("no prompt"), interactive=True) is True
    assert capsys.readouterr().out == ""


def test_cli_cancel_at_the_memory_step(tmp_path, game, monkeypatch, capsys):
    monkeypatch.setattr("leonida.cli.memory_step", lambda: False)
    monkeypatch.setattr(P, "playtest", lambda *a, **k: pytest.fail("must not start"))
    st = ["--state-dir", str(tmp_path / "st"), "--game-dir", str(game)]
    assert main([*st, "playtest"]) == 1
    assert capsys.readouterr().out.rstrip().splitlines()[-1] == "VERDICT: CANCELLED (free memory is low)"
    calls = []
    monkeypatch.setattr("leonida.cli.memory_step", lambda: calls.append(1) or True)
    monkeypatch.setattr(P, "playtest", lambda *a, **k: P.PlaytestReport(P.PASSED, "ok"))
    assert main([*st, "playtest", "--no-memory-check"]) == 0 and calls == []


# ---------------------------------------------------------------------------------------- stack summary
def make_stack_dump(path: Path, words: list[int], text: bytes = b"", thread_name: str = "") -> Path:
    """A minidump with an exception (and its CPU context), one thread whose stack holds ``words`` from RSP on (plus
    ``text`` just below RSP), modules GTA5_Enhanced.exe / ScriptHookV.dll / clr.dll / ScriptHookVDotNet.asi."""
    modules = [("GTA5_Enhanced.exe", 0x7FF6_0000_0000, 0x4000000), ("ScriptHookV.dll", 0x7FFA_0000_0000, 0x100000),
               ("clr.dll", 0x7FFB_0000_0000, 0x1000000), ("ScriptHookVDotNet.asi", 0x7FFC_0000_0000, 0x50000),
               ("ntdll.dll", 0x7FFD_0000_0000, 0x200000)]
    tid, st_start, below = 4242, 0x50_0000_0000, 0x100
    rsp = st_start + below
    stack = text.ljust(below, b"\0") + b"".join(struct.pack("<Q", w) for w in words)
    out = bytearray(b"\0" * 32)
    streams = []

    def add(blob: bytes) -> int:
        at = len(out)
        out.extend(blob)
        return at

    ctx = bytearray(0x4D0)
    struct.pack_into("<Q", ctx, 0x98, rsp)
    ctx_at = add(bytes(ctx))
    stack_at = add(stack)
    exc = struct.pack("<II", tid, 0) + struct.pack("<IIQQII", 0xC0000005, 0, 0, 0x7FF6_0000_0000 + 0x1516B9, 2, 0)
    exc += struct.pack("<15Q", 0, 0x1BA9910937A, *([0] * 13)) + struct.pack("<II", len(ctx), ctx_at)
    streams.append((6, len(exc), add(exc)))
    names = []
    for name, _b, _s in modules:
        enc = name.encode("utf-16-le")
        names.append(add(struct.pack("<I", len(enc)) + enc))
    mods = struct.pack("<I", len(modules)) + b"".join(
        struct.pack("<QIIII", b, s, 0, 0, n) + b"\0" * 84 for (_nm, b, s), n in zip(modules, names, strict=True))
    streams.append((4, len(mods), add(mods)))
    threads = struct.pack("<I", 1) + struct.pack("<IIIIQQIIII", tid, 0, 0, 0, 0, st_start, len(stack), stack_at,
                                                  len(ctx), ctx_at)
    streams.append((3, len(threads), add(threads)))
    if thread_name:
        enc = thread_name.encode("utf-16-le")
        nm = add(struct.pack("<I", len(enc)) + enc)
        tn = struct.pack("<I", 1) + struct.pack("<IQ", tid, nm)
        streams.append((24, len(tn), add(tn)))
    directory = add(b"".join(struct.pack("<III", *s) for s in streams))
    out[0:32] = b"MDMP" + struct.pack("<IIIIIQ", 0xA793, len(streams), directory, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


SCRIPT_STACK = [0x7FF6_0000_0000 + 0x1D28607, 0x50_0000_0310, 0x7FFD_0000_1234, 1,
                0x7FFA_0000_0000 + 0xE55B, 0x55E86AF2712B36A1, 0x7FFB_0000_0000 + 0x634A5, 0x7FFB_0000_0000 + 0x634A5,
                0xDEADBEEF, 0x7FFC_0000_0000 + 0x2830]


def test_stack_summary_of_a_script_crash(tmp_path):
    info = read_minidump(make_stack_dump(tmp_path / "s.dmp", SCRIPT_STACK,
                                         text=b"\0\0entity_set_car_lift_default\0x\0tr_interior_0_tuner_mod_garage\0",
                                         thread_name="Main"))
    assert info.site == "GTA5_Enhanced.exe+0x1516B9" and info.thread_name == "Main"
    # module hits from RSP outward; system DLLs and repeats left out
    assert info.stack == ["GTA5_Enhanced.exe+0x1D28607", "ScriptHookV.dll+0xE55B", "clr.dll+0x634A5",
                          "ScriptHookVDotNet.asi+0x2830"]
    assert info.native == 0x55E86AF2712B36A1                 # the qword after Script Hook V's return address
    assert info.via == "a Script Hook V .NET script, through a native call"
    assert info.stack_strings == ["tr_interior_0_tuner_mod_garage", "entity_set_car_lift_default"]  # nearest first
    info.native_name = "ACTIVATE_INTERIOR_ENTITY_SET"
    assert info.stack_summary() == (
        "called from GTA5_Enhanced.exe+0x1D28607 < ScriptHookV.dll+0xE55B < clr.dll+0x634A5 < "
        "ScriptHookVDotNet.asi+0x2830 (a Script Hook V .NET script, through a native call); native "
        "ACTIVATE_INTERIOR_ENTITY_SET (0x55E86AF2712B36A1); thread 'Main'; on the stack: "
        "tr_interior_0_tuner_mod_garage, entity_set_car_lift_default")


def test_stack_summary_of_an_engine_crash(tmp_path):
    info = read_minidump(make_stack_dump(tmp_path / "e.dmp", [0x7FF6_0000_0000 + 0xBCDA61,
                                                              0x7FF6_0000_0000 + 0x1308160]))
    assert info.stack == ["GTA5_Enhanced.exe+0xBCDA61", "GTA5_Enhanced.exe+0x1308160"] and info.native is None
    assert info.via == "" and info.stack_summary() == ("called from GTA5_Enhanced.exe+0xBCDA61 < "
                                                       "GTA5_Enhanced.exe+0x1308160")
    # an old-style dump without a CPU context: no stack, no error
    plain = read_minidump(make_minidump(tmp_path / "p.dmp"))
    assert plain.stack == [] and plain.stack_summary() == ""


def test_crash_report_names_the_native_and_keeps_script_logs(tmp_path, game, monkeypatch):
    s = make_session(tmp_path, game)
    rockstar = tmp_path / "localappdata" / "Rockstar Games" / "GTAV Enhanced" / "CrashLogs"
    monkeypatch.setattr("leonida.nativenames.native_names",
                        lambda g: {0x55E86AF2712B36A1: "ACTIVATE_INTERIOR_ENTITY_SET"})

    def crash(fake):
        fake.procs.discard(P.GAME_EXE)
        make_stack_dump(rockstar / "37b52876.dmp", SCRIPT_STACK, text=b"\0entity_set_car_lift_default\0")
        (game / "scripts").mkdir(exist_ok=True)
        (game / "scripts" / "EAIInitalization.log").write_text("State 6 (REQUESTING ALL INTERIORS)\n")

    fake = FakeGame(game, [(3, "game"), (12, "shv"), (25, "shvdn"), (88, crash)])
    rep = run(s, fake)
    assert rep.status == P.CRASHED and rep.crash_site == "GTA5_Enhanced.exe+0x1516B9"
    assert "native ACTIVATE_INTERIOR_ENTITY_SET (0x55E86AF2712B36A1)" in rep.crash_stack
    assert rep.evidence[1].startswith("crash stack: called from GTA5_Enhanced.exe+0x1D28607 < ScriptHookV.dll")
    assert "scripts\\EAIInitalization.log: State 6 (REQUESTING ALL INTERIORS)" in rep.evidence
    folder = Path(rep.crash_dir)
    assert (folder / "mod-logs" / "scripts-EAIInitalization.log").read_text().startswith("State 6")
    saved = json.loads((tmp_path / "st" / "playtest" / "last-report.json").read_text())
    assert "ACTIVATE_INTERIOR_ENTITY_SET" in saved["crash_stack"]
    series = P.SeriesReport(runs=[rep], planned=1)
    assert any(line.strip().startswith("stack: called from") for line in series.lines())


def test_report_has_the_stack_of_each_dump(tmp_path, game, monkeypatch):
    rockstar = tmp_path / "localappdata" / "Rockstar Games" / "GTAV Enhanced" / "CrashLogs"
    make_stack_dump(rockstar / "a.dmp", SCRIPT_STACK, text=b"\0entity_set_car_lift_default\0")
    monkeypatch.setattr("leonida.nativenames.native_names",
                        lambda g: {0x55E86AF2712B36A1: "ACTIVATE_INTERIOR_ENTITY_SET"} if g else {})
    text = diagnostics._crash_dumps_text(game_dir=game)
    assert "      stack: called from GTA5_Enhanced.exe+0x1D28607" in text
    assert "native ACTIVATE_INTERIOR_ENTITY_SET (0x55E86AF2712B36A1)" in text and "entity_set_car_lift_default" in text


def test_native_names_reader(tmp_path):
    from leonida import nativenames as N

    (tmp_path / "ScriptHookVDotNet3.dll").write_bytes(b"not a PE file")
    assert N.native_names(tmp_path) == {} and N.native_names(None) == {}
    real = Path(r"D:\Games\Grand Theft Auto V Enhanced")
    if not (real / "ScriptHookVDotNet3.dll").is_file():
        pytest.skip("needs Script Hook V .NET's DLL (read only)")
    names = N.native_names(real)
    assert names[0x55E86AF2712B36A1] == "ACTIVATE_INTERIOR_ENTITY_SET"
    assert names[0x7239B21A38F536BA] == "DOES_ENTITY_EXIST" and len(names) > 5000
