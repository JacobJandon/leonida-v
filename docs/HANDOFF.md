# Handoff — where Leonida V stands (2026-11-25, after the night shift)

## Night of 2026-11-24/25 (owner asleep, 3 agent sessions + coordinator)
Pushed to `main`: 8412893, 84d522b, 69ecedb, 9576d75, cfc074e, 56c0d76, b074373. CI (GitHub Actions) green on
Ubuntu + Windows, Python 3.11 + 3.13. ~990 tests, ~97% coverage. Landed: GTA V **Legacy edition** support (detection,
`mods-legacy.json`, no mixing), **modpacks** Core / Plus / Showcase with add-on categories and variants, **your own
mods**, **locked settings** (values from `docs/SETTINGS.md`, Performance / Balanced / Ultra), versions for **every
Enhanced build** (`build/build_matrix.py`; on 1.0.1013.20 all Core mods resolve, Drive V 7.4), **free routes** for paid
mods, the **new design** wired into every page, **auto-download clicks** (gta5-mods, Nexus after sign-in), Start menu /
desktop **shortcuts**, an end-to-end **release + self-update dry run**, **acceptance tests** (edition × pack, uninstall ==
baseline) and `docs/GTA6-EXPERIENCE.md` (GTA VI feature gap analysis). Nothing touched the real game overnight.
**Tell the owner:** Nexus's terms restrict automated downloading even via its own Slow download button; Leonida does it
only after the owner signs in, as asked, but the account risk is theirs (offer to make it opt-in).

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
1. The 6 guided Core installs (owner + Leonida's guided steps, CodeWalker), each followed by `leonida playtest`.
   Then the Showcase extras (downloaded in `D:\Leonida\Downloads`; new ones from GTA6-EXPERIENCE.md still to fetch).
2. Owner to try the redesigned app (`Start-Leonida.bat` → shortcuts get created) and give UI/UX feedback.
3. First GitHub release (`release/modpack.json` from this PC), then a real self-update round-trip.
4. F6 CodeWalker automation stays deferred (licence: ask dexyfex first).
5. Known limit: files > 64 MB changed by a mod's own installer are not backed up; rollback warns.
