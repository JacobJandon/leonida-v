## What this changes

<!-- One or two sentences. Link the issue it fixes: "Fixes #123". -->

## How I tested it

<!-- Which tests you added or ran; for a mod change, whether you installed it (and played) on a real game. -->

## Checklist

- [ ] `pytest -q` passes (`QT_QPA_PLATFORM=offscreen` on a machine without a screen).
- [ ] `ruff check .` is clean.
- [ ] New behaviour has a test; the install -> uninstall == baseline snapshot test still passes.
- [ ] Every file the installer writes goes through `Installer` (logged, can be rolled back).

### Mods and the manifest (skip if you didn't touch `leonida/manifest/`)

- [ ] Mod changes are in the manifest (`leonida/manifest/*.json`), not in code. See `docs/ADDING-MODS.md`.
- [ ] `page` / `download` point at the **author's own** page or release: no mirrors, no re-uploads.
- [ ] **No mod files, archives or preview images are added to this repo.**
- [ ] The mod is free and story mode only (nothing for GTA Online or that gets around BattlEye/anti-cheat).
- [ ] Credits added to `docs/CREDITS.md`, and a line in `docs/CHANGELOG.md`.
