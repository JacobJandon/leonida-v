# Leonida V 1.0.0: release notes (DRAFT)

> **Draft.** Items marked *(not verified in game yet)* still need a real install and play test on the owner's PC
> before the release. Update this list as they pass.

**Leonida V turns GTA V Enhanced into a free GTA VI experience.** It's a launcher that downloads every mod from its
own author, installs a curated, conflict-checked set one safe step at a time, and can undo every file. Story mode
only; never GTA Online.

## Download

- `LeonidaV-1.0.0-win64.zip`: unzip anywhere, start `LeonidaV.exe` (the window) or `leonida.exe` (the command line).
- `leonida-v-1.0.0.zip` + `Start-Leonida.bat`: the portable kit (sets up its own Python the first time).
- `modpack.json`: the exact mod files tested together (names, sizes, hashes and the authors' URLs, never the files).
- `SHA256SUMS.txt`: checksums for everything above; Leonida's self-update checks them.

## What's in it

**Modpacks** (all free):
- **Leonida Core**: GTA VI-Inspired HUD and 3D minimap (wanted box, police lights, stun-gun police, heists, radio
  wheel, fuel), GTA VI Combat Camera, Drive V, NextGen Euphoria, All MP Vehicles in SP, Map Fixes and Bugstar Fixes,
  Menyoo, Straight To Story Mode, on Script Hook V, Script Hook V .NET Enhanced, OpenRPF, Resource Extensions and
  DirectStorageFix.
- **Leonida Plus**: Core + Immersive Combat, Enable All Interiors (the game's own online interiors) and Jason's house.
- **Leonida Showcase (GTA VI)**: Plus + VisualV, GTA V Remastered, Map Updates, walk-in Burger Shot / Up-n-Atom /
  24/7 shops, street food, Benny's, ActionsV, the camera flinch, the GTA VI loading screens, modern phone icons, the
  dynamic first-person car camera and food-delivery / rideshare jobs.
- **Leonida Max (RTX 50)**: Plus + Better Vehicle Deformation.
- **Add-ons** in seven categories, **Performance / Balanced / Ultra** variants, and **your own mods** (from a file or a
  page link, with the same logging and undo).
- What the packs cover of GTA VI, and what no free mod can do yet: `docs/GTA6-EXPERIENCE.md`.

**The launcher**:
- Pages *Welcome, Game, Choose mods, Get mods, Check, Install, Manage* in the new design; Start menu and desktop
  shortcuts.
- **Download everything**: the authors' direct releases first, then Leonida's browser follows each site's own
  Download button (you sign in to Nexus Mods yourself; Leonida never types passwords and never touches paid content).
- Every download is checked by name and contents (wrong edition or version is refused, with the right one named).
- **Install** one mod per step, with a dry run, **Play test** (starts story mode, reads the mods' logs, closes the
  game) and **Undo this step**.
- Archive mods are installed automatically into copies in `mods\` (never the game's own files); every change can be
  undone. *(The automatic archive installs are new in this release: not verified in game for every mod yet.)*
- **Manage**: status, Online-safe switch, Leonida updates (check / update / force), tested mod updates, locked settings
  that changed (**Restore all** / **Keep mine**), undo or uninstall everything.
- **Locked settings**: the mods' settings that make them work together and look like GTA VI, per pack and variant.

**Game builds and editions**:
- Every GTA V Enhanced build from 1.0.811.8 to 1.0.1158.x gets the mod versions that fit it, or a clear reason.
  On 1.0.1013.20 (December 2025), for example, Drive V 7.4 instead of 7.5 and Enable All Interiors with its July 2026
  interiors off.
- A separate free mod list for **GTA V Legacy** (`GTA5.exe`), picked automatically from the game's exe.
  *(Not tried on a real Legacy game yet.)*

**Safety**: snapshot before the first step, a log of every file with backups, rollback per step, full uninstall back
to the snapshot, the Online-safe switch, checks before installing.

## Tested on

- GTA V Enhanced **1.0.1013.20** on Windows 11 (GTX 1070), via `PlayGTAV.exe`.
- **Verified in the real game** (install + play test passed): All MP Vehicles in SP, DirectStorageFix, Menyoo 2.0, OpenRPF, Resource Extensions [Enhanced], Script Hook V, Script Hook V .NET Enhanced, Straight To Story Mode.
- *(Not verified in game yet)*: Map Fixes, Bugstar Fixes, Drive V 7.4, NextGen Euphoria, GTA VI Combat Camera, the
  GTA VI-Inspired HUD and everything in Plus and Showcase (installs being run on the owner's PC; update this line).
- Automated: about 1,000 tests (fake game folders and archives, the archive helper with a fake engine) on Windows and
  Ubuntu, Python 3.11 and 3.13.

## Known limits

- **No Vice City / Leonida map**: no free, legitimate one exists for GTA V Enhanced.
- **NaturalVision Enhanced is paid** (Razed's Patreon); optional add-on, VisualV is the free look.
- GTA VI's own music, phone apps, cars and new movement aren't there (bring your own music for On Demand).
- The GTA VI-Inspired HUD and the Combat Camera were made on 1.0.1158; on older builds they're untested.
- Three mods need a free Nexus Mods account. Nexus's terms restrict automated downloading, so Leonida only follows
  its own Slow download button after you've signed in yourself; that's your account and your choice.
- Files over 64 MB changed by a mod's *own* installer aren't backed up (rollback warns; *Verify game files* restores
  them).
- The archive helper uses **CodeWalker.Core** by dexyfex, built on your PC from the author's published source at a
  pinned commit. Leonida never ships or re-hosts CodeWalker, whose source is "released for educational purposes
  only". Permission from the author is being asked for (`docs/codewalker-permission-request.md`). *(Resolve before
  publishing; without his OK the helper stays out of public releases.)*
- Story mode only. Leonida never modifies GTA Online and never bypasses BattlEye (switch it off for story mode in the
  Rockstar Games Launcher yourself).

## Credits

Thank you to every mod author. Leonida links to your pages and releases and never re-hosts your files.

- **All MP Vehicles in SP** by andre500 (sruckstar): <https://www.gta5-mods.com/scripts/all-mp-vehicles-in-sp>
- **Bugstar Fixes (Enhanced package)** by Alex106: <https://www.gta5-mods.com/misc/fixes-improvements>
- **Community Script Hook V .NET (nightly)** by crosire and contributors: <https://www.gta5-mods.com/tools/scripthookv-net>
- **DirectStorageFix** by alloc8or: <https://www.gta5-mods.com/scripts/directstoragefix>
- **Drive V (Realistic Driving / Handling & Damage)** by PermissionToLand: <https://www.gta5-mods.com/vehicles/drive-v-realistic-driving-car-handling>
- **GTA VI Combat Camera [Enhanced]** by klennys: <https://www.gta5-mods.com/misc/gta-vi-combat-camera-enhanced>
- **GTA VI-Inspired HUD (geckomacabre)** by Geckomacabre (fork of FBICat's VI HUD): <https://github.com/Geckomacabre/GTA-VI-Inspired-HUD>
- **Map Fixes (Enhanced package)** by Alex106: <https://www.gta5-mods.com/maps/map-fixes>
- **Menyoo 2.0** by MAFINS, ItsJustCurtis, et al.: <https://www.gta5-mods.com/scripts/menyoo-2-0>
- **NextGen Euphoria** by iammrmikeman: <https://www.nexusmods.com/gta5enhanced/mods/1>
- **OpenIV (+ OpenIV.asi)** by OpenIV Team: <https://openiv.com/>
- **OpenRPF** by LSMP (Transmet, GiZz, Antasurris): <https://www.gta5-mods.com/tools/openrpf-openiv-asi-for-gta-v-enhanced>
- **Resource Extensions [Enhanced]** by Koukol: <https://www.gta5-mods.com/scripts/resource-extensions>
- **Script Hook V** by Alexander Blade: <https://www.dev-c.com/gtav/scripthookv/>
- **Script Hook V .NET Enhanced** by Chiheb-Bacha (built on SHVDN by crosire and contributors): <https://www.gta5-mods.com/tools/script-hook-v-net-enhanced>
- **Straight To Story Mode** by Chiheb-Bacha: <https://www.gta5-mods.com/scripts/straight-to-story-mode>
- **ActionsV** by SuleMareVientu: <https://www.gta5-mods.com/scripts/actionsv>
- **AuraV Lite (path tracing)** by Kypos: <https://kyposmods.com/aurav/enhanced/>
- **Benny's Motor Works in SP Revamped** by Nochala: <https://www.gta5-mods.com/scripts/benny-s-motor-works-in-sp-revamped>
- **Better Fist Fighting** by Huskyyy: <https://www.nexusmods.com/gta5enhanced/mods/36>
- **Better Vehicle Deformation for NVE** by HSjoaco33: <https://www.gta5-mods.com/misc/better-vehicle-deformation-for-nve>
- **Drive V for NVE** by DarkenHunter47 (based on Drive V by PermissionToLand): <https://www.nexusmods.com/gta5enhanced/mods/1093>
- **Dynamic Vehicle First Person Camera** by ikt: <https://www.gta5-mods.com/scripts/dynamic-vehicle-first-person>
- **Elgin/Hawick 24/7** by frdfare: <https://www.gta5-mods.com/maps/mlo-elgin-hawick-24-7-add-on-sp-fivem>
- **Enable All Interiors** by HKH191: <https://www.gta5-mods.com/scripts/enable-all-interiors-wip>
- **Food Delivery Job (Uber Eats, DoorDash driver)** by euphoricrager: <https://www.gta5-mods.com/scripts/uber-eats-driver-mod-eatz-food-delivery>
- **fwBoxStreamerVariable and decals limit patch** by Tanuki: <https://www.gta5-mods.com/tools/ymap-load-list-extent-limit-fix-fwboxstreamervariable-patch>
- **Gameconfig.xml (per game build)** by Dilapidated / pnwparksfan: <https://www.gta5-mods.com/misc/gameconfig-xml-dilapidated>
- **GTA IV Burger Shot Interior** by Smallo: <https://www.gta5-mods.com/maps/gtaiv-burgershot-interior-sp-and-fivem>
- **GTA V Remastered: Enhanced** by Larcius: <https://www.gta5-mods.com/maps/gta-v-remastered-enhanced>
- **GTA VI Camera Flinch** by itsyaboi0008: <https://www.gta5-mods.com/scripts/gta-vi-camera-flinch>
- **GTA VI loading screens (HUD add-on)** by FBICat / Geckomacabre: <https://github.com/Geckomacabre/GTA-VI-Inspired-HUD>
- **HeapAdjuster Enhanced [Legacy + Enhanced]** by Chiheb-Bacha (based on Dilapidated's HeapAdjuster): <https://www.gta5-mods.com/tools/heapadjuster-enhanced>
- **Immersive Combat** by Artupaky01: <https://www.gta5-mods.com/weapons/immersive-combat-artupaky01>
- **iOS 26 App Icons (phone)** by shifuguru: <https://www.gta5-mods.com/misc/ios-26-app-icons>
- **Jason Duval House alpha** by MouMoud (uploaded by DimoSerb): <https://www.nexusmods.com/gta5enhanced/mods/1265>
- **LemonUI (for Script Hook V .NET)** by justalemon: <https://www.gta5-mods.com/tools/lemonui>
- **Map Updates (Enhanced package)** by Alex106: <https://www.gta5-mods.com/maps/map-updates>
- **MaxedV (Enhanced, alpha)** by MaxedDev: <https://www.gta5-mods.com/misc/maxedv>
- **Packfile Limit Adjuster Enhanced [Legacy + Enhanced]** by Chiheb-Bacha (based on alloc8or's): <https://www.gta5-mods.com/scripts/packfile-limit-adjuster-enhanced>
- **Prime Realism V (Enhanced)** by ModsTravic: <https://www.gta5-mods.com/misc/prime-realism-v-enhanced-legacy>
- **Quality of Life Vehicle Fixes Pack [Replace]** by austen64: <https://www.gta5-mods.com/vehicles/quality-of-life-vehicle-pack-replace>
- **Ryde - Rideshare Driver Mod** by euphoricrager: <https://www.gta5-mods.com/scripts/rideshare-driver-mod>
- **Static Bounds Limit Adjuster [Legacy & Enhanced]** by 3_Washing_Machines: <https://www.gta5-mods.com/scripts/static-bound-limit-adjuster>
- **Street Food Vendors Enhanced** by FastBurst: <https://www.gta5-mods.com/scripts/street-food-vendors-enhanced>
- **Up-n-Atom Burger Vinewood** by frdfare: <https://www.gta5-mods.com/maps/mlo-up-n-atom-burger-vinewood-add-on-sp-fivem>
- **Vinewood Plaza 24/7** by frdfare: <https://www.gta5-mods.com/maps/mlo-vinewood-plaza-24-7-add-on-sp-fivem>
- **VisualV** by _CP_ & robi29: <https://www.gta5-mods.com/misc/visualv>
- **GTA VI HUD (fbicat)** by fbicat: <https://discord.gg/PG5fAxvNtr>
- **GTA VI Inspired Features, HUD & Radar System (Enhanced package)** by unknown (gta5-mods page removed): <https://www.gta5-mods.com/misc/enhanced-oiv-gta-6-inspired-hud>
- **MP Jason & Lucia V (free heads + outfits)** by clutit: <https://www.gta5-mods.com/player/mp-jason-lucia-v>
- **Open World Interiors** by M8T: <https://www.gta5-mods.com/scripts/open-world-interiors-restaurants-fast-food-hospitals-diners-laundromats-nightclubs-gyms-bite>
- **Traffic V FEAR Edition** by FEAR2105: <https://www.gta5-mods.com/misc/traffic-v-fear-edition>

Paid add-ons Leonida can point to (never downloaded or unlocked by Leonida):

- Jason Duval + Lucia Caminos models by Patreon creator u10507693 (linked in INTER's video description and the GTA VI-Inspired HUD's README) (paid, optional): <https://www.patreon.com/c/u10507693/shop>
- Lively World Expansion (Enhanced build) by LWE team (paid, optional): <https://livelyworldexpansion.com/>
- NaturalVision Enhanced by Razed (paid, optional): <https://razedmods.com/gtavenhanced>

Tools:
- **CodeWalker / CodeWalker.Core** by dexyfex: <https://www.gta5-mods.com/tools/codewalker-gtav-interactive-3d-map>
  (source <https://github.com/dexyfex/CodeWalker>, "released for educational purposes only"). The archive mods are
  installed with a small helper built on your PC from his source. Thank you, dexyfex: support him on
  <https://www.patreon.com/dexyfex>.
- The **OpenIV** package format (`.oiv`) by the OpenIV Team: <https://openiv.com/>. Leonida applies the mods' `.oiv`
  packages the way OpenIV's mods-folder install does.
- OIV Package Installer (safari4831), 7-Zip (Igor Pavlov), Qt / PySide6, PyInstaller.

Fonts: Inter, Montserrat (SIL OFL 1.1). Full list with licences: `docs/CREDITS.md`.

Leonida V is MIT-licensed. Not affiliated with Rockstar Games or Take-Two Interactive.
