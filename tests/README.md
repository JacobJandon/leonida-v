# Leonida V tests

```powershell
pip install -e ".[dev,gui]"
$env:QT_QPA_PLATFORM = "offscreen"; $env:LEONIDA_NO_NET = "1"
pytest -q --cov=leonida --cov-report=term-missing
```

CI (`.github/workflows/ci.yml`) runs the same on windows-latest and ubuntu-latest (Python 3.11 and 3.13), with a
coverage gate of 90% of `leonida/` lines on Windows (`--cov-fail-under=90`). Linux has no gate, because the
Windows-only branches are skipped there.

Nothing in the suite touches the real game folder, the real state or downloads folder, or the network, and nothing
opens a browser or a dialog:
- `conftest.py` sets `LEONIDA_NO_OPEN`;
- the GUI tests monkeypatch the `QMessageBox`, `QInputDialog` and `QFileDialog` statics;
- network code is pointed at a local `127.0.0.1` server or monkeypatched.

## Markers

| Marker | What | Default |
|---|---|---|
| `e2e` | Real-file install test (`build/e2e_real_install.py`) on the real Script Hook V .NET Enhanced and Menyoo archives | skipped unless `LEONIDA_E2E_DOWNLOADS` points at a folder with them |
| `webengine` | Starts QtWebEngine (the built-in browser): slow, about 200 MB of Chromium | runs; deselect with `-m "not webengine"` |

Windows-only tests (registry, exe version via ctypes, `os.startfile`, the PowerShell GPU query) use
`skipif(sys.platform != "win32")`. They run on Windows, including CI.

```powershell
pytest -q -m "not webengine"                                           # quick run
$env:LEONIDA_E2E_DOWNLOADS = "D:\Leonida\Downloads"; pytest -q -m e2e  # real archives
```

## Suites

| File | Covers |
|---|---|
| `test_manifest.py`, `test_game_builds.py` | mods.json/profiles/hotkeys loading, validation, per-game-build variants |
| `test_matcher_archive_detect.py` | matching downloads to mods, archive listing, game detection |
| `test_installer.py` | copy/generic/run/guided installs, backups, rollback, uninstall equals the baseline |
| `test_checks_onlinesafe_cli.py` | pre-install checks, online-safe mode, CLI basics |
| `test_windows.py` | Windows-specific behaviour (launch commands, registry, 32-bit Python) |
| `test_downloader.py`, `test_updater.py`, `test_modpack.py` | GitHub/direct downloads, the self-updater, modpack.json and mod updates |
| `test_verify.py` | post-launch log verifier (sample logs quoted from the mods' sources) and the opt-in `e2e` test |
| `test_cov_cli.py`, `test_cov_core.py` | every CLI command and the core modules' remaining branches |
| `test_cov_detect_archive.py`, `test_cov_updates.py` | detection, archives, downloader, installer, mod updates |
| `test_gui.py`, `test_gui_pages.py` | offscreen GUI: every page and button handler |
| `test_gui_browser.py` | the QtWebEngine browser window (`webengine`) |
| `test_rpf.py` (+ `fake_rpf_helper.py`) | install method `rpf`: archive edits in `mods\`, `.oiv` packages, backups, rollback (fake helper; the real one: `build/e2e_rpf.py`) |
| `test_gui_shutdown.py` | clean Qt exit: worker threads, picture jobs, browser profile |
| `test_shortcuts.py` | Start menu/desktop shortcuts (temp folders), Start-Leonida.bat applying a staged update, and the opt-in release dry run (`LEONIDA_E2E_RELEASE=1`, `e2e`) |
| `test_newpages.py` | Choose your modpack, editions, the play-test view |
| `test_theme.py`, `test_widgets.py` | the Sunset Emblem theme (contrast, fonts, QSS) and the redesign components; renders every page mock |

Bugs found by tests and not fixed yet are kept as `xfail(strict=True)` tests whose reason starts with `BUG:`.
When a fix lands, the test starts passing, strict xfail turns that into a failure, and the marker must be removed.
