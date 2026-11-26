# Zero-touch: no hand steps, every mod proven on (plan F8)

Status 2026-11-26 (manifest session). After **Play**, every mod should already be on and set up, and Leonida proves it. The data is three keys per mod in `mods.json` / `mods-legacy.json`, read by `leonida/zerotouch.py` (the manifest loader ignores them):

| Key | What it holds |
| --- | --- |
| `verify` | proof the mod is on: `in: files` (Leonida checks the game folder and the logs after a start) or `in: game` (the Leonida in-game menu checks it during `playtest --deep`, with public natives: `IS_DLC_PRESENT`, `IS_IPL_ACTIVE`, `GET_CURRENT_LANGUAGE`) |
| `inGameSetup` | what the Leonida menu does once at the first story-mode load, with public natives or the mod's own documented hooks only |
| `manual.why` | why a hand step must stay |

Mod settings and GTA's own `settings.xml` are written before the first start (docs/SETTINGS.md); drift is fixed at the next `settings apply` unless the player unlocked a key.

**Result:** the base of every pack (Owner's pick, Core, Plus, Showcase) needs **no** hand step on 1.0.1013.20 (`tests/test_zerotouch.py`). What's left is in add-ons, and each says why below.

## Every mod in a pack

| Mod | Hand step today | Proof it's on |
| --- | --- | --- |
| Script Hook V | none | ScriptHookV.log: 'INIT: Success' |
| Script Hook V .NET Enhanced | none | ScriptHookVDotNet.asi loaded; ScriptHookVDotNet.log: 'ScriptHookV .Net Enhanced' |
| DirectStorageFix | none | DirectStorageFix.asi loaded; DirectStorageFix.log: 'Init finished' |
| OpenRPF | none | OpenRPF.asi loaded; asiloader.log: 'OpenRPF.asi' |
| Resource Extensions [Enhanced] | none | ResourceExtensions.asi loaded; ResourceExtensions.log: 'Main Heap: Active' |
| NaturalVision Enhanced | **by hand:** paid: the files inside 'Main Package' aren't public, so Leonida can't map them until a bought package is checked; NVE's own recommended in-game graphics settings aren't published either | onigiri present |
| Map Fixes (Enhanced package) | none | DLC pack spMapFixes_Gen9 present (in game) |
| Bugstar Fixes (Enhanced package) | none | DLC pack spFixes_Gen9 present (in game) |
| All MP Vehicles in SP | none | All MP Vehicles in SP.dll in scripts |
| Drive V (Realistic Driving / Handling & Damage) | none | update/update.rpf > common/data/handling.meta |
| NextGen Euphoria | none | update/update.rpf > x64/data/tune/physicstasks.ymt |
| GTA VI Combat Camera [Enhanced] | none | update/update.rpf > x64/data/metadata/cameras.ymt |
| GTA VI-Inspired HUD (geckomacabre) | none: Windowed Borderless: written to GTA's settings.xml (Leonida). English: checked in game; in game: check (first-load) | ViMinimap.asi loaded; ViPreload.asi loaded; GTA6Hud.dll in scripts; ViMinimap.log: 'present callback registered'; DLC pack vihud present (in game); DLC pack vihudfonts present (in game); DLC pack vihudanims present (in game) |
| Menyoo 2.0 | none | Menyoo.asi loaded; menyooLog.txt |
| Straight To Story Mode | none | StraightToStoryMode.asi loaded; StraightToStoryMode.log |
| LemonUI (for Script Hook V .NET) | none | LemonUI.SHVDN3.dll in scripts |
| Immersive Combat | none | update/update.rpf > common/data/ai/weapons.meta |
| Enable All Interiors | none: no Insert press: it loads the online maps at start; the Leonida menu reloads once if not; in game: reload-scripts (verify-fails) | EnableAllinteriors.dll in scripts; iFruitAddon2.dll in scripts; scripts/EAIInitalization.log: 'INITIALIZATION DONE'; scripts/EAIInitalization.log: 'MP MAPS LOADED'; IPL vw_casino_main active (in game) |
| Better Vehicle Deformation for NVE | none | onigiri/common/data/handling.meta present |
| Jason Duval House alpha | none | DLC pack mmd_jason_duval_houses present (in game) |
| Lively World Expansion (Enhanced build) | **by hand:** paid: the package layout (its .oiv, density folders) has to be checked in a bought copy first | its logged files are in place |
| Jason Duval + Lucia Caminos models | **by hand:** paid: what the buyer downloads and the install steps aren't public | its logged files are in place |
| Map Updates (Enhanced package) | none | MapUpdates.3.cs in scripts; DLC pack spMapUpdates_Gen9 present (in game); DLC pack spMapUpdates_Patch_Gen9 present (in game) |
| Benny's Motor Works in SP Revamped | none | BennysMotorworksRevamped.dll in scripts; DLC pack bennys_sp present (in game) |
| Street Food Vendors Enhanced | none | StreetFoodVendors.dll in scripts |
| GTA VI Camera Flinch | none | BulletNearMissFlinch.cs in scripts |
| Open World Interiors | none: the optional hospital files moved to its notes | OpenWorldInteriors.dll in scripts |
| ActionsV | none | ActionsV.asi loaded |
| GTA IV Burger Shot Interior | none | DLC pack burgershot present (in game) |
| Up-n-Atom Burger Vinewood | none | DLC pack vw_upna present (in game) |
| Elgin/Hawick 24/7 | none | DLC pack elg_247shop present (in game) |
| Vinewood Plaza 24/7 | none | DLC pack vwp_247shop present (in game) |
| GTA V Remastered: Enhanced | none | DLC pack vremastered present (in game) |
| Traffic V FEAR Edition | none | update/update.rpf > common/data/levels/gta5/popcycle.dat; update/update.rpf > x64/levels/gta5/popgroups.ymt |
| Drive V for NVE | none: optional extras moved to its notes (not part of the install) | onigiri/common/data/handling.meta present |
| MaxedV (Enhanced, alpha) | **by hand:** the download isn't checked yet; its page's steps were written for Legacy | its logged files are in place |
| Prime Realism V (Enhanced) | **by hand:** it needs ReShade installed by ReShade's own installer, a program Leonida doesn't run for you | its logged files are in place |
| Dynamic Vehicle First Person Camera | none | DynamicVehicleFirstPerson.asi loaded |
| Quality of Life Vehicle Fixes Pack [Replace] | none | DLC pack qolpack_g9 present (in game) |
| Food Delivery Job (Uber Eats, DoorDash driver) | none: Decline key locked in FoodDelivery.ini before the first start | FoodDelivery.dll in scripts |
| Ryde - Rideshare Driver Mod | none: keys locked in RideShare.ini before the first start | RideShare.dll in scripts |
| Better Fist Fighting | none | update/update.rpf > common/data/action/damages.meta |
| VisualV | none | update/update.rpf > common/data/visualsettings.dat |
| MP Jason & Lucia V (free heads + outfits) | **by hand:** the download isn't checked yet (heads go inside mppatches.rpf, outfits load in Menyoo) | its logged files are in place |
| GTA VI loading screens (HUD add-on) | none | update/update.rpf > x64/data/cdimages/scaleform_frontend.rpf/loadingscreen_startup.gfx |
| iOS 26 App Icons (phone) | none | update/update.rpf > x64/data/cdimages/scaleform_generic.rpf/cellphone_ifruit.ytd |
| AuraV Lite (path tracing) | **by hand:** DLSS has to be switched on in the game's own graphics menu (its settings.xml value isn't known yet) (files copied automatically; ray tracing written to settings.xml) | AuraV.asi loaded |
| Forza Horizon 6 Roads (road textures) | none | DLC pack FALK_FH6Roads present (in game) |
| Liberty Suspension (GTA IV handling) | **by hand:** the .ini it writes after the first start (MenuKey / ToggleKey) isn't in the download, and the page doesn't name it; once one real file is read, Leonida locks the two keys before the first start (the key rebind waits for its real .ini (see why)) | LibertySuspensionMod.cs in scripts |
| Liberty Damage (GTA IV damage) | **by hand:** the page doesn't name its script or .ini file; the same as Liberty Suspension once read | its logged files are in place |
| DLC Vehicle Traffic Popgroups | none: its popgroups.ymt copied into onigiri automatically | onigiri/platform/levels/gta5/popgroups.ymt present |
| The Downtown Cab Co. Pack | none | its logged files are in place |
| Fuel Reloaded + Coil Display | **by hand:** its install steps are in a text file inside the download, which isn't read yet | its logged files are in place |
| Immersive Enhanced Sound Pack (weapons) | none | mods/x64/audio/sfx/WEAPONS_PLAYER.rpf present; mods/x64/audio/sfx/RESIDENT.rpf present |
| Leonida menu (in game) | none | LeonidaMenu.3.cs in scripts |

With NaturalVision Enhanced (paid) ticked, several mods go into NVE's `onigiri` folder by hand: Leonida's archive engine writes the `mods` folder, which NVE's loader doesn't read.

## In game, once (for exe-build's Leonida menu)

| Mod | Action | When | Proof | Why |
| --- | --- | --- | --- | --- |
| GTA VI-Inspired HUD (geckomacabre) | `check` | first-load | GET_CURRENT_LANGUAGE = 0 (in game) | the HUD supports English only; the game's language is the store's / launcher's setting (Steam, Epic, Rockstar), which Leonida can't change |
| Enable All Interiors | `reload-scripts` | verify-fails | scripts/EAIInitalization.log: 'MP MAPS LOADED' | Enable All Interiors loads the online maps by itself at the start (its log: GAME START -> REQUEST MP MAPS -> MP MAPS LOADED, no key pressed); if they aren't loaded a minute after story mode, the Leonida menu reloads the scripts once through Script Hook V .NET's own reload key (Insert, locked by Leonida), which its page says loads them |

## Can't be automated (yet)

- **NaturalVision Enhanced**: paid: the files inside 'Main Package' aren't public, so Leonida can't map them until a bought package is checked; NVE's own recommended in-game graphics settings aren't published either.
- **GTA VI HUD (fbicat)**: Discord only (no public page), and only instead of the core HUD.
- **GTA VI Inspired Features, HUD & Radar System (Enhanced package)**: its page was removed; no official download.
- **Lively World Expansion (Enhanced build)**: paid: the package layout (its .oiv, density folders) has to be checked in a bought copy first.
- **Jason Duval + Lucia Caminos models**: paid: what the buyer downloads and the install steps aren't public.
- **MaxedV (Enhanced, alpha)**: the download isn't checked yet; its page's steps were written for Legacy.
- **Prime Realism V (Enhanced)**: it needs ReShade installed by ReShade's own installer, a program Leonida doesn't run for you.
- **MP Jason & Lucia V (free heads + outfits)**: the download isn't checked yet (heads go inside mppatches.rpf, outfits load in Menyoo).
- **AuraV Lite (path tracing)**: DLSS has to be switched on in the game's own graphics menu (its settings.xml value isn't known yet).
- **SourceMotion (procedural ragdoll)**: not installed by any pack (the same job as NextGen Euphoria).
- **Central Real-Life Traffic and Environment**: paid: its download and install guide are members-only posts.
- **Liberty Suspension (GTA IV handling)**: the .ini it writes after the first start (MenuKey / ToggleKey) isn't in the download, and the page doesn't name it; once one real file is read, Leonida locks the two keys before the first start.
- **Liberty Damage (GTA IV damage)**: the page doesn't name its script or .ini file; the same as Liberty Suspension once read.
- **Fuel Reloaded + Coil Display**: its install steps are in a text file inside the download, which isn't read yet.
- **Legacy (GTA5.exe):** archive mods stay by hand with OpenIV until Leonida's archive helper reads GTA5.exe's keys (a `build/` change).

## Ready-made setups (`leonida/manifest/setups.json`)

One click picks the pack, variant and add-ons. The mods' settings and GTA's `settings.xml` follow from the variant and the PC. Commands:
- `leonida setup list | best | choose [id]` shows the setups, picks the best one for this PC, or chooses one;
- `leonida setup export [file] / import <file>` shares your own setup;
- `leonida setup build <folder>` writes a `<id>.modpack.json` lockfile per setup for a release, from the matched downloads on the PC that tested it.

| Setup | Pack · variant | Add-ons | PC needs | Tested on |
| --- | --- | --- | --- | --- |
| **Owner's pick · 32 GB** (`owner-32gb`, enhanced) | owner-pick · ram32 | owner-gun-sounds | ramMinGB 24, vramMinGB 8 | not yet |
| **Owner's pick · 16 GB** (`owner-16gb`, enhanced) | owner-pick · ram16 | owner-gun-sounds | ramMinGB 12, vramMinGB 6 | 1.0.1013.20 |
| **Showcase · RTX** (`showcase-rtx`, enhanced) | video-setup · ultra | roads, first-person-car, side-jobs, loading-screens, phone-icons, path-tracing | ramMinGB 24, vramMinGB 12, rtx True | not yet |
| **Showcase · 8 GB card** (`showcase-gtx`, enhanced) | video-setup · balanced | roads, first-person-car, side-jobs, loading-screens, phone-icons | ramMinGB 12, vramMinGB 6 | 1.0.1013.20 |
| **Max · RTX 50** (`max-rtx50`, enhanced) | max-rtx50 | - | ramMinGB 16, gpu rtx50 | not yet |
| **Plus · Balanced** (`plus-balanced`, enhanced) | core-plus · balanced | - | ramMinGB 12, vramMinGB 4 | not yet |
| **Core · laptop** (`core-laptop`, enhanced) | core | - | ramMinGB 8, vramMinGB 2 | 1.0.1013.20 |
| **Legacy · Core** (`legacy-core`, legacy) | core | - | ramMinGB 8 | not yet |

The best setup for the owner's PC (16 GB RAM, GTX 1070 with 8 GB): **Owner's pick · 16 GB**.
