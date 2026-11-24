# build/: Windows app, release assets and the developer checks

Everything here runs on Windows with 64-bit Python 3.10+ (CI uses 3.13).

```powershell
pip install -e ".[dev,gui,build]"
```

## Windows app (PyInstaller, one folder)

```powershell
python build/build_exe.py --selftest
```

- Output: `dist/LeonidaV/` holding `LeonidaV.exe` (the GUI), `leonida.exe` (the CLI), `GUIDE.md`, `README.md`, `LICENSE`
  and `_internal/` (Python, Qt + QtWebEngine, the manifest JSON). About 320 MB.
- One folder rather than one file: QtWebEngine is ~200 MB, and a one-file exe would unpack it to %TEMP% on every start.
- The spec is `leonida.spec`. `entry_gui.py` and `entry_cli.py` are the frozen entry points. PyInstaller's work
  files go to `build/work/` (ignored by git). The spec bundles every `leonida` module, including lazily imported
  ones, and leaves out things the app never uses (DevTools, QML, translations other than en-US, tkinter, tests).
- `--selftest` starts the built `LeonidaV.exe` with `LEONIDA_SELFTEST=1` and empty temp state and download folders.
  The hook in `entry_gui.py` then runs `selftest.py` instead of the app. It imports every module, opens the main
  window, opens the built-in browser on an inline page that runs JavaScript, and exits 0 if everything worked. Users
  never set that variable. Add `--selftest-url https://...` to load a real page too.
- `--no-build` re-checks an existing build.

## Release assets

```powershell
python build/build_exe.py --release
```

This writes the assets into `dist/` and lists them in `dist/release-assets.txt`. The CI job uploads exactly that list.

| Asset | What it is |
|---|---|
| `LeonidaV-<ver>-win64.zip` | `dist/LeonidaV/` under a `LeonidaV/` folder. The frozen self-updater swaps this whole folder. |
| `leonida-v-<ver>.zip` | Source kit (`git archive` of HEAD under `leonida-v/`, so commit first). Portable kits update from this. |
| `modpack.json` | `release/modpack.json`, only if it exists (otherwise a notice, not a failure). |
| `SHA256SUMS.txt` | `<sha256>  <name>` for each asset above. The updater and `fetch_latest()` check against it. |

Mod files are never release assets. `modpack.json` holds only names, sizes, hashes and the authors' URLs.
Before publishing, the script checks `modpack.json` and stops on any of these:
- it doesn't load (`leonida.modpack.load_file`);
- its `version` differs from mods.json's `version`;
- an entry would re-host a mod without `redistribution.allowed` in mods.json, or points away from the author's source.

To make or refresh it, on a PC where the set was tested (run it again on another game build to add that build):

```powershell
leonida modpack build --out release/modpack.json
```

Then commit `release/modpack.json`.

CI (`.github/workflows/ci.yml`, job `windows-build`) runs `build_exe.py --selftest --release` on `v*` tags, or on a
manual run with "release" ticked, and publishes a GitHub release. A manual run makes a draft pre-release.

## Opt-in real-file install test

The normal `pytest -q` uses only made-up archives. On a PC that has the real downloads, this also installs the
real Script Hook V .NET Enhanced and Menyoo archives:

```powershell
$env:LEONIDA_E2E_DOWNLOADS = "D:\Leonida\Downloads"; pytest tests/test_verify.py
```

The script can also run directly:

```powershell
python build/e2e_real_install.py --downloads D:\Leonida\Downloads
```

It needs `ScriptHookVDotNetEnhanced-v*.zip` and `MenyooSP*.zip` in that folder. It works in a temp folder with a fake
game folder (never the real game) and runs these steps:
1. baseline;
2. install both through `Installer`;
3. check every file landed where mods.json says, byte for byte;
4. `verify()` reports "not seen yet";
5. roll back Menyoo, then uninstall;
6. check the folder equals the baseline, both by Leonida's snapshot and by an independent SHA-256 walk.

It also prints `MANIFEST` lines when a `files` spec doesn't fit the real archive layout. Use `--keep` to keep the
temp folder, and `--build` to choose the game build the manifest is resolved for (default 1.0.1013.20).

## RPF helper (CodeWalker) and its real-file test

Mods that edit GTA's `.rpf` archives or ship as `.oiv` packages use install method `rpf`, which runs `LeonidaRpf.exe`,
a small helper on CodeWalker.Core. Build it on the PC from CodeWalker's own source; it is never re-hosted, see
`docs/CODEWALKER.md`:

```powershell
python build/build_rpf_helper.py                     # portable .NET 8 SDK if none is installed; output build/codewalker/bin
python build/build_rpf_helper.py --install-to "$env:LOCALAPPDATA\LeonidaV\tools\LeonidaRpf"
```

Opt-in real-file test. It needs the real game (read only, for the keys and a few files) and the real downloads:

```powershell
python build/e2e_rpf.py [--only nextgeneuphoria,hud-geckomacabre] [--keep]
```

It builds a fake game folder in temp (with a copy of one real NG-encrypted DLC archive) and installs the six CodeWalker
mods from `D:\Leonida\Downloads` with the proposed mods.json entries. It checks the files inside the `mods\` archives,
`dlclist.xml` and the `gameconfig.xml` pools, then rolls everything back and compares the folder with the baseline.
