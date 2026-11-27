# Leonida V 1.0.3: release notes

**Leonida V turns GTA V Enhanced into a free GTA VI experience.** Story mode only; never GTA Online.

Already on 1.0.x? Open Leonida → **Manage → Check for updates** (or `leonida self-update`): it downloads 1.0.3,
checks it against `SHA256SUMS.txt`, swaps it in after the app closes and keeps your State and Downloads.

## Download

- **`Leonida-V-Setup-1.0.3.exe`** (recommended): per-user install, no administrator rights. Windows SmartScreen may
  warn because the exe isn't code-signed: *More info → Run anyway*.
- `LeonidaV-1.0.3-win64.zip`: the same program, portable.
- `leonida-v-1.0.3.zip` + `Start-Leonida.bat`: the portable kit with its own Python.

## Fixed

- **Burger Shot is back, without the loading crash.** On game build 1.0.1013.x the Burger Shot interior ships one
  empty stand-in for a Rockstar distance model, which crashed the loading screen when your save puts you in Vespucci
  or Del Perro. Leonida now leaves just that one file out of your own copy of the pack, so the game uses its own
  model and the interior is there as before. Nothing is re-uploaded; undoing the step puts the pack back as it came.
- **The launcher on small and large screens**: buttons no longer overlap on Manage at 1366×768, every setup step
  fits in the sidebar, progress bars only show while something downloads, long names are shortened with the full
  name on hover.

## New

- **Ready-made setups in the launcher**: *Browse → Setups* and the first-run setup show big cards with what you get,
  what your PC needs and which one is **best for this PC**. **Use this setup** downloads everything and installs it by
  itself. Export your setup to share it, import someone else's.
- **Stress play tests** (`leonida playtest --stress police` or `--stress drive`): a long police fight or a fast drive
  round the map, run by Leonida in story mode, so rare crashes can be caught with their evidence.
- **More automatic checks**: key bindings, script settings and interiors are now checked by Leonida itself; the
  in-game checklist marks what is *Automatic* and what only you can judge (looks, feel, sound).

## Known limits

- Story mode only. Before GTA Online, turn **Online-safe** on (*Manage*).
- Tested on game build 1.0.1013.20. Mods made for a newer build say so on their card.
- The exe isn't code-signed yet, so Windows asks once (*More info → Run anyway*).

Full list of changes: `docs/CHANGELOG.md`.
