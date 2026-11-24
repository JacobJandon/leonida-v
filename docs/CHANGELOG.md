# Changelog

## 1.0.0.dev0 — 2026-11-24

First development build.

- Manifest: 24 mods (14 core), 4 profiles, hotkey map; tested against GTA V Enhanced 1.0.1158.13.
- Engine: game detection (Steam, Epic, Rockstar, common paths, manual), download matching with lockfile and SHA-256,
  four install methods (copy / generic / run / guided), baseline snapshot, install log with backups,
  per-step rollback, full uninstall, online-safe switch, pre-install checks.
- CLI: `leonida` with detect, profiles, swap, get, assign, check, install, status, rollback, uninstall,
  online-safe, keys, doctor.
- GUI: PySide6 wizard (Welcome, Game, Profile, Get mods, Check, Install, Manage).
- 49 automated tests (fake game folders and archives), CI on Windows and Ubuntu.
