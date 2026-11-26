# FF2: other games (research, first candidate RDR2)

Research note for far-future item FF2 in `docs/PLAN.md`. Story mode / single player only. All sources read
2026-11-26 unless a different date is given. Nexus mod pages refuse automated fetches (HTTP 403), so Nexus facts
below come from search-result text and are marked "(search)".

## 1. RDR2 PC modding landscape

| Piece | What it is | Source |
|---|---|---|
| Script Hook RDR2 (Alexander Blade) | Latest **v1.0.1491.17, 09 Feb 2023**; supports game builds "1.0.1207.58/1491.17 and above". The download also contains the ASI loader **`dinput8.dll`** and an optional `NativeTrainer.asi`. When the game updates, only `ScriptHookRDR2.dll` needs updating. It **closes the game if you enter RDR Online**. | [dev-c.com](http://www.dev-c.com/rdr2/scripthookrdr2/) |
| ScriptHookRDR2 V2 (third party) | An alternative to Blade's hook with the same API. The page lists **build 1491.50**. Author and license not confirmed. | [Nexus 1472](https://www.nexusmods.com/reddeadredemption2/mods/1472) (search) |
| ScriptHookRDR2DotNet V2 | ASI plugin for running .NET scripts. Needs Blade's hook, .NET 4.8 and VC++ 2019 x64. Release date and build support not shown on the README. | [GitHub Halen84](https://github.com/Halen84/ScriptHookRDR2DotNet-V2) |
| Lenny's Mod Loader (LML) | Latest **0.6.8470.31280, 31 Mar 2023**. Copy "ModLoader" into the game root so **`vfs.asi` sits beside `RDR2.exe`**. Mods go in **`lml\<mod>\`** with an `install.xml`, or in the `lml\replace` / `lml\stream` folders. Optional `lml.ini`. "Older or cracked" game versions are not supported. | [rdr2mods.com](https://www.rdr2mods.com/downloads/rdr2/tools/76-lennys-mod-loader-rdr/) |
| version.dll | Many mods rely on it (online-content unlocker / Red Dead Offline). An outdated copy crashes the game after a title update. | [rdr2mods TU 1436.31](https://rdr2mods.com/news/articles/rdr2-title-update-143631-r31) |

**How updates break mods.** Title update 1.0.1436.31 broke many popular mods until each one was updated
([rdr2mods](https://rdr2mods.com/news/articles/rdr2-title-update-143631-r31)). Script Hook shows "Unknown game
version" after a launcher patch ([Nexus forums, 2022](https://forums.nexusmods.com/topic/11370443-script-hook-rdr2-critical-error)).
The latest patch notes I could find are TU 1.31, last updated 10 Apr 2024, and they only fix Red Dead Online crashes
([Rockstar](https://support.rockstargames.com/articles/rUl4IN127UGX3yFC9UGLy/red-dead-redemption-2-title-update-1-31-notes-ps4-xbox-one-pc)).
The game build has barely moved since 2023, which makes it a stable target, but I could not confirm the current build
number.

**Rockstar's position.** The launcher warns that unofficial mods "may result in being banned from online content".
Take-Two "generally will not take legal action" against single-player, non-commercial mods
([KitGuru, 10 Nov 2019](https://www.kitguru.net/gaming/matthew-wilson/rockstar-explains-stance-on-red-dead-redemption-2-pc-mods/)).
Rockstar told PC Gamer the same mod policy applies to RDR2
([PC Gamer](https://www.pcgamer.com/red-dead-redemption-2-mods-are-probably-okay-as-long-as-you-stay-offline/)).
The policy page is [PC Single-Player Mods](https://support.rockstargames.com/articles/5NVOAYjcTomO8v6SX2k76k/pc-single-player-mods).
It timed out for me. Search results said it was last updated 6 Jan 2025, which I could not confirm.

**Anti-cheat.** BattlEye with `-nobattleye` is a **GTA V** thing (already handled by Leonida). I found **no
reliable source that Red Dead Online uses BattlEye**. One low-quality page claims it does, which I could not verify
([buildstatus.puri.sm](https://buildstatus.puri.sm/red-dead-redemption-2-modded)). Rockstar has banned RDO mod-menu
users ([Rockstar Intel](https://rockstarintel.com/years-after-complaints-rockstar-games-addresses-some-of-the-most-critical-cheating-problems-for-red-dead-online-with-a-new-ban-wave)).
Leonida's rule stays the same: nothing that touches online.

**Vulkan / DX12.** You pick the API in
`Documents\Rockstar Games\Red Dead Redemption 2\Settings\system.xml` with `<API>kSettingAPI_Vulkan</API>` or
`kSettingAPI_DX12`. After changing it, delete any `sga_*` files in that folder
([Rockstar ERR_GFX_INIT](https://support.rockstargames.com/articles/2MQafAtBWiOUJrPDLx5I2U/err-gfx-init-error-when-launching-red-dead-redemption-2-on-pc)
(search; the page timed out), [techrbun](https://www.techrbun.com/change-rdr2-graphics-api-vulkan-dx12-using-notepad/)).

## 2. Mod sites and automated downloads

| Site | Rule relevant to Leonida | Source |
|---|---|---|
| Nexus Mods (ToS, updated 12 May 2026) | s.10: no downloading that "significantly exceeds normal and expected usage". s.11: no bots, spiders or scrapers. Download managers are not mentioned. | [Nexus ToS](https://help.nexusmods.com/article/18-terms-of-service) |
| Nexus API (AUP, 1 Dec 2020) | Personal keys are for private use only. Public apps must register with support and send app name/version headers. No mass fetching to rehost. | [API AUP](https://help.nexusmods.com/article/114-api-acceptable-use-policy) |
| Nexus download links | The API's download-link call is **Premium-only**. Free users must open each mod's download page, and Nexus says this is what keeps ad revenue flowing. Vortex collections download automatically only for Premium users. | [Nexus forum 2018](https://forums.nexusmods.com/topic/7189046-new-error-message/), [collections notice](https://www.nexusmods.com/news/14538), [collections preview](https://nexusmods.com/news/14568) |
| rdr2mods.com | Hosts LML and many scripts. **I could not find its terms on automated downloads.** Ask before adding it. | [rdr2mods news](https://www.rdr2mods.com/news) |
| dev-c.com | No re-hosting or download rules on the page, only a copyright line. | [dev-c.com](http://www.dev-c.com/rdr2/scripthookrdr2/) |

Leonida's current Nexus flow already fits these rules: the user signs in themselves, then Leonida clicks "Slow
download" and waits through the timer, with no API download links. gta5-mods has no RDR2 sister site. The RDR2 hubs
are Nexus and rdr2mods.com.

## 3. Example story-mode mods (install methods)

| Mod | Type | Install method | Page |
|---|---|---|---|
| Rampage Trainer | Trainer, top all-time on Nexus | `.asi` in root + Script Hook | [Nexus top list](https://www.nexusmods.com/reddeadredemption2/mods/trendingalltime/) (search) |
| VESTIGIA 2.0 | Weather / lighting (timecycle) | LML folder `lml\VESTIGIA` | [Nexus 6347](https://www.nexusmods.com/reddeadredemption2/mods/6347) (search) |
| Vivid Horizons | Graphics overhaul | LML + ASI loader | [Nexus 4426](https://www.nexusmods.com/reddeadredemption2/mods/4426) (search) |
| Ped Damage Overhaul | Gameplay (NPC reactions) | Script (`.asi`) | [PC Gamer list](https://www.pcgamer.com/best-red-dead-redemption-2-rdr2-mods) |
| Red Dead Offline | Framework that brings online assets into story mode | Needs `version.dll` | [PC Gamer list](https://www.pcgamer.com/best-red-dead-redemption-2-rdr2-mods) (exact page not confirmed) |

Leonida's install methods map cleanly: `copy` for `.asi` and dlls in the root, a new `lml` method (folder into
`lml\`, Leonida never edits `mods.xml`), and `guided` for ReShade presets. The GTA-only `rpf` method has no RDR2
equivalent here.

## 4. What a per-game `game.json` needs

- **Exe and editions.** The game folder holds `RDR2.exe` and `PlayRDR2.exe`
  ([Steam discussion](https://steamcommunity.com/app/1174180/discussions/0/3823038052309818065),
  [Rockstar](https://support.rockstargames.com/articles/6JGT3mscb7rKyB9qFQvR9h/error-unable-to-launch-rdr2-exe-due-to-lack-of-privileges-on-the-game-library-directory)).
  Steam app 1174180 ([Steam](https://store.steampowered.com/app/1174180/)). Red Dead Online standalone is app 1404210.
  Epic and Rockstar Launcher folder paths were not confirmed.
- **Build.** Read the file version of `RDR2.exe`, as Leonida does for GTA (e.g. `1.0.1491.17`). Uninstall listings
  show this format ([advanceduninstaller](https://www.advanceduninstaller.com/Red-Dead-Redemption-2-1_0_1311_23--79b2319d1964db0c4a81fa668e7d8db3-application.htm)).
- **Stack.** `dinput8.dll` (ASI loader), then `ScriptHookRDR2.dll`, then optionally the .NET hook, `vfs.asi` + `lml\`
  (LML), and `version.dll`.
- **Online-safe.** Before any Red Dead Online session, move all of these out and put them back afterwards.
- **Settings.** `system.xml` (the GPU API and graphics settings).

```json
{
  "id": "rdr2",
  "name": "Red Dead Redemption 2",
  "story_mode_only": true,
  "exes": {"game": "RDR2.exe", "launcher": "PlayRDR2.exe"},
  "stores": {
    "steam": {"app_id": 1174180},
    "epic": {"app_name": null},
    "rockstar": {"registry_hint": null}
  },
  "build": {"source": "file_version", "file": "RDR2.exe", "min_supported": "1.0.1491.17"},
  "stack": [
    {"id": "asiloader", "files": ["dinput8.dll"], "from_mod": "scripthookrdr2"},
    {"id": "scripthookrdr2", "files": ["ScriptHookRDR2.dll"], "page": "http://www.dev-c.com/rdr2/scripthookrdr2/",
     "breaks_on_update": true},
    {"id": "lml", "files": ["vfs.asi"], "dirs": ["lml"], "optional": true}
  ],
  "mod_layout": {"root_asi": ".", "loader_dir": "lml", "scripts_dir": "scripts"},
  "install_methods": ["copy", "lml", "guided"],
  "online_safe": {
    "move_out": ["dinput8.dll", "version.dll", "ScriptHookRDR2.dll", "*.asi", "vfs.asi", "lml", "scripts"],
    "online_entry_points": ["Red Dead Online menu", "Steam app 1404210"]
  },
  "settings_files": [
    {"id": "system", "path": "%USERPROFILE%/Documents/Rockstar Games/Red Dead Redemption 2/Settings/system.xml",
     "api_key": "API", "api_values": ["kSettingAPI_Vulkan", "kSettingAPI_DX12"], "clear_after_api_change": ["sga_*"]}
  ],
  "anti_cheat": {"name": null, "rule": "never install or launch anything for online play"},
  "download_sites": ["github", "dev-c.com", "nexusmods (user signs in)", "rdr2mods.com (terms unconfirmed)"],
  "manifest_dir": "manifest/rdr2"
}
```

**Leonida modules that would read it:** `detect.py` (exes, stores, build), `paths.py`, `manifest/__init__.py`
(per-game manifest folder), `matcher.py` (build ranges), `installer.py` (layout and the new `lml` method),
`onlinesafe.py` (`move_out`), `checks.py` / `verify.py` / `filecheck.py` (stack present and up to date),
`gamesettings.py` / `settings.py` (`system.xml`), `playtest.py` / `session.py` / `gamestate.py` / `playinfo.py`
(process names), `downloader.py` / `pagehints.py` (site rules), and `gui/app.py` / `gui/chooser.py` (pick the game
first). `rpf.py`, `cwtools.py`, `menubridge.py` and `ingame.py` stay GTA-only, and the in-game menu would need its
own RDR2 script.

## 5. Other candidates (context only)

| Game | Note | Next? |
|---|---|---|
| Cyberpunk 2077 | Official REDmod (free DLC, updated with every patch). Old `archive` mods still load ([cyberpunk.net](https://cyberpunk.net/en/modding-support), [GameSpot](https://www.gamespot.com/articles/cyberpunk-2077-now-has-an-official-modding-tool/1100-6507375/)). | Good second: official support, but most mods are on Nexus, so the sign-in flow applies. |
| Skyrim SE | Nexus collections and Vortex already do this job, automatically for Premium users ([Nexus](https://nexusmods.com/news/14568)). | No: crowded space, and almost entirely Nexus. |

## Could not confirm

- RDR2's current PC build, and whether anything was patched after Apr 2024.
- Whether Red Dead Online now uses BattlEye.
- The date of Rockstar's mod policy page.
- rdr2mods.com's rules on automated downloads.
- The author and license of ScriptHookRDR2 V2.
- Epic and Rockstar Launcher install paths and registry keys.
- Whether RDO standalone uses the same `RDR2.exe`.
