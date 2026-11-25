# The Leonida menu (in game)

Leonida's own menu inside GTA V. It's a Script Hook V .NET script (our own code, C# 5, API v3), and it works in
story mode only. Leonida installs it in every pack as the step **Leonida menu (in game)**. That step is logged and
undone like any mod.

## Opening it

- **F5** (the default). Pick another key in the menu itself (*Mods > Leonida menu (in game) > Keys/Open*), or in
  `scripts\LeonidaMenu.ini [Keys] Open` after unlocking it. The choices are F5, F12, Ctrl+F5, Shift+F5, Num 0,
  Scroll Lock and Pause. F5 used to be Food Delivery's "reload its settings" key; Leonida moves that one to Num 9.
- **The phone**, when iFruitAddon2 is installed: call **Leonida**.
- To move around: the arrows, Enter and Backspace, or a controller's d-pad, A and B. Left/Right changes a value.
  Esc goes back instead of opening the pause menu.

## Pages

| Page | What it shows / does |
| --- | --- |
| Status | pack, variant, game build, mods on, the last play test, a recent crash (from the game's own crash dump), whether Leonida is running, Leonida's answers to your changes |
| Mods | every mod of the pack: on/off, its locked settings with their current values. A value with *choices* can be changed (Left/Right, then Enter). *Unlock (advanced)* makes Leonida leave your own value alone. Switching a mod on or off happens after you quit |
| Pack & variant | switch the pack, or the variant (Performance / Balanced / Ultra, ram16 / ram32, …) |
| Game settings | GTA's own graphics settings that Leonida sets for this pack, variant and PC (`leonida/gamesettings.py`), with "(now …)" where the game's file differs |
| Keys | every mod's keys, clashes marked |
| Help | per mod: what it does and what to look for in game (mods.json `checks`) |
| Tools | reload scripts (presses Script Hook V .NET's reload key), make a debug report (Desktop), open Leonida after you quit, close |

## How a change is made (the bridge)

The menu never edits a mod's file or anything in the game folder. It writes a request, and Leonida applies it
through its installer and settings engine: logged, and undoable from Manage. The files live in `<State>\menu\`
(the menu finds the folder through `scripts\LeonidaMenu.ini [Leonida] StateDir`, a value Leonida fills in):

- `menu-model.json`, Leonida → menu: everything the menu shows, a heartbeat, and the answers to requests;
- `menu-requests.json`, menu → Leonida: the requests. Only the menu writes it;
- `menu-processed.json`: Leonida's record, so nothing is applied twice.

| Request | When Leonida applies it |
| --- | --- |
| a setting with choices, in a script's `.ini` (`scripts\`) | at once, while you play; then *Tools > Reload scripts* |
| any other setting, locking a key again | after the game closes |
| unlock a key | at once (only a flag) |
| switch a mod on / off | after the game closes (off = rolled back, download kept; on = installed again) |
| pack / variant | after the game closes: chosen, and the variant's settings are written. Mods that differ are added or removed on Leonida's Install page |
| debug report | at once |
| open Leonida | when the game closes |

Leonida answers while its window is open: a timer every 3 s, `leonida/gui/menuhook.py`. Without the window, use
`leonida menu serve` (answers until Ctrl+C) or `leonida menu apply` (once, for example after quitting).
`leonida menu status` shows the queue.

## Self-test

`leonida playtest --deep` writes `<State>\menu\selftest.flag`. In story mode the menu then does three things
without any key press, and writes `selftest-report.json`:
- it opens every page and draws each once;
- it sends Leonida a request and waits for the answer;
- it tries the phone entry.

The play test adds the results ("built every page", "read Leonida's data", "talk both ways") to its report.

## Design notes

- **No LemonUI.** It isn't in every pack (Core has no LemonUI), so the menu draws with the game's own natives
  (`DRAW_RECT`, the text commands) and reads the frontend controls. It works in any pack that has Script Hook V .NET.
- **iFruitAddon2 through reflection.** Without it the menu still compiles and opens with its key; with it,
  "Leonida" is a phone contact.
- **C# 5 only:** Script Hook V .NET compiles `.cs` scripts with the C# 5 rules. `tests/test_menu.py` compiles it
  with `csc -langversion:5` against a stub. It also runs its JSON code against a model Python wrote, and back.
  `build/check_menu.py` compiles it against the real `ScriptHookVDotNet3.dll` and checks every native is there.
- **The zip** (`LeonidaMenu-<version>.zip`) is made by Leonida itself (`leonida/menu/__init__.py`, download type
  `leonida`), never downloaded. Its bytes are the same on every PC, so its SHA-256 is stable.
- **GTA V Legacy:** not added yet (mods-legacy.json).
