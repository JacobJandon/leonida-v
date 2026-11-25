# Leonida V — plan

Living plan doc: https://claude.ai/artifact/BGPindmjSYZ1YCrq9fTnPd
Stable mod guide: https://claude.ai/artifact/EYNdb89Pb5wJ5k5DW9YQQ9

Three levels: **Roadmap** (now), **Future plan** (next, after 1.0), **Far future plan** (later, bigger bets).

## Roadmap (now)

| Phase | What | Status / gate |
|---|---|---|
| 0 | Plan | done |
| 1 | Manifest and packs | done: real pages, images, versions for every Enhanced build, free Core, Legacy list, Core / Plus / Showcase |
| 2 | Engine and CLI | done: ~1000 tests, ~97% coverage, CI green (Ubuntu + Windows); uninstall = snapshot |
| 3 | GUI / launcher | done: new design, modpack cards, edition picker, download everything, install stepper, play test, shortcuts; smoke test + single-instance in progress |
| 4 | Real test on the owner's PC | in progress: Showcase (Balanced) chosen, all 34 files downloaded, 17 mods installed (16 pass `leonida playtest` on 1.0.1013.20); 14 archive-editing mods next via the CodeWalker helper |
| 5 | Release 1.0 | done: v1.0.0 and v1.0.1 on GitHub (setup, portable zip, source, modpack.json, SHA256SUMS; no CodeWalker files) |
| 1.0.1 | In-game menu, GTA settings per PC, one job per mod, paid buy-and-play, contributor access | released; in-game checks of the minimap fix and the new menu text still to do (HANDOFF "RESUME HERE") |
| 1.1 | **Zero-touch + ready-made setups (F8)**: no hand steps, every mod on and checked in game, one-click setups | next, after the HANDOFF "RESUME HERE" items |
| 1.1 | Downloads | done: GitHub/direct, gta5-mods versions, Nexus after sign-in, MediaFire, archive content checks |
| 1.2 | Updates | built: self-update (check / force), modpack channel, mod auto-updater; needs the first real release |
| — | Design pass | done (wired in); owner feedback next |
### Real-PC test checklist (phase 4)
- [x] `leonida doctor` shows .NET 4.8 and VC++ as ok
- [x] `leonida detect` finds the game (1.0.1013.20, tested build)
- [x] Script Hook V works on 1.0.1013.20 (`VER_EN_1_0_1013_17`), confirmed by `leonida verify`
- [x] SHVDNE, Menyoo, DirectStorageFix, Resource Extensions, Straight To Story Mode load in the real game
- [ ] `leonida get` recognises every download (free Core: done; Nexus files need the owner's free login)
- [ ] Install the rest of Core one step at a time; after each step the game boots to story mode and `verify` is OK
- [ ] HUD key and Menyoo key don't clash in game
- [ ] 30-minute session without a crash
- [ ] `online-safe on` -> game launches clean -> `online-safe off` -> mods back
- [ ] `uninstall` -> "matches the pre-install snapshot"

## Future plan (next)

### F1. Paid mods for free — the legitimate ways
Asked for by the owner on 2026-11-24. Goal: every paid mod in the manifest gets a **free route**, so no profile
needs money. Leonida never uses leaked, cracked or re-uploaded copies of paid mods (it takes money from the
authors, breaks their terms, and those files are a common malware route). The free routes, per paid mod:
1. **Free alternative**: the best free mod for the same job, as an `alternative` in the same slot (e.g. a free
   graphics/lighting overhaul for Enhanced in place of NVE; free character models in place of the Jason + Lucia
   shop models; free world-life scripts in place of Lively World Expansion).
2. **Goes public later**: many paid mods are early access first and public later. Track each one's public release
   (`publicSince` / `earlyAccessUntil` in mods.json) and switch the mod to its free source automatically when it
   goes public; a check on start says "X is now free".
3. **Official free version**: lite or older free editions the author publishes themselves (e.g. a free "Lite" or a
   previous public release) — use them where they work on the detected game build.
4. **Ask the author**: a short, polite request for a free/redistributable build for Leonida users, recorded as
   `redistribution.proof` if granted.
- mods.json: `freeRoute` per paid mod (`alternative` / `publicSince` / `freeEdition` / `none`), shown in the chooser
  ("Paid — free alternative: X").
- Gate: every profile can be installed for free; paid mods are clearly marked optional add-ons.

### F4. Modpacks to choose from + Leonida as a general mod launcher
Asked for by the owner on 2026-11-24. Instead of one big list with profiles, Leonida offers **2-3 curated
modpacks** to pick from on the first page, each with **add-ons** grouped by category, and can also manage any
other mods the user brings, so it's a mod launcher for all of their modding, not just the GTA VI look.
- Modpacks (first ideas, each fully free with optional paid add-ons, see F1):
  1. **Leonida Core**: the GTA VI look and feel, stable, minimal (today's Core).
  2. **Leonida Plus**: Core + world life (interiors, shops, street food, map updates, Benny's, combat camera).
  3. **Leonida Showcase**: the full video-style setup (today's showcase profile), for strong PCs.
- Add-on categories under each pack: Graphics, World & interiors, Vehicles, Combat, HUD & camera, Tools & trainers,
  Characters, Performance. Each add-on is a mod (or small group) with its picture, free/paid badge, build support
  and conflicts shown before it's ticked.
- Manifest: `modpacks.json` (id, name, picture, base mod list, default add-ons, allowed add-on categories)
  replacing profiles.json (profiles become packs; old configs migrate). The modpack update channel (F2) then
  publishes per-pack lockfiles.
- "Your own mods": a section where the user adds any mod (a file from their disk or a page URL); Leonida treats it
  like a manifest mod with a user-written entry (files, target folder, order), so it gets the same logged install,
  rollback, conflict check and online-safe handling. Saved in `State\custom-mods.json`, exportable to share.
- GUI: first-run "Choose your modpack" page (big picture cards), then the add-on chooser by category, then the
  existing Get / Check / Install flow. Switching packs = Leonida rolls back what isn't in the new pack.
- Gate: all three packs install, play-test and uninstall cleanly on the owner's PC.
- Built (engine, 2026-11-25): `modpacks.json` (packs, categories, add-ons, variants; schema at the top of
  `leonida/manifest/__init__.py`), without it every profile is a pack with the same id and every pack is also a profile,
  so old configs carry over; the choice (pack, add-ons, variant) per edition in `State\pack.json`
  (`Session.pack_choice()/choose_pack()`), switching rolls back what left (`packs.rollback_mods`, refusing where a
  kept mod shares files); your own mods in `State\custom-mods.json` (`leonida/custommods.py`) become `custom` tier
  mods with the same matching (their own file wherever it is), Installer, rollback and checks; CLI `leonida pack
  list|choose|addons`, `leonida custom add|remove|list|export`. Left: the real modpacks.json data, the GUI.

### F5. Locked, tuned mod settings per modpack and variant
Asked for by the owner on 2026-11-24 ("lock mods settings so other mods work… first get it working"). After the
working phase: every modpack ships **tested settings** for its mods' own config files, so mods cooperate out of the
box and one mod's defaults can't break another.
- Per mod: `settings` in the manifest = the config files it reads (`ScriptHookVDotNet.ini`, `ResourceExtensions.ini`,
  `menyooStuff/menyooConfig.ini`, HUD/camera `.ini`/`.xml`, timecycle/`visualsettings.dat` values, keybinds) with the
  keys Leonida manages and their values per modpack/variant (e.g. Resource Extensions pool density 1.00-2.00, Menyoo
  off F8 when the HUD uses it, SHVDNE reload key off).
- Lock: Leonida writes them at install (logged, so rollback restores the user's file) and `leonida check` /
  `verify` flag drift ("menyooConfig.ini: OpenKey changed from F9 to F8, clashes with the HUD"). A per-key
  "unlock" lets advanced users override, remembered in State.
- Variants: a modpack can offer variants (e.g. Performance / Balanced / Ultra, Realistic / Arcade handling) that
  are just different locked setting sets + add-on choices, switchable without reinstalling mods.
- Conflict knowledge base: per pair of mods, the settings that make them work together, with sources; tested with
  `leonida playtest` on the owner's PC before a variant ships.
- Gate: each modpack/variant passes playtest with its locked settings; switching variants and rolling back leave no
  drift.
- Built (engine, 2026-11-25): per-mod `settings` in mods.json (ini/xml/json key paths; value / packs / variants /
  whenSelected rules; schema in `leonida/settings.py`), variant overrides in modpacks.json; written by the Installer
  inside the mod's own step (rollback restores the user's file), re-applied for variant switches as logged
  `settings:<mod>` steps (no reinstall); drift is a WARNING in `check` and shown by `verify`; per-key unlock in
  `State\settings-unlocked.json`; CLI `leonida settings show|apply|unlock|lock`. Left: the real settings data from
  docs/SETTINGS.md into mods.json, the GUI, the playtest gate.

### F6. CodeWalker for whatever doesn't work on Enhanced out of the box
Asked for by the owner on 2026-11-24. Some mods only ship Legacy files or `.oiv` packages that OpenIV installs on
Legacy but that don't apply cleanly to Enhanced (gen9 RPFs, `_g9` packs, different `dlclist.xml` / `update.rpf`
layout). CodeWalker (dexyfex, free, open source, GitHub releases) can open and edit Enhanced RPFs, so Leonida uses
it as the fallback tool:
- Prerequisite handled by Leonida: download CodeWalker automatically from its GitHub releases (already listed as a
  prerequisite) into `State\tools\CodeWalker`, never into the game folder.
- Automate what's possible: a small helper built on CodeWalker's own library (CodeWalker.Core, .NET) that Leonida
  calls to extract/replace files inside RPFs and to apply an `.oiv`'s `assembly.xml` to Enhanced paths (into
  `mods\update\update.rpf` via OpenRPF, or loose `onigiri` folders when NVE is used). Every change goes through the
  installer so it is logged and rolled back like any other step.
- Where it can't be automated: guided steps that open CodeWalker RPF Explorer at the right file, with exact
  click-by-click instructions and screenshots.
- Converting Legacy-only mods: when a mod only exists for Legacy, check (per mod, with sources) whether its files
  work on Enhanced unchanged (meta/ymt/xml data often does; models/textures may need `_g9`/gen9 conversion) and
  mark the result in mods.json (`enhancedVia: "codewalker"` + steps) instead of silently using Legacy files.
- Gate: one Legacy-only mod converted and play-tested on the owner's PC; rollback restores the original RPF.

### F7. Launcher basics: logs, crash handling, diagnostics, settings (asked 2026-11-25)
So problems can be worked out on different setups: a central rotating log (`State\logs`, Debug mode), a crash
handler with a friendly dialog, a "Report a problem" diagnostics zip (Leonida + mod logs, play-test/verify results,
steps, settings, PC info; user name, cookies and logins removed; saved locally, attached by the user to a GitHub issue;
never sent automatically), plus Settings / About / Help pages, notifications, single instance and a Play button.

### F8. Zero-touch: every mod on and perfectly set up, in game too, plus ready-made setups (asked 2026-11-25)
The owner: "auto enable each mod and make perfect settings, enabled in game without the user needing to do it
himself; have ready setups with modpacks." Today a few mods still need a hand step after install (Enable All
Interiors' "press Insert to load the MP maps", the Liberty mods' keys "set by hand after the first start", options
some mods only keep in their own in-game menus). Goal: after Play, everything is already on and tuned.
- **No hand steps left:** every `steps`/`checks` line in mods.json that asks the player to do something becomes either
  a config value Leonida writes before the first start (ini/xml/json the mod reads, incl. keys and menu options it
  saves to disk), or an in-game action the Leonida menu script performs once at the first story-mode load (only
  public natives and the mod's own documented hooks; never another script's memory). What truly can't be automated
  is listed per mod with the reason.
- **Proof it's on:** `playtest --deep` checks each mod's effect in game, not just its log: DLC packs present, the
  handling values, the HUD's minimap drawing, MP interiors loaded (IS_IPL_ACTIVE), a script's own heartbeat/log line,
  the menu's settings echo. The launcher shows "on and checked in game" per mod.
- **Perfect settings by default:** every mod's settings and GTA's settings.xml come from the setup (pack + variant +
  PC: RAM, VRAM, GPU features, screen), re-checked after each update; drift is fixed at the next start unless the
  user unlocked that key.
- **Ready-made setups:** one click = pack + variant + add-ons + game settings, tested together:
  e.g. "Owner's pick · 16 GB", "Owner's pick · 32 GB", "Core · laptop", "Showcase · RTX". Each is a
  `setups/<id>.json` with its tested `modpack.json` lockfile, published with every release; the launcher shows them
  as cards (picture, what you get, PC needs, "tested on 1.0.1013.20 / 1.0.1158.x"), picks the best one for the PC on
  first run, and lets users export / share their own setup file.
- **Gate:** on a clean game folder: choose a setup → one click → Play reaches story mode with every mod on and
  checked by `playtest --deep`, with zero hand steps, on the owner's PC; 10-run `--repeat` without a crash.

### F2. Updates and the Leonida modpack (1.2) — finish
Built: (A) modpack channel (`modpack.json` per release, author sources + SHA-256, redistribution rule), (B) mod
auto-updater (roll back + reinstall per mod, held on unsupported builds), (C) self-updater (git / portable zip /
exe folder swap; check, update and force update; daily check, never updates without a click).
Left: the first real GitHub release, a `modpack.json` made on the owner's tested PC, and a real update round-trip.

### F3. GTA V Legacy edition (1.3)
Asked for by the owner on 2026-11-24 ("every game"). The Legacy edition (`GTA5.exe`, DirectX 11, builds 1.0.3xxx)
needs its own mod list: most Enhanced mods don't run on Legacy and vice versa (different Script Hook V line,
OpenIV instead of OpenRPF, NaturalVision Evolved instead of NVE, different HUD/camera packages).
- Manifest: an `edition` field per pack (`enhanced` / `legacy`), a separate `mods-legacy.json` (+ profiles, hotkeys)
  chosen by the detected exe; `gameExeNames` per edition. The `gameBuilds` engine applies to both.
- Detection: report the edition next to the build; refuse to mix editions; list both when both are installed.
- Gate: Legacy Core verified on a real Legacy install (install, play, online-safe, uninstall = snapshot).
- Built (engine, 2026-11-25): `load_manifest(dir, edition)` with the `mods-legacy.json` / `profiles-legacy.json` /
  `hotkeys-legacy.json` set (empty scaffold until mod-sources fills it); `detect_games()` finds both exes and reports
  each install's `edition`; `Session` picks the set from the game folder's exe (`--edition` overrides); `check` errors
  and `install` refuses (even with `--force`) when the mod list's edition differs from the game's; `detect`/`doctor` show
  the edition and list both when both are installed. Left: the Legacy mod data, the GUI, the real-install gate.

## Far future plan

### FF1. Online play through roleplay platforms (3.0+)
Asked for by the owner on 2026-11-24 ("we mod online too in far future"). Story mode stays the focus until then.
**GTA Online itself is never modded**: Rockstar bans modded accounts and it breaks the multiplayer rules, so Leonida
keeps blocking it (online-safe switch, BattlEye left alone). The legitimate route to modded multiplayer is a
separate platform whose servers are built for mods, e.g. FiveM (Cfx.re, now part of Rockstar), with its own client,
mod format (resources/streaming) and server rules.
- Research first: which platforms officially allow client mods, which edition/build they run on (FiveM uses the
  Legacy game), what a "Leonida look" means there (client graphics are allowed on many servers; scripts are
  server-side).
- Then: a profile type `platform: fivem` with its own folders (the platform's `mods`/`plugins` folders, never the
  game folder), and an online-safe check that keeps story-mode mods out of them.
- Gate: only platforms whose terms allow it, and only client mods the server rules allow.

### FF2. Other games through the same engine (2.0+)
The engine (manifest -> download from authors -> match -> logged install with rollback -> uninstall to snapshot) is
not GTA-specific. To support another game: move GTA-only parts (exe names, store folders, online-safe items,
RPF/OIV notes, Script Hook checks) behind a per-game `game.json`, ship one manifest folder per game, and let the
Game page pick the game first. Candidate: Red Dead Redemption 2 (story mode only, same anti-cheat rules). Decide per
game whether its mod community allows this kit's download flow before adding it.
