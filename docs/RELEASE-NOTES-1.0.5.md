# Leonida V 1.0.5: release notes

**Leonida V turns GTA V Enhanced into a free GTA VI experience.** Story mode only; never GTA Online.

Already on 1.0.x? Open Leonida → **Manage → Check for updates** (or `leonida self-update`): it downloads 1.0.5,
checks it against `SHA256SUMS.txt`, swaps it in after the app closes and keeps your State and Downloads.

## Download

- **`Leonida-V-Setup-1.0.5.exe`** (recommended): per-user install, no administrator rights. Windows SmartScreen may
  warn because the exe isn't code-signed: *More info → Run anyway*.
- `LeonidaV-1.0.5-win64.zip`: the same program, portable.
- `leonida-v-1.0.5.zip` + `Start-Leonida.bat`: the portable kit with its own Python.

## New

- **Pure GTA: the game with no mods, in one click.** The **Pure GTA** button next to **Play** (or `leonida pure`)
  moves every mod out of the game folder (nothing is deleted), starts GTA V, and brings the mods back by itself when
  you close the game, or the next time Leonida opens. **Play** always brings them back first. Handy for a quick
  vanilla comparison or a run without mods. `leonida pure --back` and `leonida pure --status` do it by hand.

## Known limits

- Story mode only. Before GTA Online, turn **Online-safe** on (*Manage*).
- GTA needs Rockstar's Social Club to start, with or without mods; the Play test warns when it's missing files.
- Tested on game build 1.0.1013.20. Mods made for a newer build say so on their card.
- The exe isn't code-signed yet, so Windows asks once (*More info → Run anyway*).

Full list of changes: `docs/CHANGELOG.md`.
