# Leonida V — plan (v1)

Living plan doc: https://claude.ai/artifact/BGPindmjSYZ1YCrq9fTnPd
Stable mod guide: https://claude.ai/artifact/EYNdb89Pb5wJ5k5DW9YQQ9

## Roadmap

| Phase | What | Gate to leave it |
|---|---|---|
| 0 | Plan | Decisions made (done: Python + PySide6, private repo first, Core default) |
| 1 | Manifest and profiles | Every link verified by hand |
| 2 | Engine and CLI | All automated tests pass; uninstall = snapshot (**done in dev0**) |
| 3 | GUI wizard | Usable end to end (first version in dev0) |
| 4 | Real test on a PC | Core profile, then extras one at a time; 30-minute crash-free session |
| 5 | Release 1.0 | GitHub release: `.exe` (PyInstaller), source, SHA-256 sums |
| 1.1 | Later | Direct GitHub-release downloads, Nexus mod-manager links, update checker |

## Real-PC test checklist (phase 4)

- [ ] `leonida doctor` shows .NET 4.8 and VC++ as ok
- [ ] `leonida detect` finds the game; version matches the tested build
- [ ] `leonida get --watch` recognises every download (use `assign` for odd file names)
- [ ] `leonida install --dry-run` plan looks right
- [ ] Install Core; after each step: story mode loads, 1 minute of driving
- [ ] NVE textures intact after the HUD step
- [ ] HUD on F8, Menyoo rebound (then `leonida keys set menyoo "Open trainer menu" F9`)
- [ ] 30-minute session without a crash
- [ ] `online-safe on` -> game launches clean -> `online-safe off` -> mods back
- [ ] `uninstall` -> "matches the pre-install snapshot"
