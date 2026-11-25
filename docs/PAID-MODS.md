# Paid mods: buy from the author, then play

The owner's rule (2026-11-25): "people should have options to play with paid mods, just pay for them". Leonida gives
paid mods a clean path:

1. **Buy** on the author's own page.
2. **Save** your file in Downloads.
3. **Check:** Leonida checks the file in its test place.
4. **Install**, logged and undoable like every mod.

What Leonida never does:
- open, pay for or sign in to a Patreon tier or shop for you;
- use a re-upload or a "free" copy;
- type a password or keep one.

## Data (manifest session)

Each paid mod in `mods.json` (`tier: "paid"`) has these fields.

| Field | What it is |
| --- | --- |
| `buy` | `{url, price, tier, gets, checked}`: the author's own purchase page, the price as that page shows it, the tier that gives the GTA V Enhanced file, what the buyer downloads, and the date it was checked |
| `archive` + `requireMembers` / `rejectMembers` | name and content checks for the buyer's file; a wrong or repacked package is refused with the reason |
| `install` | how Leonida installs it once the file is there |
| `settings`, `features`, `sharesFeature`, `slot`, `gameBuilds` | the same as every mod (docs/CONFLICTS.md, docs/SETTINGS.md) |
| `freeRoute` | `none` (no stand-in mod, the owner's rule), or the author's own free edition (LWE's public release) |

## Engine (done: `leonida/paid.py`)

- **`paid_list(session)`:** one row per paid mod:
  - name, author, `buy_url`, price, tier, gets;
  - status: `not bought` / `downloaded` / `wrong file` / `installed`;
  - the file's name and the refusal reason;
  - the chosen pack's add-on that turns it on (`addons`), and the pack mods it takes the place of (`replaces`);
  - game builds.
- **`paid.findings(session)`,** part of `Session.findings()` (so `leonida check` and the launcher's Check page show
  them):
  - INFO `paid-downloaded`: "Your NaturalVision Enhanced download (…) is in Downloads: tick 'NaturalVision Enhanced
    (paid)', then install. Leonida checks it in its test place first. It takes the place of …";
  - WARNING `paid-wrong-file`: "… isn't the author's package (reason). Download it again from <buy page>."
- **CLI:**
  - `leonida paid list` shows the same rows.
  - A renamed file: `leonida assign <file> <mod id>`.
  - Then the usual `leonida check` → `leonida scan` (test place) → `leonida install`.

## Launcher: the "Paid mods" page (for the downloader session)

**Where:** a page under LIBRARY, or a tab on the pack page, listing `paid.paid_list(session)`. Recompute it when the
Downloads folder changes (`Session.matches` is already cached on the folder's state).

**One card per paid mod:**

| Part | Content |
| --- | --- |
| Picture | the mod's `image` |
| Title line | name, author |
| Badge | from `status`: **Not bought** (grey), **Downloaded: ready** (cyan), **Wrong file** (red, with `reason`), **Installed** (green) |
| Text | the first sentence of `notes` (what you'll see), then `gets` (what you download) and the price as `price` + `tier` ("from $10 / month, Gold tier"), with "checked <date>" in small grey text |
| "What changes in your pack" | the add-on name (`addons[0]`) and "takes the place of: …" (`replaces`) |
| Game builds | `builds`. If the detected build is outside them, show the mod's `unsupported` reason and disable the install button |

**Buttons by status:**

| Status | Buttons |
| --- | --- |
| Not bought | **Buy on the author's page** opens `buy_url` in the user's **own default browser** (`QDesktopServices.openUrl`), never the in-app browser, so Leonida never sees the purchase or the account. Small text under it: "Leonida never buys, signs in or uses re-uploads." Next to it, **I've downloaded it** (see below) |
| Downloaded | **Check and install** ticks the pack's add-on (`session.choose_pack(pid, addons + [addon id], variant)`), runs the test-place scan for this file (the same call as `leonida scan`), then the normal install steps with their dialogs |
| Wrong file | **Open Downloads** and **Buy page**; repeat the refusal reason |
| Installed | **Disable** / **Enable**, like other mods (Online-safe and undo work the same) |

**"I've downloaded it":**
1. Open a file picker in Downloads.
2. If the chosen file's name doesn't match, call `config.assignments[file.name] = mod_id` and save (what
   `leonida assign` does).
3. Refresh the card: it becomes *Downloaded* or *Wrong file*.

**Never:**
- an embedded Patreon / shop page;
- automatic clicks on Patreon;
- storing a Patreon session.

## The paid mods

The table (buy page, price, file, install, builds) is in `docs/OWNER-SOURCES.md` under "Paid mods: buy and play".
