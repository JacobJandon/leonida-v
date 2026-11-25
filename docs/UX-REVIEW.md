# Launcher UX review (fresh eyes)

Reviewed on 2026-11-25 from the 16 real screenshots in `D:\Leonida\Screenshots` (owner's PC, Leonida 1.0.0.dev1,
GTA V Enhanced 1.0.1013.20, Leonida Showcase · Balanced, 34 of 35 mods installed). The reviewer plays a first-time
user who wants "GTA VI in GTA V" with as little effort as possible, and also a CurseForge user who knows how a mod
launcher usually works.

**Ranks**
- **must**: it misleads the user, blocks them, or is wrong.
- **should**: it confuses the user or costs them a click they shouldn't need.
- **nice**: polish.

**Owner** says where the fix lives:
- **GUI**: `leonida/gui/`, the downloader session.
- **data**: `leonida/manifest/*.json`, the manifest session.
- **both**: needs both.

Screenshots are named by their number:

| # | File | # | File |
| --- | --- | --- | --- |
| 01 | `01-welcome.png` | 09 | `09-browse-mods.png` |
| 02 | `02-game.png` | 10 | `10-pack-overview.png` |
| 03 | `03-choose-mods.png` | 11 | `11-pack-mods.png` |
| 04 | `04-get-mods.png` | 12 | `12-pack-variants.png` |
| 05 | `05-check.png` | 13 | `13-pack-screenshots.png` |
| 06 | `06-install.png` | 14 | `14-pack-files.png` |
| 07 | `07-manage.png` | 15 | `15-settings.png` |
| 08 | `08-browse-packs.png` | 16 | `16-about.png` |

---

## Top 10

1. **M1** Two navigations for one job: the SET UP wizard and the LIBRARY pages do the same things.
2. **M2** A returning user with 34 mods lands on the first-run Welcome page.
3. **M3** The app never says "Windowed Borderless + English" or "press Insert once", so the HUD and the interiors can
   silently fail.
4. **M4** No page lists which keys do what.
5. **M5** Install shows a stale "next step" (Forza Roads, not downloaded) after everything else is installed, and no
   page names the one missing mod.
6. **M6** Status counts disagree: 35 / 34 / 40 steps / "34 of 35 ready".
7. **M7** A locked-setting false alarm: "Keys/CancelJob is Next, locked at PageDown" (Next *is* PageDown).
8. **M8** Developer notes are shown to users: "(the owner's PC)", raw log lines and page quotes in the locked
   settings.
9. **M9** Jargon everywhere: "scanned OK / not scanned yet", "rpf", "dlclist", "copy · 2 change(s) logged", raw hashed
   file names.
10. **S1** Not the CurseForge basics: no update badge, no per-mod changelog, no "Verify files", no last played, no
    per-mod enable/disable.

---

## Must

### M1. Two navigations for one job (01–16, sidebar)
**Issue:** the sidebar has LIBRARY (Browse, My modpack, Settings, About & help) and SET UP (Welcome, Game, Choose
mods, Get mods, Check, Install, Manage). Several pages do the same job twice:
- Choose mods (03) and Browse > Modpacks (08) plus the modpack's *Variants* tab (12);
- Get mods (04) and *Files & logs* (14), and the header's *Get the files (1)*;
- Manage (07) and My modpack (10–11).

A new user doesn't know which path to follow. A returning user sees eleven items.

**Fix (GUI):**
- Make the modpack page the home: **My modpack** with tabs *Overview · Mods · Variants & settings · Screenshots ·
  Files & logs*, one big state-driven button, and a *Manage* tab or menu.
- Show the wizard (Game → Choose → Get → Check → Install) only for the first run, and later from **My modpack >
  Set up again**.
- Collapse SET UP in the sidebar once a pack is installed. Keep it as one "Setup wizard" item.
- Move Settings and About & help to the bottom of the sidebar, apart from LIBRARY.

### M2. A returning user sees the first-run Welcome (01)
**Issue:** with 34 mods installed, Leonida opens on Welcome:
- with "Start: find my game";
- with Back/Next buttons on the first page;
- with the promise "that Vice City light" (`app.py:276`). There is no Vice City. README's *Honest limits* says so.

**Fix (GUI):**
- Once a pack is installed, open **My modpack** (10).
- Keep Welcome for the first run only. Drop *Back* on it.
- Replace "that Vice City light" with "a warmer, GTA VI-style light (VisualV)".

### M3. The two in-game requirements are never shown (01–16)
**Issue:** the GTA VI HUD needs **Screen Type = Windowed Borderless** and the **game in English**. Enable All
Interiors needs **Insert pressed once** after loading. Without them the HUD has no minimap, and online interiors are
missing or you fall through floors. Neither requirement appears on any page: not the Overview (10), Install (06),
Manage (07) nor Settings (15). `grep Borderless leonida/gui` finds nothing. They're only in `docs/IN-GAME-CHECKS.md`,
the HUD's mod notes and `checks`.

**Fix:**
- **GUI:** add a **"Before you play"** card at the top of the Overview (10) and on the screen after the last
  Install step. Example:
  > 1. In GTA V: *Settings > Graphics > Screen Type = Windowed Borderless*.
  > 2. Game language: English.
  > 3. Once in story mode, press **Insert** once.
- **GUI:** where possible, check the first two: read `settings.xml` in `Documents\Rockstar Games\GTA V Enhanced`,
  and the language from the store or launcher. Show ✓ or ⚠.
- **data:** add a pack-level `beforePlay` list to `modpacks.json` so the text isn't hard-coded. Ask the manifest
  session.

### M4. No page says which keys do what (01–16)
**Issue:** `hotkeys.json` has about 20 keys, and Leonida moved several of them:
- ActionsV F7, AuraV F11, Ryde Page Up / Page Down;
- the HUD's V and Left Alt, Menyoo F8 / F9 / F3, the SHVDN console F4, Food Delivery F6.

The launcher never shows them. The Overview's notice cards (10) mention F7 and "hold E", but not V, Left Alt, F8, F6
or Page Up. A player starts the game and doesn't know how to open anything.

**Fix (GUI):**
- Add a **Keys** card to the Overview (10): two columns (key · what it does · mod), from `hotkeys.json` filtered to
  the selected mods, with keys Leonida moved marked "moved by Leonida".
- Add a **Copy as text** or **Print** button.
- Show the same list on About & help (16).
- In each notice card, show its key as a key cap (e.g. `V` "hold for HUD settings").

### M5. A stale "next step", and the missing mod isn't named (04, 06, 08, 10, 11)
**Issue:**
- Install (06) shows **NEXT STEP 35. Forza Horizon 6 Roads … not downloaded yet** as the hero panel, while the rows
  above are installed. It reads like an error.
- Get mods (04): "34 of 35 ready" doesn't say which one.
- Browse (08): "In use · 34/35 installed".
- Mods tab (11): "35 MODS · 34 INSTALLED · 34 DOWNLOADED" without pointing at the missing one, which is row 35, at
  the very bottom.
- The header button *Get the files (1)* (10–14) doesn't say what the one file is.

**Fix (GUI):**
- One shared **status line** everywhere: "34 of 35 installed · missing: Forza Horizon 6 Roads (optional add-on) ·
  [Get it] [Skip it]".
- On Install, when the only remaining step can't run, show "All downloaded mods are installed" first. Show the
  missing one second, as a small card with **Get it** and **Remove from my pack**.
- Mods tab: sort or filter *Needs attention* first.
- Header button: "Get Forza Horizon 6 Roads" when only one file is missing.

### M6. The counts disagree (03, 04, 07, 08, 09–16)
**Issue:**
- Choose mods (03): "35 mods selected"; the bottom bar: "Mods on · 34 mods".
- Manage (07): "34 mods installed in 40 steps".
- Pack chip: "35 mods".
- Get mods: "34 of 35 ready".

Steps vs mods is an internal distinction: the pack-settings steps and the framework steps make 40.

**Fix (GUI):** always say "**installed / in your pack**": "34 / 35 mods installed". Never show step counts on user
pages; keep them in *Files & logs* / Undo. The bottom bar should say "34 of 35 mods on".

### M7. A locked-setting false alarm: "Next" is PageDown (01, 05)
**Issue:**
- Check (05): "scripts/RideShare.ini: Keys/CancelJob is Next, locked at PageDown".
- Welcome (01): "1 locked setting(s) changed".

In .NET's `Keys` enum, `Next` and `PageDown` are the same key (34), as are `Prior` and `PageUp` (33). The mod most
likely rewrote its ini with the enum's other name. `settings.same()` compares text, so it reports drift that isn't
there, and the user is asked to "restore" a key that's already right.

**Fix:**
- **settings.py** (not GUI; the downloader or main session): treat .NET key aliases as equal in `same()`:
  - `Next`/`PageDown`, `Prior`/`PageUp`;
  - `Return`/`Enter`, `Capital`/`CapsLock`;
  - `Snapshot`/`PrintScreen`, `Back`/`Backspace`.
- Add a test.
- **data** quick fix if wanted: none needed once aliases are equal.
- **GUI:** word a real drift as "Ryde's *cancel ride* key was changed to X; Leonida sets Page Down so it doesn't
  clash with Menyoo (F9). [Put it back] [Keep mine]". Not "Keys/CancelJob".

### M8. Developer notes shown to users (12, 09, 10, 03)
**Issue:**
- Variant *Performance* (12): "For GTX 1070-class cards without ray tracing **(the owner's PC)**". This is from
  `modpacks.json` lines 289 and 336.
- Locked settings (12): the `why` text quotes a raw log line: "'[ERROR] Blocking script! Script
  EnableAllinteriors.LoadMPMaps … (ScriptHookVDotNet.log, owner's PC, 1.0.1013.20, 2026-11-25)". Others say "page:
  'Set to 1 only if…'", "Its page gives no value."
- Browse detail (09): the About text quotes changelog lines ("Its page: 'Support GTA V Enhanced' (1.3.0) and 'Update
  …").
- The Look category (03): "Pick one; none is tested in the game yet."
- The Showcase *About this pack* (10): "VisualV and the extras aren't tested in the game yet". This is stale now that
  the Showcase runs on the owner's PC.

**Fix (data, manifest session):**
- Rewrite user-facing strings:
  - "For cards without ray tracing, like a GTX 1060/1070 or RX 580";
  - Look: "Pick one; all free";
  - the Showcase's About: drop "aren't tested".
- Split each locked setting's `why` into a short user-facing `why` (≤ 80 characters, e.g. "gives Enable All
  Interiors time to load the online maps") and a `source` field for provenance. The GUI shows `why` only and puts
  `source` behind an ⓘ tooltip.
- Same for `notes`: show the first sentence; put the rest behind *More*.

### M9. Jargon on the main path (02, 04, 05, 07, 14)
**Issue:**
- Game (02): "Mod list in use … 4 modpacks, 53 mods".
- Get mods (04) and Files (14): "not scanned yet" / "scanned OK"; raw hashed file names (`58cd7d-DirectStorageFix.zip`,
  `Mmd Jason Duval Houses 1265 1 2026-08-07T16-37Z Ge12K4vko.7z`).
- Check (05): "mods\update\update.rpf … gameconfig.xml"; version.dll notes.
- Manage (07): "copy · 2 change(s) logged".
- "rpf", "dlclist", "1 locked setting(s) changed".

**Fix (GUI):** a wording pass, as follows. Keep the raw text in a *Details* expander, or in Files & logs for people
who want it.

| Now | Say instead |
| --- | --- |
| scanned OK / not scanned yet | ✓ checked / not checked yet (or hide until it matters) |
| 2 change(s) logged | 2 files added (can be undone) |
| mods\update\update.rpf … | Uses its own copy of the game's update archive in the *mods* folder; the game's files aren't changed |
| 1 locked setting(s) changed | 1 mod setting changed since install |
| 53 mods, 4 modpacks (Game page) | remove; that's catalogue info, not about your game |
| version.dll … | show only if it is a problem |

### M10. The AuraV card doesn't warn on a GTX 1070 (03)
**Issue:** the AuraV Lite add-on (path tracing, NVIDIA RTX only) can be ticked like any other on a GTX 1070. The
Check page catches it only later, if at all.

**Fix (GUI):** read the detected GPU (`detect.py` already knows it). Grey out add-ons whose requirement isn't met:
"Needs an NVIDIA RTX card; you have a GTX 1070". Use the same rule for the Ultra variant (12 GB+, RT): show "Not
recommended for your GTX 1070". Recommend Performance for the detected card (see S6).

---

## Should

### S1. Things a CurseForge user looks for and doesn't find (07, 09, 11)
**Issue:** none of these exist:
- an **update badge** on mods and on the pack card ("2 updates");
- a **changelog** per mod and per pack ("What's new in 1.3.2");
- **Verify files** for the pack (re-hash installed files against the install log and repair);
- **last played** / play time;
- a per-mod **enable/disable** toggle;
- **Open folder** for a mod.

**Fix (GUI):**
- Mods tab rows (11) get a ⋯ menu: *Changelog · Open author's page · Open its files · Update · Disable · Remove
  (undo its step)*.
- Pack header gets **Verify files** next to the main button: it checks the install log's hashes and offers *Repair*.
- Bottom bar: "Last played 2 days ago".
- Updates: a dot on *My modpack* and a count on the pack card; Manage's *Check for updates* fills it.
- Changelog: the author's release notes come from the GitHub API for GitHub mods. For page mods, link the page's
  changelog tab.

### S2. The main button doesn't follow the state (06, 08, 10, bottom bar)
**Issue:** the header says *Get the files (1)*, the bottom bar *Play*, Browse cards say *Play* on one and *Open* on
the others (08), and Install has its own Next buttons. The user can't tell which button is "the" next action.

**Fix (GUI):** one state-driven primary button, the same in the pack header and the bottom bar:
*Find my game → Get mods (n) → Install (n) → Play*, plus "⚠ Fix 1 setting" when a setting drifted. Browse cards say
**Open** for every pack and **Play** only on the pack in use.

### S3. Two Next buttons on wizard pages (03, 04)
**Issue:** "Next: get mods" plus "Next" (03); the same on 04.

**Fix (GUI):** keep the named one ("Next: get mods") in the footer. Remove the generic one (`app.py:1512`) on pages
that have a named one.

### S4. Online-safe as two buttons (07)
**Issue:** Online-safe ON and OFF are two buttons. It's unclear which state is active.

**Fix (GUI):** one switch with a state line: "Mods are **in** the game folder (story mode)" / "Mods are **moved
out**: safe for GTA Online". The *Play* button should warn when Online-safe is on ("Mods are moved out: play without
mods?").

### S5. Force update sits next to Check for updates (07, 15)
**Issue:** *Force update…* is one click away from *Check now*, on both Manage and Settings. That's a risky action
next to a harmless one, and it's duplicated.

**Fix (GUI):** keep updates in Settings only. Put *Force update* behind a ⋯ menu with a confirm dialog. Manage keeps
just a "Leonida is up to date" line.

### S6. Variant choice doesn't use the detected card (12)
**Issue:** the user has a GTX 1070 and is on *Balanced*, while *Performance* says it's for GTX 1070-class cards.
Nothing says "recommended for you". The 4th column of the variant row is empty.

**Fix:**
- **GUI:** add a "Recommended for your GTX 1070" badge from the GPU and VRAM, and a soft warning when the chosen
  variant is heavier.
- **data:** add `recommend` hints to the variants (min VRAM, RT yes/no).

### S7. Locked settings are an ini dump (12)
**Issue:** rows like `ResourceExtensions.ini · budget/StreamingMemoryBudget = 0` are unreadable for players. The
`why` column is misaligned: the long key on that row pushes "page: 'Set to 1…'" out of the column, and the two mod
blocks have different column starts. The list is long, and there's no *Reset* or *Keep mine* here.

**Fix (GUI):**
- One line per setting in words: "**People on foot:** 1.5× (Balanced)". Use a `label` field from the data with the
  key as a tooltip.
- A two-column grid with a fixed key column and wrapping.
- Collapse per mod.
- Show drift inline with *Put back / Keep mine*.

**data:** add `label` to each locked key.

### S8. The Screenshots tab only repeats the Mods thumbnails (13)
**Issue:** the tiles are the same cover images as the Mods tab, including placeholder tiles ("FRAMEWORK",
"DirectStorage" on black). There are no in-game shots, and nothing shows what GTA VI-like change to expect. The grid
leaves a gap on the right.

**Fix (GUI):**
- Show only mods with real gallery images, framework mods excluded, and several images per mod where the manifest
  has them.
- Add a lightbox.
- Let the grid fill the width.
- Or merge the tab into Overview as a strip under *What you'll notice*.

The rule stays: images are hot-linked from the author's page, never re-hosted.

### S9. Overview: the description is shown twice, and the hero picture is random (10–14)
**Issue:** the header repeats the pack description, cut off at "the dyn…". The full text is right below under
*About this pack*. The hero image (a yellow building with a "Dusche" sign) doesn't say GTA VI.

**Fix (GUI):**
- The header gets a one-line tagline: "Everything free that brings GTA V closest to GTA VI". The full text stays in
  About.
- Use a pack-specific hero image from a mod's own gallery (hot-linked), e.g. the HUD or VisualV.

### S10. "What you'll notice" doesn't say how (10)
**Issue:** 24 equal cards in pack order, and some are terse ("Jason's house."). There are no keys and no places, and
nothing links a card to its mod.

**Fix:**
- **GUI:** group the cards like *IN-GAME-CHECKS.md* (HUD & police · World & look · Driving · Fighting · Places ·
  Jobs). Show the key cap or place on each card.
- **GUI:** clicking a card opens the mod.
- **data:** the mods' `checks` already have the keys and places. Use the first check as the card text, or add a
  short `notice` per mod.

### S11. Browse rows are noisy and truncated (09)
**Issue:**
- Every row repeats "Version for build 1.0.1013.20:".
- The badges are inconsistent: "In this pack" stacked over "Installed"; "Ready" (downloaded, not installed?); "Not
  downloaded"; "Paid".
- The paid Jason + Lucia row shows "by Patreon creator u10507693 (linked in INTER's video …D's README)", with a raw id
  and a mid-word cut, and "Version for build 1.0.1013.20: —".
- "In my pack only" touches the right edge.

**Fix:**
- **GUI:** row line 2 = author · category · size. Show the version only in details.
- **GUI:** one status badge from a fixed set:
  - *In your pack · Installed* / *Downloaded* / *To download*;
  - *Not in your pack*;
  - *Paid (author's shop)*.
- **GUI:** "In my pack only" gets right padding.
- **data:** give the paid mod a proper `author` (the creator's display name, or "Patreon creator") and move the
  provenance to notes.

### S12. Browse categories don't match Choose mods (03, 09)
**Issue:** Browse filters by 18 kinds, including the technical *Framework, Fixes, Tools*. Choose mods uses the
add-on categories *Look, World life, Driving, Combat, Characters, Menus, phone & sound*. That's two taxonomies.

**Fix (GUI):** use the add-on categories as the main chips, plus "Required (framework)". Put the fine-grained kinds
in a *More filters* dropdown.

### S13. The Browse detail panel can't act on a mod (09)
**Issue:** the only action is *Open the author's page*. There's no *Add to my pack / Remove*. The About text box is
small, and its scrollbar sits inside the panel's own scroll.

**Fix (GUI):**
- *Add to my pack* / *Remove from my pack*, which add or remove it as an add-on, with a clash check.
- *Changelog* (S1).
- Let the panel scroll as a whole.

### S14. The Game page is mostly empty and repeats itself (02)
**Issue:**
- A large empty "Detected folders" box.
- A "Selected: … version:" line that repeats the card above it.
- Half the page is blank.

**Fix (GUI):** one card: "GTA V Enhanced · 1.0.1013.20 · Steam · D:\Games\…  ✓ supported", with *Change folder*. Show
the folder list only when more than one install is found.

### S15. Files & logs shows downloads, not logs (14)
**Issue:** the tab shows the Downloads list, the same as Get mods, with "not scanned yet" / "scanned OK". No logs are
visible above the fold. Mod names (large, bold) and file names (small, grey) don't line up in columns.

**Fix (GUI):**
- Two sections, *Installed files* (per mod: files added, backups, Undo) and *Game logs* (ScriptHookV.log,
  ScriptHookVDotNet.log, asiloader.log, with ✓/⚠ from `leonida verify`, and *Open*).
- Downloads collapse into one line: "35 files in D:\Leonida\Downloads · [Open folder] [Verify]".
- Use a table layout.

### S16. "Good to know" twice on Check (05)
**Issue:** two cards with the same title.

**Fix (GUI):** title them by content: "Your game" / "Your mods". Or merge them.

### S17. Install rows: repeated download method, missing badges, an empty log (06)
**Issue:**
- "in-app download (author's page)" on every row.
- Some installed rows lack the "OK in game" badge, and it's unclear why: not play-tested yet?
- The Step log box is empty.

**Fix (GUI):**
- Drop the download method on Install.
- Show *Installed · Play-tested ✓* or *Installed · not play-tested yet*.
- Hide the Step log until a step runs, or show the last step's log.

---

## Nice

| ID | Screen | Issue | Fix | Owner |
| --- | --- | --- | --- | --- |
| N1 | 01, bottom bar | "ⓘ 1 new": new what? | Show a tooltip and click target: "1 new: Leonida 1.0.1 is out" / "1 mod update". | GUI |
| N2 | 01 | The Welcome notice says "1 locked setting(s) changed" without a link | Make it a link to the setting, with *Put back / Keep mine*. | GUI |
| N3 | 03 | Pack radio buttons on Choose mods and a *Change pack* button | Keep one: the pack card with *Change*. | GUI |
| N4 | 03 | The Forza card title is cut off; "1 mod: X" lines repeat the card's name | Wrap titles to 2 lines; drop "1 mod: X" when the add-on is a single mod. | GUI |
| N5 | 04 | "Download all automatic (0)" is a disabled button | Hide it at 0, or say "Nothing to download automatically". | GUI |
| N6 | 04 | The double-click hint is buried in help text | Add a row hover hint: "Double-click to open the author's page". | GUI |
| N7 | 08 | Browse-packs grid: descriptions cut off, empty space | Use 2-line descriptions with *More*, and a responsive grid. | GUI |
| N8 | 11 | The Script Hook V placeholder thumbnail reads "FRAMEW…" | Fit the placeholder label, or use a short label ("CORE"). | GUI |
| N9 | 11 | "v3889.0 / 1158.13 or newer" on a 1013.20 game reads as a mismatch | Show "v3889.0 (works on your 1.0.1013.20)". The build range goes in details. | GUI + data |
| N10 | 11 | "All add-ons…" link: unclear | "Add or remove add-ons". | GUI |
| N11 | 12 | Variant cards leave the 4th column empty | Use 3 equal columns over the full width. | GUI |
| N12 | 15 | Shortcuts: *Make* / *Remove them*, with no state | Show "Shortcuts: on Start menu ✓, desktop ✓" with one toggle. | GUI |
| N13 | 15 | "Downloads: Leonida's clicks on the sites" heading | "Let Leonida click Download for me on:". | GUI |
| N14 | 15 | The Modpack section in Settings repeats the variant picker | Remove it; link "Change variant on the Modpack page". | GUI |
| N15 | 15 | No game section in Settings | Add *Game*: the Windowed Borderless / English check (M3), Online-safe (S4), Verify game files (Steam/Epic/RGL link). | GUI |
| N16 | 16 | About & help has no help besides *Report a problem* | Add *Keys* (M4), *In-game checks* (from `checks`), *FAQ* (HUD missing, mods off for Online, undo). | GUI + data |
| N17 | 16 | Credits list mods that aren't in the pack (Community SHVDN nightly) in one flat list | Group the credits: *In your pack* first, then *Other mods Leonida knows*. | GUI |
| N18 | 16 | "Source checkout · Python 3.13.17", "1.0.0.dev1" shown prominently | Move the build info to a *Copy system info* tooltip; show "Leonida V 1.0" in release builds. | GUI |
| N19 | 06, 09, 11 | "in-app download (author's page)" / "automatic download" wording | Use one phrase set: "Downloads automatically" / "From the author's page (Leonida opens it)" / "Sign in to Nexus (free)" / "Paid: author's shop". | GUI |
| N20 | all | Contrast: grey secondary text (#8a8a8a-ish on #121216) at 12 px is hard to read on the Files and Variants tabs | Raise secondary text to ≥ 4.5:1, and ≥ 13 px for body text. | GUI |

---

## Data-side fixes (status 2026-11-25)

1. **Done:** variant descriptions without "(the owner's PC)" (M8).
2. **Done:** the Look category no longer says "none is tested in the game yet" (both `modpacks*.json`).
3. **Done:** the Showcase *About* no longer says "VisualV and the extras aren't tested in the game yet". VisualV is
   also out of the Showcase defaults (it draws grid lines on 1.0.1013.20).
4. **Done in part:** every locked setting's `why` is now a short plain sentence. Raw log lines and page quotes moved
   into the mod's notes, and the "(clash Cn)" ids are gone.
   - **Still open:** a separate `source` field and a `label` per key (S7) need a loader change: the loader belongs to
     the downloader session, so agree on the field names first.
5. **Open:** a pack-level `beforePlay` list (M3) and variant `recommend` hints (S6) need the same loader change.
   Meanwhile the owner's pick has *16 GB* / *32 GB* variants, and docs/IN-GAME-CHECKS.md has a checklist.
6. **Done:** the paid Jason + Lucia entry's author is "the Jason & Lucia model creator (Patreon shop)"; the raw
   creator id is in its notes.
