# Leonida V 1.0.2: release notes

**Leonida V turns GTA V Enhanced into a free GTA VI experience.** Story mode only; never GTA Online.

Already on 1.0.0 or 1.0.1? Open Leonida → **Manage → Check for updates** (or `leonida self-update`): it downloads
1.0.2, checks it against `SHA256SUMS.txt`, swaps it in after the app closes and keeps your State and Downloads.
Then let Leonida update the in-game menu (its step on the Install page): the new menu does the in-game steps below.

## Download

- **`Leonida-V-Setup-1.0.2.exe`** (recommended): per-user install, no administrator rights. Windows SmartScreen may
  warn because the exe isn't code-signed: *More info → Run anyway*.
- `LeonidaV-1.0.2-win64.zip`: the same program, portable.
- `leonida-v-1.0.2.zip` + `Start-Leonida.bat`: the portable kit with its own Python.

## Fixed

- **Leonida remembers you.** The installed app could start on an empty folder and ask to set everything up again
  (and download mods again). It now always finds your data, also after uninstalling (when you kept your data),
  reinstalling, or reinstalling Windows with your data on another drive, and it logs where its data is.
- **The in-game menu sees Leonida.** "Open Leonida to apply changes" no longer shows while Leonida is open.
- **Long notes in the in-game menu** show every line.

## New

- **Your game lost its mods?** After Steam, Epic or Rockstar repaired or reinstalled GTA V, Leonida tells you and
  **Repair** puts every mod back from your Downloads, without downloading anything.
- **No hand steps.** After **Play**, the mods of every pack's base are on and set up without you doing anything in
  game. Enable All Interiors loads the online interiors by itself; if they aren't there a minute after story mode,
  the Leonida menu reloads the scripts once for you (no more "press Insert"). Where a step still needs you (some paid
  add-ons, ReShade's own installer), Leonida says why.
- **On and checked in game.** A deep play test (`leonida playtest --deep`, or the app's Play test) now checks each
  mod inside the game: its DLC packs and interiors are loaded, its own log says it started. The Manage page shows
  **on and checked in game** on each mod, or what's missing.
- **Ready-made setups**: a pack, its variant, add-ons and GTA's settings, chosen together for your PC in one click;
  export yours to share it.
- **Faster start**: the window appears sooner; pages are built when you first open them.
- Paid add-ons say **Paid by creator**: buy them on the creator's own page to enable them.
- The command line no longer crashes on characters your console can't show.

## Known limits

- Story mode only. Before GTA Online, turn **Online-safe** on (*Manage*).
- Tested on game build 1.0.1013.20. Mods made for a newer build say so on their card.
- The exe isn't code-signed yet, so Windows asks once (*More info → Run anyway*).

Full list of changes: `docs/CHANGELOG.md`.
