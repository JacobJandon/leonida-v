# CodeWalker in Leonida: editing GTA V Enhanced archives (plan item F6)

Seventeen mods can only be installed by editing GTA's `.rpf` archives, or ship as OpenIV `.oiv` packages. All of
them use install method `rpf` in mods.json:
- Map Fixes, Bugstar Fixes, Map Updates;
- Drive V, NextGen Euphoria, Immersive Combat, GTA VI Combat Camera;
- the GTA VI-Inspired HUD and its loading screens;
- Benny's Motorworks, GTA V Remastered, VisualV, iOS 26 app icons;
- the four walk-in interiors (Burger Shot, Up-n-Atom, Elgin and Vinewood 24/7).

Leonida does this itself with a small helper built on **CodeWalker.Core** (dexyfex), install method `rpf`. It always
edits copies in `<game>\mods\` (OpenRPF loads those first), never the game's own archives. Every change is logged and
rolled back exactly.

## Pieces

| Piece | What |
|---|---|
| `build/codewalker/LeonidaRpf/` | C# console helper (net48; .NET Framework 4.8 ships with Windows 10/11) on CodeWalker.Core |
| `build/build_rpf_helper.py` | builds it from CodeWalker's GitHub source at a pinned commit (see below) into `build/codewalker/bin/` (`--install-to <state>\tools\LeonidaRpf`) |
| `leonida/rpf.py` | finds and runs the helper, parses `.oiv` packages, turns mods.json `install.rpf` into archive work |
| `leonida/installer.py` | method `rpf`: copies, archive work, logging, backups, rollback |
| `tests/test_rpf.py` + `tests/fake_rpf_helper.py` | the whole cycle in CI, with a fake helper (archives are zips) |
| `build/e2e_rpf.py` | opt-in real run: the real helper, the real downloads, real game files (read only) in a temp fake game |

The helper is found in `$LEONIDA_RPF_HELPER`, then `<state>\tools\LeonidaRpf\LeonidaRpf.exe`, then
`build\codewalker\bin\`. If it's missing, `leonida install --dry-run` lists the problem, and installing those mods
stops with "run `python build/build_rpf_helper.py`".

## How it works

- **Keys:** CodeWalker derives them itself. `GTA5Keys.LoadFromPath(gameDir, gen9: true)` reads
  `GTA5_Enhanced.exe`, finds the AES key by hash, and unlocks the NG tables shipped inside CodeWalker.Core. Nothing is
  stored, and Leonida never handles keys. All 176 archives of the owner's Enhanced build are NG-encrypted.
- **Helper protocol:** `LeonidaRpf.exe <gameDir> <ops.json>`. It prints one JSON object (`ok`, `results`, or
  `error` with the failing op index). Ops:
  - `keys`, `create`, `list`, `extract`;
  - `put`, `delete` (a file, nested archive or folder);
  - `xml`: `add` / `replace` / `remove` by XPath 1.0, with .NET `XmlDocument`, comments and formatting kept;
  - `ytd`: replace one texture of a texture dictionary with a `.dds`, the way CodeWalker's texture editor does;
  - `hash`: entry hashes of some entries, or of the whole archive (`all`), plus the first folder / nested archive
    on a missing entry's path;
  - `export`: an entry backup that `put` imports back as the same entry (resources keep their RSC7 header and flags).

  A path segment ending in `.rpf` steps into a nested archive; missing folders and nested archives are created.
  Deriving the keys takes about 15 s per helper run.
- **Entry hashes:** SHA-256 over the entry's kind (resource / binary), a resource's system and graphics flags, and
  its unpacked data. The same entry gives the same hash wherever CodeWalker puts it inside the archive. The archive's
  own bytes change with the layout, so whole-archive hashes can't tell whether an archive is back as it was.
- **Encryption:** before writing, the archive and its parents are switched to OPEN, exactly like CodeWalker RPF
  Explorer ("converting for OpenRPF"). The game then needs OpenRPF (Core) to load the `mods\` copies.
- **Logging and rollback (installer):** for every game archive a step touches (`update\update.rpf`, ...):
  - no `mods\` copy yet: log `ADD mods/<path>` first, then copy the game's archive there. If the game has no such
    archive and an `.oiv` says `createIfNotExist`, an empty one is made instead, with a warning (the package was made
    for a newer game build). Rollback deletes it.
  - a `mods\` copy exists (an earlier step made it, or the user did): **entry-level backup**. One helper run hashes
    the entries the step will write and exports the ones that exist into
    `<state>\backups\step-N\rpf-entries\mods\<path>\` (about the size of those entries: KB to MB, never the 3 GB
    archive). Each archive is then logged as `rpf-edit`, with `entries.json`: every entry with its hash before, its
    backup file (or none: a new entry), the folder / nested archive the step creates on its path, and its hash after.
  - then one helper run makes all the edits and hashes the touched entries again. If the helper fails part-way, the
    step is `failed`, and rollback still restores everything.
  - **rollback of an `rpf-edit`:** put every backed-up entry back, delete the entries the step added (and the
    folders / nested archives it created), then hash every entry and compare it with its hash from before the step.
    It warns about an entry that was changed after the install (the version from before the step still comes back),
    and about any entry that doesn't come back as it was. The earlier steps that own that archive copy get its new
    file hash, so they still remove it cleanly.
  - **dependencies** (mod updates, switching packs): an `rpf-edit` owns only its entries and the containers it
    created. Two mods that edit different entries of `mods\update\update.rpf` can be rolled back independently.
    The step that made the copy stays as long as a later step edits it.
  - A `mods\` copy that existed before Leonida comes back entry for entry. Its bytes can differ, because CodeWalker
    moves entries inside an archive.
  - `.oiv` loose files go through the normal copy path (`ADD`/`REPLACE` + backup). Its `<delete>`s of loose files are
    backed up and logged as `external-remove`, so rollback brings them back.
  - **Disk space** is checked first, per drive (game folder and Leonida's state). The check counts:
    - the `mods\` copy of each archive the step is the first to touch;
    - the new data CodeWalker writes inside archives (it appends entries);
    - the entry backups;
    - the files the step copies.

    The error says what takes how much, and that nothing was changed. The archives are big: `update.rpf` is 2.9 GB,
    `x64e.rpf` 1.9 GB, DLC packs 0.5–2.3 GB.
- **`.oiv` packages:** `assembly.xml` `<content>` is applied the way OpenIV's "mods folder" install does it:
  - `<archive path createIfNotExist>` (nested too) with `<add source>`, `<delete>` and `<xml path>` (`add` / `replace`
    / `remove` with XPath, append First/Last);
  - loose `<add>`/`<delete>` go to the game folder, or to `mods\` for game data (`update\…`, `x64\…`, `*.rpf`).
  - `<text>` and `<defragmentation>` aren't supported yet; a package using them stops with a clear error.
  - Content files are unpacked flat (`c/<n>.<ext>` plus an index), not at their own paths. Map packages nest 10+
    folders deep and would otherwise pass Windows' 260-character path limit under a temp folder.
- **mods.json ops** (`install.rpf`):
  - `put`, `dlclist`, `xml`, `delete`;
  - `putdir`: every file of a download folder, at the same paths inside the archive (VisualV's "manual installation"
    folder);
  - `texture` + `ytd`: replace one texture in a `.ytd` (iOS 26 icons);
  - `oiv`: a file name pattern, or `folder/name` to pick by path (`Enhanced/MP Map Files.oiv`), with `skip`: archive
    entries to leave out of the package.

## The mods (mods.json, every `rpf` entry)

The 17 entries in mods.json use these specs. Only what a person has to do in the game stays as `steps`, shown as
"by hand afterwards"; download notes are in each mod's notes. Every NVE override keeps `"method": "guided"`: NVE's
loader doesn't read `mods\`, so its onigiri instructions are unchanged.

| Mod | Install |
|---|---|
| Map Fixes | `spMapFixes_Gen9` → `mods\update\x64\dlcpacks`, its dlclist line, `MP Map Fixes.oiv` |
| Bugstar Fixes | `spFixes_Gen9` → dlcpacks, its dlclist line, `Enhanced Update RPF Content.oiv` |
| Map Updates | both `Enhanced` packs → dlcpacks, two dlclist lines, `Enhanced/MP Map Files.oiv`, `MapUpdates.3.cs`/`.ini` → scripts |
| Drive V (7.4 on 1.0.1013.20) | `Install.oiv` (never `Uninstall.oiv`) |
| NextGen Euphoria / Combat Camera | `put` physicstasks.ymt → `x64\data\tune`, cameras.ymt → `x64\data\metadata` |
| Immersive Combat | `I?[0-9].[0-9]*[0-9].oiv` (the name has a Cyrillic С; never the Uninstaller or the Optional files) |
| GTA VI-Inspired HUD | `GTA-VI-Inspired-HUD-*[0-9]-Enhanced.oiv`; with Resource Extensions: `skip` `common\data\gameconfig.xml` |
| HUD loading screens | `*LoadingScreens-Enhanced.oiv` |
| Benny's | scripts → scripts, `bennys_sp.oiv` |
| Burger Shot, Up-n-Atom, Elgin 24/7, Vinewood 24/7, GTA V Remastered | the `SP` (or `GTA V Enhanced`) pack folder → dlcpacks + its dlclist line; `FiveM` folders are never picked |
| VisualV | `putdir` `manual installation/mods/update.rpf` |
| iOS 26 icons | `texture` icons_spritesheet_ifruit.dds → `scaleform_generic.rpf\cellphone_ifruit.ytd` |

**gameconfig.xml:** the HUD's Enhanced guide, on Resource Extensions: keep the game's own gameconfig.xml, because
"ResourceExtensions raises the limits instead". Resource Extensions doesn't support a modded gameconfig.xml. So with
Resource Extensions selected (every Core pack), the HUD's five pool edits are left out. NVE leaves NVE's own
gameconfig alone, as the guide says.

**Disk, Showcase pack on 1.0.1013.20** (`python build/e2e_rpf.py --space`, real sizes):
- about **23.0 GB of `mods\` copies**: `update.rpf` 2.9 GB; Map Fixes' 13 DLC packs about 17 GB; Bugstar's
  `x64e.rpf` 1.9 GB and `update2.rpf` 0.6 GB;
- about 1.2 GB of pack folders and loose files;
- about 0.1 GB of entry backups.

That's about **24.4 GB** in all. With whole-archive backups, every later step on `update.rpf` (all 17 mods edit it)
would have added another copy: about 52 GB more.

## Licence and distribution

CodeWalker has no licence file. Its `Readme_Src.txt` says "This source code is released for educational purposes
only", and the gta5-mods page asks for credit and a link. So:
- Leonida never ships or re-hosts CodeWalker binaries. `build_rpf_helper.py` builds a local copy on the user's PC
  from the author's published source (github.com/dexyfex/CodeWalker). Gen9 support exists only in the source: the
  public build v30_dev46 (gta5-mods.com) is from January 2024, before GTA V Enhanced.
- Before this goes to other users: ask dexyfex for permission (Discord or Patreon), and credit CodeWalker in
  `docs/CREDITS.md` and the app.
- Building needs a .NET 8 SDK. The script installs a portable one from Microsoft if none is present, about 220 MB,
  with no system install. Running the helper needs only .NET Framework 4.8.

## Verified (2026-11-25, owner's PC, game 1.0.1013.20)

- **Prototype on a temp copy** of the real NG `patch2023_01_g9ec\dlc.rpf`:
  - list (nested archives too);
  - replace `content.xml` and read it back byte-identical;
  - add a new file (folders created), XPath XML edit, delete;
  - the archive becomes OPEN, and the original copy stays untouched.
- **`build/e2e_rpf.py`, real downloads and real game files, fake game in temp:**
  - NextGen Euphoria (15 s), Combat Camera (16 s) and the HUD `.oiv` (95 s, 1477 logged changes) installed.
  - `dlclist.xml` keeps the game's 100 packs and adds the HUD's three once each. `gameconfig.xml` pools are raised,
    and the mods' files are byte-identical inside `mods\update\update.rpf`.
  - Rollback of every step leaves the folder byte-identical to the baseline. The real game is untouched.
  - The full six-mod run (Map Fixes on the real 0.5 GB NG `mpApartment\dlc.rpf`, Bugstar, Drive V): see the e2e
    output in the session report.
- **Entry-level backups, all 17 mods from mods.json** (`build/e2e_rpf.py`, game 1.0.1013.20, the Showcase
  selection; 143 checks passed in 36 min). The fake game had 15 compact archives with 291 real entries / real nested
  archives read from the game, plus the whole real NG `mpApartment\dlc.rpf`.
  - Every file a step puts in matches the package by entry hash: Map Fixes' 392 + 182, Bugstar's 98, Drive V's 93,
    Immersive Combat's 86, VisualV's 41, ...
  - The iOS 26 texture is replaced inside `cellphone_ifruit.ytd`.
  - `dlclist.xml` has the 13 packs' lines once each.
  - `gameconfig.xml` stays the game's own (Resource Extensions selected).
  - `mods\update\update.rpf` is OPEN.
  - Entry backups per step: 0.0–20.5 MB (VisualV the largest). The old whole-archive backup was 2.9 GB per step.
  - After each of the 17 rollbacks (newest first), every entry of every edited `mods\` archive had the hash it had
    after the step before, and the other files were as before. Uninstall left the folder equal to the baseline
    (snapshot and full SHA-256 walk). The real game's 18 archives read were untouched.
  - Resource round trip on the real game's own entries (`physicstasks.ymt`, `cameras.ymt`, `gameconfig.xml`, the RSC7
    `cellphone_ifruit.ytd` in a nested archive): export → put gives the same entry hash.
- **Not checked in the game yet:** whether the game loads everything (needs the owner's real install and a play
  test), and how the Gen9 texture CodeWalker writes for the iOS 26 icons looks on the phone.
