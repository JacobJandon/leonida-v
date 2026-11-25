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
    happened with the HUD's ViMinimap/ViPreload ASIs on and off, so memory is the cause, not the HUD.
  - Check: `leonida playtest --repeat 8` shows the free RAM and commit before each run, grouped by passed and
    crashed runs.
- [ ] **Open World Interiors vs the walk-in restaurants:**
  - Walk into the **Burger Shot** in Vespucci and the **Up-n-Atom** on Vinewood (X 80.76, Y 273.01). There should be
    one interior each: no doubled walls, tables or counters, no props floating or poking through, and the doors work.
  - If something is doubled, note which building. The fix is to switch that restaurant off in
    `scripts\OpenWorldInteriors.ini`.
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

## Before you start (1 minute)

1. **Settings > Graphics: Screen Type = Windowed Borderless**, and the game in **English**. The HUD needs both.
2. Start the game from the **Leonida V** shortcut or `PlayGTAV.exe`.
   - **Straight To Story Mode:** no legal, splash or landing screens; it goes straight into story mode.
   - **GTA VI loading screens:** Vice City pictures while it loads.
3. Once you're in, press **Insert** once (Enable All Interiors loads the online interiors).

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
| Enable All Interiors | falling through floors in online interiors | press **Insert** once after loading (it loads the MP maps) |
|  | online interiors missing, and `ScriptHookVDotNet.log` says *Blocking script! Script EnableAllinteriors.LoadMPMaps ... was terminated because it caused the game to freeze too long* | `ScriptTimeoutThreshold` in `ScriptHookVDotNet.ini` must be **15000**: Leonida locks it whenever Enable All Interiors is in your pack; run `leonida settings apply` (or **Manage > Restore all**) and press **Insert** again |
| VisualV | a crash at start, or a strange night sky texture | undo the step; tell the project which (a comment says some files weren't converted for Enhanced) |
| GTA V Remastered | a crash while loading | on builds before 1.0.1158.13 Leonida raises Building 70000 / phInstGta 20000 / StaticBounds 20000 in `gameconfig.xml` (its troubleshooting.txt, the HUD's Legacy guide): reinstall its step if they're missing, or undo it |
| Forza Horizon 6 Roads | black or flickering roads | undo the step |
| Menyoo / ActionsV / Food Delivery / Ryde | the key does nothing | `leonida keys` for clashes; check its `.ini` in `scripts` |
| iOS 26 icons | broken or blank phone icons | undo the step |

When in doubt: undo the last step, play again, and tell the project what you saw (the mod, the place, and what
`leonida verify` says).
