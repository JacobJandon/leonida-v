# Asking dexyfex for permission to use CodeWalker.Core (draft for the owner)

This is a draft. **The owner sends it.** Leonida and its developers don't contact anyone. Edit it freely.

## Where to send it

Found on the CodeWalker page on gta5-mods (checked 2026-11-25):
- **CodeWalker Discord server:** <https://discord.gg/BxfKHkk>. Ask in the server, or DM dexyfex there. This is the
  most direct route.
- **Patreon:** <https://www.patreon.com/dexyfex>. You can send a message there, even without a membership.
- His homepage: <https://dexyfex.com>.

What his pages say today:
- The gta5-mods page asks that anyone using CodeWalker "provide some credits and also a link to this download page"
  (<https://www.gta5-mods.com/tools/codewalker-gtav-interactive-3d-map>).
- Its v.29 changelog calls CodeWalker.Core a "library which can be used by other developers".
- The GitHub repo (<https://github.com/dexyfex/CodeWalker>) has no licence file. Its `Readme_Src.txt` says "This
  source code is released for educational purposes only." So Leonida asks before any public release.

## The message (Discord DM / Patreon message)

> Hi dexyfex,
>
> I'm [your name], and I make **Leonida V**, a free, open-source mod manager for GTA V. It's **story mode only**: it never
> touches GTA Online or BattlEye. The source is on GitHub:
> https://github.com/JacobJandon/leonida-v
>
> Leonida installs a curated set of single-player mods (Map Fixes, Drive V, the GTA VI-Inspired HUD and so on). It
> downloads each mod only from its author's own page, logs every file, and can undo any step.
>
> Several of these mods have to be added into `.rpf` archives, or come as `.oiv` packages. For those I'd like to use
> **CodeWalker.Core**. Here's exactly how, so you can say yes, no, or "do it differently":
>
> - **Built from your source, on the user's PC.** A small helper (a console program of a few hundred lines) is compiled
>   locally from your published GitHub source at a pinned commit. Neither Leonida's repository nor its releases ever
>   ship or re-host CodeWalker binaries or source.
> - **Only for copies in the game's `mods` folder.** The helper copies an archive into `mods`, converts it to OPEN
>   for OpenRPF the way RPF Explorer does, and puts the mod's files in (plus `dlclist.xml` lines and `.oiv`
>   installs). The game's own archives are never written, and every change can be rolled back.
> - **Keys** come from the user's own `GTA5_Enhanced.exe`, through CodeWalker's own key loading. Nothing is stored or
>   shared.
> - **Credit:** CodeWalker and you are credited in the README, in `docs/CREDITS.md` and in the release notes (and will be in
>   the app's About / credits screen),
>   with a link to your gta5-mods page and the "educational purposes" note from your readme.
>
> Is this OK with you? If you'd rather it worked differently, I'll change it. For example:
> - users download CodeWalker themselves and Leonida only calls it;
> - Leonida just shows the steps to do by hand in CodeWalker;
> - or anything else you prefer.
>
> I can also tell users about your Patreon and Discord wherever CodeWalker is used.
>
> Thanks for CodeWalker. A lot of the GTA V Enhanced modding scene wouldn't exist without it.
>
> [your name] (JacobJandon on GitHub)

## Shorter version (Discord, first message)

> Hi dexyfex! I make Leonida V, a free, open-source, story-mode-only GTA V mod manager
> (https://github.com/JacobJandon/leonida-v). It builds a small local helper from your CodeWalker.Core source, on
> the user's PC at a pinned commit (no CodeWalker binaries shipped or re-hosted). The helper installs mods into
> copies in the game's `mods` folder, and you're credited with a link to your page. Would that be OK with you, or
> would you prefer another way, e.g. users install CodeWalker themselves and Leonida just calls it? Thanks for
> CodeWalker!

## What to do with the answer

- **Yes:** note the date and his words in `docs/CREDITS.md` ("Still to sort out" → done), and remove the "permission
  is being asked for" line from the release notes.
- **Yes, with conditions:** follow them (e.g. a link in the app's About box), and note them in `docs/CREDITS.md`.
- **"Users install CodeWalker themselves":** point `LEONIDA_RPF_HELPER` / the helper search at the user's own
  CodeWalker folder (`leonida/rpf.py`, `find_helper`). The helper is a separate small program, so it would then load
  CodeWalker.Core from that folder. Plan the change before the release.
- **No:** the archive mods go back to guided steps (the `rpf` entries in mods.json → `guided`; the steps are in git
  history), and the helper is removed from the build.
- **No answer:** keep the helper out of public releases (it stays a local build for the owner's own PC) until there
  is one.
