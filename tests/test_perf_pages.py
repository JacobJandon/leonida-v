"""Page switches stay fast with a realistic state: the biggest pack (35+ mods), 40 downloads, 40 install steps.

Every page is visited once (its first build), then three more rounds are timed. A page fails when the MEDIAN of
its three repeat switches is over the budget (``LEONIDA_PERF_BUDGET_MS``, 100 ms by default), measured again once
before failing (a busy PC has spikes). First visits (the cold build) get a looser budget, five times that, and a
slow one is measured again in a fresh window (cold again) before failing. With
``CI`` set every budget is three times as large (shared runners). On a loaded PC the budgets grow with the machine:
Settings, About and Welcome are static pages (``REFERENCE``: their switch on an idle PC), so how much slower they
are scales every budget up (never down). The table is printed either way and is in the
failure message. A page that rebuilds everything on each visit, or hashes downloads on the UI thread, fails here.
"""
from __future__ import annotations

import os
import time
from fnmatch import fnmatch

import pytest

pytest.importorskip("PySide6")

from conftest import make_zip  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from test_gui_pages import BUILD, dialogs, qapp, wait_idle  # noqa: E402,F401  (fixtures)

import leonida.gui.app as A  # noqa: E402
from leonida.log import Action, now  # noqa: E402
from leonida.session import Session  # noqa: E402

CI_FACTOR = 3.0 if os.environ.get("CI") else 1.0
BUDGET_MS = float(os.environ.get("LEONIDA_PERF_BUDGET_MS", "100")) * CI_FACTOR
FIRST_MS = BUDGET_MS * 5
# Static pages and what a switch to them takes on an idle PC: how much slower they are now is the machine's load
# (a busy PC, or a long test run whose earlier windows still take their share of every event loop turn).
REFERENCE = {"settings": 30.0, "about": 30.0, "step 0: Welcome": 60.0}


def _name_for(pattern: str) -> str:
    return pattern.replace("*", "1.0").replace("?", "x")


def _member_for(pattern: str) -> str:
    out = pattern.replace("**", "x").replace("*", "x").replace("?", "x")
    return out if not out.endswith("/") else out + "file.txt"


def fake_pictures(s: Session, mods) -> int:
    """A real-size picture (1280x720 JPEG, like the authors' screenshots) in the picture cache for every mod and
    pack that has one: the pages then decode, shrink and show them as they do on a real PC."""
    import hashlib

    from PySide6.QtGui import QColor, QImage

    folder = s.state / "images"
    folder.mkdir(parents=True, exist_ok=True)
    urls = {m.image for m in mods if getattr(m, "image", None)}
    urls |= {p.picture for p in s.base_manifest.packs.values() if getattr(p, "picture", None)}
    for i, url in enumerate(sorted(urls)):
        img = QImage(1280, 720, QImage.Format.Format_RGB32)
        img.fill(QColor.fromHsv(i * 37 % 360, 160, 200))
        img.save(str(folder / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".jpg")), "JPG", 85)
    return len(urls)


def fake_state(s: Session, downloads, game) -> list:
    """The pack with the most mods, chosen; 40 downloads that match mods (real zips, with the members each mod's
    requireMembers asks for); 40 finished install steps with 5 files each; a real-size picture for every mod."""
    base = s.base_manifest
    best = max(base.packs, key=lambda p: len(base.pack_mod_ids(p)))
    s.choose_pack(best)
    for extra in [m.id for m in base.mods.values() if m.tier != "custom" and not m.slot]:
        if len(s.mods()) >= 35:
            break
        if extra not in s.selection_ids():
            s.config.add.append(extra)
    mods = s.mods()
    others = [m for m in base.mods.values() if m not in mods and m.tier != "custom"]
    made = 0
    for m in [*mods, *others]:
        pats = [p for p in (getattr(m, "archive", None) or []) if p.lower().endswith(".zip")]
        if not pats or made >= 40:
            continue
        members = {_member_for(p): "x" for p in (getattr(m, "require_members", None) or [])} or {"readme.txt": "x"}
        name = _name_for(pats[0])
        if (downloads / name).exists():
            name = f"{made}-{name}"
        if any(fnmatch(name.lower(), r.lower()) for r in (getattr(m, "reject_members", None) or [])):
            continue
        make_zip(downloads / name, members)
        made += 1
    while made < 40:  # pad with files no mod claims (they show as "not recognised")
        make_zip(downloads / f"random-download-{made}.zip", {"a.txt": "x"})
        made += 1
    for i in range(40):
        st = s.log.new_step(mods[i % len(mods)].id, "copy")
        for j in range(5):
            rel = f"scripts/fake{i}_{j}.dll"
            (game / rel).parent.mkdir(parents=True, exist_ok=True)
            (game / rel).write_bytes(b"x")
            st.actions.append(Action("add", rel))
        st.status, st.finished = "done", now()
    s.log.save()
    fake_pictures(s, list(base.mods.values()))
    return mods


def _switches(w):
    out = [("browse: packs", lambda: (w.show_home("browse"), w.browse.tabs.setCurrentIndex(0))),
           ("browse: mods", lambda: w.browse.tabs.setCurrentIndex(1)),
           ("pack: overview", lambda: (w.show_home("pack"), w.pack_page.tabs.setCurrentIndex(0)))]
    out += [(f"pack: tab {i}", lambda i=i: w.pack_page.tabs.setCurrentIndex(i)) for i in range(1, 5)]
    out += [(f"step {i}: {n}", lambda i=i: w.go(i)) for i, n in enumerate(A.PAGES)]
    out += [("settings", lambda: w.show_home("settings")), ("about", lambda: w.show_home("about"))]
    return out


def _timed(fn) -> float:
    t = time.perf_counter()
    fn()
    for _ in range(3):
        QApplication.processEvents()
    ms = (time.perf_counter() - t) * 1000
    _idle()
    return ms


def _idle(seconds: float = 0.15) -> None:
    """The moment between two clicks: idle work (rows filled in batches, pictures) runs here, not in the switch."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.003)


def _median(ts: list[float]) -> float:
    return sorted(ts)[len(ts) // 2]


def _rounds(steps, n: int = 3) -> dict[str, list[float]]:
    times: dict[str, list[float]] = {}
    for _ in range(n):
        for name, fn in steps:
            times.setdefault(name, []).append(_timed(fn))
    return times


def _window(session):
    w = A.MainWindow(session)
    w.resize(1600, 1000)
    w.show()
    _idle(1.5)                                # a person takes a moment before the first click: the idle warm-up
    return w                                  # (MainWindow._warm_tasks) runs then


def _close(w) -> None:
    wait_idle(w, *w.pages)
    w.close()
    w.deleteLater()


def test_page_switches_stay_under_the_budget(qapp, tmp_path, game, downloads):  # noqa: F811
    def session():
        return Session(state=tmp_path / "perf-state", download_dir=str(downloads), game_dir=str(game),
                       game_build=BUILD)

    s = session()
    mods = fake_state(s, downloads, game)
    assert len(mods) >= 35 and len(list(downloads.iterdir())) == 40 and len(s.log.steps) == 40
    assert len(list((s.state / "images").glob("*.jpg"))) >= 33          # real-size pictures, decoded by the pages
    w = _window(s)
    try:
        steps = _switches(w)
        first = {name: _timed(fn) for name, fn in steps}
        wait_idle(w, *w.pages)               # the lock file hashed on its worker thread
        times = _rounds(steps)
        load = max(1.0, *(_median(times[n]) / base for n, base in REFERENCE.items()))
        budget, first_budget = BUDGET_MS * load, FIRST_MS * load
        again = [(n, fn) for n, fn in steps if _median(times[n]) > budget]
        if again:                            # a busy PC: measure the slow ones once more, keep the better median
            _idle(1.0)
            for n, ts in _rounds(again).items():
                if _median(ts) < _median(times[n]):
                    times[n] = ts
        report = "\n".join(f"  {n:20} first {first[n]:6.0f}  then " + " ".join(f"{t:5.0f}" for t in ts)
                           + f"  (median {_median(ts):.0f})" for n, ts in times.items())
        report = (f"page switches (ms): median of the repeats <= {budget:.0f}, first visit <= {first_budget:.0f}"
                  f" (machine load x{load:.1f}{', CI x3' if CI_FACTOR > 1 else ''})\n{report}")
        print(report)
        slow = {n: round(_median(ts)) for n, ts in times.items() if _median(ts) > budget}
        assert not slow, f"repeat switches over budget: {slow}\n{report}"
        if any(t > first_budget for t in first.values()):   # one cold sample each: once more, in a fresh window
            w2 = _window(session())
            try:
                for n, fn in _switches(w2):
                    first[n] = min(first[n], _timed(fn))
            finally:
                _close(w2)
            report += "\n  first visits measured again in a fresh window: " + ", ".join(
                f"{n} {t:.0f}" for n, t in first.items())
        slow_first = {n: round(t) for n, t in first.items() if t > first_budget}
        assert not slow_first, f"first visits over budget: {slow_first}\n{report}"
        page = w.pages[6]
        assert not page.rows_pending()       # the Installed list was filled in while idle
        assert not w.pictures.waiting        # every picture was decoded (off the UI thread) by the end
    finally:
        _close(w)
