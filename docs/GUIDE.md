# Leonida V: your step-by-step guide

This guide is for **your** PC: GTA V Enhanced in `D:\Games\Grand Theft Auto V Enhanced`, game build
**1.0.1013.20**, a GTX 1070, and the Leonida folder `D:\Leonida`. Follow the parts in order. Each part says what you
should see when it worked.

> **Story mode only.** Never go into GTA Online with mods. Before you play Online, switch on *Online-safe* (part 8).

---

## 1. Start Leonida

1. Open `D:\Leonida` and double-click **`Start-Leonida.bat`** (or, from a release zip, **`LeonidaV.exe`**).
   - The first time it sets itself up: a few minutes. Afterwards it opens straight away.
   - It also adds a **Leonida V** shortcut to the Start menu and the desktop. From then on, start it from there.
   - Everything stays in `D:\Leonida`: your downloads in `Downloads`; Leonida's settings, log and backups in
     `State`.
2. The window opens on **Welcome**. The left side lists the seven pages (*Welcome, Game, Choose mods, Get mods,
   Check, Install, Manage*); the box at the bottom left always shows your game and its build.
   Click **Start: find my game**.
3. **Game**: Leonida shows your game folder, `D:\Games\Grand Theft Auto V Enhanced`, and the build **1.0.1013.20**.
   Click **Next**.

Prefer typing? Double-click **`Leonida-CLI.bat`**. Every part below also gives its command.

---

## 2. Choose mods

### The modpack

**Choose your modpack** shows four cards. Click **Choose this pack** on one, then **Next: add-ons**.

| Pack | What it is |
| --- | --- |
| **Leonida Core** (*Recommended*) | the free, stable base: one mod per job |
| **Leonida Plus** | Core plus Immersive Combat, the game's own online interiors and Jason's house |
| **Leonida Max (RTX 50)** | Plus and Better Vehicle Deformation; greyed out without an RTX 50 card (yours is a GTX 1070) |
| **Leonida Showcase (GTA VI)** | everything that brings the free game closest to GTA VI (see [GTA6-EXPERIENCE.md](GTA6-EXPERIENCE.md)) |

Every pack is free. **Switching packs later** rolls back what isn't in the new pack (only steps that no kept mod
depends on). **Your own mods**: **Add a mod** takes any mod from a file or a page link; it gets the same logged
install, undo and Online-safe handling.

### Add-ons and variant

**Choose your mods** then shows your pack ticked, with **Change pack** at the top right.

- **Variant** (Plus and Showcase): **Performance**, **Balanced** or **Ultra**. Pick **Performance** on your GTX 1070.
  It sets how full the streets are (Resource Extensions' people, traffic and parked cars, All MP Vehicles' extra
  cars) and switches off Resource Extensions' ray-tracing memory, which your card doesn't use.
- **Add-ons**, by category: *Look*, *World life*, *Driving*, *Combat & camera*, *Things to do*, *Characters* and
  *Menus, phone & sound*. Tick the ones you want; none is paid. Each card says what it adds and which mods.
- Cards that can't run on your game build are greyed out with the reason; the others show the version for your
  build (for example Drive V 7.4, part 3).
- Click a picture to see it bigger, **Page** for the mod's own page.
- **Look** has one free graphics mod at a time: **VisualV** (the best free one for your PC: weather, lighting and
  colour, no ReShade, light on a GTX 1070), then Prime Realism V (a GTA VI-style volumetric sky, but it needs
  ReShade and is heavy and new) or MaxedV (an alpha). **Forza Horizon 6 Roads** adds new road textures next to any
  of them. **AuraV Lite** (path tracing) is only for NVIDIA RTX cards. The Showcase ticks VisualV and the roads.
- Paid add-ons (**NaturalVision Enhanced**, Lively World Expansion, the Jason + Lucia models) are shown with their
  free alternative. Bought NVE? Tick it: Leonida then picks its December 2025 release for 1.0.1013.20, swaps Drive V
  for *Drive V for NVE*, leaves OpenRPF out and installs the other mods into NVE's `onigiri` folder.

Click **Next: get mods**.

**How Leonida picks between similar mods:** always the better, newer, working one. The other one stays an
*alternative* (shown, not in any pack), and its card says why:
- **Interiors:** seamless interiors built into the map's buildings (Burger Shot, Up-n-Atom, the 24/7 shops) over
  Open World Interiors, which moves you elsewhere through map icons.
- **HUD:** Geckomacabre's GTA VI-Inspired HUD (newer, bigger, public download) over FBICat's original.
- **Traffic:** All MP Vehicles in SP over Traffic V FEAR Edition.

Command line: `leonida pack choose <pack> --addons visualv,interiors --variant performance` (or `leonida profiles
--use core`).

### Locked settings

Leonida writes the mods' settings that make them work together and look like GTA VI: no car or interior blips on the
minimap, one radio wheel, the right reload key, the street density of your variant, keys that don't clash. If a mod
update (or you) changes one, **Manage** shows it with **Restore all** and **Keep mine**. Command line: `leonida
settings show`, `leonida settings apply`, `leonida settings unlock <mod> "<file>" "<key>"`.

---

## 3. Get the mods

Leonida never keeps mod files itself: each one comes from its author, into `D:\Leonida\Downloads`.

1. On **Get mods**, click **Download everything**.
   - First it downloads every mod whose author publishes a direct release (GitHub: Script Hook V .NET Enhanced,
     Menyoo, the HUD and its loading screens, LemonUI, ActionsV).
   - Then Leonida's browser goes through the rest, one author's page after another. It finds the right file (the
     version for your build) and clicks the site's own Download button, waiting through its countdown.
   - **Nexus Mods** (NextGen Euphoria, Jason's house, Better Fist Fighting) needs a free account. When Leonida asks,
     **sign in to nexusmods.com in Leonida's browser window**; it carries on by itself afterwards. Leonida never
     types or stores your password.
   - Each file is checked as it arrives (name and contents), and the row turns **ready**.
2. Only want the automatic ones? **Download all automatic**. One mod by hand? **Open page** on its row.
3. A file wasn't recognised? **Assign a file...** tells Leonida which mod it is. **Rescan** looks again;
   **Open download folder** shows the folder.

A wrong file is refused with the reason, for example *wrong edition/version* for a Legacy file or Drive V 7.5 on
your build, and Leonida names the right one.

### Older versions for your game build (1.0.1013.20)

Your game is from December 2025. Some mods' newest versions add cars or places from the July 2026 GTA Online
update (the Kortz Center Heist), which your game doesn't have. Leonida picks the version before it:

| Mod | Version for your game | Why |
| --- | --- | --- |
| Drive V | **7.4** (30 Mar 2026), from the page's **All Versions** list | 7.5 adds two of the July 2026 cars to traffic |
| Drive V for NVE (only with NVE) | **7.4**, under **Old files** on its Nexus Files tab | 7.5.1 adds the July 2026 cars too |
| Enable All Interiors | the newest (47.1.1) | Leonida switches its nine Kortz Center Heist interiors off |

Two Core mods were made on a newer game and haven't been tried on yours yet: the **GTA VI-Inspired HUD** and the
**GTA VI Combat Camera**. If the pause menu or the aiming camera looks wrong, undo that step (part 9).

### Which downloads need an account, and which cost money

| Mod | Where | Cost | Account |
| --- | --- | --- | --- |
| Script Hook V | dev-c.com | free | none |
| Most mods | gta5-mods.com | free | none (adverts, sometimes a short countdown) |
| Script Hook V .NET Enhanced, Menyoo, the HUD + loading screens, LemonUI, ActionsV | GitHub | free | none |
| NextGen Euphoria (Core), Jason's house, Better Fist Fighting | Nexus Mods | free | **a free Nexus Mods account** |
| AuraV Lite (RTX add-on) | kyposmods.com | free | none |
| **NaturalVision Enhanced** | razedmods.com → Razed's Patreon | **paid** (Gold tier) | Patreon |
| **Lively World Expansion** | Patreon | **paid** | Patreon |
| **Jason + Lucia models** | the creator's Patreon shop | **paid** | Patreon |

Paid content stays manual: Leonida never opens a Patreon tier or a shop for you, and never uses "free" copies of
paid mods from other sites (those are re-uploads). **Every paid add-on has a free way to
do the same job**, shown on its card:

| Paid | Free instead | What's different |
| --- | --- | --- |
| NaturalVision Enhanced (graphics) | **VisualV** (or Prime Realism V / MaxedV) | VisualV redoes weather, lighting and colour; NVE also replaces textures and models |
| Lively World Expansion (trees, plants, props) | **GTA V Remastered** | similar extra vegetation and props; don't use the two together. LWE's own free *Public Release* (2022) is in the Legacy list: it's from the old game and untested on Enhanced |
| Jason Duval + Lucia Caminos models | **MP Jason & Lucia V** (clutit) | two reshaped freemode heads plus Menyoo outfits, not full character models |

Command line: `leonida get --auto --watch`.

When it worked: every mod of your pack shows **ready**.

---

## 4. Check

Open **Check** (or `leonida check`).

- **ERROR** must be fixed before you install; the message says how.
- **WARNING** means think first; **info** is just for you.
- It checks your game build (and which mod versions it gets), two HUDs or cameras, key clashes, old limit adjusters
  next to Resource Extensions, wrong-edition downloads, missing .NET 4.8 / VC++ runtimes, and locked settings that
  changed.

Click **Run checks again** after you fix something. On your PC Core shows no errors.

---

## 5. Install, one step at a time

**Install, one step at a time** shows a stepper on the left (one mod per step, in order) and the **Next step** on
the right.

1. **Dry run (show plan)** shows what the next step will do. Nothing changes.
2. **Install next** (the button names the mod) installs it. The **Step log** tab shows what happened.
3. Then test it: the **Play test** tab (button **Play test**) closes GTA if it's running, starts it from
   `PlayGTAV.exe`, waits for story mode, reads the mods' own logs (Script Hook V, the HUD, ...) and closes the game
   again. Tick **Leave the game running afterwards** to keep playing. Command line: `leonida playtest`.
4. Something's wrong? **Undo this step**, and the game folder is as it was before that step.

**How mods are installed.** Leonida copies files itself where a mod is just files (Script Hook V, the scripts,
...). Mods that change GTA's archives (Map Fixes, the HUD, Drive V, the walk-in shops, VisualV, ...) are installed
the same way: **Leonida edits copies in `mods\`** (OpenRPF makes the game load those first), never the game's own
files, and **every change can be undone**. It does the archive editing with CodeWalker's library (by dexyfex), the
way CodeWalker RPF Explorer does it by hand. A few optional mods still have hand-made steps (for example Prime
Realism V and its ReShade); Leonida shows them, waits for you and records what changed.

**Script Hook V** is the first step: Leonida copies `ScriptHookV.dll` and `xinput1_4.dll` (the `.asi` loader GTA V
Enhanced uses). It leaves out `dinput8.dll` (the Legacy loader), `NativeTrainer.asi` (Menyoo is your trainer) and
`args.txt` (it switches BattlEye off; do that yourself in the Rockstar Games Launcher's settings for GTA V).

Before the first step Leonida takes a snapshot of your game folder; every file it adds or replaces is logged with a
backup (part 9).

### Only with the paid NVE: the `onigiri` folder

NaturalVision Enhanced loads mods with its own loader, **onigiri**, from the `onigiri` folder, and doesn't read
`mods\`. While NVE is selected Leonida leaves OpenRPF out (shown as *not needed*, with the reason), uses Drive V for
NVE and puts the other mods' files into `onigiri`:

| A mod's readme says | With NVE it goes to |
| --- | --- |
| `mods\update\x64\dlcpacks\<pack>` | `onigiri\dlcpacks\<pack>` |
| a line in `dlclist.xml` inside `update.rpf` | the same line in `onigiri\common\data\dlclist.xml` |
| `update.rpf\common\...` | `onigiri\common\...` |
| `update.rpf\x64\...` | `onigiri\platform\...` |

---

## 6. After Script Hook V: check that it runs

Script Hook V is the base every script mod needs. Its author only offers the newest version (made for 1.0.1158.13).
**On your game, 1.0.1013.20, it works**: tested on 24 November 2026. Script Hook V sees 1.0.1013.20 as 1.0.1013.17,
so its log says "game version is VER_EN_1_0_1013_17", and Menyoo and Script Hook V .NET loaded. Check it once after
installing anyway (and again after any game update):

1. Start the game and load story mode. Quit.
2. On **Manage**, click **Check the game's logs (after playing)**, or run `leonida verify` (or open
   `D:\Games\Grand Theft Auto V Enhanced\ScriptHookV.log` with Notepad). The **Play test** does all of this for you.
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
| Hold **Left Alt** | Switch character (GTA VI's character cards) |
| **K** | Skills panel |
| **Y / U** | Greet / antagonize someone |
| **N** / **Shift + N** | Push-ups / sit-ups |
| **Left Ctrl** twice, **Right Ctrl** | Crouch, lie down and crawl |
| **F10** | Reloads the HUD's settings |
| **F8** | Menyoo (trainer). **F9** Spooner, **F3** free camera |
| **F7** | ActionsV menu (Showcase). Its own default is F10, so Leonida moves it |
| **F11** | AuraV Lite's menu (RTX add-on; also moved off F10) |
| **F4** | Script Hook V .NET console |
| **F6** / **F5** | Food Delivery menu / reload its settings (Showcase) |
| **Page Up** / **Page Down** | Ryde rideshare menu / cancel the ride (Showcase; Leonida moves them off F10 and F9) |
| **Insert** | Only with Enable All Interiors: reload scripts once after loading, so the online interiors appear |

What to look for in game, mod by mod, on a 15-minute route: [IN-GAME-CHECKS.md](IN-GAME-CHECKS.md).

`leonida keys` lists them and warns about clashes. Changed a key in a mod's `.ini`? Tell Leonida:
`leonida keys set <mod> "<action>" <key>`.

---

## 8. Manage: status, Online-safe, updates

The **Manage** page has three boxes at the top and three tabs:

- **Status**: whether the mods are in, how many steps are installed, and **Check the game's logs (after playing)**.
- **Online-safe**: before you play **GTA Online**, click **Online-safe ON (move mods out)**. Leonida moves every mod
  file (Script Hook V, `.asi` files, `scripts`, `mods`, `onigiri`, ...) into `_LeonidaV_offline` in the game folder.
  Back to story mode: **Online-safe OFF (bring mods back)**. Commands: `leonida online-safe on|off|status`.
- **Pure GTA** (the button next to **Play**): plain GTA V story mode with no mods at all, for a quick comparison or a
  vanilla run. Leonida moves every mod out the same way, starts the game, and brings the mods back by itself when you
  close it (or the next time Leonida opens). Commands: `leonida pure`, `leonida pure --back`, `leonida pure --status`.
- **Leonida**: **Check for updates** looks for a newer Leonida V on GitHub; **Update Leonida** installs it (checked
  against the release's `SHA256SUMS.txt`), and **Force update** reinstalls the latest release even when you have it.
  Commands: `leonida self-update [--check]`.
- A yellow box appears when **a locked setting changed** since install: **Restore all** puts Leonida's values back
  (a logged step you can undo), **Keep mine** keeps yours.
- Tabs: **Installed** (each mod, its version and step), **Play test** (part 5), **Log and updates**: the install
  log, **Check for mod updates** (the mod versions tested together with this Leonida release) and **Install mod
  updates**. Command: `leonida update [--check]`.
- Shortcuts missing? `leonida shortcuts` makes the Start menu and desktop shortcuts again.

---

## 9. Undo and uninstall

- **Undo the last step**: **Manage** → **Undo last step** (or **Undo this step** on *Install*), or `leonida rollback`.
  A particular step: `leonida rollback <step>` (`leonida status` lists the steps).
- **Remove everything**: **Manage** → **Uninstall everything**, or `leonida uninstall`. Leonida puts back every file
  it backed up and compares the game folder with the snapshot from before your first step.
- Archive mods are undone exactly: Leonida backed up the copies in `mods\` before each change.
- One limit: files over 64 MB that a mod's *own* installer changed aren't backed up. Leonida warns you; restore them
  with *Verify game files* in your game launcher.

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

## 11. Other PCs: other GTA V Enhanced builds

Leonida reads the build from `GTA5_Enhanced.exe` and picks each mod's version for it. Script Hook V, Script Hook V
.NET Enhanced and Menyoo support every Enhanced build from the March 2025 launch (1.0.811.8) to 1.0.1158.x. What
changes per build:

| Game build | When | What Leonida does differently |
| --- | --- | --- |
| 1.0.811.8 – 814.9 | Mar–Apr 2025 (launch) | OpenRPF 0.2; Drive V 6.8; **no Map Fixes / Bugstar Fixes** (their only version needs the Dec 2025 mansions pack); Traffic V FEAR v1.1 |
| 1.0.889.15 – 889.22 | Jun–Aug 2025 (Money Fronts) | OpenRPF 0.2; Drive V 7.3; **no Map Fixes / Bugstar Fixes**; Traffic V FEAR v1.2 |
| 1.0.1013.17 – 1013.34 | Dec 2025 – Apr 2026 (Safehouse in the Hills) | Drive V 7.4; Enable All Interiors with its Kortz switches off; NVE only on 1013.20 and 1013.34 |
| 1.0.1158.13 and newer | Jul 2026 on (Kortz Center Heist) | the newest version of everything |

A mod Leonida can't offer on a build shows the reason on its card and in **Check**, and is left out of the install.
Mods made on a newer game than yours (the GTA VI-Inspired HUD, the Combat Camera) are still offered, but they're
marked as untested on older builds.

---

## 12. GTA V Legacy (the old `GTA5.exe` game)

Leonida reads which game is in the folder. For **GTA V Legacy** (`GTA5.exe`, builds 1.0.3xxx) it uses its own
mod list, because most Enhanced mods don't run there and the other way round. Everything in it is free.

| Job | Legacy pick | Enhanced counterpart |
| --- | --- | --- |
| Script loader | Script Hook V with **`dinput8.dll`** (from the same download) | Script Hook V with `xinput1_4.dll` |
| .NET scripts | **Community Script Hook V .NET 3.7.0 nightly** (the HUD needs nightly 193 or newer) | Script Hook V .NET Enhanced |
| Mods folder | **OpenIV** + OpenIV.asi (Tools > ASI Manager) | OpenRPF |
| HUD | GTA VI-Inspired HUD, the **`-Legacy.oiv`** | the `-Enhanced.oiv` |
| Euphoria | **NextGen Euphoria (Legacy Edition)**, same author, on Nexus | NextGen Euphoria |
| Driving, traffic, trainer, start | Drive V, All MP Vehicles in SP, Menyoo, Straight To Story Mode (same downloads) | same |
| Map Fixes / Bugstar Fixes | their **Legacy** files, plus HeapAdjuster, Packfile Limit Adjuster, Static Bounds Limit Adjuster, the fwBoxStreamerVariable patch and the gameconfig.xml for your build (Core + Safe Extras) | Resource Extensions does the limits |
| Graphics (pick one, optional) | VisualV (Legacy file), Prime Realism V, MaxedV | same three |
| Extra vegetation (pick one, optional) | GTA V Remastered (Legacy package) or **Lively World Expansion's free Public Release** (0.2, 2022; page comments report missing trees on recent builds) | GTA V Remastered |

- Every `.oiv` goes in with OpenIV: **Tools > Package Installer**, choose the **mods folder**.
- Install the **gameconfig.xml before the HUD**. The HUD adds its own limits to it, and a gameconfig installed
  afterwards removes them (then install the HUD's `.oiv` again).
- Turn BattlEye off in the Rockstar Games Launcher's settings for GTA V, as on Enhanced. Leonida doesn't copy
  Script Hook V's `args.txt`.
- The GTA VI Combat Camera is made for Enhanced; on Legacy it's offered separately, untried.
- Older Legacy builds get older versions the same way as on Enhanced (Drive V 7.4 / 7.3 / 6.8, the gameconfig for
  your build). Map Fixes and Bugstar Fixes need 1.0.3717 (Dec 2025) or newer.

The Legacy list hasn't been tried on a real Legacy game yet.

---

## Where things are

| What | Where |
| --- | --- |
| Leonida | the **Leonida V** Start menu shortcut, or `D:\Leonida\Start-Leonida.bat` (window), `D:\Leonida\Leonida-CLI.bat` (commands) |
| Your mod downloads | `D:\Leonida\Downloads` |
| Settings, install log, backups | `D:\Leonida\State` |
| The game | `D:\Games\Grand Theft Auto V Enhanced` |
| Script Hook V's log | `D:\Games\Grand Theft Auto V Enhanced\ScriptHookV.log` |
