# Mod settings knowledge base (plan item F5)

Research for **F5: locked, tuned mod settings per modpack and variant** (`docs/PLAN.md`). Nothing here is
implemented yet. It lists, for every mod in **Core** and **Core + Safe Extras**, the config files it reads, the
keys that matter when it runs next to the other mods, the values we recommend, and the known clashes between mods
with their settings fix.

- Gathered on 2026-11-24 from the real downloads in `D:\Leonida\Downloads` (the `.ini` files as shipped), the mods'
  own pages and readmes, and the GTA VI-Inspired HUD's GitHub repo (`scripts\*.ini`, `INSTALL-ENHANCED.md`).
- Owner's PC: GTA V Enhanced **1.0.1013.20** (Script Hook V runs it as 1.0.1013.17), **GTX 1070 8 GB** (no ray
  tracing), game in `D:\Games\...` (not under Program Files).
- "Default" = the value in the file as the author ships it. "Lock" = what Leonida should write and watch.
- Variants used below: **Performance** (GTX 1070 class, no RT), **Balanced**, **Ultra** (RT GPU, 12 GB+ VRAM).

---

## 1. Hotkeys (the whole pack)

The clash check (`hotkeys.json`) already knows these. Locking them means writing them to the files below and
flagging drift.

| Key | Mod | Action | File / key | Default | Lock |
| --- | --- | --- | --- | --- | --- |
| F3 | Menyoo | Free camera | `menyooStuff\menyooConfig.ini` `FreeCamButton` | 114 (F3) | keep |
| F4 | Script Hook V .NET Enhanced | Console | `ScriptHookVDotNet.ini` `ConsoleKeyBinding` | F4 | keep |
| F8 | Menyoo | Open menu | `menyooConfig.ini` `open_key` | 119 (F8) | keep; **121 (F10) if the old "GTA VI Inspired Features" HUD (F8) is swapped in**, but then ActionsV (F10) must move |
| F9 | Menyoo | Spooner | `menyooConfig.ini` `SpoonerModeHotkey` | 120 (F9) | keep |
| F11 | Menyoo | Clone protection (MP only) | `menyooConfig.ini` `CloneProtectionHotkey` | 122 | keep (unused in story mode) |
| F10 | ActionsV (extra) | Menu | `ActionsV.ini` `[Input] MenuKey` | F10 | keep |
| Insert | SHVDNE, needed by Enable All Interiors | Reload all scripts | `ScriptHookVDotNet.ini` `ReloadKeyBinding` | None | **Insert only when Enable All Interiors is selected**, else None |
| hold V | GTA VI-Inspired HUD | HUD options | `scripts\GTA6Hud.ini` `[SettingsMenu] Key` | V | keep (a tap of V is still GTA's camera view) |
| hold Left Alt | HUD | Character wheel | (not rebindable) | Left Alt | — |
| K | HUD | Skills | `scripts\ViExtras.ini` `[Skills] Key` | K | keep |
| Y / U | HUD | Greet / antagonize | `ViExtras.ini` `GreetKey` / `AntagonizeKey` | Y / U | keep |
| N, Shift+N | HUD | Push-ups / sit-ups | `ViExtras.ini` `PushUpsKey` / `SitUpsKey` | N / N,Shift | keep |
| O | HUD | Mute radio | `ViExtras.ini` `MuteKey` | O | keep |
| H (J) | HUD | Activities (dive) | `GTA6Hud.ini` `[Activities] Key` / `AltKey` | H / J | keep |
| T, L | HUD | Fence tracker, call Lester | `GTA6Hud.ini` `TrackerKey`, `LesterKey` | T, L | keep |
| Left Ctrl ×2, Right Ctrl | HUD | Crouch, crawl | `scripts\ViCrouch.ini` `[Crouch] Key`, `[Crawl] Key` | LControlKey, RControlKey | keep (first tap of Left Ctrl is still GTA's stealth) |

Controller combos: Menyoo opens on **RB + D-pad Left** (`open_button_for_gamepad_1 = 206`, `_2 = 189`); ActionsV
on **D-pad Left + LB** (`MenuBinds`). They differ (RB vs LB). The HUD's radio wheel holds D-pad Left in a car, so
ActionsV's combo only matters on foot. No change needed.

---

## 2. Per mod

### Script Hook V (Core)
- Files: none of its own. `args.txt` (in the zip's `bin`) switches BattlEye off; Leonida doesn't copy it (repo rule).
- Lock: nothing. Check: `ScriptHookV.log` says `INIT: Success, game version is ...` (on 1.0.1013.20 it says
  `VER_EN_1_0_1013_17`).

### Script Hook V .NET Enhanced (Core) — `ScriptHookVDotNet.ini`
| Key | Default | Lock | Why |
| --- | --- | --- | --- |
| `ReloadKeyBinding` | None | None; **Insert** with Enable All Interiors | EAI's page: set a reload key, press it once after loading to load the MP maps. Reloading restarts *every* script, the HUD included. |
| `ConsoleKeyBinding` | F4 | F4 | no clash |
| `ScriptTimeoutThreshold` | 5000 | 5000 | author default; the HUD's 2.8.2 notes work around the console during mass script aborts, not the timeout |
| `ScriptsLocation` | "scripts" | "scripts" | every script mod here installs to `scripts` |
| `WarnOfDeprecatedScriptsWithTicker` | true | (not managed) | SHVDNE 1.1.0.6 no longer reads it (removed in its source with the deprecation ticker) |
| `AutoLoadScripts` | true | true | |

### DirectStorageFix (Core)
- Files: none (writes `DirectStorageFix.log`). Its readme: needed on 1.0.1013.17+, so scripts can write their own
  `.ini`/log files (the HUD saves its settings, EAI and Menyoo write configs). **Keep it whenever script mods are
  installed.** On builds below 1013 it stops itself.

### OpenRPF (Core; not with NVE)
- Files: none. Needs the `mods` folder, and `mods\update\update.rpf` before any hand edit of `dlclist.xml`.

### Resource Extensions [Enhanced] (Core) — `ResourceExtensions.ini`
| Key | Default | Performance (GTX 1070) | Balanced | Ultra | Source / why |
| --- | --- | --- | --- | --- | --- |
| `[density] AmbientPeds` | 1.00 | 1.00 | 1.50 | 2.00 | page: "I seriously recommend against pushing ped settings past 5.00"; 2-4 = heavy load |
| `ScenarioPeds` | 1.00 | 1.00 | 1.50 | 2.00 | same |
| `AmbientVehicles` | 1.00 | 1.00 | 1.25 | 1.50 | traffic 0-4; All MP Vehicles adds its own cars on top |
| `ParkedVehicles` | 1.00 | 1.00 | 1.50 | 2.00 | |
| `[population] Cyclists` | 1.00 | 1.00 | 1.00 | 1.00 | |
| `[decals] Persistence` | 0 | 0 | 2 | 4 | |
| `[budget] VehicleModelBudget` | 0 | 0 | 1 | 2 | page: increase gradually for more vehicle variety if VRAM allows; All MP Vehicles adds hundreds of models |
| `StreamingMemoryBudget` | 0 | 0 | 0 | 1 | page: "Set to 1 only if your mods need higher budgets" |
| `BvhVertexArena` | 1 | **0** | 0 | 1 | ray-tracing geometry; GTX 1070 has no RT, 0 saves memory (page) |
| `[world] LowPriorityProps` | 0 | 0 | 0 | 1 | off by default (page) |
| `[logging] EnableLog` | 0 | **1** for the first runs | 0 | 0 | shows which RE features are active on this build ("Partially Active" on older builds) |

Rule (page): no other limit adjuster (HeapAdjuster, PackfileLimitAdjuster, ...) and **no modified `gameconfig.xml`**
alongside it. See clash C1.

### Map Fixes + Bugstar Fixes (Core)
- No config files (checked against the real Enhanced downloads, `383134-MapFixes_v21.8.2_Gen9.rar` and
  `978dba-BugstarFixes_v7.8.1_Gen9.rar`: a DLC pack, an `.oiv`, and ReadMe/Changes/Credits). Their `.oiv`s don't
  touch any file that Drive V, the HUD or Resource Extensions write. Bugstar's `.oiv` also writes `update2.rpf`,
  `x64e.rpf` (minimap) and `update\x64\dlcpacks\patch2026_01`. The owner's 1.0.1013.20 has no `patch2026_01`
  (read 2026-11-24). The `.oiv` creates that pack in `mods` (only content.xml + setup2.xml) and the game ignores it.
  Its `mods` copies need about 2.7 GB free (x64e.rpf 2.07 GB + update2.rpf 644 MB). Map Updates (extra) has `scripts\MapUpdates.ini` (all `false` by default: Christmas/Halloween
  props, motel room curtains/TV, extra scenarios and blips). Lock: author defaults.

### All MP Vehicles in SP (Core) — `scripts\AllMpVehiclesInSp.ini`
| Key | Default | Lock | Why |
| --- | --- | --- | --- |
| `parking_lots_spawn` | 1 | 1 | |
| `spawn_traffic` | 1 | 1 | **0 if Traffic V FEAR Edition is used instead** (clash C3) |
| `max_traffic_vehicles` | 3 | 3 (Performance) / 5 (Ultra) | |
| `time_traffic_gen` | 3000 | 3000 | |
| `blips`, `traffic_cars_blips` | 1, 1 | **0, 0** | GTA VI look: the HUD's minimap shouldn't fill up with car blips |
| `tuning`, `tuning_hsw` | 1, 1 | 1, 1 | |
| `[ADVANCED] SpawnDistance` / `DespawnDistance` | 300 / 500 | keep | |
| `[PRESET] preset` | lore | lore | |
- Extra files: `NewVehiclesList.txt` (add-on cars), `mp_blacklist.txt`.

### Drive V (Core)
- No `.ini`. Checked against the real 7.5 zip (`6b9a30-DriveV 7.5.zip`, 2026-11-24). Its `Installation readme.txt`
  covers: `settings.xml` `VehicleVarietyMultiplier` (the author uses 0.8; higher = more car models but fewer colours;
  on Enhanced the file is `Documents\Rockstar Games\GTAV Enhanced\settings.xml`; the owner's has
  `VehicleVarietyMultiplier`, `PedVarietyMultiplier` and `LodScale` at 1.0, read 2026-11-24), ENB
  `IgnoreDamageLimits=true` (no ENB in Core), InversePower `AngleEnd 15.0` / `AngleEndTorqueMod 2.5` (InversePower is
  not in Leonida), a trainer against DLC-car despawn (Menyoo), and the taxi colour edit in `carvariations.ymt`.
  Lock: `VehicleVarietyMultiplier` stays at the game's 1.0 (the author uses 0.8) until it has been tested (doubt: it's a game setting
  that also changes how fast the game streams cars); taxi colours as shipped.
- Optional parts in the zip: "Optional Traffic Edits" (popgroups.ymt → `update.rpf\x64\levels\gta5`, popcycle.dat →
  `update.rpf\common\data\levels\gta5`; "BOTH FILES ARE NECESSARY") and "Optional AI improvements"
  (vehicleaihandlinginfo.meta → `common.rpf\data\ai`). Lock: **don't install the traffic edits** (All MP Vehicles
  handles traffic, clash C4); AI improvements: off by default (untested).
- "Enhanced Handling etc" folder (no readme): a `handling.meta` dated 2025-10-18 that differs from the 7.5 one
  mainly in higher `fCollisionDamageMult`/`fEngineDamageMult`, plus `mpg9ec` meta files for 5 Enhanced-only HSW cars.
  Lock: **not used**. It's older than 7.5 and the author gives no install path.

### NextGen Euphoria (Core)
- No config (one `physicstasks.ymt`). Order: before Immersive Combat (Immersive Combat's page).

### GTA VI Combat Camera (Core)
- No config (one `cameras.ymt`). Only one mod may replace `cameras.ymt`.

### GTA VI-Inspired HUD (Core) — `scripts\GTA6Hud.ini`, `scripts\ViExtras.ini`, `scripts\ViCrouch.ini`, `scripts\ViCustoms.ini`, `scripts\ViWasted.ini`, `scripts\MiniMap.settings`
Settings to lock for cooperation (everything else: author defaults; its update resets the `.ini` files, so Leonida
must re-apply them after each HUD update):
| File / key | Default | Lock | Why |
| --- | --- | --- | --- |
| `GTA6Hud.ini [Hitmarkers] Enabled` | False | False while `ViExtras [Switches] KillMarks = True` | the file itself: both draw in the same spot |
| `GTA6Hud.ini [Reticle] Enabled` | False | False | ViExtras' crosshair replaces it |
| `GTA6Hud.ini [Radio] Enabled` | False | False | ViExtras' radio wheel is used (`RadioWheel = True`); only one may be on |
| `GTA6Hud.ini [FuelStation] BurnFuel` | True | True; **False if any other fuel mod** is installed | the HUD has fuel, nozzle and pumps; Fuel Reloaded etc. were rejected for that reason |
| `GTA6Hud.ini [Police] SmartAiEnabled` | True | True; **False with a dispatch/police AI mod** (e.g. Traffic V's optional dispatch .oiv, LSPDFR) | two police brains fight |
| `GTA6Hud.ini [Dealership] Enabled` | True | True | no other dealership mod in the pack (Simmy Car Lots rejected) |
| `GTA6Hud.ini [Swap] Enabled` | True | True | |
| `ViExtras.ini [Switches] Gym` | True | True | Open World Interiors' gyms (alternative) duplicate it |
| `ViExtras.ini [Switches] CameraWeight`, `CrashCamera` | True | True | vehicle-only; Camera Flinch (on foot) and Dynamic Vehicle First Person (first person) don't overlap |
| `ViExtras.ini [GameFolder] FixAccess` | True | True | only acts when the game is under Program Files |
| `ViCrouch.ini` keys | LControlKey / RControlKey | keep | no other crouch mod (Stance rejected) |
- Game settings it needs: **Screen Type = Windowed Borderless** (minimap), **language English**.

### Menyoo 2.0 (Core) — `menyooStuff\menyooConfig.ini`
- Keys: see section 1. `open_key = 119` stays unless the old F8 HUD is swapped in.
- Launcher: BattlEye off (its page).

### Straight To Story Mode (Core)
- No config (one `.asi`, writes `StraightToStoryMode.log`).

### Core + Safe Extras
| Mod | Files | Keys / values | Notes |
| --- | --- | --- | --- |
| Immersive Combat | none (`.oiv` / loose metas) | — | install after NextGen Euphoria |
| LemonUI | none | — | one copy in `scripts`; the HUD's `.oiv` also brings `LemonUI.SHVDN3.dll` (same 2.2 size); keep the newest |
| Enable All Interiors | `scripts\EnableAllInteriors.ini` (746 lines), `scripts\iFruitAddon2\config.ini` | `LOADMPMAPSONREFRESH = True`, `READYFORLOADONLINE = 1` (author defaults); per-interior `ENABLE...`/`LOAD...` toggles; `ENABLEMARKERS_TELEPORT = False`, `ENABLEBLIPS = False` | needs SHVDNE `ReloadKeyBinding = Insert`; keep its iFruitAddon2 2.1.1 (its note: not 3.1/3.1.1) |
| Jason Duval House alpha | none | — | add last, test alone |

---

## 3. Known clashes between mods, and the settings fix

| # | Mods | Clash | Fix (setting) | Source |
| --- | --- | --- | --- | --- |
| C1 | HUD + Resource Extensions | the HUD's `.oiv` raises 5 pools in `mods\update\update.rpf\common\data\gameconfig.xml`; RE doesn't support a modified `gameconfig.xml` | test after the HUD step; if loading crashes, put the game's own `gameconfig.xml` back (RE raises limits itself). **Needs a real-game test.** | RE page; HUD guide ("ResourceExtensions doesn't support a modded one") |
| C2 | HUD + paid NVE | NVE's own `gameconfig.xml` / `dlclist.xml` win | add the HUD's 3 packs to NVE's `dlclist.xml`; **never raise NVE's pools** (out of memory) | HUD guide |
| C3 | All MP Vehicles + Traffic V FEAR (alternative) | both put MP/DLC cars into traffic | use one; if Traffic V: `spawn_traffic = 0` in All MP Vehicles | pages |
| C4 | Drive V optional traffic edits + Traffic V / All MP Vehicles | same popgroups/popcycle | don't install Drive V's traffic edits | Drive V readme |
| C5 | Menyoo + old HUD (alternative) | both F8 | Menyoo `open_key = 121` (F10), then ActionsV `MenuKey` to another key (e.g. F7) | hotkeys |
| C6 | Enable All Interiors + SHVDNE | EAI needs a reload key | `ReloadKeyBinding = Insert`; pressing it reloads the HUD too | EAI page |
| C7 | HUD hit markers vs kill marks | both in the reticle spot | keep `GTA6Hud.ini [Hitmarkers] Enabled = False` (the default) | GTA6Hud.ini / ViExtras.ini comments |
| C8 | HUD radio wheels | GTA6Hud's and ViExtras' on the same button | GTA6Hud `[Radio] Enabled = False` (default) | ViExtras.ini comment |
| C9 | Immersive Combat + NextGen Euphoria | order | Euphoria first | Immersive Combat page |
| C10 | Better Vehicle Deformation + Drive V for NVE (NVE only) | both `handling.meta` | one file; BVD's replaces Drive V's (backup kept) | BVD page |
| C11 | Map Updates (extra) + Enable All Interiors | both touch the FIB building interiors (Map Updates' unused FIB office, EAI's FIB elevator menu) | not confirmed; test with both | pages |
| C12 | Any script mod on 1.0.1013.17+ | can't write its own files without DirectStorageFix | keep DirectStorageFix | DSF readme |
| C13 | Map Fixes / Bugstar + RE | they list RE as a requirement on Enhanced | keep RE in Core | their pages |

---

## 4. Not known yet (to find out in the real game)
- C1 (HUD gameconfig vs Resource Extensions).
- Good Resource Extensions densities on the GTX 1070 next to All MP Vehicles (frame time at 1.00 vs 1.50).
- Comments on gta5-mods load separately and weren't read; known issues above come from pages, readmes and the HUD's
  guide/changelog only.
