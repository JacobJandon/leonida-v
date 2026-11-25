# Leonida V 1.0.1: release notes

**Leonida V turns GTA V Enhanced into a free GTA VI experience.** Story mode only; never GTA Online.

Already on 1.0.0? Open Leonida → **Manage → Check for updates** (or `leonida self-update`): it downloads 1.0.1,
checks it against `SHA256SUMS.txt`, swaps it in after the app closes and keeps your State and Downloads.

## Download

- **`Leonida-V-Setup-1.0.1.exe`** (recommended): per-user install, no administrator rights. Windows SmartScreen may
  warn because the exe isn't code-signed: *More info → Run anyway*.
- `LeonidaV-1.0.1-win64.zip`: the same program, portable.
- `leonida-v-1.0.1.zip` + `Start-Leonida.bat`: the portable kit with its own Python.

## New

- **The Leonida menu, in game.** Press **F5** (or call "Leonida" on the phone with iFruitAddon2): Status, Mods (on/off
  and their settings), Pack & variant, GTA's game settings, Keys, Help, Tools. It sends requests; Leonida applies them
  with its installer (logged, undoable), at once when that's safe while playing, otherwise when the game closes.
  Food Delivery's settings-reload key moves from F5 to Num 9. Self-tested in the real game (`playtest --deep`).
- **GTA's own settings, set up for your PC.** Leonida locks the `settings.xml` values that matter for the pack:
  window mode (borderless, which the GTA VI HUD's minimap needs), textures, grass, population and variety, HD
  streaming while flying, upscaling and frame generation by GPU. Your file is backed up first; `leonida settings
  unlock gta-settings …` keeps your own value.
- **One job, one mod.** Two mods that do the same thing (fuel, police, handling, cameras, interiors…) can't be
  installed together unless Leonida knows how they coexist.
- **Paid mods: buy and play.** `leonida paid list` shows each paid mod's own buy page and price. Buy and download it
  yourself; Leonida recognises the file in Downloads, scans it and installs it. Re-uploads are refused.
- **Contact and contribute:** issue forms for bugs, crashes, mod requests and ideas; `CONTRIBUTING.md` with a one-step
  dev setup; *About & help → Report a problem…* opens a prefilled bug report.

## Faster

- The window appears in about 2 s instead of about 15 s; pack switches take about 0.6 s; page switches 64–134 ms.

## Fixed

- The GTA VI HUD's minimap no longer draws Enable All Interiors' hidden online-property blips (they showed as small
  "IR"/cursor icons). *(not verified in game yet)*
- The load crashes found on 1.0.1013.20 (VisualV; Enable All Interiors' Tuners auto shop) stay fixed: 15 of 15 play
  tests passed.

## Known issues

- On 16 GB PCs, close big apps (browsers, Discord) before playing; Play warns when free memory is low.
- One engine crash during a long 3-star police fight on 1.0.1013.20 (19:53, 2026-11-25) isn't explained yet
  (`docs/IN-GAME-CHECKS.md`, "Known crashes").
- CodeWalker isn't shipped; Leonida fetches it from its author's GitHub when an archive mod first needs it.
