# PyInstaller spec for Leonida V: one folder dist/LeonidaV/ holding
#   LeonidaV.exe  windowed GUI (leonida.gui.app:main, with QtWebEngine for the built-in browser)
#   leonida.exe   console CLI (leonida.cli:main)
# Both exes share one _internal/ folder (Python runtime, Qt, manifest JSON).
# Build with:  python build/build_exe.py   (it calls PyInstaller on this file)
# -*- mode: python -*-

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32 import versioninfo as vi

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is set by PyInstaller
BUILD = ROOT / "build"

VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "leonida" / "__init__.py").read_text("utf-8")).group(1)


def version_resource(description: str, internal_name: str, filename: str) -> vi.VSVersionInfo:
    # "1.0.0.dev1" -> (1, 0, 0, 0); the exact string (incl. .devN/rcN) goes in the string table below.
    nums = [int(n) for n in re.match(r"\d+(?:\.\d+)*", VERSION).group(0).split(".")]
    nums = (nums + [0, 0, 0, 0])[:4]
    strings = [
        vi.StringStruct("CompanyName", "JacobJandon"),
        vi.StringStruct("FileDescription", description),
        vi.StringStruct("FileVersion", VERSION),
        vi.StringStruct("InternalName", internal_name),
        vi.StringStruct("LegalCopyright", "MIT License"),
        vi.StringStruct("OriginalFilename", filename),
        vi.StringStruct("ProductName", "Leonida V"),
        vi.StringStruct("ProductVersion", VERSION),
    ]
    return vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=tuple(nums), prodvers=tuple(nums), mask=0x3F, flags=0x0, OS=0x40004,
                             fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[vi.StringFileInfo([vi.StringTable("040904B0", strings)]), vi.VarFileInfo([vi.VarStruct("Translation", [1033, 1200])])],
    )


DATAS = [(str(p), "leonida/manifest") for p in sorted((ROOT / "leonida" / "manifest").glob("*.json"))]
# The app logo: gui/app.py logo_path() looks under sys._MEIPASS/leonida/gui/assets when frozen.
# (The repo-root assets/ folder is source art and make_icons.py, not app data: never bundled.)
ASSETS = ROOT / "leonida" / "gui" / "assets"
# logo + fonts (assets/fonts: Inter and Montserrat, SIL OFL 1.1, licences shipped next to them)
DATAS += [(str(p), (Path("leonida/gui/assets") / p.parent.relative_to(ASSETS)).as_posix())
          for p in sorted(ASSETS.rglob("*")) if p.is_file()]
ICON = str(ASSETS / "leonida.ico")

# Everything in the package (lazily imported modules such as gui.browser and updater included), but no tests.
HIDDEN = [m for m in collect_submodules("leonida") if ".tests" not in m] + [
    "leonida.gui.browser",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
]

# Never needed at runtime. Qt modules the GUI does not import are listed so a stray hook can't drag them in;
# QtWebEngine itself needs QtNetwork, QtQml/QtQuick, QtPositioning, QtWebChannel and QtPrintSupport, so those stay.
EXCLUDES = [
    "tkinter", "_tkinter", "turtle", "turtledemo", "idlelib", "lib2to3", "pydoc_data", "test", "tests",
    "unittest", "doctest", "pytest", "_pytest", "pip", "setuptools", "pkg_resources", "distutils", "ruff",
    "PyInstaller",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender", "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtGraphs", "PySide6.QtGraphsWidgets", "PySide6.QtHelp", "PySide6.QtHttpServer",
    "PySide6.QtLocation", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNetworkAuth",
    "PySide6.QtNfc", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtQuick3D", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtSvgWidgets", "PySide6.QtTest", "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools", "PySide6.QtWebSockets", "PySide6.QtWebView", "PySide6.QtAxContainer",
    # The QtWebEngine hooks pull in these Python bindings, and the QtQml hook then copies every QML plugin (~100 MB with
    # their DLLs). The GUI uses no QML; the Qt6Qml/Qt6Quick/Qt6OpenGL DLLs that Qt6WebEngineCore.dll links against are
    # still collected by the binary dependency scan.
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
]

KEEP_LOCALES = {"en-US.pak"}  # Chromium falls back to en-US for other UI languages; the app itself is English only


def drop(dest: str) -> bool:
    """Files the hooks collect that a user never needs."""
    d = dest.replace("\\", "/")
    if d.startswith("PySide6/qml/"):
        return True
    if d.startswith("PySide6/resources/qtwebengine_devtools_resources"):  # Chromium DevTools (83 MB), no UI for it
        return True
    if d.startswith("PySide6/resources/") and ".debug." in d:  # only loaded by debug builds of Qt
        return True
    # Plugins nobody uses here, plus the DLLs only they link against (checked with pefile against Qt 6.12):
    # PDF image format (Qt6Pdf), virtual keyboard, geolocation backends (Qt6SerialPort via NMEA).
    # Qt6Positioning.dll itself stays: Qt6WebEngineCore.dll links it.
    if d in ("PySide6/plugins/imageformats/qpdf.dll", "PySide6/Qt6Pdf.dll", "PySide6/Qt6VirtualKeyboard.dll",
             "PySide6/Qt6SerialPort.dll"):
        return True
    if d.startswith(("PySide6/plugins/platforminputcontexts/", "PySide6/plugins/position/")):
        return True
    if d.startswith("PySide6/translations/qtwebengine_locales/"):
        return d.rsplit("/", 1)[-1] not in KEEP_LOCALES
    return d.startswith("PySide6/translations/") and d.endswith(".qm")  # Qt's own UI translations, never loaded


def trim(toc):
    return [entry for entry in toc if not drop(entry[0])]

gui = Analysis(  # noqa: F821
    [str(BUILD / "entry_gui.py")],
    pathex=[str(ROOT), str(BUILD)],
    datas=DATAS,
    hiddenimports=HIDDEN + ["selftest"],
    excludes=EXCLUDES,
    noarchive=False,
)
cli = Analysis(  # noqa: F821
    [str(BUILD / "entry_cli.py")],
    pathex=[str(ROOT)],
    datas=DATAS,
    hiddenimports=[m for m in collect_submodules("leonida") if not m.startswith("leonida.gui")],
    excludes=EXCLUDES + ["PySide6", "shiboken6"],
    noarchive=False,
)

gui_exe = EXE(  # noqa: F821
    PYZ(gui.pure),  # noqa: F821
    gui.scripts,
    [],
    exclude_binaries=True,
    name="LeonidaV",
    icon=ICON,
    console=False,
    upx=False,
    strip=False,
    version=version_resource("Leonida V installer kit", "LeonidaV", "LeonidaV.exe"),
)
cli_exe = EXE(  # noqa: F821
    PYZ(cli.pure),  # noqa: F821
    cli.scripts,
    [],
    exclude_binaries=True,
    name="leonida",
    icon=ICON,
    console=True,
    upx=False,
    strip=False,
    version=version_resource("Leonida V command line", "leonida", "leonida.exe"),
)

COLLECT(  # noqa: F821
    gui_exe, trim(gui.binaries), trim(gui.datas),
    cli_exe, cli.binaries, cli.datas,
    name="LeonidaV",
    upx=False,
    strip=False,
)
