"""What a player needs before and while playing, from the manifest (never typed into the GUI):

* ``keys(session)``: the keys of the selected mods (hotkeys.json, after the user's overrides and the values Leonida
  locks in the mods' own settings files), each marked when Leonida moved it from the mod's default;
* ``before_play(session)``: the in-game steps the selected mods need (a mod's ``beforePlay`` list when the manifest
  has one, else its by-hand steps that happen in the game: "In the game: …", "In story mode, …", "Set GTA V's …");
* ``screen_type()``: GTA V's Screen Type from its settings.xml (Documents), to check "Windowed Borderless".

Stdlib only.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

IN_GAME = re.compile(r"^(In the game\b|In story mode\b|Set GTA V's\b)", re.I)
SETTINGS_DIRS = ("GTAV Enhanced", "GTA V Enhanced", "GTA V")
SCREEN_TYPES = {"0": "fullscreen", "1": "windowed", "2": "borderless"}


_VK = {8: "Backspace", 9: "Tab", 13: "Enter", 16: "Shift", 17: "Ctrl", 18: "Alt", 20: "Caps Lock", 27: "Esc",
       32: "Space", 33: "Page Up", 34: "Page Down", 35: "End", 36: "Home", 37: "Left", 38: "Up", 39: "Right",
       40: "Down", 45: "Insert", 46: "Delete", 160: "Left Shift", 161: "Right Shift", 162: "Left Ctrl",
       163: "Right Ctrl", 164: "Left Alt", 165: "Right Alt"}
_NAMES = {"lcontrolkey": "Left Ctrl", "rcontrolkey": "Right Ctrl", "leftctrl": "Left Ctrl", "rightctrl": "Right Ctrl",
          "lshiftkey": "Left Shift", "rshiftkey": "Right Shift", "leftshift": "Left Shift", "rightshift": "Right Shift",
          "lmenu": "Left Alt", "rmenu": "Right Alt", "leftalt": "Left Alt", "rightalt": "Right Alt", "menu": "Alt",
          "controlkey": "Ctrl", "shiftkey": "Shift", "next": "Page Down", "pagedown": "Page Down", "prior": "Page Up",
          "pageup": "Page Up", "return": "Enter", "capital": "Caps Lock", "capslock": "Caps Lock", "back": "Backspace",
          "escape": "Esc", "snapshot": "Print Screen", "printscreen": "Print Screen", "oemtilde": "~"}


def key_label(value) -> str:
    """A key as people say it: '119' (a Windows key code) -> 'F8', 'LControlKey' -> 'Left Ctrl', 'NumPad7' -> 'Num 7'."""
    text = str(value).strip()
    if text.isdigit():
        code = int(text)
        if 112 <= code <= 135:
            return f"F{code - 111}"
        if 48 <= code <= 57 or 65 <= code <= 90:
            return chr(code)
        if 96 <= code <= 105:
            return f"Num {code - 96}"
        return _VK.get(code, text)
    low = text.lower().replace(" ", "")
    if low in _NAMES:
        return _NAMES[low]
    m = re.fullmatch(r"numpad(\d)", low)
    if m:
        return f"Num {m.group(1)}"
    return text if len(text) > 1 else text.upper()


@dataclass(frozen=True)
class KeyRow:
    key: str
    action: str
    mod: str          # the mod's name
    moved: bool       # Leonida set it away from the mod's default (or the user changed it)
    rebindable: bool


def _where(where: str) -> tuple[str, str] | None:
    """'scripts\\\\GTA6Hud.ini [SettingsMenu] Key' -> ('scripts/gta6hud.ini', 'settingsmenu/key'); None when unclear."""
    m = re.match(r"\s*(\S+\.(?:ini|xml|json|cfg|txt))\s+(?:\[([^\]]+)\]\s*)?([\w.@]+)", where or "", re.I)
    if not m:
        return None
    file = m.group(1).replace("\\", "/").lower()
    key = f"{m.group(2)}/{m.group(3)}" if m.group(2) else m.group(3)
    return file, key.lower()


def keys(session, mods=None) -> list[KeyRow]:
    """The selected mods' keys, in the manifest's order (``mods``: defaults to the session's selection)."""
    mods = mods if mods is not None else session.mods()
    by_id = {m.id: m for m in mods}
    locked: dict[tuple[str, str], str] = {}
    for m in mods:
        try:
            wanted = session.settings_for(m)
        except Exception:  # noqa: BLE001 - keys must show even when a settings rule can't be read
            wanted = []
        for w in wanted:
            k = w.key.lower()
            locked[(w.file.replace("\\", "/").lower(), k)] = str(w.value)
            locked.setdefault((w.file.replace("\\", "/").lower(), k.split("/")[-1]), str(w.value))
    overrides = session.config.key_overrides or {}
    out = []
    for h in session.manifest.hotkeys:
        mod = by_id.get(h.get("mod"))
        if mod is None:
            continue
        key = h["key"]
        where = _where(h.get("where", ""))
        if where is not None:
            key = locked.get(where) or locked.get((where[0], where[1].split("/")[-1])) or key
        key = key_label(overrides.get(f"{mod.id}/{h['action']}", key))
        out.append(KeyRow(key, h["action"], mod.name, key.lower() != key_label(h["key"]).lower(),
                          bool(h.get("rebindable", True))))
    return out


def keys_text(rows: list[KeyRow]) -> str:
    """The list as plain text (Copy as text)."""
    width = max((len(r.key) for r in rows), default=3)
    return "\n".join(f"{r.key:<{width}}  {r.action} ({r.mod})" + ("  [moved by Leonida]" if r.moved else "")
                     for r in rows)


def before_play(session, mods=None) -> list[tuple[str, str]]:
    """[(mod name, step)] the selected mods need in the game, in install order, without repeats."""
    mods = mods if mods is not None else session.mods()
    out, seen = [], set()
    for m in mods:
        items = getattr(m, "before_play", None) or [s for s in (m.steps or ()) if IN_GAME.match(s.strip())]
        for s in items:
            if s not in seen:
                seen.add(s)
                out.append((m.name, s))
    return out


GPU_NAMES = {"rtx": "an NVIDIA RTX card", "rtx50": "an NVIDIA RTX 50-series card"}


def gpu_meets(need: str | None, gpu_names: list[str] | None) -> bool | None:
    """Does this PC's graphics card meet a ``requires.gpu`` value ("rtx", "rtx50")? None when the card is unknown
    (never block on a guess)."""
    if not need:
        return True
    if not gpu_names:
        return None
    if need == "rtx50":
        return any(re.search(r"RTX\s*50\d0", g, re.I) for g in gpu_names)
    if need == "rtx":
        return any(re.search(r"\bRTX\b", g, re.I) for g in gpu_names)
    return None


def gpu_note(need: str | None, gpu_names: list[str] | None) -> str:
    """"Needs an NVIDIA RTX card; you have a GTX 1070" when the card doesn't meet ``need``, else ""."""
    if gpu_meets(need, gpu_names) is not False:
        return ""
    card = re.sub(r"^(NVIDIA|AMD|Intel\(R\))\s+(GeForce\s+|Radeon\s+)?", "", gpu_names[0], flags=re.I)
    return f"Needs {GPU_NAMES.get(need, need)}; you have a {card}"


def settings_xml(home: Path | None = None) -> Path | None:
    """GTA V's settings.xml in Documents\\Rockstar Games (OneDrive's Documents too), None when not found."""
    home = Path(home) if home else Path(os.environ.get("USERPROFILE") or Path.home())
    for docs in (home / "Documents", home / "OneDrive" / "Documents"):
        for name in SETTINGS_DIRS:
            p = docs / "Rockstar Games" / name / "settings.xml"
            if p.is_file():
                return p
    return None


def screen_type(path: Path | None = None) -> str | None:
    """'fullscreen', 'windowed' or 'borderless' from settings.xml's <Windowed value=...>; None when unknown."""
    path = path or settings_xml()
    if path is None:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"<Windowed\s+value=\"(\d)\"", text, re.I)
    return SCREEN_TYPES.get(m.group(1)) if m else None
