# Leonida V

**A guided installer kit that turns GTA V Enhanced into a GTA VI-style experience.**
Next-gen lighting, a GTA VI HUD and radar, GTA VI combat camera, heavier physics and driving, denser traffic — installed in the right order, checked for conflicts, and fully undoable.

> **Story mode only.** Mods in GTA Online can get your account banned. Use `leonida online-safe on` (or the *Manage* page) before going online.

Leonida V **does not include or re-host any mod files.** It opens each author's own download page, recognises your downloads, installs them in a tested order, and logs every file it touches so it can roll anything back.

## What you get

| Layer | Mod (core profile) |
|---|---|
| Framework | Script Hook V · Script Hook V .NET Enhanced · DirectStorageFix · OpenRPF · Resource Extensions [Enhanced] |
| Graphics | NaturalVision Enhanced (Razed) |
| Fixes | Bugstar Fixes |
| Traffic | All MP Vehicles in SP |
| Driving | Drive V for NVE |
| Physics | NextGen Euphoria |
| Camera | GTA VI Combat Camera [Enhanced] |
| HUD | GTA VI Inspired Features, HUD & Radar System (or fbicat / geckomacabre alternatives) |
| Tools | Menyoo 2.0 · Straight To Story Mode |

Profiles: **Core** (default) · **Core + Safe Extras** · **Max (RTX 50)** (adds DLSS5-Swapper) · **Vice City Photo** (adds the fan-made Project Vice map).
The full list with versions, links and install methods lives in [`leonida/manifest/mods.json`](leonida/manifest/mods.json).

## Install

Requires Windows, GTA V Enhanced, and Python 3.10+ (a standalone `.exe` is planned for 1.0).

**Easiest (portable folder):** put `Start-Leonida.bat`, `Leonida-CLI.bat` and `leonida-v-<version>.zip` in one folder (for example `D:\Leonida`) and double-click `Start-Leonida.bat`.
It unpacks the project, creates a private Python environment, installs everything on first run and opens the wizard.
Mod downloads go to `<folder>\Downloads`, logs and backups to `<folder>\State`. `Leonida-CLI.bat` opens the command line with the same folders.

**Or with pip:**

```powershell
pip install "leonida-v[gui] @ git+https://github.com/JacobJandon/leonida-v"
leonida-gui          # the wizard
# or the command line:
leonida detect       # find the game
leonida get --watch  # open every download page, track downloads in Downloads\LeonidaV
leonida check        # version, leftovers, HUD/camera clashes, hotkeys, prerequisites
leonida install      # one mod at a time, with a test pause after each
```

## Safety model

* **Baseline snapshot** of the game folder before the first step.
* **Install log** (`%LOCALAPPDATA%\LeonidaV\install-log.json`): every file added or replaced, with its hash and a backup of anything overwritten.
* **Four install methods**: `copy` (only the named files), `generic` (shows the proposed files and asks first), `run` (the mod's own installer, changes recorded), `guided` (step-by-step instructions, changes recorded).
* **Rollback** any step (`leonida rollback`), or **uninstall** everything (`leonida uninstall`) and compare with the snapshot.
* **Online-safe switch** moves every mod file into `_LeonidaV_offline` and back.
* **Checks**: game build vs the tested build, old heap/packfile adjusters or `gameconfig.xml` next to Resource Extensions, two HUDs or two `cameras.ymt` mods, hotkey clashes (F8 is shared by the HUD, Menyoo and DLSS5-Swapper), missing .NET 4.8 / VC++ runtimes, RTX 50 requirement.

Known limit: files larger than 64 MB changed by a mod's *own* installer (for example inside `mods\update\update.rpf`) cannot be backed up cheaply; rollback warns and you restore them with *Verify game files*.

## Commands

```
leonida detect [--set PATH]           find / set the game folder
leonida profiles [--use PROFILE]      list or choose a profile
leonida swap hud hud-fbicat           pick an alternative for a slot
leonida get [--watch] [--no-open]     open pages, track downloads, write the lockfile
leonida assign FILE MOD               tell Leonida what an unrecognised file is
leonida check                         run every check
leonida install [--dry-run] [--only MOD ...] [--yes] [--no-pause]
leonida status                        settings, steps, mods on/off
leonida rollback [STEP]               undo one step (default: the last)
leonida uninstall                     undo everything
leonida online-safe on|off|status     move mods out / back
leonida keys [set MOD ACTION KEY]     hotkeys and clashes
leonida doctor                        GPU, prerequisites, 7-Zip
```

## Development

```bash
pip install -e ".[dev,gui]"
pytest            # 49 tests, no game needed (fake game folders and archives)
ruff check .
```

Project plan, architecture and roadmap: see `docs/`.

## Credits and licence

The kit's code is MIT-licensed (see `LICENSE`). Every mod belongs to its author and keeps its own licence. See [`docs/CREDITS.md`](docs/CREDITS.md). Not affiliated with Rockstar Games or Take-Two Interactive.
