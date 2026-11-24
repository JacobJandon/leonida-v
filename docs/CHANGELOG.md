# Changelog

## Unreleased

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
