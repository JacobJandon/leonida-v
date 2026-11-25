"""Native Windows dialogs for Leonida-V-Setup.exe and "LeonidaV.exe --uninstall": no Qt, stdlib ctypes only.

    choice, desktop = ask_install(version, install_dir, data_dir)   # "install" / "folder" / "cancel"
    folder = pick_folder("Where should Leonida keep your data?", start)
    result = run_with_progress("Installing Leonida V", "...", work)  # work(progress) on a thread, a progress bar
    start = finished(text)                                           # True: "Start Leonida V"
    ask_yes_no(text, default_no=True); message(text, error=False)

The dialogs are Windows' own TaskDialog (comctl32 v6: the setup exe's manifest asks for it). Without it (e.g. a plain
python.exe), they fall back to MessageBox, and the progress dialog just runs the work.
"""

from __future__ import annotations

import contextlib
import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes as w
from pathlib import Path

TITLE = "Leonida V setup"
_WM_USER = 0x400
TDN_CREATED, TDN_BUTTON_CLICKED, TDN_TIMER = 0, 2, 4
TDM_CLICK_BUTTON, TDM_SET_PROGRESS_BAR_POS, TDM_ENABLE_BUTTON = _WM_USER + 102, _WM_USER + 106, _WM_USER + 111
TDM_SET_ELEMENT_TEXT, TDE_CONTENT = _WM_USER + 108, 0
TDF_ALLOW_DIALOG_CANCELLATION, TDF_USE_COMMAND_LINKS = 0x8, 0x10
TDF_VERIFICATION_FLAG_CHECKED, TDF_SHOW_PROGRESS_BAR, TDF_CALLBACK_TIMER = 0x100, 0x200, 0x800
TDF_SIZE_TO_CONTENT = 0x1000000
TDCBF_OK, TDCBF_CANCEL, TDCBF_CLOSE = 0x1, 0x8, 0x20
IDOK, IDCANCEL, IDYES, IDNO = 1, 2, 6, 7
ICON_WARNING, ICON_ERROR, ICON_INFO = 0xFFFF, 0xFFFE, 0xFFFD
BTN_INSTALL, BTN_FOLDER, BTN_START = 1001, 1002, 1003

CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_long, w.HWND, w.UINT, w.WPARAM, w.LPARAM, ctypes.c_ssize_t)


class TASKDIALOG_BUTTON(ctypes.Structure):  # noqa: N801 - the Windows name
    _pack_ = 1
    _fields_ = [("nButtonID", ctypes.c_int), ("pszButtonText", w.LPCWSTR)]


class TASKDIALOGCONFIG(ctypes.Structure):  # noqa: N801 - the Windows name (packed: pshpack1.h in commctrl.h)
    _pack_ = 1
    _fields_ = [
        ("cbSize", w.UINT), ("hwndParent", w.HWND), ("hInstance", w.HINSTANCE), ("dwFlags", ctypes.c_int),
        ("dwCommonButtons", ctypes.c_int), ("pszWindowTitle", w.LPCWSTR), ("pszMainIcon", ctypes.c_void_p),
        ("pszMainInstruction", w.LPCWSTR), ("pszContent", w.LPCWSTR), ("cButtons", w.UINT),
        ("pButtons", ctypes.POINTER(TASKDIALOG_BUTTON)), ("nDefaultButton", ctypes.c_int),
        ("cRadioButtons", w.UINT), ("pRadioButtons", ctypes.POINTER(TASKDIALOG_BUTTON)),
        ("nDefaultRadioButton", ctypes.c_int), ("pszVerificationText", w.LPCWSTR),
        ("pszExpandedInformation", w.LPCWSTR), ("pszExpandedControlText", w.LPCWSTR),
        ("pszCollapsedControlText", w.LPCWSTR), ("pszFooterIcon", ctypes.c_void_p), ("pszFooter", w.LPCWSTR),
        ("pfCallback", CALLBACK), ("lpCallbackData", ctypes.c_ssize_t), ("cxWidth", w.UINT),
    ]


def _task_dialog_fn():
    try:
        fn = ctypes.windll.comctl32.TaskDialogIndirect
    except (AttributeError, OSError):
        return None
    fn.argtypes = [ctypes.POINTER(TASKDIALOGCONFIG), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                   ctypes.POINTER(w.BOOL)]
    fn.restype = ctypes.c_long
    return fn


def available() -> bool:
    """True when Windows' TaskDialog can be used (comctl32 v6 in this process)."""
    return _task_dialog_fn() is not None


def _dpi_aware() -> None:  # pragma: no cover - a Windows call, nothing to check
    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)


def _show(main: str, content: str = "", *, buttons: list[tuple[int, str]] = (), common: int = 0, icon: int = 0,
          verification: str = "", checked: bool = False, default: int = 0, flags: int = 0,
          callback=None, footer: str = "") -> tuple[int, bool]:
    fn = _task_dialog_fn()
    if fn is None:
        raise OSError("TaskDialog is not available")
    arr = (TASKDIALOG_BUTTON * max(len(buttons), 1))(*[TASKDIALOG_BUTTON(i, t) for i, t in buttons])
    cfg = TASKDIALOGCONFIG()
    cfg.cbSize = ctypes.sizeof(TASKDIALOGCONFIG)
    cfg.dwFlags = flags | TDF_SIZE_TO_CONTENT | (TDF_VERIFICATION_FLAG_CHECKED if checked else 0)
    cfg.dwCommonButtons = common
    cfg.pszWindowTitle = TITLE
    cfg.pszMainIcon = icon or None
    cfg.pszMainInstruction = main
    cfg.pszContent = content
    cfg.cButtons = len(buttons)
    cfg.pButtons = arr if buttons else None
    cfg.nDefaultButton = default
    cfg.pszVerificationText = verification or None
    cfg.pszFooter = footer or None
    auto = _autoclick()
    if auto is not None:  # tests: press a button as soon as the dialog is there
        inner = callback

        def callback(hwnd, msg, wparam, lparam, data, inner=inner, auto=auto):  # noqa: PLR0913
            ret = inner(hwnd, msg, wparam, lparam, data) if inner else 0
            if msg == TDN_CREATED and not (common & TDCBF_OK and not buttons and flags & TDF_SHOW_PROGRESS_BAR):
                if verification and auto < 0:
                    ctypes.windll.user32.SendMessageW(hwnd, _WM_USER + 113, 0, 0)  # TDM_CLICK_VERIFICATION: untick
                # this dialog's own buttons; another id means "close it" (so a wrong id never leaves it open)
                ids = {i for i, _ in buttons} | {b for flag, b in ((TDCBF_OK, IDOK), (TDCBF_CANCEL, IDCANCEL),
                                                                  (TDCBF_CLOSE, 8)) if common & flag}
                press = abs(auto) if abs(auto) in ids else next((b for b in (8, IDCANCEL, IDOK) if b in ids),
                                                                 IDCANCEL)
                ctypes.windll.user32.PostMessageW(hwnd, TDM_CLICK_BUTTON, press, 0)
            return ret
    keep = CALLBACK(callback) if callback else CALLBACK(lambda *a: 0)
    cfg.pfCallback = keep
    pressed, radio, verified = ctypes.c_int(0), ctypes.c_int(0), w.BOOL(False)
    hr = fn(ctypes.byref(cfg), ctypes.byref(pressed), ctypes.byref(radio), ctypes.byref(verified))
    if hr != 0:
        raise OSError(f"TaskDialogIndirect failed (0x{hr & 0xFFFFFFFF:08X})")
    return pressed.value, bool(verified.value)


def _autoclick() -> int | None:
    """LEONIDA_SETUPUI_AUTOCLICK=<button id> (tests and the release check): every dialog presses that button at
    once; a negative id also unticks the checkbox first. Never set in normal use."""
    import os

    raw = os.environ.get("LEONIDA_SETUPUI_AUTOCLICK", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _message_box(text: str, flags: int) -> int:
    auto = _autoclick()
    if auto is not None:  # tests: never block on a message box either
        return IDYES if abs(auto) in (IDYES, IDOK, BTN_INSTALL, BTN_START) else IDNO
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags)


# ------------------------------------------------------------------------------------------------ dialogs
def message(text: str, error: bool = False, main: str = "") -> None:
    try:
        _show(main or ("Something went wrong" if error else "Leonida V"), text, common=TDCBF_CLOSE,
              icon=ICON_ERROR if error else ICON_INFO)
    except OSError:
        _message_box(f"{main}\n\n{text}" if main else text, 0x10 if error else 0x40)


def ask_yes_no(text: str, main: str = "", default_no: bool = True, yes: str = "Yes", no: str = "No") -> bool:
    try:
        pressed, _ = _show(main or "Leonida V", text, buttons=[(IDYES, yes), (IDNO, no)], icon=ICON_WARNING,
                           default=IDNO if default_no else IDYES, flags=TDF_ALLOW_DIALOG_CANCELLATION)
        return pressed == IDYES
    except OSError:
        flags = 0x4 | 0x30 | (0x100 if default_no else 0)   # MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2
        return _message_box(f"{main}\n\n{text}" if main else text, flags) == IDYES


def ask_install(version: str, install_dir: Path, data_dir: Path, upgrade: bool = False) -> tuple[str, bool]:
    """The setup's first page. ("install" | "folder" | "cancel", desktop shortcut wanted)."""
    _dpi_aware()
    what = "Update" if upgrade else "Install"
    content = (f"Leonida V {version} turns GTA V Enhanced into a GTA VI-style game, story mode only.\n\n"
               f"Program:  {install_dir}\n"
               f"Your data:  {data_dir}\n"
               "     State (settings, install log, backups) and Downloads (the mods' own files)\n\n"
               "For this Windows user only: no administrator rights needed. Setup doesn't touch your game; "
               "Leonida only changes it when you install mods from inside it, and every change can be undone.")
    try:
        pressed, desktop = _show(
            f"{what} Leonida V {version}", content,
            buttons=[(BTN_INSTALL, f"{what}\nPut Leonida V on this PC"),
                     (BTN_FOLDER, "Choose another data folder…\nFor example on a drive with more space")],
            common=TDCBF_CANCEL, flags=TDF_USE_COMMAND_LINKS | TDF_ALLOW_DIALOG_CANCELLATION,
            verification="Create a desktop shortcut", checked=True)
        return {BTN_INSTALL: "install", BTN_FOLDER: "folder"}.get(pressed, "cancel"), desktop
    except OSError:
        answer = _message_box(f"{what} Leonida V {version}?\n\n{content}\n\nYes: {what.lower()}.   No: choose another "
                              "data folder.   Cancel: stop.", 0x3 | 0x20)
        return {IDYES: "install", IDNO: "folder"}.get(answer, "cancel"), True


def pick_folder(title: str, start: Path | None = None) -> Path | None:  # pragma: no cover - interactive
    """Windows' folder picker (with "Make New Folder"). None when cancelled."""

    class BROWSEINFOW(ctypes.Structure):  # noqa: N801 - the Windows name
        _fields_ = [("hwndOwner", w.HWND), ("pidlRoot", ctypes.c_void_p), ("pszDisplayName", w.LPWSTR),
                    ("lpszTitle", w.LPCWSTR), ("ulFlags", w.UINT), ("lpfn", ctypes.c_void_p),
                    ("lParam", w.LPARAM), ("iImage", ctypes.c_int)]

    browse_cb = ctypes.WINFUNCTYPE(ctypes.c_int, w.HWND, w.UINT, w.LPARAM, w.LPARAM)
    start_buf = ctypes.create_unicode_buffer(str(start or ""))

    def on_event(hwnd, msg, _lparam, data):
        if msg == 1 and start:  # BFFM_INITIALIZED: select the start folder
            ctypes.windll.user32.SendMessageW(hwnd, _WM_USER + 103, 1, data)  # BFFM_SETSELECTIONW
        return 0

    keep = browse_cb(on_event)
    ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
    ole32.CoInitialize(None)
    name = ctypes.create_unicode_buffer(260)
    info = BROWSEINFOW(None, None, ctypes.cast(name, w.LPWSTR), title, 0x1 | 0x10 | 0x40,  # FS dirs, edit box, new UI
                       ctypes.cast(keep, ctypes.c_void_p), ctypes.cast(start_buf, ctypes.c_void_p).value or 0, 0)
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
    if not pidl:
        return None
    path = ctypes.create_unicode_buffer(32768)
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, w.LPWSTR]
    ok = shell32.SHGetPathFromIDListW(pidl, path)
    ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
    return Path(path.value) if ok and path.value else None


def run_with_progress(main: str, content: str, work: Callable[[Callable[[int, int], None]], object]):
    """Run ``work(progress)`` on a thread while a dialog shows a progress bar; returns its result or raises its
    error. The dialog can't be closed until the work is done. Without TaskDialog, the work just runs."""
    if not available():
        return work(lambda done, total: None)
    state: dict = {"done": 0, "total": 1, "finished": False, "result": None, "error": None}

    def runner() -> None:
        try:
            state["result"] = work(lambda done, total: state.update(done=done, total=max(total, 1)))
        except BaseException as exc:  # noqa: BLE001 - handed back to the caller below
            state["error"] = exc
        state["finished"] = True

    thread = threading.Thread(target=runner, daemon=True)

    def callback(hwnd, msg, wparam, _lparam, _data):
        if msg == TDN_CREATED:
            ctypes.windll.user32.SendMessageW(hwnd, TDM_ENABLE_BUTTON, IDOK, 0)
            thread.start()
        elif msg == TDN_TIMER:
            pct = int(100 * state["done"] / state["total"])
            ctypes.windll.user32.SendMessageW(hwnd, TDM_SET_PROGRESS_BAR_POS, min(pct, 100), 0)
            if state["finished"]:
                ctypes.windll.user32.SendMessageW(hwnd, TDM_ENABLE_BUTTON, IDOK, 1)
                ctypes.windll.user32.PostMessageW(hwnd, TDM_CLICK_BUTTON, IDOK, 0)
        elif msg == TDN_BUTTON_CLICKED and not state["finished"]:
            return 1  # S_FALSE: keep the dialog open until the work is done
        return 0

    _show(main, content, common=TDCBF_OK, flags=TDF_SHOW_PROGRESS_BAR | TDF_CALLBACK_TIMER, callback=callback)
    thread.join()
    if state["error"] is not None:
        raise state["error"]
    return state["result"]


def finished(text: str, main: str = "Leonida V is installed") -> bool:
    """The last page. True when the person clicked "Start Leonida V"."""
    try:
        pressed, _ = _show(main, text, buttons=[(BTN_START, "Start Leonida V")], common=TDCBF_CLOSE, icon=ICON_INFO,
                           default=BTN_START, flags=TDF_ALLOW_DIALOG_CANCELLATION)
        return pressed == BTN_START
    except OSError:
        return _message_box(f"{main}\n\n{text}\n\nStart Leonida V now?", 0x4 | 0x40) == IDYES


def uninstall_main(argv: list[str]) -> int:
    """``LeonidaV.exe --uninstall [--silent] [--delete-state] [--delete-downloads]`` (Apps & features). It asks
    before touching State or Downloads (default: keep both); the game is never touched."""
    from . import winsetup

    silent = "--silent" in argv or "/S" in argv
    reg = winsetup.registered()
    if not reg:
        if not silent:
            message("Leonida V isn't installed for this Windows user, so there's nothing to remove.")
        return 1
    data = Path(str(reg.get("DataDir") or winsetup.default_data_dir()))
    delete_state, delete_downloads = "--delete-state" in argv, "--delete-downloads" in argv
    if not silent:
        _dpi_aware()
        if not ask_yes_no("Mods Leonida installed stay in your game. To take them out too, choose No, start "
                          "Leonida V and use Manage > Uninstall everything first.\n\nYour game itself is never "
                          "touched.", main="Remove Leonida V from this PC?", yes="Remove Leonida V", no="No"):
            return 1
        if (data / "State").exists():
            delete_state = ask_yes_no(
                f"{data / 'State'}\n\nSettings, the install log and the backups Leonida needs to undo the mods "
                "it installed. Keep it if mods are still installed, or if you'll use Leonida again.",
                main="Also delete your Leonida data (State)?", yes="Delete it", no="Keep it")
        if (data / "Downloads").exists():
            delete_downloads = ask_yes_no(
                f"{data / 'Downloads'}\n\nThe mods' own files you downloaded. Keeping them saves downloading "
                "them again.", main="Also delete the downloaded mod files?", yes="Delete them", no="Keep them")
    try:
        res = winsetup.uninstall(delete_state, delete_downloads)
    except winsetup.SetupError as exc:
        if not silent:
            message(str(exc), error=True)
        return 1
    if not silent:
        kept = "\n".join(f"Kept: {k}" for k in res.kept)
        message("Leonida V is removed." + (f"\n\n{kept}" if kept else ""), main="Done")
    return 0
