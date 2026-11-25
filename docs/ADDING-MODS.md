# Adding or updating a mod

Every mod Leonida V installs is one entry in the manifest: `leonida/manifest/mods.json` for GTA V Enhanced and
`mods-legacy.json` for GTA V Legacy. Packs and add-ons that offer the mod are in `modpacks.json`. There is no
per-mod code: the loader (`leonida/manifest/__init__.py`, whose docstring is the full schema) validates the
entry, and the installer, checks, GUI cards and in-game checks all read it.

## The rules

These are the project's rules (from `CLAUDE.md`). A mod that can't follow them can't be added:

- **Author sources only.** `page` is the author's own page: gta5-mods.com, Nexus, the author's GitHub or website.
  `download` (optional) is the author's own GitHub release or a direct link the author publishes. No mirrors, no
  re-uploads, no "found it on a forum".
- **Never re-host.** No mod files, archives or preview images go into this repo, a release or a modpack. `image` is
  a URL on the author's page, fetched at runtime. (`redistribution` stays off unless the author's licence or written
  permission allows re-uploads, with a proof URL.)
- **Story mode only.** Nothing for GTA Online, nothing that gets around BattlEye or other anti-cheat.
- **Free, or manual.** Paid mods (tier `paid`, Patreon, shops) only link to the author's buy page; the user buys and
  downloads their own copy, and Leonida checks and installs it. Leonida never uses leaked or cracked copies, or
  premium-only download routes. Discord-only files stay manual.
- **Manifest only.** Change mods in the JSON, not in Python. If the schema can't say what a mod needs, open an issue
  first: a new manifest key is a code change with its own tests.

## Worked example: Street Food Vendors Enhanced

This is the real entry for FastBurst's [Street Food Vendors Enhanced](https://www.gta5-mods.com/scripts/street-food-vendors-enhanced),
a Script Hook V .NET script: one DLL (plus optional files) that goes into `scripts\`.

### 1. Read the author's page

Write down what the page says: the latest version and which game edition it's for, the file names in the download,
where the author says to put them, and what it needs. Here: *"Drop StreetFoodVendors.dll into your scripts folder"*,
needs Script Hook V and Script Hook V .NET; LemonUI comes in the download.

Then download it yourself (from the author's page) and look inside the archive: the manifest's `files` must match
its real layout.

### 2. Write the entry

Add it to `"mods"` in `mods.json` (shortened here; the real one has longer notes):

```json
{
  "id": "streetfood",
  "order": 43,
  "tier": "optional",
  "layer": "Gameplay",
  "name": "Street Food Vendors Enhanced",
  "author": "FastBurst",
  "version": "1.2.1.0 Enhanced or newer",
  "source": "direct",
  "page": "https://www.gta5-mods.com/scripts/street-food-vendors-enhanced",
  "image": "https://img.gta5-mods.com/q75/images/street-food-vendors-enhanced/ac63e7-banner1.png",
  "archive": ["*Street*Food*Enhanced*.rar", "*Street*Food*Enhanced*.zip", "*Street*Food*Enhanced*.7z"],
  "install": {
    "method": "copy",
    "createDirs": ["scripts"],
    "files": [
      {"match": "StreetFoodVendors.dll", "to": "scripts"},
      {"match": "StreetFoodVendors.pdb", "to": "scripts", "optional": true},
      {"match": "StreetFoodVendors.ini", "to": "scripts", "optional": true},
      {"match": "LemonUI.SHVDN3.dll", "to": "scripts", "optional": true}
    ]
  },
  "notes": "Buy hotdogs, burgers and drinks from street stands to heal (press E). Its page: 'Drop StreetFoodVendors.dll into your scripts folder'...",
  "pick": {"versionMatch": "(?i)\\benhanced\\b"},
  "checks": [
    "On Del Perro Pier, stand at a hotdog / burger stand or the Cherry Popper kiosk and press E: a menu to buy food that heals you."
  ],
  "features": ["street-food"]
}
```

What each key does:

| Key | Meaning |
|---|---|
| `id` | Short, lowercase, unique. Used by packs, add-ons, conflicts and settings. Never change it once released. |
| `order` | Unique install order. Frameworks (Script Hook V, .NET) come first; a mod comes after what it needs. |
| `tier` | `core` (in every pack), `optional` (packs and add-ons pick it), `alternative` (swaps in for another mod in the same `slot`), `paid`. |
| `layer` | The group it shows under in the app: Framework, Graphics, World, HUD, Gameplay, ... (copy a neighbour's). |
| `version` | What the author's page offers, and "or newer" when later versions install the same way. |
| `source` | Where the file comes from: `direct` (the author's page, the user or Leonida clicks its Download button), `github-release`, `nexus-login`, `patreon`, `shop`, `discord`. |
| `page` | The author's own page (https). The app opens it in its own browser. |
| `download` | Optional. `{"type": "github", "repo": "owner/name", "asset": "glob*.zip"}` for an author's GitHub release, or `{"type": "direct", "url": "https://...", "file": "name.zip"}` for a direct link the author publishes. Omit it and the author's page opens instead. |
| `archive` | File-name patterns that recognise the download in the user's Downloads folder. Cover the extensions the author has used. |
| `install` | How it installs. `copy`: each `files` entry copies a file (or `"type": "dir"`) found anywhere in the archive to a game-relative folder. Others: `generic`, `run` (the author's own installer), `guided` (the user follows `steps`), `rpf` (archive edits in copies under `mods\`, see `leonida/rpf.py`). |
| `pick` | Which entry of the author's "All versions" list to download: `versionMatch` (a regex) or `versionLabel`. Here: the Enhanced build, not the Legacy one. |
| `checks` | What to do in the game to see it works. Shown in the app and in `docs/IN-GAME-CHECKS.md`. |
| `features` | What it changes in the game, from `VOCAB` in `leonida/features.py`. Two selected mods with the same feature are a clash unless one has a `sharesFeature` note saying how they coexist. Add a word to `VOCAB` if none fits. |

Optional keys you may need: `conflicts`, `slot` and `replaces` (one HUD, one camera, ...), `warnings`,
`minGameBuild` / `gameBuilds` (versions per game build), `requireMembers` / `rejectMembers` (tell the Enhanced file
from the Legacy one by what's inside), `settings` (config keys Leonida locks, see `docs/SETTINGS.md`),
`whenSelected` / `whenMissing` (install differently next to another mod). Each one is described in the loader's
docstring.

Hotkeys the mod uses go in `hotkeys.json`, so the key-clash check knows them.

### 3. Offer it in a pack

An optional mod is installed when a pack or an add-on includes it. Street food is an add-on in `modpacks.json`:

```json
{
  "id": "street-food",
  "name": "Street food vendors",
  "category": "world",
  "mods": ["streetfood"],
  "description": "Buy food from the street carts.",
  "picture": "https://img.gta5-mods.com/q75/images/street-food-vendors-enhanced/ac63e7-banner1.png"
}
```

A pack can also list it in `base` or `defaultAddons`; `profiles.json` keeps the older profile lists in step.

### 4. Credit the author

Add a row to `docs/CREDITS.md` (name, author, editions, tier, the licence the author states, the page) and a line
to `docs/CHANGELOG.md` under *Unreleased*.

### 5. Test it

```powershell
pytest tests/test_manifest.py tests/test_features.py -q   # the entry loads, ids and features are valid
leonida check                                             # with your game: build, slots, keys, prerequisites
pytest -q                                                 # everything (the GUI tests count mods per pack)
```

A new mod in a pack changes counts some GUI tests expect; update those numbers in the same pull request.

With the real file and a game:

- `python build/e2e_real_install.py` (or `build/e2e_rpf.py` for `rpf` mods) installs real downloads into a **fake**
  game folder, checks each file landed where `files` says, then uninstalls and compares with the baseline.
- Install it with Leonida, play, and do what `checks` says. `leonida verify` reads the mods' own logs after a game
  start. Say in the pull request what you tested and on which game build.

## Updating a mod

Usually: change `version`, check `archive` still matches the new file name, and check `files` against the new
archive. If the new version needs a newer game build, give the old version a `gameBuilds` entry so people on older
builds keep a working one. Run the tests above.

## Asking instead

Not sure how a mod should install? Open a [mod request](https://github.com/JacobJandon/leonida-v/issues/new?template=mod_request.yml)
with the author's page and what you found; someone can help write the entry.
