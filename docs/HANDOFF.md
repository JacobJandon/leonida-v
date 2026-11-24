# Handoff — where Leonida V stands (2026-11-24)

Read this first when continuing in Claude Code. Rules and commands: `CLAUDE.md`. Roadmap and real-PC checklist: `docs/PLAN.md`.

## Decisions already made
- Name: **Leonida V**. Repo: `JacobJandon/leonida-v` (private for now).
- Stack: Python 3.10+ stdlib engine + CLI, PySide6 GUI, PyInstaller exe later.
- Default profile: **Core**. Max (RTX 50) profile only when an RTX 50 GPU is detected.
- Store detection: Steam, Epic, Rockstar, common paths, manual.
- The kit never re-hosts mods; it links to each author's page and matches the user's downloads.

## The owner's PC
- Windows, machine `desktop-t4a67fd`, user folder `C:\Users\misho`.
- GTA V Enhanced: `D:\Games\Grand Theft Auto V Enhanced` (`GTA5_Enhanced.exe`, not a Steam library folder).
- Portable kit folder: `D:\Leonida`
  - `Start-Leonida.bat` (GUI) / `Leonida-CLI.bat` (command line)
  - `leonida-v\` = the project (zip unpacked there, or better: a git clone of this repo)
  - `Downloads\` = mod downloads, `State\` = config, install log, backups, `.venv\` = Python env
  - `State\config.json` is pre-set with the game folder and the Core profile.

## Status
| Phase | Status |
|---|---|
| 0 Plan | done |
| 1 Manifest | draft done; links still need verifying (below) |
| 2 Engine + CLI | done, 49 tests pass on Linux (fake game folders) |
| 3 GUI | first version done, offscreen smoke-tested |
| 4 Real test on the PC | **next** |
| 5 Release 1.0 (exe) | build script + manual CI job exist, never run |

## Open items, in priority order
1. **Run on real Windows.** Nothing Windows-specific has run yet: `Start-Leonida.bat`, `winreg` store detection,
   `exe_version` (ctypes), GPU via PowerShell, prerequisite registry checks, `os.startfile`, launching `.bat`
   installers, the GUI on Windows. Run `leonida doctor`, `leonida detect`, `leonida check`, fix what breaks.
2. **Check the game build.** `testedGameBuild` in mods.json is `1.0.1158.13`. Compare with the real exe version
   (`leonida detect` prints it).
3. **Verify mod links (phase 1 gate).** These still use a DuckDuckGo search link instead of the real page:
   openrpf, bugstarfixes, allmpvehicles, drivevnve, menyoo, straighttostory, immersivecombat,
   enableallinteriors, hud-fbicat, hud-geckomacabre, projectvice. Replace with the real page URL in mods.json.
4. **Archive name patterns are guesses.** After real downloads, check `leonida get` recognises each file;
   fix `archive` patterns in mods.json (and add a test in `tests/test_matcher_archive_detect.py`).
5. **Hotkeys are assumptions.** Menyoo on F8 and the HUD wake key need checking against the real mods.
6. **GUI runs installs on the UI thread.** Move `Installer.install` to a `QThread` so big archives don't freeze it.
7. **CI**: first GitHub Actions run (Windows + Ubuntu) has not been checked.
8. **Known limit**: files > 64 MB changed by a mod's own installer are not backed up; rollback warns.

## Links
- Plan doc: https://claude.ai/artifact/BGPindmjSYZ1YCrq9fTnPd
- Stable mod guide: https://claude.ai/artifact/EYNdb89Pb5wJ5k5DW9YQQ9
