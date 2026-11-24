# CodeWalker in Leonida: editing GTA V Enhanced archives (plan item F6)

Some Core mods can only be installed by editing GTA's `.rpf` archives, or ship as OpenIV `.oiv` packages:
- Map Fixes and Bugstar Fixes;
- Drive V;
- NextGen Euphoria;
- GTA VI Combat Camera;
- GTA VI-Inspired HUD.

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
  `error` with the failing op index). Ops: `keys`, `create`, `list`, `extract`, `put`, `delete`, and `xml` (`add` /
  `replace` / `remove` by XPath 1.0, with .NET `XmlDocument`, comments and formatting kept). A path segment ending in
  `.rpf` steps into a nested archive; missing folders and nested archives are created. One batch per install step:
  deriving the keys takes about 15 s.
- **Encryption:** before writing, the archive and its parents are switched to OPEN, exactly like CodeWalker RPF
  Explorer ("converting for OpenRPF"). The game then needs OpenRPF (Core) to load the `mods\` copies.
- **Logging and rollback (installer):** for every game archive a step touches (`update\update.rpf`, ...):
  - no `mods\` copy yet: log `ADD mods/<path>` first, then copy the game's archive there. If the game has no such
    archive and an `.oiv` says `createIfNotExist`, an empty one is made instead, with a warning (the package was made
    for a newer game build). Rollback deletes it.
  - a `mods\` copy exists (an earlier step made it, or the user did): back it up whole, then log `REPLACE` with the
    backup. Rollback restores it byte for byte.
  - then one helper batch runs all the edits, and each archive's final SHA-256 is recorded. If the helper fails
    part-way, the step is `failed` and rollback still restores everything.
  - `.oiv` loose files go through the normal copy path (`ADD`/`REPLACE` + backup). Its `<delete>`s of loose files are
    backed up and logged as `external-remove`, so rollback brings them back.
  - Disk space is checked first. The archives are big: `update.rpf` is 3.1 GB, `x64e.rpf` 2.1 GB, DLC packs
    0.5–2.3 GB. A step that edits an existing `mods\` copy backs it up whole.
- **`.oiv` packages:** `assembly.xml` `<content>` is applied the way OpenIV's "mods folder" install does it:
  - `<archive path createIfNotExist>` (nested too) with `<add source>`, `<delete>` and `<xml path>` (`add` / `replace`
    / `remove` with XPath, append First/Last);
  - loose `<add>`/`<delete>` go to the game folder, or to `mods\` for game data (`update\…`, `x64\…`, `*.rpf`).
  - `<text>` and `<defragmentation>` aren't supported yet; a package using them stops with a clear error.

## Using it per mod (proposed mods.json `install` entries)

All six mods were checked in `build/e2e_rpf.py` with the real downloads. Each needs OpenRPF (Core) and the helper.

```jsonc
// Map Fixes (Enhanced package): the pack folder, its dlclist line, then MP Map Fixes.oiv
"install": {"method": "rpf",
  "files": [{"match": "spMapFixes_Gen9", "type": "dir", "to": "mods/update/x64/dlcpacks"}],
  "rpf": [{"archive": "update\\update.rpf", "dlclist": "dlcpacks:/spMapFixes_Gen9/"},
          {"oiv": "MP Map Fixes.oiv"}]}
// Bugstar Fixes (Enhanced package)
"install": {"method": "rpf",
  "files": [{"match": "spFixes_Gen9", "type": "dir", "to": "mods/update/x64/dlcpacks"}],
  "rpf": [{"archive": "update\\update.rpf", "dlclist": "dlcpacks:/spFixes_Gen9/"},
          {"oiv": "Enhanced Update RPF Content.oiv"}]}
// Drive V 7.5 (Install.oiv only; never Uninstall.oiv)
"install": {"method": "rpf", "rpf": [{"oiv": "Install.oiv"}]}
// NextGen Euphoria
"install": {"method": "rpf", "rpf": [
  {"archive": "update\\update.rpf", "put": "physicstasks.ymt", "to": "x64\\data\\tune\\physicstasks.ymt"}]}
// GTA VI Combat Camera [Enhanced]
"install": {"method": "rpf", "rpf": [
  {"archive": "update\\update.rpf", "put": "cameras.ymt", "to": "x64\\data\\metadata\\cameras.ymt"}]}
// GTA VI-Inspired HUD (the download is the .oiv itself)
"install": {"method": "rpf", "rpf": [{"oiv": "*.oiv"}]}
```

Things to keep in mind for these mods (from the real packages):
- **Map Fixes 21.8.2** edits 14 archives: `update.rpf` and 13 DLC packs (`mpApartment`, `mpBattle`, `mpHeist`, …).
  That's about **20 GB of copies in `mods\`**. The step checks free space first.
- **Bugstar Fixes 7.8.1** edits `update.rpf`, `update2.rpf`, `x64e.rpf` and `update\x64\dlcpacks\patch2026_01\dlc.rpf`.
  **Drive V 7.5** edits `mp2026_01\dlc.rpf`. Neither pack exists on game build 1.0.1013.20, so Leonida warns and
  makes an empty archive for those files, as OpenIV would. The game ignores them, so on that build those parts of the
  mods do nothing.
- **The HUD** raises five pools in `gameconfig.xml`. Its own step text already covers the clash with Resource
  Extensions.
- **Order matters:** each later step backs up the `mods\update\update.rpf` that earlier steps made. Rolling back a
  step restores exactly the archive from before that step.

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
