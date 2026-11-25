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
| `Leonida-V-Setup-<ver>.exe` | The per-user installer (`build/build_setup.py`): the win64 zip inside, checked by its SHA-256 before anything is written. No admin rights. The program goes into `%LOCALAPPDATA%\Programs\Leonida V`, the data into a folder you pick. It makes Start menu and desktop shortcuts and an Apps & features entry (`LeonidaV.exe --uninstall`). Silent: `/S [--dir D] [--data D] [--no-desktop] [--no-shortcuts] [--launch] [--log F]`. |
| `modpack.json` | `release/modpack.json`, only if it exists (otherwise a notice, not a failure). |
| `SHA256SUMS.txt` | `<sha256>  <name>` for each asset above. The updater and `fetch_latest()` check against it. |

Mod files are never release assets. `modpack.json` holds only names, sizes, hashes and the authors' URLs.
CodeWalker's files never are either: the build stops if a zip holds `CodeWalker.Core.dll`, `SharpDX*.dll`, a built
`LeonidaRpf.exe` or CodeWalker's source (the app fetches it at first use, `leonida/cwtools.py`).
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
manual run with "release" ticked. Then it runs `e2e_setup.py --smoke dist` (the setup installs and uninstalls
silently, in a temp folder with its own registry root) and publishes a GitHub release. A manual run makes a draft
pre-release.

Dry run of that job, locally, without publishing:

```powershell
python build/release_dryrun.py --working-tree   # or without the flag: a clean clone of HEAD
```

It builds in a temp folder, runs the job's steps (tag/version check, modpack check, build + self-check + zips +
setup, setup smoke test) and lists the artifacts with their sizes and SHA-256s.

### Publishing a release

Tag a **stable** version for the first public release (`v1.0.0`, not `v1.0.0rc1`). The job publishes `rc`/`a`/`b`/
`dev` versions as pre-releases, and GitHub's `releases/latest`, which installed copies ask for updates, skips
pre-releases.

```powershell
git switch main
git pull --ff-only
python -c "import leonida; print(leonida.__version__)"   # must print 1.0.0: the job stops if the tag differs
git tag -a v1.0.0 -m "Leonida V 1.0.0"
git push origin v1.0.0
```

The tag starts the `ci` workflow. First the tests run (Windows + Ubuntu, Python 3.11 / 3.13). Then `windows-build`
does the version check, the modpack check, the build with its self-check, the setup smoke test and
`check_release.py`. Then it publishes **Leonida V 1.0.0** with `docs/RELEASE-NOTES-1.0.0.md` as its notes, marked
Latest. The assets are the setup exe, the win64 zip, the source zip, modpack.json and SHA256SUMS.txt.

After it's published:

```powershell
gh release view v1.0.0                                    # title, "Latest", 5 assets, not a pre-release
(Invoke-RestMethod https://api.github.com/repos/JacobJandon/leonida-v/releases/latest).tag_name   # v1.0.0
gh release download v1.0.0 -D $env:TEMP\leonida-1.0.0
python build/check_release.py $env:TEMP\leonida-1.0.0     # checksums, setup payload, no CodeWalker file
python build/e2e_setup.py --smoke $env:TEMP\leonida-1.0.0 # the published setup installs + uninstalls (temp only)
```

Then, on the owner's PC:
- the portable kit or an older exe: **Manage > Check for updates** (or `leonida self-update --check`) shows 1.0.0;
- the setup double-clicked: install, start, close, then uninstall from Apps & features.

The exe isn't code-signed, so SmartScreen says "Windows protected your PC": click *More info* > *Run anyway*.

### End-to-end update check

End-to-end check of the installer and the installed app's self-update, with two real builds, version N and N+1:

```powershell
python build/e2e_setup.py --old <dist of N> --new <dist of N+1>
```

It installs N silently and serves N+1 from a fake GitHub on 127.0.0.1. A corrupt download is refused. The real one
is verified, swapped in, and restarts LeonidaV.exe on N+1, keeping State and Downloads. Then it uninstalls.

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

## Release dry run: the self-updater against the real release files

After `python build/build_exe.py --release`:

```powershell
python build/e2e_update.py [--keep]          # or: $env:LEONIDA_E2E_RELEASE = "1"; pytest -m e2e tests/test_shortcuts.py
```

It serves `dist/` on 127.0.0.1 with a fake GitHub `releases/latest` (v9.9.9, the files in `dist/release-assets.txt`)
and runs `updater.check()` + `apply()` on throwaway copies in temp:
- a git clone, which fast-forwards (local changes are refused);
- a portable kit, where the real `Start-Leonida.bat` with `LEONIDA_SWAP_ONLY=1` swaps `leonida-v.new` in;
- an unpacked exe folder, where the real `apply-update.bat` helper swaps `LeonidaV.new` in (restart off, so no window).

## Shortcuts

`Start-Leonida.bat` makes a "Leonida V" shortcut in the Start menu and on the desktop on its first run. It points
at itself, runs minimized and uses `leonida/gui/assets/leonida.ico`; `State\.shortcuts-created` makes sure this
happens only once. For the frozen build, run `leonida.exe --create-shortcuts [--no-desktop]` (target: LeonidaV.exe).
`LEONIDA_NO_SHORTCUTS=1` makes none and `LEONIDA_NO_DESKTOP_SHORTCUT=1` skips the desktop one. Tests write them
into `LEONIDA_STARTMENU_DIR` / `LEONIDA_DESKTOP_DIR`.
