# In-game checks: does each mod really work?

Leonida's **Play test** proves the mods *load* (it reads their logs). This page is the other half: a short route
through the map where you **see** each mod of the **Leonida Showcase (GTA VI)** pack working, on GTA V Enhanced
1.0.1013.20. About 15 minutes. The same checks are in `mods.json` (`checks` for each mod), so Leonida can show them
after a play test.

**Fast travel:** Menyoo (**F8**) > *Teleport* takes you to a place or to coordinates; *Time* / *Weather* change the
light. All coordinates below come from the mods' own pages.

---

## Owner's checklist: still to confirm in game (owner's pick, 2026-11-25)

The conflict audit (docs/CONFLICTS.md) couldn't settle these from the files alone. Tick them off once, and tell the
project what you saw.

- [ ] **Before playing (16 GB PC):** have about **6 GB of RAM** and **12 GB of commit** free (commit is RAM plus page
      file). Close browsers, chat apps and other launchers first. Play and Play test now check this. When memory is
      low they say "GTA may crash while loading: free memory is low", list the biggest memory users, and offer
      **Close them and play** (only the apps you tick, each closed like clicking its X) or **Play anyway**. The
      owner's play tests, 2026-11-25:
  - **About 4.6 GB free** (Firefox, Discord and Claude open): about **4 crashes in 19 loads**, at 72–79 s, before
    story mode. Free RAM dropped to 0.5 GB and the commit charge reached 96% of the limit during loading.
  - **5.8–6.3 GB free, 14–15 GB of commit free** (Firefox and Discord closed): **8 of 8 loaded**, story mode in
    72–77 s, no crash dumps.
  - The crashes were at two places in the game, `GTA5_Enhanced.exe+0xBCC6AD` (a null pointer) and `+0x1516B9`. Both
    happened with the HUD's ViMinimap/ViPreload ASIs on and off, so the HUD isn't the cause. Low memory made them
    more likely, but `+0xBCC6AD` came back on 2026-11-26 with 3.5 GB free. It turned out to be the GTA IV Burger
    Shot Interior when the save spawns on the west coast: see "Known crashes" below.
  - Check: `leonida playtest --repeat 8` shows the free RAM and commit before each run, grouped by passed and
    crashed runs.
- [ ] **Open World Interiors vs the walk-in restaurants:**
  - Walk into the **Burger Shot** in Vespucci and the **Up-n-Atom** on Vinewood (X 80.76, Y 273.01). There should be
    one interior each: no doubled walls, tables or counters, no props floating or poking through, and the doors work.
  - If something is doubled, note which building. The fix is to switch that restaurant off in
    `scripts\OpenWorldInteriors.ini`.
  - On game build 1.0.1013.x the Burger Shot is off (the `+0xBCC6AD` loading crash), so only the Up-n-Atom applies.
- [ ] **Food Delivery and Ryde keys:**
  - On a delivery offer, **Delete** declines it. On a ride offer, **Home** accepts and **End** declines.
  - In a car in first person, **N** switches the camera and declines nothing.
- [ ] **Only with *GTA IV handling* chosen** (Liberty Suspension + Liberty Damage):
  - After the first game start, their `.ini` files are in `scripts`. Set the keys there (Suspension: MenuKey
    NumPad7, ToggleKey NumPad8; Damage: menu NumPad4, on/off NumPad5) and restart the game.
  - Then **F7** opens only ActionsV, **F8** only Menyoo, **F6** only Food Delivery, and **F10** only reloads the HUD.
  - Drive V is not installed.
  - Change a Liberty setting, restart (don't use Insert to reload), and drive: the car shouldn't get stiffer each
    time.
- [ ] **Only with *Fuel Reloaded* chosen:** one fuel gauge only (Fuel Reloaded's). The HUD's pump prompt is gone or
      does nothing.
- [ ] **Only with *Downtown Cab Co.* chosen:** taxis in traffic are the Downtown Cab Co. ones, with no missing
      textures, not the Quality of Life pack's Taxi (Downtown Cab installs after it and should win by load order).
- [ ] **Immersive weapon sounds:** a pistol and a rifle sound different from vanilla, and shotguns aren't silent.
- [ ] **Minimap icons:** after `leonida settings apply`, the minimap near Michael's house shows no small card-and-hand icons (online money factories) or striped container icons. A blue "?" is the game's own Strangers & Freaks marker and stays.
- [ ] **Two mods with the same job** (docs/CONFLICTS.md, *Features*):
  - [ ] **Benny's vs the HUD's Leonida Customs:** drive into Benny's in Strawberry, then into the HUD's own shop.
        Each opens one tuning menu, never two at once.
  - [ ] **Binoculars:** ActionsV's binoculars (F7 menu) and the HUD's work one at a time, with no doubled overlay.
  - [ ] **Cameras:** with the HUD's *camera weight* on, getting punched shakes the camera once (Camera Flinch), not
        twice; aiming still uses the GTA VI Combat Camera.
  - [ ] **Only with NVE:** the game starts straight in story mode (Straight To Story Mode and NVE both skip the
        start-up screens) and NVE's loader doesn't crash.
- [ ] **The Leonida menu** (`docs/LEONIDA-MENU.md`):
  - F5 opens it. Status shows your pack, variant and build; the footer says "Leonida is running" while Leonida
    is open.
  - Mods > Leonida menu > Keys/Open: pick F12 and press Enter. Status says it was applied; after *Tools > Reload
    scripts*, F12 opens it.
  - With iFruitAddon2, calling "Leonida" on the phone opens it.
  - `leonida playtest --deep` reports "LeonidaMenu built every page" and "talk both ways".

## Before you start (1 minute)

1. **Settings > Graphics: Screen Type = Windowed Borderless**, and the game in **English**. The HUD needs both.
2. Start the game from the **Leonida V** shortcut or `PlayGTAV.exe`.
   - **Straight To Story Mode:** no legal, splash or landing screens; it goes straight into story mode.
   - **GTA VI loading screens:** Vice City pictures while it loads.
3. Nothing to press: Enable All Interiors loads the online interiors by itself at the start, and if they aren't there a minute later, the Leonida menu reloads the scripts once (docs/ZERO-TOUCH.md).

## The route

### 1. Where you are (2 minutes)
- **GTA VI-Inspired HUD:**
  - the GTA VI HUD and the 3D minimap; set a waypoint, and the route is **teal** (missions are **pink**);
  - hold **V** for its settings, hold **Left Alt** for the character cards, **K** for skills;
  - **Left Ctrl** twice crouches, **Right Ctrl** lies down.
- **Script Hook V .NET:** **F4** opens its console (close it again with F4).
- **Menyoo:** **F8** opens it (**F9** Spooner, **F3** free camera).
- **iOS 26 icons** (Michael or Franklin): **arrow up** for the phone; the app icons are iOS 26-style.
- **Enable All Interiors:** its menu is in the phone.
- **ActionsV:** **F7** opens its menu; try *smoke* or *binoculars*.
- **DirectStorageFix:** change one HUD setting (hold V). Next time you start the game, it's still changed.

### 2. Look at the world (2 minutes)
- **VisualV:** with Menyoo > *Time*, try midday, sunset and night. You should see:
  - a clearer, warmer sunny day and deeper sunset colours;
  - real fog, and the moon rising in the east.
- **Forza Horizon 6 Roads:** fresh asphalt, crosswalks and sidewalks on any city street.
- **GTA V Remastered:** many more trees and bushes. Drive up into the Vinewood Hills.

### 3. Get a car (3 minutes)
- **Drive V (7.4):**
  - steering is slower to react, there's body roll in corners, and top speeds are realistic;
  - hit a wall at speed: the car dents much more than in vanilla.
- **All MP Vehicles in SP:** online-only cars drive in traffic and stand in parking lots. They have **no blips**.
- **Resource Extensions:** on game build 1.0.1158.13 or newer, streets and parking lots are fuller on *Balanced* /
  *Ultra* than on *Performance*. On older builds (1.0.1013.20) its density settings do nothing (its log: *Population
  Density (INI): Inactive*), so the three variants look the same there.
- **Dynamic first-person car camera:** tap **V** in the car for first person. The camera moves with the road and
  your head; **N** switches its camera position.
- **HUD fuel:** at a gas station, on foot, **E** at a pump takes the nozzle, and **E** again at the car's fuel cap.

### 4. Vinewood (3 minutes)
- **Up-n-Atom** on Vinewood (X 80.76, Y 273.01): walk in. There's a full interior with people inside.
- **Vinewood Plaza 24/7** (X 200.84, Y -29.87): a full interior with restrooms and a storage room.
- **Elgin Avenue 24/7**, Hawick (X 528.28, Y -157.25): a full interior with restrooms and a back room.
- **Map Updates:** the Be Lucky Casino front has doors and a valet instead of the "Opening Soon" banner.
- **Enable All Interiors:** the game's online interiors (casino, apartments) can be entered.

### 5. South Los Santos and Vespucci (3 minutes)
- **Benny's Motor Works:** drive into Benny's Original Motor Works in Strawberry. Its tuning menu opens.
- **Map Updates:** La Mesa police station has a custom interior.
- **Burger Shot**, Vespucci: the building Rockstar left without an interior. Walk in: dining room, bathrooms, kitchen
  and walk-in freezer.
- **Street Food Vendors:** on **Del Perro Pier**, stand at a hotdog or burger stand or the Cherry Popper kiosk and
  press **E**. A menu sells food that heals you.
- **Map Fixes:** on **Vespucci Beach** the volleyball nets' collisions match the nets, and the beach huts look right
  from far away.
- **Bugstar Fixes:** palm-tree leaves look right close up. Most fixes are small; mostly you notice nothing broken.

### 6. Fight (2 minutes)
- **NextGen Euphoria:** shoot a pedestrian in the leg, or knock one over with a car. They stumble, try to keep their
  balance and fall naturally.
- **Immersive Combat:** guns kick and hit harder.
- **GTA VI Combat Camera:** aim a pistol, then a rifle. The camera sits further back, more of your character shows
  and the crosshair stays centred.
- **Camera Flinch:** get punched or shot. The camera shakes briefly.
- **HUD police:** with a wanted star you get the **wanted box** and the police lights at the screen edge. Police try
  to tase you; hold **E** facing a cop to surrender.

### 7. Jobs and the rest (2 minutes)
- **Food Delivery:** **F6**, go on duty. Accept an order with **Y** (**Delete** declines), pick it up with **E**,
  follow the GPS.
- **Ryde (rideshare):** **Page Up**, go on duty, accept a ride with **Home**, decline with **End** (**Page Down**
  cancels). Leonida moved these keys off F10, F9, Y and N, which the HUD, Menyoo, Food Delivery and the first-person
  car camera use (docs/CONFLICTS.md).
- **Jason Duval House:** a new house in the hills of Banham Canyon / Pacific Bluffs.

Done. Back in Leonida: **Manage > Check the game's logs (after playing)**, or `leonida verify`.

---

## What broken looks like, and what to do

The way out for every mod is the same:
- `leonida verify` (or **Manage > Check the game's logs**) says which mods loaded.
- **Undo** a step: **Manage > Undo last step**, or `leonida rollback <step>` (`leonida status` lists the steps).
- To check whether it's mods at all: **Online-safe ON** moves every mod out; OFF brings them back.

| Mod | Looks broken when | Do this |
| --- | --- | --- |
| Script Hook V | no script mod works; the game says "unknown game version" | `leonida verify`; GUIDE part 10 |
| Script Hook V .NET | no HUD, F4 does nothing | open `ScriptHookVDotNet.log` and `asiloader.log`; install .NET 4.8 / VC++ x64; check your antivirus quarantine |
| DirectStorageFix | the HUD's settings reset on every start | `leonida verify`; reinstall the step |
| OpenRPF | none of the archive mods show (no shops, no new roads) | check `asiloader.log` lists `OpenRPF.asi` |
| Resource Extensions | a crash while loading | check `ResourceExtensions.log`. On builds before 1.0.1158.13 it says *Packfile Limit* and *Engine Pools: Inactive*; there Leonida raises the pools in `mods\update\update.rpf\common\data\gameconfig.xml` instead (the HUD's five, GTA V Remastered's Building / phInstGta / StaticBounds; `leonida check` shows *gameconfig-pools*). Still crashing: undo GTA V Remastered first, then the walk-in shops |
| GTA VI-Inspired HUD | no minimap | `ViMinimap.asi` must be next to `GTA5_Enhanced.exe`; Windowed Borderless |
|  | a crash a few seconds after loading | `ViPreload.asi` must be next to the exe |
|  | the pause menu looks wrong | it was made on 1.0.1158; undo the step and report it |
| GTA VI loading screens | the game's own loading screens | the step didn't install; reinstall it |
| Combat Camera | the aim camera is odd or jumps | undo the step (it was made on 1.0.1158) |
| NextGen Euphoria / Immersive Combat | peds freeze or slide instead of falling | undo Immersive Combat first, then Euphoria |
| Drive V | cars barely turn or explode at small hits | undo the step; make sure Liberty Damage isn't installed too |
| Map Fixes / Bugstar Fixes | a crash while loading, missing buildings | undo Bugstar, then Map Fixes; `leonida verify` |
| Walk-in shops | the door stays closed or you fall through the floor | undo that shop's step; check that the game build is 1.0.1013.17 or newer |
| Enable All Interiors | falling through floors in online interiors | `scripts\EAIInitalization.log` should say *MP MAPS LOADED*; if not, press **Insert** once (the Leonida menu normally does it for you) |
|  | online interiors missing, and `ScriptHookVDotNet.log` says *Blocking script! Script EnableAllinteriors.LoadMPMaps ... was terminated because it caused the game to freeze too long* | `ScriptTimeoutThreshold` in `ScriptHookVDotNet.ini` must be **15000**: Leonida locks it whenever Enable All Interiors is in your pack; run `leonida settings apply` (or **Manage > Restore all**) and press **Insert** again |
| VisualV | a crash at start, or a strange night sky texture | undo the step; tell the project which (a comment says some files weren't converted for Enhanced) |
| GTA V Remastered | a crash while loading | on builds before 1.0.1158.13 Leonida raises Building 70000 / phInstGta 20000 / StaticBounds 20000 in `gameconfig.xml` (its troubleshooting.txt, the HUD's Legacy guide): reinstall its step if they're missing, or undo it |
| Forza Horizon 6 Roads | black or flickering roads | undo the step |
| Menyoo / ActionsV / Food Delivery / Ryde | the key does nothing | `leonida keys` for clashes; check its `.ini` in `scripts` |
| iOS 26 icons | broken or blank phone icons | undo the step |

When in doubt: undo the last step, play again, and tell the project what you saw (the mod, the place, and what
`leonida verify` says).

## Known crashes

These were found on the owner's PC (GTA V Enhanced 1.0.1013.20, 16 GB of RAM, 16 GB page file) on 2026-11-25,
from the game's own crash dumps. The dumps are in `%LOCALAPPDATA%\Rockstar Games\GTAV Enhanced\CrashLogs`, not
in Windows' CrashDumps. To read the same evidence on any PC:
- `leonida playtest --repeat N` gives each crash's site, its stack, and the free memory before each run.
- `leonida report` adds `results/crash-dumps.txt`.

A crash *site* is the place in the game where it failed, like `GTA5_Enhanced.exe+0x1516B9`. The same site means
the same bug.

### `GTA5_Enhanced.exe+0x1516B9`: Enable All Interiors and the Tuners auto shop

- **Seen:** 3 times (10:50, 15:01 and 16:19), 65–92 s after the launch, while story mode starts. The player was at
  Michael's house during `startup_positioning`. It happened with the HUD's Vi ASIs on and with them off.
- **What the dumps show:** all three are identical.
  - The crash is an access violation reading a wild address, on the game's script thread.
  - The calls lead back to it: `GTA5_Enhanced.exe+0x1D28607` ← `ScriptHookV.dll+0xE55B` (Script Hook V's native
    call) ← `clr.dll` ← `ScriptHookVDotNet.asi`. So a Script Hook V .NET script called a native.
  - The native is `0x55E86AF2712B36A1`, **ACTIVATE_INTERIOR_ENTITY_SET**. Script Hook V .NET's own list of natives
    gives the name.
  - The interior ID it was given is not a real one: its pool index was 0x1ED03A–0x45F8DC, while real interior IDs
    have an index of about 0x300.
  - Left on the stack: `entity_set_car_l…car_lift_default` and `…nterior_0_tuner…`.
- **Cause:** Enable All Interiors (`EnableAllinteriors.dll`). It's the only script in the pack that has the
  Tuners auto shop's names (`tr_interior_0_tuner_mod_garage_milo_`, `entity_set_car_lift_*`). Its log puts its
  interior work 78–87 s after the launch ("REQUESTING ALL INTERIORS", then the mansions). It activates the auto
  shop's car-lift entity set (`[TUNERGARAGE] CARLIFT = 1`) without checking that the interior is valid, and
  low free memory makes that more likely.
- **Fix:** Leonida locks `INTERIORS / LOADTUNERGARAGE = False` in `EnableAllInteriors.ini` on builds up to
  1.0.1158.12. You lose the auto shop's interior. Also keep about 6 GB of RAM free (the memory step before Play).
- **Check:** `leonida playtest --repeat 15`; no crash at `+0x1516B9` should come back.

### `GTA5_Enhanced.exe+0xBCC6AD`: the GTA IV Burger Shot Interior on 1.0.1013.x (west-coast spawns)

- **Seen:** on the loading screen ("Loading : 7"), 49–69 s after the launch:
  - 2026-11-25 10:30, 13:45 and 13:51, with VisualV installed, 0.6–1.4 GB of RAM free;
  - 2026-11-26 18:07, 18:11 and 18:12, **without VisualV**, 3.4–3.5 GB free (commit 21–22 of 31.6 GB). The 18:12
    run also had **no ViMinimap / ViPreload** (8 ASIs).
  - later on 2026-11-26, with **Resource Extensions off**: 4 crashes in 8 runs.
  So it isn't VisualV, the HUD's Vi ASIs, Resource Extensions or low memory. (VisualV, and a 6-of-6 run without
  Resource Extensions, were luck.)
- **Cause: the GTA IV Burger Shot Interior** (`burgershot`, `66ab92-Burgershot_new.rar`, v2.1 ENHANCED ONLY). The
  owner's current save spawns on the west coast (Vespucci / Del Perro). From it, the game crashed about 1 load in 3
  with the Burger Shot on. With only it off (the 8 mods that share its `dlclist.xml` reinstalled), **8 of 8** loads
  passed (2026-11-26).
- **What the dumps show:** all are identical.
  - A null-pointer read (`reading 0x18`) on an unnamed game worker thread (number 13), frames only the game's own:
    `+0xBCDA61` ← `+0xC24720` ← `+0x1308160` ← `+0x1308243` ← `+0xBCD9FD` ← `+0x1302173` ← `+0xCD2DC1`.
  - The same 32-bit value `0xE2FD295F` is in RBP and R9 every time. It is the name hash (joaat) of
    **`vb_03_bld2_e_lod`**, a distance (LOD) model of a building in Rockstar's Vespucci map block `vb_03`. The earlier
    search of about 43,000 names missed it: nothing names it as text, only by its hash.
  - The Burger Shot's `dlc.rpf` ships its own copy of that map block:
    - in `x64\levels\gta5\basev.rpf`: the `vb_03_*` models, LODs, collisions, `vb_03_strm_0.ymap` and
      `vb_occl_01.ymap`;
    - in `meta.rpf`: `hei_vb_03.ymap` (a CodeWalker edit from 2018) and `hei_vb_03_strm_0.ymap`.

    `hei_vb_03.ymap` places `vb_03_bld2_e_lod`. The only model in `vb_03_bld2_e_slod_children.ydd` is named just
    `hash_E2FD295F`, CodeWalker's stand-in for a name it didn't know. The game loads that LOD on the loading screen
    when the player spawns in sight of Vespucci, and can't resolve it there; exe-build's dump analysis read it as a
    missing shader. Checked read-only on a copy of the download.
  - Script Hook V .NET hadn't started its scripts yet (`ScriptHookV.log` ends at "Waiting to launch
    ScriptHookVDotNet.asi"), so no .NET script was involved.
- **The author and the page:** v2.1 ENHANCED ONLY (9 April 2025) is the only Enhanced file; the older ones are for
  Legacy. Enhanced players report crashes near this Burger Shot in the comments (2025–2026): at night, with NVE,
  "5–20 seconds after loading". The fixes posted there are a re-upload on Mediafire, or deleting ymaps inside the
  author's `dlc.rpf`:
  - the author's pinned note, for the online map: `vb_03.ymap` and `vb_03_strm_0.ymap`;
  - a player, for Enable All Interiors' white walls: `hei_vb_03*.ymap`, `vb_occl_01.ymap` and the occluder models.

  Leonida doesn't edit authors' archives or use re-uploads.
- **Fix:** the Burger Shot is off on game builds up to 1.0.1013.x (its `gameBuilds` entry in mods.json). It stays in
  the owner's pick and the Showcase pack and comes back on newer builds, unless the same crash is reported there. An
  optional mod the game build can't run is left out, with its reason on its card, instead of blocking the checks.
- **Check:** `leonida playtest --repeat 8` from the west-coast save; no `+0xBCC6AD`.
- **Ruled out on the way:**
  - Rockstar's crash log names `HUD.SET_COMPONENT_POSITION` (component 17, the game's own loading spinner) as the
    last HUD call: the last thing the HUD movie did, not the cause.
  - VisualV, the HUD's Vi ASIs and Resource Extensions were each off in runs that still crashed here.
