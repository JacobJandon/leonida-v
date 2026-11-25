# Handoff — where Leonida V stands (2026-11-25, evening: stopped and saved by the owner's request)

## RESUME HERE (saved 2026-11-25 evening)
**Released:** v1.0.0 (setup + portable zip + source + modpack.json + SHA256SUMS, no CodeWalker files) and v1.0.1
(this commit: faster launcher, in-game menu, GTA settings per PC, one job per mod, paid buy-and-play, GitHub contact
files). The owner's PC runs the **installed** exe (`%LOCALAPPDATA%\Programs\Leonida V`, data `D:\Leonida`) and the
**owner's pick, ram16** pack in the real game (34 mods incl. LeonidaMenu; GTA `settings.xml` locked, backup kept).
15/15 play tests passed after the load-crash fixes; the in-game menu self-test passed; real menu screenshots are in
`D:\Leonida\Screenshots\in-game\`. Releases are pre-approved by the owner (no asking); GitHub API calls go through
the public REST API (no `gh` on this PC).

**Next steps, in order:**
1. If the owner's installed Leonida hasn't updated itself to 1.0.1 yet: Manage → Check for updates (or
   `"%LOCALAPPDATA%\Programs\Leonida V\leonida.exe" self-update`), then confirm the window opens in ~2 s.
2. Real game: reinstall the LeonidaMenu step (its zip name stayed 1.0.0 but the script changed: title, word wrap,
   "open Leonida" wording), `leonida settings apply` (minimap HiddenBlips fix), then in game check: the minimap at
   Michael's house has no "IR"/cursor icons, the menu title reads "LEONIDA V", Pack & variant text wraps. Screenshot
   script: hold each key ~80 ms, wait ~300 ms after release (the last capture ran one page ahead).
3. The 19:53 crash (GTA5_Enhanced.exe+0x1C8B958, engine-only, a 3-star police fight on foot near (-800, 1424),
   memory load 91%): try to reproduce with more free RAM; if it repeats, turn off NextGen Euphoria first, then
   Traffic V FEAR; if not after 2-3 tries, list it as a one-off under "Known crashes" in `docs/IN-GAME-CHECKS.md`.
4. Launcher speed, still open (`docs/PERF.md` TODO): window frame to ~1 s (build hidden pages after first paint via
   `after_first_paint()` in `gui/app.py`), pack switch ~600 ms (`Session.installed_settings()` off the UI thread in
   `ChoosePage.switch()`), first visits 230-490 ms (idle prebuild or list views), cache `Session.online_status()`.
5. GUI for paid mods from `docs/PAID-MODS.md` (Buy button → author's page; "I've downloaded it" → scan + install).
6. Wire `gamesettings.suggest_variant` into first-run setup and the Settings page.
7. The owner's in-game checklist (`docs/IN-GAME-CHECKS.md`), incl. checking once in GTA's menu that
   `ResScalingType` 0 / `FrameGenType` 0 mean "off"; Downtown Cab's .oiv vs the QoL taxi when it's downloaded.
8. **Only the owner can click these on GitHub:** Settings → General → Features → Discussions; Settings → Security →
   Private vulnerability reporting → Enable; Settings → Actions → General → "Require approval for first-time
   contributors" and Workflow permissions → read-only; Actions → labels → Run workflow (or wait for the next push).
9. Remind the owner about the NVE options (buy from the author, or the author's own free release) when they're back.

Session roles used today: **exe-build** (build, CI, releases, in-game probe/menu, crash dumps), **mod-sources**
(manifest data, sources, conflicts/features, settings, paid mods), **downloader** (downloads, GUI, speed). Their
notes are in the shared notes folder (`community-and-1953-crash.md`, `night-queue-manifest.md`).

## Earlier: the night of 2026-11-24/25

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

**Load crashes: both solved** (details in `docs/IN-GAME-CHECKS.md`, "Known crashes"). 0xBCC6AD (engine, null+0x18)
only happened while VisualV was installed (removed). 0x1516B9 was Enable All Interiors activating the Tuners auto
shop's car-lift entity sets with an invalid interior ID (ACTIVATE_INTERIOR_ENTITY_SET, from the dumps' stacks);
`INTERIORS/LOADTUNERGARAGE = False` is now locked on builds ≤1.0.1158.12. After that: `--repeat 15` = **15 of 15
passed** (story mode in 68-73 s). The game still peaks at ~9.5 GB private with ~1 GB RAM free on this 16 GB PC, so
Play warns below 6 GB free and offers to close apps the user ticks. Dumps:
`%LOCALAPPDATA%\Rockstar Games\GTAV Enhanced\CrashLogs` (read by `leonida playtest` and `leonida report`).

## Status
| Area | Status |
|---|---|
| Engine + CLI | done: game-build ranges, whenSelected/whenMissing, freeRoute, requireMembers/rejectMembers, pick hints, modpack + mod updates, self-update (check/force/reinstall), verify, playtest |
| GUI | functional: picture chooser, built-in browser + capture, download all, background installs, log check after each step, mod/Leonida updates, logo; "Download everything" (auto sign-in flow) in progress |
| Tests | ~780 tests, ~98% coverage, CI gate 90% (Windows); shutdown segfault fixed |
| Exe | `build/build_exe.py` -> `dist/LeonidaV` (321 MB, icon, self-test); release job (exe zip, source zip, modpack.json, SHA256SUMS) written, never run on GitHub |
| Design | `docs/DESIGN.md` + `leonida/gui/theme.py` + fonts done; components/page mocks in progress; not wired in yet |

## Open items, in priority order
1. A 30-minute play session by the owner on the owner's pick (the in-game checklist in `docs/IN-GAME-CHECKS.md`:
   Liberty keys, Open World Interiors vs the walk-in shops, the HUD, sounds).
2. Owner to try the installed app and give UI/UX feedback.
3. Self-update round trip 1.0.0 → 1.0.1 on the owner's PC (see RESUME HERE).
4. CodeWalker: never shipped; fetched from dexyfex's GitHub at first use (`leonida tools codewalker`). The
   permission request (`docs/codewalker-permission-request.md`) is still worth sending for credit/goodwill.
5. Known limit: files > 64 MB changed by a mod's own installer are not backed up; rollback warns.
