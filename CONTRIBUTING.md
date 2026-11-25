# Contributing to Leonida V

Thanks for wanting to help! Leonida V is a launcher that installs a curated set of free GTA V mods for a GTA VI feel,
one safe step at a time. You can help without writing code: report bugs and crashes, suggest mods, test packs on your
PC, improve the docs. And if you do want to code, this page gets you from a fresh clone to a pull request.

- **Questions, ideas, "is this normal?"**: [Discussions](https://github.com/JacobJandon/leonida-v/discussions).
- **Bugs, crashes, mod requests, features**: [open an issue](https://github.com/JacobJandon/leonida-v/issues/new/choose)
  (the forms ask for what we need).
- Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems: [SECURITY.md](SECURITY.md), not a
  public issue.

## The rules (please read these first)

These come from the project's own rules, and a pull request that breaks one can't be merged:

1. **Never add or re-host mod files** in this repo: no mod archives, DLLs, ASIs, .oiv packages, mod preview images.
   At runtime Leonida fetches a mod only from **its author's own source** into the user's Downloads folder: a GitHub
   release, a direct link the author publishes, or the author's page opened inside the app's browser.
2. **Story mode only.** Nothing that targets GTA Online or gets around BattlEye/anti-cheat.
3. **Paid content stays manual.** Leonida links to a paid mod's own buy page (Patreon tiers, shops) and never
   downloads it, unlocks it or uses a leaked copy. Discord-only files stay manual too.
4. **The manifest is the single source of truth** (`leonida/manifest/*.json`) for mods, install order, packs,
   settings and hotkeys. Change mods there, not in code.
5. **Every file the installer writes goes through `Installer`** (`leonida/installer.py`), so it is logged and can
   be rolled back.
6. **Keep the invariant tested:** install N steps, uninstall, and the game folder equals the baseline snapshot.

## Set up (Windows)

You need [Git](https://git-scm.com/download/win) and [Python 3.10+](https://www.python.org/downloads/windows/)
(3.13 recommended; tick *Add python.exe to PATH*). You **don't** need GTA V for the tests.

```powershell
git clone https://github.com/<you>/leonida-v.git
cd leonida-v
powershell -ExecutionPolicy Bypass -File build\dev_setup.ps1
```

`build/dev_setup.ps1` makes `.venv`, installs Leonida with its dev and GUI extras (`pip install -e ".[dev,gui]"`),
then runs `ruff` and the tests. Options: `-NoTests` (install only), `-Recreate` (start a fresh `.venv`).
Then activate the venv in each new terminal:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS work for everything except the Windows-only parts (registry, shortcuts, the exe build):
`python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,gui]"`.

## Everyday commands

| What | Command |
|---|---|
| All tests | `pytest -q` (set `$env:QT_QPA_PLATFORM="offscreen"` so the GUI tests don't open windows) |
| One file / one test | `pytest tests/test_installer.py -q`, `pytest -k rollback -q` |
| Lint | `ruff check .` (`ruff check . --fix` for the easy ones) |
| The launcher (GUI) | `leonida-gui` |
| The command line | `leonida --help`, e.g. `leonida detect`, `leonida check`, `leonida status` |
| A debug report | `leonida report` (the zip people attach to bug reports) |

The tests use fake game folders and archives (see `tests/conftest.py`). They never touch your real game, registry,
Start menu, desktop or `%LOCALAPPDATA%`: when you add a test that would, use the `LEONIDA_REG_ROOT`,
`LEONIDA_STARTMENU_DIR`, `LEONIDA_DESKTOP_DIR` and state-folder overrides the existing tests use. CI runs the same
tests on Windows and Ubuntu with Python 3.11 and 3.13, and checks coverage (90% of `leonida/` on Windows).

## How the code is laid out

```
leonida/
  manifest/        mods.json, modpacks.json, profiles.json, hotkeys.json, gamesettings.json (+ *-legacy.json)
                   and the loader that validates them (__init__.py: the full schema is in its docstring)
  session.py       shared app state for the CLI and the GUI: config, manifest, install log, matches, checks
  detect.py        find the game and its edition/build, GPU, prerequisites, 7-Zip
  downloader.py    fetch a mod from its author's own source (GitHub release / direct link), stdlib only
  matcher.py       which downloaded file is which mod; SHA-256; the lockfile
  quarantine.py    every download is checked (Defender, contents, a trial install) before it can be installed
  installer.py     the install methods (copy / generic / run / guided / rpf), logging, rollback, uninstall
  rpf.py           archive mods: edits copies of game archives in mods\ through the CodeWalker-based helper
  snapshot.py      the game-folder snapshot and diff; log.py the per-step install log
  checks.py        pre-install checks (build, slots, conflicts, hotkeys, prerequisites); features.py clashes
  settings.py      locked mod settings; gamesettings.py GTA's own settings.xml per pack
  onlinesafe.py    move every mod out of the game folder before going online, and back
  playtest.py      start the game, wait for story mode, read the mods' logs; verify.py, memwatch.py, minidump.py
  diagnostics.py   `leonida report`: the debug zip (private details removed)
  updater.py       self-update; winsetup.py / setupui.py the per-user setup exe
  menu/, menubridge.py   LeonidaMenu, the in-game menu (a Script Hook V .NET script) and its bridge
  probe/           the in-game probe used by `leonida playtest --deep`
  cli.py           the `leonida` command line
  gui/             the PySide6 launcher: app.py (window and wizard), launcher.py, newpages.py, extras.py
                   (About & help, Manage), browser.py (the in-app browser), widgets.py, theme.py
tests/             pytest; fake games and archives, no network (LEONIDA_NO_NET=1 in CI)
build/             the Windows exe and setup, release checks, opt-in end-to-end tests (build/README.md)
docs/              GUIDE.md (users), PLAN.md (roadmap), SETTINGS.md, CONFLICTS.md, IN-GAME-CHECKS.md, CREDITS.md
```

## Adding or updating a mod

Mods are data, not code: one entry in `leonida/manifest/mods.json` (and `mods-legacy.json` for GTA V Legacy), plus a
place in a pack or add-on in `modpacks.json`. **[docs/ADDING-MODS.md](docs/ADDING-MODS.md)** walks through a real
entry step by step, with the checks to run. Updating a mod to a newer version is usually just its `version`,
`archive` patterns and maybe `files`.

## Testing on a real game (optional)

Most changes only need `pytest`. When you change how a mod installs or touch the in-game parts:

- `leonida playtest` starts the game (story mode), waits for it to load and reads the mods' logs;
  `leonida playtest --deep` also runs the in-game probe (are the DLC packs and scripts really loaded?).
- `python build/check_probe.py` and `python build/check_menu.py` compile the probe and LeonidaMenu with the C# 5
  rules Script Hook V .NET uses, against your game's `ScriptHookVDotNet3.dll` (read only).
  `tests/test_probe.py` and `tests/test_menu.py` do the same against a stub, so CI catches it too.
- `python build/e2e_real_install.py` and `python build/e2e_rpf.py` install real downloaded archives into a **fake**
  game folder in a temp directory, check every file, then uninstall and compare with the baseline. They never write
  to the real game.
- `python build/e2e_setup.py` and `python build/e2e_update.py` check the setup exe and the self-updater against real
  built files, in temp folders only.

Details for each are in [build/README.md](build/README.md). Please never test with GTA Online.

## Building the Windows app

```powershell
pip install -e ".[gui,build]"
python build/build_exe.py --selftest     # dist/LeonidaV/LeonidaV.exe, then a self-check of the frozen build
python build/build_exe.py --release      # + the setup exe, the zips and SHA256SUMS.txt
python build/release_dryrun.py           # the whole release job locally
```

## Releases (maintainers)

The version lives in `leonida/__init__.py`; the notes in `docs/RELEASE-NOTES-<x.y.z>.md` and `docs/CHANGELOG.md`.
Pushing a `v<version>` tag runs the `ci` workflow: tests, then the Windows build, the setup smoke test,
`check_release.py`, and the GitHub release. `rc`/`a`/`b` versions are published as pre-releases. Step by step:
[build/README.md, *Publishing a release*](build/README.md#publishing-a-release). Contributors never need to tag.

## Making a pull request

1. Fork the repo and make a branch: `git switch -c fix-hotkey-clash`.
2. Make the change with a test. Keep pull requests small and about one thing.
3. `ruff check .` and `pytest -q` pass.
4. Add a line to `docs/CHANGELOG.md` under *Unreleased* if users would notice the change.
5. Open the pull request; the template has a short checklist. CI runs on your pull request automatically (with a
   read-only token and no secrets, so it's safe for forks). A first-time contributor's run may wait for a
   maintainer to approve it.

## Good first contributions

Look for issues labelled [`good first issue`](https://github.com/JacobJandon/leonida-v/labels/good%20first%20issue)
and [`help wanted`](https://github.com/JacobJandon/leonida-v/labels/help%20wanted). Some ideas that are always
welcome:

- **Docs**: a clearer step in [docs/GUIDE.md](docs/GUIDE.md), a screenshot, a typo.
- **In-game checks**: play a mod and confirm (or correct) its line in [docs/IN-GAME-CHECKS.md](docs/IN-GAME-CHECKS.md).
- **Mod updates**: a mod's author released a new version; update its `version` / `archive` / `files` and test it.
- **A new mod** that fits a pack (see the rules above and [docs/ADDING-MODS.md](docs/ADDING-MODS.md)).
- **Tests** for a module with low coverage (`pytest --cov=leonida --cov-report=term-missing`).
- **Crash reports**: a crash with its `leonida report` zip helps more than you'd think.
