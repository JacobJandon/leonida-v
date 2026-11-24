# Leonida V — notes for Claude

Guided installer kit that turns GTA V Enhanced into a GTA VI-style setup. Python 3.10+, stdlib-only engine,
optional PySide6 GUI. Owner: JacobJandon.

**Start every new session by reading `docs/HANDOFF.md`** (status, the owner's PC layout, open items in priority order).
Keep it updated when you finish an item.

## Rules
- Never add or re-host mod files (or preview images) in this repo. At runtime the kit may fetch a mod only from the
  author's own source into the user's Downloads: a GitHub release, a direct link the author publishes
  (`download` in mods.json), or the author's page opened inside the app's browser.
- In the app's browser, Leonida may follow a site's **own** Download buttons for the user, as the user would
  (owner's decision, 2026-11-24): gta5-mods' button / version list and its countdown, Nexus's "Slow download" once
  the user has signed in themselves, dev-c.com / GitHub links. It always waits through the site's countdowns and
  timers, never skips or hides ads, never types or stores passwords, never uses private APIs or premium-only routes,
  and never touches paid content (Patreon tiers, shops) or Discord: those stay manual.
- Story mode only. Never add anything that targets GTA Online or bypasses BattlEye/anti-cheat.
- The manifest (`leonida/manifest/*.json`) is the single source of truth for mods, order, profiles and hotkeys.
  Change mods there, not in code.
- Every file the installer writes must go through `Installer` so it is logged and can be rolled back.
- Keep the invariant tested: install N steps -> uninstall -> game folder equals the baseline snapshot.

## Commands
- `pip install -e ".[dev,gui]"`
- `pytest -q` (set `QT_QPA_PLATFORM=offscreen` for the GUI tests on headless machines)
- `ruff check .`
- `python -m leonida --help`, `leonida-gui`
- Windows exe: `pip install -e ".[gui,build]"` then `python build/build_exe.py`

## Layout
- `leonida/manifest/` mods.json, profiles.json, hotkeys.json + loader
- `leonida/detect.py` game/store detection, exe version, GPU, prerequisites, 7-Zip
- `leonida/matcher.py` downloads -> mods, SHA-256, lockfile
- `leonida/installer.py` copy / generic / run / guided, rollback, uninstall
- `leonida/snapshot.py`, `log.py`, `checks.py`, `onlinesafe.py`, `session.py`
- `leonida/cli.py` CLI, `leonida/gui/app.py` wizard
- `docs/PLAN.md` roadmap + real-PC test checklist
