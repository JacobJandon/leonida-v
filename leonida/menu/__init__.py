"""LeonidaMenu, Leonida's own in-game menu (a Script Hook V .NET script; source: LeonidaMenu.cs next to this file).

It's a mod like the others: mods.json ``leonidamenu`` (tier core, so in every pack), installed by the Installer as
a logged step and rolled back like any mod. Its "download" is made by Leonida itself, never fetched:

    make_zip(dest_dir) -> <dest_dir>/LeonidaMenu-<version>.zip     (downloader.download, type "leonida")

The zip holds ``LeonidaMenu.3.cs`` (".3": Script Hook V .NET compiles it for API v3) and ``LeonidaMenu.ini``. It's
the same bytes on every PC for one Leonida version (fixed timestamps), so its SHA-256 is stable. The two values that
differ per PC are locked settings that Leonida writes into the ini: ``[Leonida] StateDir`` (``{state}``, where the
menu finds menu-model.json and leaves its requests) and ``[Keys] Open`` (F5, the player can pick another).
The bridge between the menu and Leonida is leonida/menubridge.py.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .. import __version__

SCRIPT_NAME = "LeonidaMenu.3.cs"
INI_NAME = "LeonidaMenu.ini"
SOURCE = Path(__file__).with_name("LeonidaMenu.cs")
ZIP_PREFIX = "LeonidaMenu-"
INI_TEXT = """; Leonida V's in-game menu. Leonida writes these two values (locked settings): change the key in Leonida, or
; in the menu itself (Mods > Leonida menu > Keys/Open).
[Leonida]
StateDir={state}

[Keys]
Open=F5
"""
_FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def script_text(version: str = __version__) -> str:
    return SOURCE.read_text(encoding="utf-8").replace("/*VERSION*/", version)


def zip_name(version: str = __version__) -> str:
    return f"{ZIP_PREFIX}{version}.zip"


def zip_bytes(version: str = __version__) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in ((SCRIPT_NAME, script_text(version)), (INI_NAME, INI_TEXT)):
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    return buf.getvalue()


def make_zip(dest_dir: Path, version: str = __version__) -> Path:
    """Write LeonidaMenu-<version>.zip into ``dest_dir`` (Downloads), unless an identical one is there."""
    dest = Path(dest_dir) / zip_name(version)
    data = zip_bytes(version)
    if dest.is_file() and dest.read_bytes() == data:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".zip.part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest
