# Changelog

## Unreleased

- `leonida playtest --repeat N [--pause S]`: N play tests in a row with a summary. It counts passed / failed /
  crashed / hang runs, and shows the time to story mode, the crash times and reasons, and each run's memory peaks.
  It's saved as `<state>\logs\playtest\series-<time>.txt/.json`.
- Every play test samples memory every 2 s into `<state>\logs\playtest\run-<time>.csv`: free RAM, commit charge,
  page file, the game's working set and private bytes, and GPU memory (the game's own and the whole card's).
- A crash collects the crash dumps, with the exception and the module read from each dump. It also collects
  Rockstar's own crash log (`%LOCALAPPDATA%\Rockstar Games\GTAV Enhanced\CrashLogs`), the Windows events, new
  files in `%LOCALAPPDATA%\CrashDumps`, the last lines of every mod log and the memory just before. All of it goes
  into `<state>\logs\playtest\crash-<time>\`, and `leonida report` includes its text files (never the dumps).
  Each crashed run reports the crash site (module+offset), the ASIs loaded at the time and the memory load. The
  `--repeat` summary groups the crashes by site ("3× GTA5_Enhanced.exe+0xBCC6AD").
- Crash dumps get a stack summary: the return addresses on the crashing thread's stack that land in a module
  (ScriptHookV, Script Hook V .NET, an ASI, the game). When a script called a native, it also gives the native's
  name, read from the game folder's own Script Hook V .NET; Leonida ships no list. It adds the names left on the
  stack (an entity set, a model) and the thread's name. The summary is in each crashed run, the `--repeat`
  summary and `leonida report`. A crash folder also keeps the scripts' own logs (`scripts\*.log`) from that run.
- `leonida report` adds `results/crash-dumps.txt`: the game's newest crash dumps from Rockstar's CrashLogs and
  Windows' CrashDumps, read, grouped by site, with their ASIs and the key lines of Rockstar's crash log. It covers
  crashes outside play tests too and is redacted like the rest.
- The play test never kills the game halfway through a crash dump. It waits while a dump is still growing, or
  is a fresh 0-byte file, or a crash handler (WerFault) is still running. After closing, it waits until the game,
  the launcher and the handlers have all exited, plus 10 s, so the next run doesn't find locked logs.
- `playtest` always ends with one `VERDICT:` line: `VERDICT: CRASHED GTA5_Enhanced.exe+0xBCC6AD (at 76 s)`, or
  `VERDICT: PASSED (story mode after 87 s)`. With `--repeat` there's one per run, and a last one for the series.
- A memory step before the game starts (Play, Play test, `leonida playtest`). With under 6 GB of RAM or 12 GB of
  commit free, it says "GTA may crash while loading: free memory is low" and lists the biggest memory users. Then
  it offers **Close them and play** or **Play anyway**:
  - only the apps the user ticks are closed, each like clicking its X, never forced;
  - Windows, security, the game, the stores and Leonida are never offered;
  - from the command line it prompts in a terminal and only warns in scripts (`--no-memory-check` skips it).

  The owner's tests: about 4 crashes in 19 loads with about 4.6 GB free, and 8 of 8 loads with 5.8–6.3 GB free.
  The `--repeat` summary compares the free RAM and commit before the passed and the crashed runs. It names the apps using the most memory.

## 1.0.0rc1 (2026-11-25): release candidate, not published

Not published until CodeWalker's author has answered (`docs/codewalker-permission-request.md`). What it adds over
the first real-PC runs below: `docs/RELEASE-NOTES-1.0.0.md`.

- The full Showcase pack (38 steps) is installed and play-tested on the owner's PC (GTA V Enhanced 1.0.1013.20).
  `leonida playtest --deep` checked all 24 added DLC packs in the game, and the Drive V handling.
- 17 archive mods install automatically into copies in `mods\` with the CodeWalker-based RPF helper. Entry-level
  backups make the Showcase pack about 24 GB on disk instead of about 75 GB.
- New launcher views (modpacks, browse, install), GTA V Legacy support, modpacks with add-ons and variants, your own
  mods, locked settings.
- `leonida playtest --deep`, an in-game probe: are the DLC packs loaded, is a test car's handling the modded one.
- Leonida's own log (`<state>\logs`, Debug mode), the crash dialog, `leonida report` (a debug zip with private
  details removed).
- `leonida verify` attributes Script Hook V .NET failures to the right script file.

## Before 1.0.0rc1

First run on a real Windows PC (Windows 11, GTA V Enhanced 1.0.1013.20, 32-bit Python 3.14).

- Start-Leonida.bat requires 64-bit Python 3.10+ (prefers `py -3-64`) and rebuilds a 32-bit `.venv`; PySide6 has
  no 32-bit Windows wheels, so the GUI install used to fail.
- Registry reads (store detection, prerequisites) check both the 64-bit and 32-bit views, so a 32-bit Python is no
  longer redirected to WOW6432Node only.
- 7-Zip is found through its registry key and `%ProgramW6432%` (a 32-bit Python sees `%ProgramFiles%` as x86).
- Mod installers (.bat/.exe/.msi) launch correctly from paths containing `&`.
- `leonida doctor` shows the Python version and bitness and warns when the GUI can't run.
- Downloads: `leonida/downloader.py` fetches GitHub-release and author-published direct downloads (resume, https
  only, never overwrites); `leonida get --auto`. Manifest gains per-mod `image` and `download`.
- GUI: "Choose mods" page with a preview picture per mod (fetched from the author's page, cached), alternatives side
  by side; built-in browser that captures downloads from authors' pages into the downloads folder; "Download all
  automatic" with progress and cancel; installs and dry runs run off the UI thread; Leonida update check on Manage.
- Manifest: real pages for every mod, preview images, GitHub sources for SHVDNE, Menyoo and the geckomacabre HUD;
  Project Vice and DLSS5-Swapper removed.
- Readmes, `.url` and `.lnk` files in the downloads folder are no longer reported as unrecognised mods.
- Game builds: per-mod `minGameBuild`/`maxGameBuild`/`gameBuilds`; 1.0.1013.20 is a tested build (Script Hook V,
  SHVDNE, Menyoo, DirectStorageFix, Resource Extensions, Straight To Story Mode, OpenRPF, All MP Vehicles confirmed
  in the real game).
- `leonida verify` reads the mods' own logs; `leonida playtest` starts the game, waits for story mode, verifies and
  closes it.
- Archive contents are checked (`requireMembers`/`rejectMembers`), so Legacy files can't pass as Enhanced; gta5-mods
  "All Versions" picking; Nexus downloads after sign-in; browser logins persist.
- Core is fully free (NVE moved to paid add-ons); free routes for paid mods (`freeRoute`); overlap audit (seamless
  interiors win).
- Modpack channel, mod auto-updater, Leonida self-update with force/reinstall; Windows exe build with the new logo.
- Fixed: lockfile check reported every non-selected mod as missing during `install --only`.

## 1.0.0.dev1 — 2026-11-24

- Portable launchers: Start-Leonida.bat and Leonida-CLI.bat keep the project, downloads and state in one folder.

## 1.0.0.dev0 — 2026-11-24

First development build.

- Manifest: 24 mods (14 core), 4 profiles, hotkey map; tested against GTA V Enhanced 1.0.1158.13.
- Engine: game detection (Steam, Epic, Rockstar, common paths, manual), download matching with lockfile and SHA-256,
  four install methods (copy / generic / run / guided), baseline snapshot, install log with backups,
  per-step rollback, full uninstall, online-safe switch, pre-install checks.
- CLI: `leonida` with detect, profiles, swap, get, assign, check, install, status, rollback, uninstall,
  online-safe, keys, doctor.
- GUI: PySide6 wizard (Welcome, Game, Profile, Get mods, Check, Install, Manage).
- 49 automated tests (fake game folders and archives), CI on Windows and Ubuntu.
