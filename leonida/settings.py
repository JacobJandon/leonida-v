"""Locked, tuned mod settings (plan F5; the knowledge base is docs/SETTINGS.md).

A mod's ``settings`` in mods.json name the config files it reads and the keys Leonida manages::

    "settings": [
      {"file": "ScriptHookVDotNet.ini",                  # relative to the game folder
       "format": "ini",                                  # ini | xml | json (default: from the extension)
       "create": false,                                  # write the file if it doesn't exist yet (default: skip)
       "keys": {
         "ReloadKeyBinding": {"value": "None", "whenSelected": {"enableallinteriors": "Insert"},
                              "why": "Enable All Interiors needs a reload key"},
         "ConsoleKeyBinding": "F4",                      # shorthand: just the value
         "Settings/PoolDensity": {"value": "1.00", "packs": {"showcase": "1.50"}, "variants": {"ultra": "2.00"}}}}]

Key paths: ini ``Section/Key`` (``Key`` alone = before the first section); xml ``Child/Sub`` (element text) or
``Child/@attr`` (relative to the root element); json ``a/b/c``. A modpacks.json variant may override values:
``"settings": {"<mod id>": {"<file>": {"<key>": value}}}``.

Which value is locked, highest first: the chosen variant's modpacks settings, the rule's ``variants[variant]``, the
first ``whenSelected`` mod that is selected, the rule's ``packs[pack]``, the rule's ``value``.

Leonida writes them while installing the mod (in the same logged step, so rollback restores the user's file) and
again on ``apply`` (variant switches; a new logged ``settings:<mod>`` step, no reinstall). ``drift`` lists keys whose
file value differs from the locked one; a key the user unlocked (``<state>/settings-unlocked.json``) is left alone.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

UNLOCK_FILE = "settings-unlocked.json"
FORMATS = ("ini", "xml", "json")


class SettingsError(ValueError):
    """A settings file can't be read or written as its format says."""


@dataclass(frozen=True)
class Wanted:
    mod: str
    file: str            # relative to the game folder, POSIX
    format: str
    key: str
    value: Any
    why: str = ""
    create: bool = False

    @property
    def label(self) -> str:
        return f"{self.file}: {self.key}"


@dataclass(frozen=True)
class Drift:
    wanted: Wanted
    have: str | None      # None = the key or the file isn't there

    def message(self) -> str:
        w = self.wanted
        have = "missing" if self.have is None else repr(self.have)
        why = f" ({w.why})" if w.why else ""
        return (f"{w.file}: {w.key} is {have}, but the locked value is {_text(w.value)!r}{why}. "
                f"`leonida settings apply` puts it back, or `leonida settings unlock {w.mod} \"{w.file}\" \"{w.key}\"` "
                "keeps your value.")


def format_of(file: str, declared: str | None = None) -> str:
    if declared:
        return declared
    ext = PurePosixPath(file).suffix.lower()
    return {".xml": "xml", ".meta": "xml", ".json": "json"}.get(ext, "ini")


def _text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def same(a: Any, b: Any) -> bool:
    """Values compared the way config files treat them: trimmed, case-insensitive, numbers by value."""
    if a is None or b is None:
        return a is b
    x, y = _text(a).strip(), _text(b).strip()
    try:
        return float(x) == float(y)
    except ValueError:
        return x.lower() == y.lower()


# --------------------------------------------------------------------------------------------- rules -> values
def rule_value(rule: Any, pack: str | None, variant: str | None, selected: set[str]) -> Any:
    if not isinstance(rule, dict):
        return rule
    if variant and variant in rule.get("variants", {}):
        return rule["variants"][variant]
    for other, value in rule.get("whenSelected", {}).items():
        if other in selected:
            return value
    if pack and pack in rule.get("packs", {}):
        return rule["packs"][pack]
    return rule.get("value")


def wanted_for(mod, pack: str | None = None, variant_obj=None, selected: set[str] | frozenset = frozenset(),
               unlocked: set[str] | frozenset = frozenset()) -> list[Wanted]:
    """The locked values of one mod for this pack / variant / selection, without the keys the user unlocked."""
    out: list[Wanted] = []
    variant = variant_obj.id if variant_obj is not None else None
    overrides = (variant_obj.settings.get(mod.id, {}) if variant_obj is not None else {}) or {}
    for spec in getattr(mod, "settings", ()) or ():
        file, fmt = spec["file"], format_of(spec["file"], spec.get("format"))
        file_over = overrides.get(file, {})
        for key, rule in spec["keys"].items():
            if unlock_key(mod.id, file, key) in unlocked:
                continue
            value = file_over[key] if key in file_over else rule_value(rule, pack, variant, set(selected))
            if value is None:
                continue
            why = rule.get("why", "") if isinstance(rule, dict) else ""
            out.append(Wanted(mod.id, file, fmt, key, value, why, bool(spec.get("create", False))))
    return out


# ----------------------------------------------------------------------------------------------- unlocking
def unlock_key(mod_id: str, file: str, key: str) -> str:
    return f"{mod_id}|{file}|{key}"


def unlocked(state: Path) -> set[str]:
    try:
        data = json.loads((Path(state) / UNLOCK_FILE).read_text(encoding="utf-8"))
        return {k for k, v in data.items() if v} if isinstance(data, dict) else set()
    except (OSError, ValueError):
        return set()


def set_unlocked(state: Path, mod_id: str, file: str, key: str, value: bool) -> None:
    p = Path(state) / UNLOCK_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    k = unlock_key(mod_id, file, key)
    if value:
        data[k] = True
    else:
        data.pop(k, None)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------------------------- file formats
def _decode(data: bytes) -> tuple[str, str, str]:
    """(text, encoding, newline) of a config file; keeps its BOM/encoding and line endings on write."""
    if data.startswith(b"\xef\xbb\xbf"):
        enc, text = "utf-8-sig", data[3:].decode("utf-8", errors="replace")
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        enc, text = "utf-16", data.decode("utf-16", errors="replace")
    else:
        enc, text = "utf-8", data.decode("utf-8", errors="replace")
    nl = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), enc, nl


def _encode(text: str, enc: str, nl: str) -> bytes:
    text = text.replace("\n", nl)
    if enc == "utf-8-sig":
        return b"\xef\xbb\xbf" + text.encode("utf-8")
    return text.encode(enc)


_SECTION = re.compile(r"^\s*\[(?P<name>[^\]]*)\]\s*$")
_ENTRY = re.compile(r"^(?P<lead>\s*)(?P<key>[^=;#\[\s][^=]*?)(?P<sep>\s*=\s*)(?P<value>.*?)\s*$")


def _ini_split(key: str) -> tuple[str | None, str]:
    if "/" in key:
        sec, k = key.split("/", 1)
        return sec, k
    return None, key


def ini_get(text: str, key: str) -> str | None:
    section, k = _ini_split(key)
    current = None
    for line in text.split("\n"):
        m = _SECTION.match(line)
        if m:
            current = m.group("name").strip()
            continue
        e = _ENTRY.match(line)
        if e and e.group("key").strip().lower() == k.lower() and \
                ((current or "").lower() == (section or "").lower()):
            return e.group("value")
    return None


def ini_set(text: str, key: str, value: Any) -> str:
    """``text`` with ``key`` set to ``value``: the line edited in place (spelling, spacing and comments kept), else
    added at the end of its section (the section is created at the end of the file if it's missing)."""
    section, k = _ini_split(key)
    lines = text.split("\n") if text else []
    current, last_in_section, section_seen = None, None, section is None
    for i, line in enumerate(lines):
        m = _SECTION.match(line)
        if m:
            current = m.group("name").strip()
            if section is not None and current.lower() == section.lower():
                section_seen, last_in_section = True, i
            continue
        in_section = (current or "").lower() == (section or "").lower()
        if in_section:
            if line.strip():
                last_in_section = i
            e = _ENTRY.match(line)
            if e and e.group("key").strip().lower() == k.lower():
                lines[i] = f"{e.group('lead')}{e.group('key')}{e.group('sep')}{_text(value)}"
                return "\n".join(lines)
    entry = f"{k}={_text(value)}"
    if section is None:  # before the first section
        first = next((i for i, ln in enumerate(lines) if _SECTION.match(ln)), len(lines))
        lines.insert(first, entry)
    elif section_seen and last_in_section is not None:
        lines.insert(last_in_section + 1, entry)
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", entry]
    out = "\n".join(lines)
    return out if out.endswith("\n") or not text.endswith("\n") else out


def _xml_target(root: ET.Element, key: str, create: bool):
    parts = [p for p in key.split("/") if p and p != "."]
    attr = parts.pop()[1:] if parts and parts[-1].startswith("@") else None
    node = root
    for part in parts:
        child = node.find(part)
        if child is None:
            if not create:
                return None, attr
            child = ET.SubElement(node, part)
        node = child
    return node, attr


def xml_get(text: str, key: str) -> str | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SettingsError(f"not valid XML: {exc}") from None
    node, attr = _xml_target(root, key, False)
    if node is None:
        return None
    return node.get(attr) if attr else (node.text or "").strip()


def xml_set(text: str, key: str, value: Any) -> str:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SettingsError(f"not valid XML: {exc}") from None
    node, attr = _xml_target(root, key, True)
    if attr:
        node.set(attr, _text(value))
    else:
        node.text = _text(value)
    decl = '<?xml version="1.0" encoding="UTF-8"?>\n' if text.lstrip().startswith("<?xml") else ""
    return decl + ET.tostring(root, encoding="unicode") + ("\n" if text.endswith("\n") else "")


def json_get(text: str, key: str) -> Any:
    try:
        node = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise SettingsError(f"not valid JSON: {exc}") from None
    for part in key.split("/"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def json_set(text: str, key: str, value: Any) -> str:
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise SettingsError(f"not valid JSON: {exc}") from None
    node = data
    parts = key.split("/")
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value
    return json.dumps(data, indent=2) + "\n"


def get_value(text: str, fmt: str, key: str) -> str | None:
    if fmt == "xml":
        return xml_get(text, key)
    if fmt == "json":
        v = json_get(text, key)
        return None if v is None else _text(v)
    return ini_get(text, key)


def set_value(text: str, fmt: str, key: str, value: Any) -> str:
    if fmt == "xml":
        return xml_set(text, key, value)
    if fmt == "json":
        return json_set(text, key, value)
    return ini_set(text, key, value)


def render(path: Path, wanted: list[Wanted]) -> bytes | None:
    """The file's new bytes with all ``wanted`` values of that file set, or None when nothing changes (or the file
    doesn't exist and may not be created)."""
    if not wanted:
        return None
    if path.is_file():
        text, enc, nl = _decode(path.read_bytes())
    elif any(w.create for w in wanted):
        text, enc, nl = ("<settings/>\n" if wanted[0].format == "xml" else ""), "utf-8", "\r\n"
    else:
        return None
    new = text
    for w in wanted:
        if not same(get_value(new, w.format, w.key), w.value):
            new = set_value(new, w.format, w.key, w.value)
    if new == text and path.is_file():
        return None
    return _encode(new, enc, nl)


def by_file(wanted: list[Wanted]) -> dict[str, list[Wanted]]:
    out: dict[str, list[Wanted]] = {}
    for w in wanted:
        out.setdefault(w.file, []).append(w)
    return out


def drift(game: Path, wanted: list[Wanted]) -> list[Drift]:
    """Locked keys whose value in the game folder differs (files that don't exist yet are skipped)."""
    out: list[Drift] = []
    for file, items in by_file(wanted).items():
        p = Path(game) / file
        if not p.is_file():
            continue
        try:
            text = _decode(p.read_bytes())[0]
        except OSError:
            continue
        for w in items:
            try:
                have = get_value(text, w.format, w.key)
            except SettingsError:
                have = None
            if not same(have, w.value):
                out.append(Drift(w, have))
    return out
