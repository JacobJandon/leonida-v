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

| Cold start (ms) | Before | After |
| --- | ---: | ---: |
| Python + imports | 720 | 554 |
| `leonida.gui.app` import | 94 | 111 |
| `MainWindow()` | 12092 | 1461 |
| first paint (from process start) | 13072 | 2176 |
| interactive (from process start) | 13072 | 2176 |

| Page | First visit before | First visit after | Repeat before | Repeat after |
| --- | ---: | ---: | ---: | ---: |
| Setup: Welcome | 180 | 113 | 157 | 88 |
| Setup: Game | 204 | 130 | 130 | 81 |
| Setup: Choose mods | 336 | 490¹ | 134 | 88 |
| Setup: Get mods | 881 | 401 | 116 | 77 |
| Setup: Check | 552 | 304 | 123 | 64 |
| Setup: Install | 803 | 330 | 165 | 83 |
| Setup: Manage | 549 | 230 | 161 | 100 |
| Browse / Modpacks | 852 | 410 | 183 | 130 |
| Browse / Mods | 190 | 104 | 36 | 24 |
| My modpack / Overview | 167 | 84 | 142 | 83 |
| My modpack / Mods (33 mods, pictures) | 485 | 263 | 27 | 15 |
| My modpack / Variants & settings | 356 | 151 | 21 | 14 |
| My modpack / Screenshots | 124 | 79 | 30 | 13 |
| My modpack / Files & logs | 265 | 141 | 22 | 11 |
| Manage / Installed (52 steps) | 253 | 126 | 255 | 134 |
| Manage / Play test | 43 | 13 | 18 | 13 |
| Manage / Log and updates | 165 | 32 | 13 | 7 |
| Settings | 124 | 58 | 69 | 36 |
| About & help | 116 | 45 | 77 | 35 |

¹ Choose mods was built during window start (about 8 s, most of the old cold start). It is now built when it's
first shown, with the top of the page first and each layer of mod cards in its own idle moment.

| Click (ms to the visible response) | Before | After |
| --- | ---: | ---: |
| About: What's new (dialog) | 31 | 22 |
| My modpack: More… (menu) | 2 | 2 |
| Settings: Move… (folder dialog) | 7 | 4 |
| Check: Run checks again | 268 | 74² |
| Choose: switch pack → Next: add-ons | 2014 | 597 |
| Choose: switch back → Next: add-ons | 2454 | 665 |
| Choose: same pack → Next: add-ons | 127 | 270³ |

² The checks run on a worker now; the list fills in when they finish.
³ Within the noise of a loaded PC: the earlier rebuild skipped more often in that run.

| Pictures (ms until every cached picture is on screen) | Before | After |
| --- | ---: | ---: |
| Browse / Modpacks | 1224 | 743 |
| My modpack / Mods | not measured⁴ | 970 |

⁴ The first run waited for pictures that aren't cached (offline they never come).

| Scrolling (ms per frame) | Max before | Max after | p95 before | p95 after |
| --- | ---: | ---: | ---: | ---: |
| Browse / Mods | 34.1 | 14.2 | 28.5 | 13.5 |
| My modpack / Mods | 34.3 | 11.7 | 31.2 | 11.3 |
| Choose mods (11 000 px) | 25.9 | 19.1 | 18.1 | 15.8 |
| Install | 22.4 | 13.0 | 21.8 | 10.1 |
| Manage / Installed | 15.8 | 4.6 | 9.1 | 4.3 |

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

## Still over the targets

- **First visits** to Get mods, Check, Install, Browse / Modpacks and Choose mods take 230-490 ms. That's building
  their widgets (tables, tiles, cards) the first time; repeat visits are 64-130 ms. Next: build hidden pages in idle
  time after start, or turn the long card lists into a `QListView` with a delegate.
- **Switching packs** (Next: add-ons) takes ~600 ms. About 300 ms of that is working out the locked settings of
  every installed mod for the new selection (`installed_settings`), which the switch needs to offer a rewrite; the
  rest is the new page's first layer. Next: compute the settings on a worker and show the page first.
- **Browse / Modpacks and Manage / Installed** repeat at 130 ms with the running game. `update_sidebar` and the
  bottom bar look at the game folder on every switch (the online-safe state), and with GTA running those disk reads
  are slow.
- **Cold start** is 2.2 s to the first paint, of which 0.55 s is Python and PySide6 imports. PySide6 also reads
  the source of every module it imports (≈19 ms each).

The fake-data test (`tests/test_perf_pages.py`) runs the biggest pack plus extras: 35 mods, 40 downloads, 40 install
steps, and a 1280×720 picture for every mod. It checks:
- the median repeat switch is under 100 ms, and first visits under 500 ms;
- both budgets are scaled for CI and for the machine's measured load;
- every picture is decoded (off the UI thread) by the end.
