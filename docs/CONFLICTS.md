# Conflicts in the owner's pick, and how Leonida settles them

This is an audit of **Leonida (owner's pick)** on GTA V Enhanced, done on 2026-11-25. It's built from the real
downloads in `D:\Leonida\Downloads`, read and never installed:
- the dry run of every file each mod writes;
- every entry the `.oiv` packages write inside an archive (`leonida.rpf.parse_oiv_file`);
- the mods' own `.ini` keys;
- the authors' pages.

For each clash, the rule that settles it is in the manifest, so the pack can't install a clashing pair:
- **slot:** one mod per job;
- **whenSelected / whenMissing skip:** either/or;
- **locked keys:** `settings`;
- **pair warnings:** `warnings`;
- **build ranges:** `gameBuilds`.

`tests/test_owner_pick.py` checks that no either/or pair ever installs both, there's no check error, and no two
selected mods use the same key.

## Same files

| Mod A | Mod B | What clashes | How Leonida settles it |
| --- | --- | --- | --- |
| LemonUI | GTA VI-Inspired HUD (.oiv), Street Food Vendors (bundled) | all three write `scripts\LemonUI.SHVDN3.dll` | all three are LemonUI **2.2.0.0** (checked). The later step overwrites an identical file, and rollback restores the earlier copy |
| GTA VI-Inspired HUD | GTA V Remastered | both edit `update.rpf\common\data\gameconfig.xml` (builds before 1.0.1158.13) | different pools, and both edits are raise-only (a higher value is never lowered); tested with the real helper on the real 1.0.1013.20 file |
| GTA VI-Inspired HUD | Benny's, Map Updates, the MLO shops, GTA V Remastered, Jason Duval House | all add lines to `update.rpf\common\data\dlclist.xml` | additive: each line is added only if it isn't there; no pack name is used twice (checked) |
| Drive V | Liberty Suspension + Liberty Damage | handling at runtime on top of Drive V's `handling.meta`; Liberty Damage's page: "x5 damage to engines" with Drive V | **either/or**: the *GTA IV handling* choice skips Drive V (and Drive V for NVE) |
| Traffic V FEAR | DLC Vehicle Traffic Popgroups | both replace `popgroups.ymt` (Traffic V also `popcycle.dat`) | **either/or**: the Popgroups choice skips Traffic V. Popgroups needs NVE's onigiri, so its choice brings NVE, and it's unsupported before 1.0.1158.13 (it needs the Kortz Center Heist cars) |
| Quality of Life Vehicle Fixes | The Downtown Cab Co. Pack | both replace the vanilla Taxi | load order: the QoL Taxi is in its DLC pack `qolpack_g9`; Downtown Cab Co. installs after it (order 73 vs 57), so its `dlclist.xml` line is later and its Taxi wins if its .oiv brings the Taxi as a DLC pack. **Not checked yet:** the .oiv isn't downloaded; if it replaces the Taxi in the base archives instead, the QoL pack's would still show |
| GTA V Remastered | Lively World Expansion (paid) | both plant trees in the same countryside ("trees inside trees") | slot `vegetation`; ticking LWE skips Remastered |
| NaturalVision Enhanced (paid) | Drive V, OpenRPF, Traffic V, Map Updates, the HUD | NVE's onigiri loader replaces the `mods` folder | with NVE: OpenRPF is skipped, Drive V becomes *Drive V for NVE*, and the other mods' steps go into onigiri (whenSelected `nve`) |
| NaturalVision Enhanced | ChromatiX (paid) | two graphics overhauls overwrite each other's timecycles | slot `graphics`; ChromatiX isn't offered (NVE: 4 sources, ChromatiX: 1) |
| Resource Extensions | XtremeTool, Heap / Packfile / Modkit adjusters, Dispatch Reworked's gameconfig | two limit adjusters patch the same memory | XtremeTool isn't offered. Resource Extensions' `conflicts` list makes `leonida check` stop on old adjusters; a loose `gameconfig.xml` in the game folder is an error |
| GTA VI Combat Camera | Dynamic Vehicle First Person, Camera Flinch | cameras | no overlap: Combat Camera is the only `cameras.ymt` (on-foot aim cameras); DFP works at runtime in cars only; Flinch is a script shake on foot |
| NextGen Euphoria | SourceMotion | ragdoll (`physicstasks.ymt` vs its own) | slot `euphoria`; SourceMotion isn't offered |

## Features: one job, one mod

Every mod in `mods.json` / `mods-legacy.json` has a `features` list, words from a fixed vocabulary in
`leonida/features.py`, for example `hud`, `fuel`, `vehicle-handling`, `ragdoll`, `interiors-fastfood`. Rules:
- **Error:** two selected mods with the same feature are an error in `leonida check` (`feature-clash`).
- **Unless a record says how they coexist:** one of them carries
  `sharesFeature: {feature, with, how, verified}`, i.e. a part switched off by a locked setting, a load order, or
  truly different parts.
- **Not checked here:** either/or pairs never meet (a whenSelected skip takes one out first), and mods in one slot are
  left to the slot check.
- **Tested:** `tests/test_features.py` checks every pack, with every add-on, on 1.0.1013.20, 1.0.1158.16 and Legacy.
  None has an unsettled pair.

| Mod A | Mod B | Same feature? | How Leonida settles it | Verified |
| --- | --- | --- | --- | --- |
| GTA VI HUD (fuel) | Fuel Reloaded | yes: `fuel` | the HUD's `[FuelStation] BurnFuel` locked to False while Fuel Reloaded is selected | locked setting (test); whether the HUD's pump prompt still shows: **in game** |
| GTA VI HUD (police AI, wanted box) | anything dispatch | `police-ai`, `wanted-system`: no other mod in any pack has them | Dispatch Reworked stays out (not in the owner's sources; it needs a replaced gameconfig) | n/a |
| Enable All Interiors (its hidden interior blips) | GTA VI HUD (3D minimap) | the minimap finds every blip itself, so the online businesses' icons Enable All Interiors creates and hides (`ENABLEBLIPS = False`) showed at its edge (sprite 500 money factory, 677 container; screenshot 2026-11-25) | Leonida adds the online-only property sprites to the minimap's `HiddenBlips` (`scripts\MiniMap.settings`) while Enable All Interiors is selected | the screenshot; **in game** after `leonida settings apply` |
| Enable All Interiors | Open World Interiors | no: `interiors-mp` (the online interiors) vs `interiors-open-world` | they open different interiors | the mods' pages |
| Open World Interiors | Burger Shot, Up-n-Atom (walk-in) | yes: `interiors-fastfood` | recorded as **unknown**: Open World Interiors opens the game's fast-food places, and the walk-in mods fill buildings Rockstar left empty | **in game** (owner's checklist) |
| Burger Shot | Up-n-Atom; Elgin 24/7 / Vinewood 24/7 | yes: `interiors-fastfood`, `interiors-shop` | different buildings (coordinates on their pages) | their pages |
| Jason Duval House | Map Updates | yes: `map-additions` | different places (Banham Canyon vs the casino front, La Mesa police, Lester's house) | their pages |
| Drive V | Liberty Suspension / Liberty Damage | yes: `vehicle-handling`, `vehicle-damage` | either/or: the *GTA IV handling* choice skips Drive V (Liberty Damage's page: "x5 damage to engines" with Drive V) | the pages; `tests/test_owner_pick.py` |
| Drive V for NVE | Better Vehicle Deformation | yes: `vehicle-handling`, `vehicle-damage` | load order: its `handling.meta` (made from Drive V for NVE) replaces Drive V for NVE's on purpose | the real download |
| NextGen Euphoria | Better Fist Fighting / ActionsV / Immersive Combat | no: `ragdoll` (`physicstasks.ymt`) vs `melee` (`damages.meta`) vs `actions-animations` vs `weapon-damage` (`weapons.meta`) | different files and jobs | the real downloads |
| NextGen Euphoria | SourceMotion | yes: `ragdoll` | slot `euphoria`: only one | slot check |
| Combat Camera / Camera Flinch / Dynamic First Person / the HUD's crash camera | each other | no: `camera-aim` (`cameras.ymt`), `camera-shake-hit` (a script), `camera-vehicle-firstperson`, `camera-crash` (vehicle-only) | different cameras | files and pages; the HUD's *camera weight* option: **in game** |
| Traffic V | DLC Vehicle Traffic Popgroups | yes: `traffic-population` (both `popgroups.ymt`) | either/or: the Popgroups choice skips Traffic V; it needs NVE and 1.0.1158.13+ | `tests/test_owner_pick.py` |
| Traffic V | All MP Vehicles | yes: `traffic-population` | All MP Vehicles' `spawn_traffic` locked to False with Traffic V | locked setting |
| Traffic V | Map Updates | no: Map Updates' `.oiv` writes no `popgroups` / `popcycle` (only map files and a valet scenario) | n/a | the real `.oiv` |
| Menyoo | other trainers | `trainer`: no other trainer in any pack | n/a | |
| Immersive weapon sounds | anything audio | `weapon-sounds`: the only audio mod in the packs (not with RateV, its page says) | n/a | the real download (`x64\audio\sfx`) |
| iFruitAddon2 | its copies | `phone-contacts`: only Enable All Interiors ships it (checked in every download) | n/a | the real downloads |
| GTA V Remastered | Map Updates / Map Fixes | no: `vegetation` vs `map-additions` vs `map-fixes` | different jobs | the pages |
| Map Fixes | Bugstar Fixes | yes: `map-fixes` | made together: Bugstar requires Map Fixes and installs after it | both ReadMes |
| GTA V Remastered | Lively World Expansion | yes: `vegetation` | slot `vegetation`; ticking LWE skips Remastered | slot check |
| GTA VI HUD | GTA V Remastered (gameconfig) | yes: `gameconfig-pools` | different pools, both raise-only, builds before 1.0.1158.13 only | the real helper on the real file |
| GTA VI HUD (Leonida Customs) | Benny's | yes: `vehicle-tuning` | different places: Benny's garage in Strawberry, and the HUD's own shop | **in game** |
| GTA VI HUD (binoculars) | ActionsV (binoculars) | yes: `binoculars` | separate menus and keys | **in game** |
| NVE | Straight To Story Mode | yes: `startup-skip` | no clash reported, but the HUD's guide says another start-up shortcut (AuraV's) crashes NVE's loader | **in game, with NVE** |
| VisualV / Prime Realism V | AuraV | yes: `sky` | AuraV's path-traced sky over theirs | **in game** (AuraV's card: "untested together with VisualV") |

## Scripts doing the same job

| Mod A | Mod B | Job | How Leonida settles it |
| --- | --- | --- | --- |
| GTA VI-Inspired HUD | GTA VI HUD (fbicat), GTA VI MiniMap 3D | HUD, 3D minimap | slot `hud`; fbicat's isn't offered; the MiniMap mod is gone (the HUD also deletes an old `MiniMap.asi`) |
| GTA VI-Inspired HUD (fuel, pumps, nozzle) | Fuel Reloaded | fuel | **either/or**: with Fuel Reloaded the HUD's `[FuelStation] BurnFuel` is locked to False |
| GTA VI-Inspired HUD (police AI, tasers, surrender) | Dispatch Reworked | police | not offered: it's not in the owner's sources, and it wants a replaced gameconfig and old adjusters |
| GTA VI-Inspired HUD (crouch, crawl) | "Stance" (jedijosh920) | crouch / prone | not offered (Legacy-era; J or Left Ctrl) |
| GTA VI-Inspired HUD (gym, dealership) | Gymnasium, Simmy Car Lots | gym, car lots | not offered (Legacy-era / broken, E clashes) |
| Benny's Revamped | Single Player Benny's Original Motor Works | Benny's | Revamped is its Enhanced rewrite; the 2020 original isn't offered |
| Enable All Interiors | Open World Interiors, the MLO shops | interiors | different jobs: Enable All Interiors loads the online interiors; Open World Interiors opens story-mode ones; the MLO shops add new ones. **Unconfirmed** whether Open World Interiors also opens the Burger Shot / Up-n-Atom buildings the MLOs fill. Check it in game (docs/IN-GAME-CHECKS.md, part 4-5) |
| Liberty Suspension / Liberty Damage | Enable All Interiors (Insert) | script reload | a pair warning: their multipliers stack again on every script reload (comments), and Insert is the reload key Enable All Interiors needs. After changing their settings, restart the game |

## SHVDN and ASI versions

There are no double versions in the pack:
- **.NET scripts:** one Script Hook V .NET (Enhanced, no Community SHVDN), one LemonUI (SHVDN3 build).
- **.asi:** Menyoo, ActionsV, Dynamic First Person, Resource Extensions, OpenRPF and DirectStorageFix are each a
  single `.asi`.

Two related rules:
- **Script reload timeout:** Enable All Interiors' MP-map load needs a longer timeout, so `ScriptTimeoutThreshold` is
  locked to 15000.
- **`xinput1_4.dll`:** Script Hook V's own `xinput1_4.dll` replaces any loader DLL already there. The original is
  backed up first.

## Keys

| Key | Mod A | Mod B | How Leonida settles it |
| --- | --- | --- | --- |
| F10 | GTA VI-Inspired HUD (reload settings) | ActionsV (menu), Ryde (menu), Liberty Damage (on/off) | locked: ActionsV F7, Ryde Page Up; Liberty Damage set to NumPad5 by hand |
| F9 | Menyoo (Spooner) | Ryde (cancel) | locked: Ryde Page Down |
| F7 / F8 | ActionsV / Menyoo | Liberty Suspension (menu / on-off) | set to NumPad7 / NumPad8 by hand (its .ini appears after the first start) |
| F6 | Food Delivery (menu) | Liberty Damage (menu) | Liberty Damage set to NumPad4 by hand |
| N | Dynamic First Person (next camera, in a car) | Food Delivery and Ryde (decline an offer while you drive) | locked: Food Delivery Decline = Delete, Ryde Decline = End |
| Y | Food Delivery (accept) | Ryde (accept); both offers can show while you drive | locked: Ryde Accept = Home |
| Y, N | GTA VI-Inspired HUD (greet, push-ups: on foot) | Food Delivery accept (in a car) | context-split: on foot vs an offer in the car. Left as is |
| E | GTA VI-Inspired HUD (pump, surrender), Street Food (buy), Food Delivery (interact) | each other | context-split: each only near its own thing. With Fuel Reloaded (E or horn), the HUD's fuel is off |
| Insert | Enable All Interiors (script reload) | Liberty mods | see the pair warning above |
| H | GTA VI-Inspired HUD (activities) | DropWeapons (hard-coded) | DropWeapons isn't offered |

`leonida keys` lists the keys of your selection and any clash. Keys that only one mod uses, or that only work in
different situations, are listed above for completeness.
