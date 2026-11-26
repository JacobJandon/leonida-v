"""GTA V's own settings (``settings.xml`` in Documents) locked for the chosen pack, variant and PC.

The rules are data (``leonida/manifest/gamesettings.json``): each key of GTA's settings.xml may have a value per
variant, per PC (RAM, video memory, ray tracing, frame generation), per selected mod or per pack. They become the same
``settings.Wanted`` values the mods' locked settings use (mod id ``gta-settings``), so the installer writes them in a
logged step (the user's file is backed up first), rollback restores it, ``drift`` shows when the game or the player
changed one, and the player can unlock any key.

Rule order, highest first: the chosen variant (``variants``), the first matching PC condition (``pc``), the first
selected mod (``whenSelected``), the pack (``packs``), ``value``. No value: the key isn't locked.
PC conditions: ``ramBelowGB`` / ``ramAtLeastGB``, ``vramBelowGB`` / ``vramAtLeastGB``, ``rtx`` (an NVIDIA RTX card),
``frameGen`` (an RTX 40 or 50 card); an unknown fact never matches. ``editions`` limits a key to Enhanced or Legacy
(Legacy's settings.xml has no ray tracing or frame generation).

Read-only detection: total RAM (GlobalMemoryStatusEx), the graphics cards (detect.detect_gpus) and their video
memory (the display adapters' ``HardwareInformation.qwMemorySize`` in the registry).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from . import settings as S

MOD_ID = "gta-settings"
NAME = "GTA V settings"
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_PC_KEYS = {"ramBelowGB", "ramAtLeastGB", "vramBelowGB", "vramAtLeastGB", "rtx", "frameGen", "value"}


@dataclass(frozen=True)
class PC:
    """What the rules look at. None = unknown (no condition on it matches)."""
    ram_gb: float | None = None
    vram_gb: float | None = None
    gpus: tuple[str, ...] = ()

    @property
    def rtx(self) -> bool | None:
        return any("rtx" in g.lower() for g in self.gpus) if self.gpus else None

    @property
    def frame_gen(self) -> bool | None:
        if not self.gpus:
            return None
        return any(re.search(r"rtx\s*[45]0\d\d", g.lower()) for g in self.gpus)

    def describe(self) -> str:
        bits = []
        if self.ram_gb is not None:
            bits.append(f"{self.ram_gb:.0f} GB RAM")
        if self.gpus:
            bits.append(", ".join(self.gpus))
        if self.vram_gb is not None:
            bits.append(f"{self.vram_gb:.0f} GB video memory")
        return "; ".join(bits) or "unknown PC"


@dataclass
class Pseudo:
    """Stands in for a Mod where the installer needs one (step names, unlock keys)."""
    id: str = MOD_ID
    name: str = NAME
    settings: list = field(default_factory=list)


def load_rules(path: Path | None = None) -> dict:
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.loads(resources.files("leonida.manifest").joinpath("gamesettings.json").read_text(encoding="utf-8"))


def validate(rules: dict) -> None:
    """Raise ValueError for rules the engine can't use (tested against the bundled file)."""
    if set(rules.get("files", {})) - {"enhanced", "legacy"} or not rules.get("files"):
        raise ValueError("gamesettings: 'files' must map enhanced/legacy to a {documents}/... path")
    for ed, f in rules["files"].items():
        if not S.is_outside(f):
            raise ValueError(f"gamesettings: the {ed} file must start with {S.DOCUMENTS}/")
    for key, rule in rules.get("keys", {}).items():
        bad = set(rule) - {"value", "variants", "pc", "whenSelected", "packs", "why", "label", "editions"}
        if bad:
            raise ValueError(f"gamesettings: {key}: unknown {sorted(bad)}")
        for cond in rule.get("pc", []):
            if set(cond) - _PC_KEYS or "value" not in cond:
                raise ValueError(f"gamesettings: {key}: a pc condition needs known facts and a value")
        if not rule.get("why"):
            raise ValueError(f"gamesettings: {key}: say why")
    for tier in rules.get("gpuTiers", []):
        if set(tier.get("when", {})) - {"vramAtLeastGB", "vramBelowGB", "rtx"} or not tier.get("why"):
            raise ValueError(f"gamesettings: gpu tier {tier.get('id')}: bad 'when' or no 'why'")
        unknown = set(tier.get("values", {})) - set(rules.get("keys", {}))
        if unknown:
            raise ValueError(f"gamesettings: gpu tier {tier.get('id')}: unknown keys {sorted(unknown)}")
    tune = rules.get("tune", {})
    for step in tune.get("steps", []):
        bad_step = (step.get("key") not in rules.get("keys", {}) or len(step.get("values", [])) < 2
                    or step.get("cost") not in ("gpu", "vram", "ram"))
        if bad_step:
            raise ValueError(f"gamesettings: tune step {step.get('key')}: a known key, 2+ values, cost gpu|vram|ram")
    for key, values in tune.get("knownCrash", {}).items():
        if key not in rules.get("keys", {}) or not isinstance(values, list):
            raise ValueError(f"gamesettings: knownCrash {key}: a known key and a list of values")


def _pc_match(cond: dict, pc: PC) -> bool:
    checks = []
    if "ramBelowGB" in cond:
        checks.append(pc.ram_gb is not None and pc.ram_gb < cond["ramBelowGB"])
    if "ramAtLeastGB" in cond:
        checks.append(pc.ram_gb is not None and pc.ram_gb >= cond["ramAtLeastGB"])
    if "vramBelowGB" in cond:
        checks.append(pc.vram_gb is not None and pc.vram_gb < cond["vramBelowGB"])
    if "vramAtLeastGB" in cond:
        checks.append(pc.vram_gb is not None and pc.vram_gb >= cond["vramAtLeastGB"])
    if "rtx" in cond:
        checks.append(pc.rtx is not None and pc.rtx == cond["rtx"])
    if "frameGen" in cond:
        checks.append(pc.frame_gen is not None and pc.frame_gen == cond["frameGen"])
    return bool(checks) and all(checks)


def tier_for(pc: PC, rules: dict | None = None) -> dict | None:
    """The graphics card's tier (gpuTiers): the first whose 'when' the PC meets. Unknown video memory: none."""
    rules = rules or load_rules()
    if pc.vram_gb is None:
        return None
    for tier in rules.get("gpuTiers", []):
        w = tier.get("when", {})
        if "vramAtLeastGB" in w and pc.vram_gb < w["vramAtLeastGB"]:
            continue
        if "vramBelowGB" in w and pc.vram_gb >= w["vramBelowGB"]:
            continue
        if "rtx" in w and pc.rtx != w["rtx"]:
            continue
        return tier
    return None


def _value(rule: dict, pack: str | None, variant: str | None, selected: set[str], pc: PC,
           key: str = "", tier: dict | None = None, tuned: dict | None = None) -> tuple[str | None, str]:
    if tuned and key in tuned:
        return tuned[key], "tuned on this PC (leonida settings tune)"
    if variant and variant in rule.get("variants", {}):
        return rule["variants"][variant], f"variant {variant}"
    if tier and key in tier.get("values", {}):
        return tier["values"][key], f"your graphics card ({tier['id']} tier, {pc.describe()})"
    for cond in rule.get("pc", []):
        if _pc_match(cond, pc):
            return cond["value"], f"your PC ({pc.describe()})"
    for other, value in rule.get("whenSelected", {}).items():
        if other in selected:
            return value, f"pack: needed by {other}"
    if pack and pack in rule.get("packs", {}):
        return rule["packs"][pack], f"pack {pack}"
    if "value" in rule:
        return rule["value"], "Leonida"
    return None, ""


def wanted(edition: str, pack: str | None, variant: str | None, selected: set[str] | frozenset, pc: PC,
           unlocked: set[str] | frozenset = frozenset(), rules: dict | None = None,
           tuned: dict | None = None) -> list[S.Wanted]:
    """The locked GTA settings for this choice and PC (unlocked keys left out). ``tuned``: key -> value measured on
    this PC by `leonida settings tune` (they win over everything else)."""
    rules = rules or load_rules()
    tier = tier_for(pc, rules) if edition == "enhanced" else None
    file = rules["files"].get(edition)
    if not file:
        return []
    out = []
    for key, rule in rules["keys"].items():
        if edition not in rule.get("editions", (edition,)):
            continue
        if S.unlock_key(MOD_ID, file, key) in unlocked:
            continue
        value, source = _value(rule, pack, variant, set(selected), pc, key, tier, tuned)
        if value is None:
            continue
        why = rule["why"] + (f" [{rule['label']}]" if rule.get("label") else "")
        out.append(S.Wanted(MOD_ID, file, "xml", key, value, why, False, source))
    return out


# ------------------------------------------------------------------------------------------------- detection
def total_ram_gb() -> float | None:
    if os.name != "nt":
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
        except (ValueError, OSError, AttributeError):
            return None
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(st)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return st.ullTotalPhys / 2**30
    except (OSError, AttributeError):
        pass
    return None


def video_memory_gb() -> float | None:
    """The largest display adapter's video memory (registry; read-only)."""
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    best = 0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS) as cls:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(cls, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(cls, sub) as k:
                        val, _ = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")
                        if isinstance(val, bytes):
                            val = int.from_bytes(val[:8], "little")
                        best = max(best, int(val))
                except (OSError, ValueError, TypeError):
                    continue
    except OSError:
        return None
    return best / 2**30 if best else None


def detect_pc(gpus: list[str] | None = None) -> PC:
    from .detect import detect_gpus

    return PC(total_ram_gb(), video_memory_gb(), tuple(gpus if gpus is not None else detect_gpus()))


def suggest_variant(pack, pc: PC) -> str | None:
    """The variant the first-run setup preselects for this PC (None: the pack has no variants, or keep its default).
    RAM variants (the owner's pick): under 24 GB -> ram16, else ram32. Look variants: Ultra needs an RTX card with 12 GB
    or more; under 6 GB of video memory -> Performance; otherwise Balanced (the GTX 1070's 8 GB)."""
    ids = [v.id for v in getattr(pack, "variants", ())]
    if not ids:
        return None
    if {"ram16", "ram32"} <= set(ids):
        if pc.ram_gb is None:
            return None
        return "ram16" if pc.ram_gb < 24 else "ram32"
    if {"performance", "balanced", "ultra"} <= set(ids):
        if pc.vram_gb is None:
            return None
        if pc.vram_gb >= 12 and pc.rtx:
            return "ultra"
        return "performance" if pc.vram_gb < 6 else "balanced"
    return None
