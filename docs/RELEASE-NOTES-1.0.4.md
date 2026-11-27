# Leonida V 1.0.4: release notes

**Leonida V turns GTA V Enhanced into a free GTA VI experience.** Story mode only; never GTA Online.

Already on 1.0.x? Open Leonida → **Manage → Check for updates** (or `leonida self-update`): it downloads 1.0.4,
checks it against `SHA256SUMS.txt`, swaps it in after the app closes and keeps your State and Downloads.

## Download

- **`Leonida-V-Setup-1.0.4.exe`** (recommended): per-user install, no administrator rights. Windows SmartScreen may
  warn because the exe isn't code-signed: *More info → Run anyway*.
- `LeonidaV-1.0.4-win64.zip`: the same program, portable.
- `leonida-v-1.0.4.zip` + `Start-Leonida.bat`: the portable kit with its own Python.

## Fixed

- **No more false "DLC pack NOT loaded"** for the 24/7 shops in the Play test before Leonida's archive reader was set
  up: Leonida now takes each pack's name from its mod list instead of guessing it from the folder name.

## New

- **Interiors checked in game**: the deep Play test visits the Burger Shot, Up-n-Atom and 24/7 interiors you have
  installed, checks the game loaded each one, and brings you back where you were. (Tested offline and compiled
  against Script Hook V .NET; its first run on a real game is still to come, so tell us if it says an interior
  wasn't checked.)
- **Social Club check**: GTA needs Rockstar's Social Club to start. If it's missing files (for example half-way
  through one of Rockstar's own updates), the Play test now says so and how to fix it, instead of only waiting.

## Known limits

- Story mode only. Before GTA Online, turn **Online-safe** on (*Manage*).
- Tested on game build 1.0.1013.20. Mods made for a newer build say so on their card.
- The exe isn't code-signed yet, so Windows asks once (*More info → Run anyway*).

Full list of changes: `docs/CHANGELOG.md`.
