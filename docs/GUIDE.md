# Leonida V: your step-by-step guide

This guide is for **your** PC: GTA V Enhanced in `D:\Games\Grand Theft Auto V Enhanced`, game build
**1.0.1013.20**, a GTX 1070, and the Leonida folder `D:\Leonida`. Follow the parts in order. Each part says what you
should see when it worked.

> **Story mode only.** Never go into GTA Online with mods. Before you play Online, switch on *Online-safe* (part 8).

---

## 1. Start Leonida

1. Open `D:\Leonida`.
2. Double-click **`Start-Leonida.bat`**.
   - The first time it sets itself up: this takes a few minutes. The next times it opens straight away.
   - It keeps everything in `D:\Leonida`: your downloads in `Downloads`, Leonida's settings, log and backups in
     `State`.
3. The Leonida window opens on **Welcome**. Click **Next**.
4. **Game**: Leonida shows your game folder, `D:\Games\Grand Theft Auto V Enhanced`, and the game build
   **1.0.1013.20**. Click **Next**.

Prefer typing commands? Double-click **`Leonida-CLI.bat`** instead. Every step below also has its command.

---

## 2. Choose mods

The **Choose mods** page shows every mod with a picture. Click a picture to see it bigger, or **Page** to open the
mod's own page.

- Keep the profile **Core**. It's the stable set, and your GPU (GTX 1070) is not an RTX 50, so leave out *Max (RTX 50)*.
- **Extras** have an **Include** tick box. Leave them off for your first install. Add them later, one at a time.
- The **HUD** has a choice of three. Keep **GTA VI-Inspired HUD (geckomacabre)**: it downloads by itself and its
  keys don't clash with anything.
- **Core is free.** It has no graphics overhaul: the well-known one, **NaturalVision Enhanced**, is paid (Razed's
  Patreon Gold tier or higher), so it's only offered as a paid add-on. Free graphics options are under *Graphics*
  (pick one): **MaxedV** (an alpha) and **Prime Realism V** (needs ReShade). Neither has been tested in the game yet.
- Bought NVE? Tick it: Leonida then picks its December 2025 release for 1.0.1013.20, swaps Drive V for *Drive V for
  NVE*, leaves OpenRPF out and switches the other mods' steps to NVE's `onigiri` folder (part 5).

**How Leonida picks between similar mods:** always the better, newer, working one. Where two mods do the same job,
the other one is only an *alternative* (shown, not in any pack), and its card says why:

- **Interiors:** seamless interiors built into the buildings on the map (Burger Shot, Up-n-Atom, the 24/7 shops,
  Map Updates) are in the packs. **Open World Interiors** moves you into interiors placed elsewhere through map icons
  and a cutscene (and its comments report people landing in the wrong place), so it's an alternative.
- **HUD:** Geckomacabre's GTA VI-Inspired HUD (a newer, bigger fork of FBICat's, with a public download) over FBICat's
  original and the removed "GTA VI Inspired Features" HUD.
- **Traffic:** All MP Vehicles in SP (newer, no trainer needed) over Traffic V FEAR Edition. Use one of them.
- **Driving:** the newest Drive V; Drive V for NVE only with the paid NVE.

Command line: `leonida profiles --use core`.

---

## 3. Get the mods

Leonida never keeps mod files itself. It fetches each one from its author, into `D:\Leonida\Downloads`.

1. On **Get mods**, click **Download all automatic**. Script Hook V .NET Enhanced, Menyoo and the HUD come straight
   from their authors' GitHub pages. The list turns to **ready** for each one.
2. Click **Get the rest in Leonida's browser**. It opens the first missing mod's page inside Leonida.
   - Click the page's own **Download** button. Leonida sees the file arrive and ticks the mod off.
   - Click **Next missing mod >** for the next one.
   - Pages on gta5-mods.com may show adverts and a short countdown before the download starts. That's normal.
3. **Nexus Mods** (NextGen Euphoria in Core; Jason Duval House and Drive V for NVE as extras): Nexus needs a free account. Log in on the Nexus page inside
   Leonida's browser, then click **Manual download** on the mod's **Files** tab. Pick the file the page calls *Main*.
4. **NaturalVision Enhanced** (paid add-on, not in Core): the download is only for Razed's Patreon Gold supporters.
   If you have that, your build needs the December 2025 release (its Patreon post links the Gold-only download post).
5. Something wasn't recognised? Leonida lists it. Tell Leonida which mod it is: `leonida assign "<file>" <mod id>`.

### Which downloads need an account, and which cost money

Checked on 24 November 2026 in a browser, logged out:

| Mod | Where | Cost | Account needed |
| --- | --- | --- | --- |
| Script Hook V | dev-c.com | free | none |
| Everything on gta5-mods.com (most Core mods and extras) | gta5-mods.com | free | none (adverts, sometimes a short countdown) |
| Script Hook V .NET Enhanced, Menyoo, GTA VI-Inspired HUD, LemonUI, ActionsV | GitHub (automatic) | free | none |
| **NaturalVision Enhanced** (any version) | razedmods.com -> Razed's Patreon | **paid** | Patreon **Gold tier or higher** (the download post says "Download Links for Gold and Platinum Supporters ... Join to unlock") |
| **NextGen Euphoria** (Core), **Jason Duval House**, **Drive V for NVE** (extras) | Nexus Mods | free | **a free Nexus Mods account**: without it the page only says *Log in to download* |
| MaxedV, Prime Realism V (free graphics options) | gta5-mods.com | free | none (Prime Realism V also needs ReShade from reshade.me) |
| GTA VI HUD by fbicat (alternative HUD) | fbicat's Discord server | free | a free Discord account |
| Lively World Expansion | Patreon | **paid** ($10 tier for Enhanced single player) | a paid Patreon membership |
| Jason Duval + Lucia Caminos models | the creator's Patreon shop | **paid** | a Patreon purchase |

So for **Core** you need one free account, **Nexus Mods** (for NextGen Euphoria). Nothing in Core or the free
extras costs money. NaturalVision Enhanced, Lively World Expansion and the Jason + Lucia models are paid add-ons.

Command line: `leonida get --auto --watch` downloads the automatic ones, opens the other pages and waits for your downloads.

When it worked: every Core mod shows **ready**.

---

## 4. Check

Open the **Check** page (or `leonida check`).

- **ERROR** must be fixed before you install. The message says how.
- **WARNING** means think first; **info** is just for you.
- On your PC you should see no errors with Core. (If you add NVE, an info line says it uses its December 2025
  release, the one made for 1.0.1013.20.)

Click **Run checks again** after you fix something.

---

## 5. Install, one step at a time

Open **Install** (or `leonida install`). Leonida installs one mod per step, in the right order.

1. Click **Dry run (show plan)** to see what the next step will do. Nothing changes yet.
2. Click **Install next**.
   - Some mods Leonida copies by itself (Script Hook V, Script Hook V .NET Enhanced, Combat Camera, ...).
   - For the others it shows **steps** to follow by hand. Do exactly what they say, then confirm.
3. Leonida asks you to **start the game and test** after a step. Load story mode, look around, quit. Then go on.

**Script Hook V** is the first step. Leonida copies two files from its `bin` folder: `ScriptHookV.dll` and
`xinput1_4.dll`, the mod loader GTA V Enhanced uses for `.asi` files. It leaves `dinput8.dll` out (that's the loader
for the old *Legacy* game), `NativeTrainer.asi` (Menyoo is your trainer) and `args.txt` (it switches BattlEye off;
switch BattlEye off yourself in the Rockstar Games Launcher's settings for GTA V, as Menyoo's page asks).
If you add the paid **NaturalVision Enhanced**, it brings its own `xinput1_4.dll` a few steps later: when Windows
asks, click **Replace**. It's the same loader. Leonida keeps Script Hook V's copy as a backup, so undoing NVE puts it
back.

In **Core**, mods that change the game's archives go into the **`mods`** folder, which **OpenRPF** (a Core step) loads.
Your original game files are never changed.

Before the first step Leonida takes a snapshot of your game folder. Every file it adds or replaces is written to its
log with a backup, so each step can be undone (part 9).

### Things you need for the hand-made steps

- **7-Zip** (www.7-zip.org) to open `.7z` / `.rar` downloads and `.oiv` packages.
- **OIV Package Installer** (gta5-mods.com/tools/oiv-package-installer): installs `.oiv` packages on Enhanced.
- **CodeWalker RPF Explorer** (from dexyfex's Discord, version 30_dev48 or newer): to take files out of an `.rpf`.

### Only with the paid NVE: the `onigiri` folder

Skip this part with Core. NaturalVision Enhanced (NVE) loads mods with its own loader, **onigiri**, from the
`onigiri` folder in the game folder. It does **not** read the `mods` folder. Leonida knows this: while NVE is in your
selection it leaves **OpenRPF** out (Leonida shows it as *not needed*, with the reason), uses Drive V for NVE instead
of Drive V, and the steps of the mods below say *onigiri*.

| Mod | With NVE |
| --- | --- |
| Combat Camera | Leonida copies `cameras.ymt` into `onigiri\platform\data\metadata` by itself |
| Map Fixes, Bugstar Fixes | the pack folder goes into `onigiri\dlcpacks`, plus a line in `onigiri\common\data\dlclist.xml`; then the `.oiv` (below) |
| GTA VI-Inspired HUD | the `.oiv` as usual, then its three packs into `onigiri\dlcpacks` and their lines in `dlclist.xml` |
| Immersive Combat (extra) | the `.oiv` (below) |

Where things go, in general:

| A mod's readme says | With NVE it goes to |
| --- | --- |
| `mods\update\x64\dlcpacks\<pack>` | `onigiri\dlcpacks\<pack>` |
| a line in `dlclist.xml` inside `update.rpf` | the same line in `onigiri\common\data\dlclist.xml` (just above `</Paths>` at the bottom) |
| `update.rpf\common\...` | `onigiri\common\...` |
| `update.rpf\x64\...` | `onigiri\platform\...` |

**`.oiv` packages with NVE** (Map Fixes, Bugstar Fixes, Immersive Combat): install the `.oiv` with the OIV Package
Installer as usual, then copy what it changed into `onigiri`. Open the `.oiv` with 7-Zip and read `assembly.xml`: it
lists every file. Open `mods\update\update.rpf` in CodeWalker RPF Explorer, right-click each listed file and choose
**Extract Raw...** into the matching `onigiri` folder from the table. If a file is inside another `.rpf`, extract that
whole `.rpf`. Each mod's steps in Leonida repeat this.

---

## 6. After Script Hook V: check that it runs

Script Hook V is the base every script mod needs. Its author only offers the newest version (made for 1.0.1158.13).
**On your game, 1.0.1013.20, it works**: tested on 24 November 2026. Script Hook V sees 1.0.1013.20 as 1.0.1013.17,
so its log says "game version is VER_EN_1_0_1013_17", and Menyoo and Script Hook V .NET loaded. Check it once after
installing anyway (and again after any game update):

1. Start the game and load story mode. Quit.
2. Run `leonida verify` (or open `D:\Games\Grand Theft Auto V Enhanced\ScriptHookV.log` with Notepad).
   - **"Success, game version is ..."** or `verify` shows **OK**: it works. Carry on.
   - A message **"unknown game version"** or `verify` shows **FAILED**: see part 10.

Run `leonida verify` again after the other steps: it reads each mod's log and says which ones really loaded.
No `.asi` mod loads at all? Check that `xinput1_4.dll` is next to `GTA5_Enhanced.exe`, and open `asiloader.log` in
the game folder: it lists every `.asi` the loader started.

---

## 7. Keys

| Key | What it does |
| --- | --- |
| Hold **V** | HUD settings |
| Hold **Left Alt** | Switch character |
| **K** | Skills panel |
| **Y / U** | Greet / antagonize someone |
| **F8** | Menyoo (trainer). **F9** Spooner, **F3** free camera |
| **F4** | Script Hook V .NET console |
| **Insert** | Only with Enable All Interiors: reload scripts once after loading, so online interiors work |

`leonida keys` lists them and warns about clashes. Changed a key in a mod's `.ini`? Tell Leonida:
`leonida keys set <mod> "<action>" <key>`.

---

## 8. Online-safe mode

Before you play **GTA Online**:

- **Manage** page → **Online-safe ON (move mods out)**, or `leonida online-safe on`.
  Leonida moves every mod file (Script Hook V, `.asi` files, `scripts`, `mods`, `onigiri`, ...) into
  `_LeonidaV_offline` in the game folder.
- Back to story mode: **Online-safe OFF (bring mods back)**, or `leonida online-safe off`.
- `leonida online-safe status` tells you which state you're in.

---

## 9. Undo and uninstall

- **Undo the last step**: **Manage** → **Undo last step**, or `leonida rollback`. To undo a particular step:
  `leonida rollback <step>` (`leonida status` lists the steps).
- **Remove everything**: **Manage** → **Uninstall everything**, or `leonida uninstall`. Leonida puts back every file
  it backed up and compares the game folder with the snapshot from before your first step.
- One limit: files over 64 MB that a mod's *own* installer changed (for example `mods\update\update.rpf`) aren't
  backed up. Leonida warns you; restore them with *Verify game files* in your game launcher.

---

## 10. Script Hook V says "unknown game version"

On your current game (1.0.1013.20) this doesn't happen: Script Hook V works there (part 6). It can happen after a
game update, or on another PC with a game build the current Script Hook V doesn't know. Then:

1. **Don't** download Script Hook V from other sites. "Old version" copies on re-upload sites can be fake or
   infected, and Leonida never uses them.
2. Switch on **Online-safe** (part 8) or **Undo** the Script Hook V step, so the game starts cleanly.
3. Mods that don't need Script Hook V still work: OpenRPF, Drive V, NextGen Euphoria, Combat Camera, Straight To
   Story Mode, the paid NaturalVision Enhanced and the add-on interiors and map packs (Burger Shot, Up-n-Atom, the 24/7
   shops, GTA V Remastered). Script mods need it: Script Hook V .NET, Resource Extensions, Menyoo, the HUD,
   All MP Vehicles, Enable All Interiors, LemonUI and the other script extras. Map Fixes and Bugstar Fixes need it
   too, because their pages list Resource Extensions as a requirement.
4. Check the Script Hook V page (www.dev-c.com/gtav/scripthookv/) now and then: a new release can add your build.
5. Tell the project (an issue on GitHub) which message you got, so the manifest can mark the build.

---

## Where things are

| What | Where |
| --- | --- |
| Leonida | `D:\Leonida\Start-Leonida.bat` (window), `D:\Leonida\Leonida-CLI.bat` (commands) |
| Your mod downloads | `D:\Leonida\Downloads` |
| Settings, install log, backups | `D:\Leonida\State` |
| The game | `D:\Games\Grand Theft Auto V Enhanced` |
| Script Hook V's log | `D:\Games\Grand Theft Auto V Enhanced\ScriptHookV.log` |
