# Handoff — where Leonida V stands (2026-11-25)

Read this first when continuing in Claude Code. Rules and commands: `CLAUDE.md`. Roadmap, Future plan and Far
future plan: `docs/PLAN.md`. Owner's guide: `docs/GUIDE.md`. Design system: `docs/DESIGN.md`. CodeWalker research:
`docs/CODEWALKER.md`. Settings knowledge base (in progress): `docs/SETTINGS.md`.

## Decisions already made
- Name **Leonida V**, repo `JacobJandon/leonida-v`. Logo: **02 / Sunset Emblem** (`assets/`, `leonida/gui/assets/`,
  regenerate with `python assets/make_icons.py`).
- Stack: Python 3.10+ stdlib engine + CLI, PySide6 GUI (QtWebEngine built-in browser), PyInstaller one-folder exe.
- **Story mode only.** GTA Online is never modded; modded multiplayer only via mod-friendly platforms (far future).
- **Core is fully free** (NVE turned out to be Patreon Gold-tier only and is a paid add-on now). One free Nexus
  account is enough for Core.
- Downloads come only from each author's own source: GitHub releases / direct links automatically, otherwise the
  author's page in Leonida's browser (the app follows the site's own Download buttons, countdowns and "Slow download";
  it never types passwords and never touches paid/Patreon gates). Never leaked or re-uploaded copies.
- Always prefer the better, newer, working mod (e.g. seamless MLO interiors over teleport-style ones).
- Work order: everything working and verified first, then the UI/UX design pass.
- CodeWalker automation (F6) is **deferred by the owner**; the 6 mods that need it are guided installs for now.

## The owner's PC
- Windows 11, GTX 1070, .NET 4.8 + VC++ x64 ok, 64-bit Python 3.13.17 (user install, `py -3-64`), 7-Zip 26.06, Git.
- GTA V Enhanced at `D:\Games\Grand Theft Auto V Enhanced`, exe **1.0.1013.20** (can't be updated). Script Hook V
  treats it as 1013.17 (`VER_EN_1_0_1013_17`), so current SHV 3889.0 works. Started via `PlayGTAV.exe` (desktop
  shortcut); `GTA5_Enhanced.exe` directly exits with 4919. The "Run as administrator" compat flag on PlayGTAV.exe was
  removed (backup `D:\Leonida\State\backup-PlayGTAV-runasadmin.reg`) so Leonida can start/close the game.
  `version.dll` in the game root is Social Club's (Take-Two), not a mod.
- Kit `D:\Leonida`: `Start-Leonida.bat` (keep identical to the repo copy), `leonida-v\` git clone, `.venv\`,
  `Downloads\` (all free Core + extras; `_wrong-edition\` holds 7 Legacy files kept for reference), `State\`
  (config, install log, baseline, lockfile, image cache, browser profile with the owner's Nexus login).

## Installed in the real game (logged steps, all undoable)
Script Hook V, Script Hook V .NET Enhanced 1.1.0.6, Menyoo 2.4.4, DirectStorageFix, Resource Extensions 2.5,
Straight To Story Mode, OpenRPF, All MP Vehicles in SP. `leonida playtest` PASSED with all 8 OK (story mode in
~104-132 s). Not installed yet (guided, need CodeWalker): Map Fixes, Bugstar Fixes, Drive V 7.5, NextGen Euphoria,
GTA VI Combat Camera, GTA VI-Inspired HUD.

## Status
| Area | Status |
|---|---|
| Engine + CLI | done: game-build ranges, whenSelected/whenMissing, freeRoute, requireMembers/rejectMembers, pick hints, modpack + mod updates, self-update (check/force/reinstall), verify, playtest |
| GUI | functional: picture chooser, built-in browser + capture, download all, background installs, log check after each step, mod/Leonida updates, logo; "Download everything" (auto sign-in flow) in progress |
| Tests | ~780 tests, ~98% coverage, CI gate 90% (Windows); shutdown segfault fixed |
| Exe | `build/build_exe.py` -> `dist/LeonidaV` (321 MB, icon, self-test); release job (exe zip, source zip, modpack.json, SHA256SUMS) written, never run on GitHub |
| Design | `docs/DESIGN.md` + `leonida/gui/theme.py` + fonts done; components/page mocks in progress; not wired in yet |

## Open items, in priority order
1. The 6 guided Core installs (owner + Leonida's guided steps), each followed by `leonida playtest`.
2. Finish "Download everything" in the GUI; then wire in the design system and redesigned pages.
3. First commit/push, first CI run on GitHub, first release (`release/modpack.json` from this PC).
4. F5 locked settings (knowledge base first), F4 modpacks/launcher, F1 free routes for paid mods.
5. Known limit: files > 64 MB changed by a mod's own installer are not backed up; rollback warns.
