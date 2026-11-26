# GTA V Legacy (GTA5.exe): data status (plan F3)

Status 2026-11-26 (manifest session). The Legacy mod list is `mods-legacy.json`, with modpacks, profiles and
hotkeys `-legacy.json`.

## What's done in the data

Every Legacy mod has:
- a real page, a version, an image, features and a proof that it's on (`verify`);
- the settings it needs: SHVDN's script timeout with Enable All Interiors, the HUD's keys and options, Menyoo's key,
  All MP Vehicles' traffic and blips.

`leonida check --edition legacy` against a fake Legacy folder (GTA5.exe, build 1.0.3725.0) is clean for Core, Plus
and Showcase: no error, no warning. The only notes are which mods use an older version on that build (Drive V 7.4,
the build's own gameconfig.xml, Enable All Interiors).

The mods without an archive (the .asi and script mods) install automatically:
- Script Hook V, Script Hook V .NET, Menyoo, LemonUI;
- the Heap / Packfile / StaticBounds adjusters;
- All MP Vehicles, Straight To Story Mode, Enable All Interiors, Street Food, ActionsV, the Camera Flinch.

The archive mods are by hand with OpenIV (each says why):
- the HUD's .oiv, Drive V, NextGen Euphoria, Immersive Combat;
- Map Fixes / Bugstar / Map Updates, the walk-in interiors, GTA V Remastered;
- the gameconfig.xml for your build, the fwBoxStreamer patch.

The reason: Leonida's archive helper only reads GTA5_Enhanced.exe's keys. Supporting GTA5.exe is a change in
`build/`, for the exe-build session.

## What only a real Legacy install can confirm

1. Script Hook V (v3889.0 or newer) loads on the installed build (`ScriptHookV.log`: "INIT: Success").
2. OpenIV.asi loads the `mods` folder (the Legacy equivalent of OpenRPF), and an .oiv installed into `mods` shows in
   game.
3. Script Hook V .NET (the community 3.7.0 nightly 193+) runs the GTA VI-Inspired HUD: its minimap draws in Windowed
   Borderless, and the three vihud packs load.
4. The per-build gameconfig.xml together with HeapAdjuster, PackfileLimitAdjuster and StaticBoundLimitAdjuster loads
   Showcase without a crash. This is the Legacy answer to the Enhanced memory crash.
5. Map Fixes, Bugstar and Map Updates Legacy packs (`spmapfixes`, `spfixes`, `spmapupdates`) and GTA V Remastered
   (`vremastered`) are present in game (IS_DLC_PRESENT through the Leonida menu).
6. Enable All Interiors loads the MP maps by itself on Legacy too (`scripts\EAIInitalization.log`: "MP MAPS LOADED").
7. The Lively World Expansion free 2022 release works on today's Legacy build (its page doesn't say).
8. Online-safe moves the `mods` folder and the .asi files out, and the game starts clean. Uninstall then matches the
   pre-install snapshot.
9. A 30-minute session and a 10-run `playtest --repeat` without a crash.
