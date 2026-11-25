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
- CodeWalker automation (F6) is **done and live** (2026-11-25, owner's go):
  - Every archive-editing mod uses install method `rpf`: 17 mods in mods.json, all applied by Leonida's RPF helper
    (`build/codewalker/bin/LeonidaRpf.exe`, built locally from dexyfex's CodeWalker.Core source).
  - Edits go only into copies in `mods\`, with **entry-level backups**: a step that edits an existing `mods\` copy
    backs up only the entries it changes, and rollback restores them, verified by entry hash.
  - The Showcase pack needs about 24.4 GB on 1.0.1013.20, instead of about 75 GB with whole-archive backups.
  - NVE overrides stay guided.
  - Details and the 17-mod real-file e2e (143 checks passed): `docs/CODEWALKER.md`.

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
**Leonida (owner's pick), variant ram16** (chosen 2026-11-25 afternoon): only mods from the owner's own sources
(`docs/OWNER-SOURCES.md`) plus the tools they need; clashes settled in `docs/CONFLICTS.md`. 33 mods. Left on the way:
VisualV (full-screen grid lines on 1013.20, owner-confirmed), All MP Vehicles, Immersive Combat, Map Fixes, Bugstar
Fixes, FH6 Roads, iOS 26 icons (not from the owner's sources). Added: Open World Interiors, Traffic V FEAR, QoL
Vehicle Fixes (DLC pack), Better Fist Fighting, Immersive weapon sounds (all automatic now).
`leonida playtest --repeat 10` (Firefox + Discord closed): **9 passed, 1 crash** (GTA5_Enhanced.exe+0x1516B9, right
after story mode); `--deep`: every DLC pack loaded, Drive V handling active.

**Load crash findings:** two sites. 0xBCC6AD (null+0x18) went away once free RAM was ~6 GB before start; 0x1516B9
(wild read) still happens about 1 in 10 (also with the Vi ASIs off). The game peaks at ~9.5 GB private with only
~1 GB RAM free on this 16 GB PC, so Play now warns below 6 GB free and offers to close apps the user ticks. The page
file is already system managed (~16 GB cap; C: is small). Dumps are in
`%LOCALAPPDATA%\Rockstar Games\GTAV Enhanced\CrashLogs`; stack analysis of 0x1516B9 is the open item.

## Status
| Area | Status |
|---|---|
| Engine + CLI | done: game-build ranges, whenSelected/whenMissing, freeRoute, requireMembers/rejectMembers, pick hints, modpack + mod updates, self-update (check/force/reinstall), verify, playtest |
| GUI | functional: picture chooser, built-in browser + capture, download all, background installs, log check after each step, mod/Leonida updates, logo; "Download everything" (auto sign-in flow) in progress |
| Tests | ~780 tests, ~98% coverage, CI gate 90% (Windows); shutdown segfault fixed |
| Exe | `build/build_exe.py` -> `dist/LeonidaV` (321 MB, icon, self-test); release job (exe zip, source zip, modpack.json, SHA256SUMS) written, never run on GitHub |
| Design | `docs/DESIGN.md` + `leonida/gui/theme.py` + fonts done; components/page mocks in progress; not wired in yet |

## Open items, in priority order
1. The remaining 1-in-10 load crash at GTA5_Enhanced.exe+0x1516B9: stack analysis of the dumps, then an A/B of
   the suspect (biggest map mod, a pool limit, streaming memory) with `leonida playtest --repeat 10`.
2. Owner to try the redesigned app (`Start-Leonida.bat` → shortcuts get created) and give UI/UX feedback.
3. First GitHub release (`release/modpack.json` from this PC), then a real self-update round-trip.
4. F6 CodeWalker automation: **done** (see Decisions). Before a public release, the owner asks dexyfex for
   permission: the draft message, where to send it and what to do with each answer are in
   `docs/codewalker-permission-request.md`. Credits are in `docs/CREDITS.md`, the README and the release notes. The
   app has no About / credits screen yet: add one (CodeWalker + link) in the UI redo. Until dexyfex answers, the
   helper stays a local build, out of public releases.
5. Known limit: files > 64 MB changed by a mod's own installer are not backed up; rollback warns.
