# Launcher performance on real data

Measured 2026-11-25 on the owner's PC with the owner's real data:
- a copy of `D:\Leonida\State` (without the browser profile and the logs) as `LEONIDA_STATE_DIR`;
- the real `D:\Leonida\Downloads` (45 files) and the real game folder, both only read;
- the owner's pack: Leonida (owner's pick), 33 mods installed in 52 steps, with their cached pictures.

Nothing was installed and no game was started. Write guards refused every install, rollback, settings write and
online-safe move, and the game folder's listing was compared before and after each run.

The window ran offscreen at 1600×1000, with times taken by `QElapsedTimer`: the call plus three rounds of event
processing (layout and paint). Each repeat is the median of three visits. Bottlenecks were found with cProfile.

GTA V was running its own 10-run crash test on the same PC throughout, so expect about ±30% between runs. Script:
`real_perf.py` in the downloader session's scratch folder. The fake-data version is `tests/test_perf_pages.py`.

Targets:
- a click shows a visible response within 50 ms;
- a page switch takes under 100 ms on a repeat visit and under 200 ms on the first;
- no frame takes over ~50 ms while scrolling.

## Before / after

Three runs of the same script: **before** (2026-11-25 morning), **pass 1** (2026-11-25 evening) and **now**
(2026-11-26, pass 2: `MainWindow(defer=True)` as LeonidaV.exe starts, pages built and filled ahead).

| Cold start (ms) | Before | Pass 1 | Now |
| --- | ---: | ---: | ---: |
| Python + imports | 720 | 554 | 687 |
| `leonida.gui.app` import | 94 | 111 | 145 |
| `MainWindow()` | 12092 | 1461 | 302 |
| **first paint** (from process start) | 13072 | 2176 | 1009 |
| every page built and filled ahead (after the first paint) | – | – | 4559 |

| Page | First visit before | Pass 1 | Now | Repeat before | Pass 1 | Now |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Setup: Welcome | 180 | 113 | 167 | 157 | 88 | 96 |
| Setup: Game | 204 | 130 | 172 | 130 | 81 | 72 |
| Setup: Choose mods | 336 | 490 | 549 | 134 | 88 | 73 |
| Setup: Get mods | 881 | 401 | 205 | 116 | 77 | 73 |
| Setup: Check | 552 | 304 | 204 | 123 | 64 | 67 |
| Setup: Install | 803 | 330 | 176 | 165 | 83 | 84 |
| Setup: Manage | 549 | 230 | 103 | 161 | 100 | 84 |
| Browse / Modpacks | 852 | 410 | 142 | 183 | 130 | 111 |
| Browse / Mods | 190 | 104 | 70 | 36 | 24 | 23 |
| My modpack / Overview | 167 | 84 | 90 | 142 | 83 | 87 |
| My modpack / Mods | 485 | 263 | 42 | 27 | 15 | 16 |
| My modpack / Variants & settings | 356 | 151 | 64 | 21 | 14 | 14 |
| My modpack / Screenshots | 124 | 79 | 35 | 30 | 13 | 12 |
| My modpack / Files & logs | 265 | 141 | 26 | 22 | 11 | 13 |
| Manage / Installed | 253 | 126 | 151 | 255 | 134 | 140 |
| Manage / Play test | 43 | 13 | 17 | 18 | 13 | 16 |
| Manage / Log and updates | 165 | 32 | 30 | 13 | 7 | 8 |
| Settings | 124 | 58 | 88 | 69 | 36 | 24 |
| About & help | 116 | 45 | 107 | 77 | 35 | 26 |

Choose mods is built when it is first shown (it was built during window start: about 8 s of the old cold start); its first visit includes its first layers of mod cards.

| Click (ms) | Before | Pass 1 | Now |
| --- | ---: | ---: | ---: |
| About: What's new (dialog) | 31 | 22 | 25 |
| My modpack: More… (menu) | 2 | 2 | 2 |
| Settings: Move… (folder dialog) | 7 | 4 | 4 |
| Check: Run checks again | 268 | 74 | 42 |
| Choose: switch to core → Next: add-ons | 2014 | 597 | 593 |
| Choose: back to owner-pick → Next: add-ons | 2454 | 665 | 525 |
| Choose: same pack (owner-pick) → Next: add-ons | 127 | 270 | 336 |

The pack-switch rows time the click plus three rounds of event processing, which includes the first idle batches of mod cards. The click's visible response is less: from the click to the first paint of the new cards it is **170-300 ms** now (`switch` 25-60 ms, `rebuild` 45-100 ms; measured separately).

| Pictures (ms until every cached picture is on screen) | Before | Pass 1 | Now |
| --- | ---: | ---: | ---: |
| Browse / Modpacks | 1224 | 743 | 1015 |
| My modpack / Mods | not measured | 970 | 888 |

| Scrolling (ms per frame, max / p95) | Before | Pass 1 | Now |
| --- | ---: | ---: | ---: |
| Browse / Mods | 34.1 / 28.5 | 14.2 / 13.5 | 18.2 / 16.6 |
| My modpack / Mods | 34.3 / 31.2 | 11.7 / 11.3 | 13.3 / 12.2 |
| Choose mods | 25.9 / 18.1 | 19.1 / 15.8 | 15.0 / 11.8 |
| Install | 22.4 / 21.8 | 13.0 / 10.1 | 10.5 / 10.1 |
| Manage / Installed | 15.8 / 9.1 | 4.6 / 4.3 | 11.4 / 9.8 |

## Cold start: v1.0.0 exe vs. now

v1.0.0 (the onedir exe on the owner's PC) logged "window starting" 20:26:31.2, "GPU detected" 20:26:33.2 and the
first page 20:26:46.0: about **15 s** from window start to a page. That build predates the fixes below. The 13 s
between the GPU line and the first page were the cached pictures, decoded synchronously while the Choose page
built about 60 mod cards at window start. The 2 s before it were PowerShell's GPU query.

The same start from source, on the real State copy (three runs, same loaded PC, ms from process start):

| | v1.0.0 exe | Now |
| --- | ---: | ---: |
| Python + PySide6 + Leonida imports | (in the exe) | 550-715 |
| `Session()` (config, install log) | | 5-8 |
| `MainWindow()` | ~14 800 | 1 200-1 400 |
| show → first paint of the window frame | | 150-280 |
| **first paint** | **~15 000** | **1 900-2 400** |
| the modpack page filled in (after the first paint) | | +180-280 |

What changed for the start, on top of the fixes below:
- the window paints its frame first: `MainWindow.after_first_paint()` runs the page fills after the sidebar's first
  paint (the modpack page shows its banner and fills right after);
- the sidebar no longer opens the start page twice (marking the current row re-ran `show_home`);
- About & help builds its keys card when it's first opened, and checks for the report module without importing it;
- the GPU list comes from `<state>/pc-gpus.json` and is checked again on a worker.

`MainWindow()` is now about 0.6 s of Qt assembling eleven pages: layout insertions, adding pages to the stack, the
central widget. That's another 0.37 s of page constructors (Choose 99 ms, bottom bar 61, About 46, Install 45,
Settings 40) plus 0.2 s of module imports. Next step to a ~1 s frame: build the hidden pages after the first paint.
This is a larger change, because many callers expect every page to exist right after the window is built.

## What was slow, and the fix

1. **Pictures decoded on the UI thread.** The Choose page and the modpack cards decoded every cached picture
   synchronously: 3.3 s for 57 pictures at window start. All pictures now go through `Pictures.show()`, which
   decodes and shrinks on a pool thread. The shrunk copies are kept on disk (`images/small/`), so a later start
   decodes 960-px JPEGs instead of the originals.
2. **PowerShell at window start.** `detect_gpus()` ran `Get-CimInstance` (2.4 s) while the window was built. The
   cards are now remembered in `<state>/pc-gpus.json` and checked again on a worker after start. Only the very first
   start asks synchronously.
3. **Choose mods built at start.** About 60 mod cards and 22 add-on cards were built before the first paint. They
   are now built on first use. On screen, the page shows the top at once and adds one layer of cards per idle
   moment. Its rebuild is skipped when nothing it shows has changed. The old page is hidden and deleted later
   instead of taken out of the scroll area, which stalled the click.
4. **Repeat work per switch.** `Session.mods()` (every page and the bottom bar ask for it) and
   `Session.settings_for()` (68 calls for the keys card and the locked settings) are cached per selection.
5. **The running game's logs.** GTA V writes its logs all the time, so Install and Manage rebuilt every visit. The
   logs are no longer part of their rebuild key: only the "loaded / not seen" pills follow the logs, read on a
   worker.
6. **Picture lookups scanned the cache folder.** `ImageLoader.cached()` globbed the folder for each picture. It now
   uses a listing read once, and again only when the folder's time changes.
7. **Check: Run checks again** ran every check on the UI thread. It now runs on a worker.
8. **Manage / Installed** builds the first 8 cards at once and the rest in idle batches. Online-safe, Undo, Uninstall
   and the problem report run on workers.

## Pass 2 (2026-11-26): the parked TODO

Done:
1. **Hidden pages built after the first paint.** `MainWindow(defer=True)` (what `main()` uses) builds the frame and
   the start page. The other pages are placeholders in the stack (`_Placeholder`, `_Pages`), built when first
   opened, or one per idle moment after the first paint (`_build_rest`). After that, Get mods, Check, Install,
   Manage, Browse and the modpack page's tabs are filled while hidden (`_prefill_tasks`, 50 ms apart so clicks get
   through). Timers and caches only `peek()`: they never build a page. `MainWindow()` 1.5 s → 0.3 s; first paint
   ~1.0 s from process start.
2. **Pack switch.** The "write the new variant's settings?" check runs on a worker (`ChoosePage._offer_settings`).
   The locked settings of all mods are worked out from one shared context per state (`Session._settings_ctx`), not
   per mod (68 file reads). The old page of cards is deleted 2 s later; card batches have a 15 ms gap. Click → new
   cards painted: 170-300 ms.
3. **First visits** come from the fill-ahead: Get 205, Check 204, Install 176, Manage 103, Browse 142 ms.
4. **The online-safe state** is looked up at most every 2 s on page switches (`update_sidebar(force=False)`);
   actions that change it force a fresh look.
5. **Session stamp:** the game folder's own time (the running game touches it all the time) and config fields no
   page shows (the What's-new note records the version at start) no longer make every page rebuild.

Left (exact next steps):
- **Choose mods' first visit** is ~550 ms with its first card layers. Fill it ahead too (its `rebuild` is
  progressive only when visible), or make its card grid a `QListView` + delegate (`leonida/gui/chooser.py`).
- **Manage / Installed and Browse / Modpacks repeat** at 110-140 ms while GTA runs. Manage re-reads the settings
  drift (`Session.settings_drift`, one stat per locked file) and the game logs' stamp on every visit; Browse's key
  scans the downloads folder. Cache both per second, like the online-safe state.
- **Rebuild the exe** so the owner's LeonidaV.exe gets all of this (exe-build).

## Tests

The deferred start has its own test (`tests/test_deferred_pages.py`): only the start page is built, a page is
built when it's opened, timers never build one, and every page is built and filled after the first paint.

The fake-data test (`tests/test_perf_pages.py`) runs the biggest pack plus extras: 35 mods, 40 downloads, 40 install
steps, and a 1280×720 picture for every mod. It checks:
- the median repeat switch is under 100 ms, and first visits under 500 ms;
- both budgets are scaled for CI and for the machine's measured load;
- every picture is decoded (off the UI thread) by the end.
