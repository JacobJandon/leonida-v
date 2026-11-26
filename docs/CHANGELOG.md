# Changelog

## 1.0.2 (unreleased)

- **Leonida remembers.** On 26 Nov the installed window started on an empty State in `%LOCALAPPDATA%\LeonidaV`
  instead of the setup's data folder (D:\Leonida): it ran the first-run setup again, downloaded 7 mods again, and
  served the in-game menu from a folder the menu doesn't read ("Open Leonida to apply changes" while it was open).
  Now:
  - the installed exe never starts over: if its registry entry can't be read, it uses the data folder it used last;
    every start logs which State it uses and why;
  - the setup remembers the data folder across an uninstall that keeps it, and finds an existing one
    (`<drive>:\<folder>\State`, e.g. D:\Leonida after a Windows reinstall), silently in `/S` too;
  - the menu's bridge starts first thing with the window (nothing before it can stop it), and the frozen app's
    self-check proves it writes the menu's data into its own State.
- **The game lost its mods?** When Steam / Epic / Rockstar repaired or reinstalled GTA V, Leonida says so and
  **Repair** (or `leonida repair`) installs every lost mod again from Downloads, nothing downloaded, then writes the
  locked settings again. Uninstalling afterwards still gives the pre-install snapshot back.
- **In-game menu:** wrapped notes showed only their first line. GTA draws only the first 90-letter text part, so the
  measurement saw a 126-letter note as fitting; no menu line is longer than one part now.

- **Zero-touch: no hand steps, every mod proven on** (plan F8, `docs/ZERO-TOUCH.md`). Every mod has `verify` proofs
  in mods.json (`in: files` from the game folder and its logs, `in: game` with public natives), `inGameSetup`
  for what used to be a hand step, and `manual.why` where one must stay. The base of every pack needs no hand step
  on 1.0.1013.20.
- **The Leonida menu does the in-game steps** (`docs/LEONIDA-MENU.md`, "In-game setup"). Enable All Interiors no
  longer asks you to press Insert: it loads the online maps at the start, and if its log doesn't say *MP MAPS
  LOADED* within a minute, the menu reloads the scripts once and checks again. The GTA VI HUD's English-only check
  shows a notification when the game's language isn't English. What ran is recorded, so nothing repeats; *Tools >
  Run the in-game setup again*.
- **"On and checked in game".** `leonida playtest --deep` checks every installed mod in game through the menu (DLC
  packs, IPLs, the mods' own logs and files, read-only natives) plus Leonida's file proofs; the Manage page shows
  each mod as *on and checked in game* or *not confirmed in game* with what failed; `leonida menu status` lists it.
  A script reload during the play test no longer cuts the in-game probe short.
- **Ready-made setups**: pack + variant + add-ons + game settings in one click (`leonida setup list | choose |
  export | import`).
- **Faster first window**: pages are built when first needed or in idle moments after the first paint.
- **Paid mods say "Paid by creator"**: buy it on the creator's page to enable it.
- **CLI**: never crashes on characters the console can't print (1.0.0's piped `self-update` did).

## 1.0.1 (2026-11-25)

- **Faster launcher.** The window shows in about 2 s instead of about 15 s: the GPU query and the mod pictures no
  longer run on the window's thread. Pack switch about 0.6 s instead of 2–2.5 s, repeat page visits 64–134 ms,
  smoother scrolling (`docs/PERF.md`, before/after table).
- **GTA's own settings per configuration.** `settings.xml` is a locked-settings target with backup, rollback, drift
  and unlock; values come from the pack, the variant and the PC (RAM, video memory, GPU features), each with its
  reason (`leonida settings show`). On 16 GB / 8 GB VRAM: borderless window (the GTA VI HUD's minimap needs it), High
  textures, Very High grass, 80% population and variety, no HD streaming while flying.
- **One job, one mod.** Every mod has a `features` list; `check` refuses two mods doing the same job unless the
  manifest records how they coexist (`docs/CONFLICTS.md`, "Features").
- **Paid mods: buy and play.** The authors' own buy pages and prices (`leonida paid list`); your own download is
  recognised, scanned and installed, and a wrong or re-uploaded package is refused (`docs/PAID-MODS.md`). Leonida
  never touches Patreon or shops itself.
- **Minimap:** Enable All Interiors' hidden online-property blips are kept off the GTA VI HUD's minimap (they drew
  as "IR"/cursor icons).
- **Contact us and contribute on GitHub.** Issue forms (bug, crash, mod request, feature), a pull request checklist,
  `CONTRIBUTING.md` (one setup script: `build/dev_setup.ps1`), `docs/ADDING-MODS.md`, a Code of Conduct, `SECURITY.md`
  and `SUPPORT.md`. *About & help*: **Report a problem…** now opens the bug form with your version, edition, build,
  pack and system info filled in (you attach the zip), plus **Ask a question** (Discussions) and **Contribute**.
- **The Leonida menu, in game** (`docs/LEONIDA-MENU.md`): our own Script Hook V .NET script, in every pack.
  - F5 or the phone (iFruitAddon2: call "Leonida") opens it. It has pages for Status, Mods (their locked settings,
    editable within the manifest's new `choices`, plus unlock), Pack & variant, GTA's game settings, Keys, Help
    and Tools.
  - It never edits files: it sends Leonida requests. Leonida applies them through the installer (logged,
    undoable), at once when that's safe while playing, else after the game closes. The answers show in the menu.
  - `leonida menu serve | apply | status`; Leonida's window answers by itself.
  - `playtest --deep` runs its self-test: every page, plus a request to Leonida and back.
  - Food Delivery's settings-reload key moves from F5 to Num 9.

## 1.0.0 (2026-11-25): the first public release

- **`Leonida-V-Setup-<version>.exe`**: a per-user installer with no administrator rights. It's our own small
  PyInstaller setup with Windows' own dialogs; no installer tool is needed to build it.
  - The program goes into `%LOCALAPPDATA%\Programs\Leonida V`. The data (State + Downloads) goes into a folder you
    pick, default `%LOCALAPPDATA%\Leonida V`; it's recorded in HKCU, so self-updates never lose it.
  - It makes Start menu and desktop shortcuts and an Apps & features entry. The uninstaller asks before touching
    State or Downloads, and never touches the game; the setup refuses any folder inside a game folder.
  - Silent mode for winget and tests: `/S`. The portable zip and kit stay.
- Self-update works for the installed exe too: the new folder is swapped in after the app exits, and Apps &
  features shows the new version. `build/e2e_setup.py` proves it end to end with two real builds and a fake GitHub:
  install N, refuse a corrupt N+1, then update to the real N+1, restart, keep the data, uninstall.
- CodeWalker isn't in any release. `leonida tools codewalker` fetches dexyfex's source at the pinned commit from his
  GitHub at first use, records and shows its SHA-256, and builds the RPF helper on the user's PC with Microsoft's
  .NET SDK. dexyfex publishes no binary releases, and the last public binary predates GTA V Enhanced. The release
  build refuses any CodeWalker file.
- Release job: setup + portable zip + source zip + modpack.json + SHA256SUMS, plus a setup smoke test.
  `build/release_dryrun.py` runs the same steps locally without publishing.
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
