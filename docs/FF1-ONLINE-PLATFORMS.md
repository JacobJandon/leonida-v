# FF1: a "Leonida look" on multiplayer platforms (research)

Researched 2026-11-26. Every source below was read that day unless a different date is given. This is research
only, not legal advice.

**The rule for Leonida, in every case:** story mode only, never GTA Online. Leonida must never bypass, evade or
interfere with BattlEye or any other anti-cheat, and never inject into a protected process. Nothing in this file
changes that.

## 1. The big picture (Nov 2026)

| Platform | Status | Source |
|---|---|---|
| **FiveM / RedM (Cfx.re)** | Alive. Owned by Rockstar since 2023. Rockstar now calls it the official "Creator Platform". | [Cfx.re Creator PLA, last updated 10 Sep 2026](https://fivem.net/terms) (redirects to the PDF); [fivem.net](https://fivem.net/) |
| **alt:V** | Shut down after a request from Take-Two. No new servers from 2 Mar 2026, server list offline 4 May, community servers stop 6 Jul 2026. | [GTABoom, 10 Feb 2026 (updated 22 Jul)](https://www.gtaboom.com/popular-gta-v-mod-platform-given-shutdown-notice-after-9-years-of-operation-33dc) |
| **RAGE:MP** | Shutting down after a Take-Two cease-and-desist (announced 25 May 2026). Server list closed 1 Jun, client and backend off "as early as" 31 Aug 2026. | [Notebookcheck, 29 May 2026 (updated 5 Oct)](https://www.notebookcheck.net/Take-Two-shuts-down-GTA-V-RP-platform-RAGE-MP-after-cease-and-desist.1309478.0.html) |

Both teams said "FiveM is the only authorized platform for GTA V multiplayer modding" (quoted by the two articles
above). **Not confirmed first-hand:** rage.mp returned HTTP 403 and altv.mp got stuck in a redirect loop when I
tried them, so I could not read their own shutdown notices. I also found no post-August report confirming that
RAGE:MP actually went offline.

**Other platforms (brief):** I found no other active GTA V multiplayer platform that is authorised. Rockstar's mod
guidelines (published 10 Sep 2026) say "Multiplayer modding is limited to Rockstar Games' official licensed Creator
Platform", unless Rockstar licenses something directly ([MP1st, 21 Sep 2026](https://mp1st.com/news/ahead-of-gta-6s-release-rockstar-updates-modding-guidelines-monetization-multiplayer);
[Game Developer, 22 Sep 2026](https://www.gamedeveloper.com/production/-do-not-rockstar-outlines-modding-rules-before-gta-vi-touches-down)).
Rockstar's own page ([rockstargames.com/community-resources/mod-guidelines](https://www.rockstargames.com/community-resources/mod-guidelines))
only renders with JavaScript, so I could not read its text. The quotes here come from press coverage. **In
practice, FF1 means FiveM only.**

## 2. FiveM in detail

### Terms (Creator Platform License Agreement, read directly from the PDF)
- It is an agreement with Rockstar / Take-Two, on top of the Rockstar TOS and Community Guidelines. It also brings
  in the Rockstar Games Mod Guidelines as "Creator Policies" (§1.3).
- You must own a valid copy of the game (a "Covered Game", §1.2).
- Custom servers are allowed, but nothing may suggest that Rockstar approves, sponsors or endorses them (§2.3).
- Nothing grants any right to modify the Covered Games "other than as expressly permitted by Rockstar" (§2.2).
- Commercial use is limited (§3). Rockstar can take "Adverse Action" against users, content or servers (§7.2).
- I found no clause that names ReShade or graphics mods. Client-mod rules live in the technical docs below.

### Mod guidelines (from press coverage, see links above)
- No cheat menus or "other software that interferes with" Rockstar's online services or the Creator Platform.
- No mixing assets from one Rockstar game into another. No extending official storylines.
- Monetisation only through storefronts Rockstar approves. No gambling, loot boxes or crypto.

### Game edition and build ([docs: Server Commands](https://docs.fivem.net/docs/server-manual/server-commands/), [docs: Legacy vs Enhanced](https://docs.fivem.net/docs/developers/legacy-vs-enhanced/))

| | FiveM (Legacy) | FiveM for GTAV Enhanced |
|---|---|---|
| Game needed | GTA V Legacy | GTA V Enhanced |
| Status | Stable | **Early access** since 21 Jul 2026 ([GTABoom, 22 Jul 2026](https://www.gtaboom.com/fivem-for-gta-v-enhanced-is-live-c7cc)) |
| Build | The server picks it with `sv_enforceGameBuild` (startup only), builds 1 to 3889 | Latest build only (`1` = base game without DLC) |
| Pure mode (`sv_pureLevel`) | Set by the server: level 1 blocks modified client files except audio and "known graphics mods". Level 2 blocks all of them. | **Always on.** Server owners cannot turn it off. |
| Graphics mods | Allowed only if the server's pure level allows them | **"Graphic mods cannot be used"** during early access |
| Server assets | `stream` folder | `stream_enhanced` takes priority over `stream` |

The same docs say that if a player has modified base game files, FiveM shows an error naming the file. A GTA folder
with Leonida's story-mode mods installed may therefore break FiveM on pure-mode servers. Leonida's uninstall back to
the baseline snapshot is the clean fix.

### Anti-cheat
- Cfx.re runs its own enforcement, and servers may run their own anti-cheat resources. Cfx.re discourages
  global ban lists ([docs: Resource FAQ](https://docs.fivem.net/docs/support/resource-faq/)).
- ReShade: community and forum replies say a legitimate ReShade does not get you a global ban
  ([forum](https://forum.cfx.re/t/reshade-global-ban/5105314)). **This is not an official Cfx.re statement and
  is not confirmed.** Individual servers can still kick players.
- FiveM says it validates game ownership with Rockstar's services. Its FAQ also says it "doesn't modify game files"
  ([fivem.net](https://fivem.net/)).

### Custom HUDs and visuals
On FiveM these are **server resources**: Lua/JS scripts, NUI HTML HUDs, and streamed timecycle, weather and texture
files. The server owner installs them and FiveM streams them to players
([Legacy vs Enhanced docs](https://docs.fivem.net/docs/developers/legacy-vs-enhanced/)). This route is the one the
platform supports, and it works under pure mode.

## 3. What a "Leonida look" could legally be

| Option | Allowed? | Who must agree |
|---|---|---|
| **A. A FiveM server resource** (HUD in NUI, timecycle and weather presets, map props built from GTA V's own assets), published free and open source, installed by server owners | Yes, within the PLA and Creator Policies. Works on Legacy and Enhanced (`stream_enhanced`). | Each server owner. The Leonida owner decides the licence and the name. |
| **B. A client-side graphics preset** (for example a ReShade preset) for FiveM **Legacy** | Only on servers whose pure level and rules allow it. Not possible on Enhanced during early access. | Each server's rules. The player opts in. |
| **C. Leonida's story-mode mods (ASI, ScriptHookV, RPF edits) used in FiveM** | **No.** Pure mode blocks them, and they target story mode. | Not applicable |
| **Anything touching GTA Online, BattlEye or anti-cheat** | **Never.** | Not applicable |

**Leonida itself must never:** launch or touch GTA Online. Never inject into FiveM, GTA or any protected process.
Never patch FiveM files, get around pure mode or a server's rules, or help anyone dodge a ban. Never use GTA VI assets
(the guidelines forbid mixing assets between games). Never sell anything outside Rockstar-approved channels. Never
suggest that Rockstar endorses it.

**Name risk (owner decision):** "Leonida" is the state in GTA VI. Under PLA §2.3 and the guidelines, branding that
borrows from GTA VI could be read as implying a link to Rockstar or mixing IP. A neutral resource name is safer.
**Not confirmed:** I found no ruling on this.

## 4. Recommendation

**Is FF1 feasible?** Yes, but only as Option A: a free, open-source FiveM server resource that server owners choose
to install. It is not feasible as a Leonida feature that changes players' clients for online play. Option B is
narrow: Legacy only, per server, and resting on unofficial assurances.

**First legal step:** before writing any code, the owner should read the full Creator PLA, the Rockstar TOS and
the mod guidelines (rockstargames.com, in a real browser). Then build a small proof of concept on a **private local
FiveM test server** that the owner runs: a Leonida-style HUD in NUI plus one timecycle preset, using only GTA V
assets, under a neutral name. Keep it out of the Leonida app. Make it a separate repo or folder with no installer
path into the game.

**Needs permission:**
- **Owner:** whether to pursue FF1 at all, the name, the licence, and whether Leonida should ever link to it.
- **Each server owner:** installing the resource on their server. Any client-side preset needs that server's
  written rules to allow it.
- **Rockstar / Cfx.re:** any monetisation, or anything beyond what the PLA allows.
- **Wait:** do not plan client-side graphics for FiveM Enhanced until Cfx.re lifts the early-access ban.
