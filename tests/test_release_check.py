"""build/check_release.py: the release job's last gate (asset list, checksums, the setup's payload, no CodeWalker)."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import check_release as C  # noqa: E402

V = "9.9.9"


class FakeReader:
    """Stands in for PyInstaller's CArchiveReader over the setup exe: a toc and extract()."""

    entries: dict[str, bytes] = {}

    def __init__(self, path):
        self.toc = dict.fromkeys(self.entries)

    def extract(self, name):
        return self.entries[name]


def make_dist(tmp: Path, win_extra: dict[str, bytes] | None = None, payload: bytes | None = None,
              setup_extra: dict[str, bytes] | None = None, sums_override: dict[str, str] | None = None) -> Path:
    dist = tmp / "dist"
    dist.mkdir()
    win = dist / f"LeonidaV-{V}-win64.zip"
    with zipfile.ZipFile(win, "w") as z:
        z.writestr("LeonidaV/LeonidaV.exe", "MZ")
        z.writestr("LeonidaV/leonida.exe", "MZ")
        z.writestr("LeonidaV/_internal/leonida/rpfhelper/Program.cs", "// ours")
        for name, data in (win_extra or {}).items():
            z.writestr(name, data)
    src = dist / f"leonida-v-{V}.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("leonida-v/pyproject.toml", "[project]")
        z.writestr("leonida-v/leonida/__init__.py", f'__version__ = "{V}"')
        z.writestr("leonida-v/build/codewalker/LeonidaRpf/Program.cs", "// ours")
    win_bytes = win.read_bytes()
    setup = dist / f"Leonida-V-Setup-{V}.exe"
    setup.write_bytes(b"MZ setup")
    inner = payload if payload is not None else win_bytes
    FakeReader.entries = {
        "struct": b"", "payload\\payload.json": json.dumps({"file": win.name, "version": V,
                                                           "sha256": hashlib.sha256(win_bytes).hexdigest()}).encode(),
        f"payload\\{win.name}": inner, **(setup_extra or {})}
    mods = json.loads((ROOT / "leonida" / "manifest" / "mods.json").read_text(encoding="utf-8"))
    (dist / "modpack.json").write_text(json.dumps({"version": mods["version"], "builds": {}}), encoding="utf-8")
    assets = [setup, win, src, dist / "modpack.json"]
    sums = {a.name: hashlib.sha256(a.read_bytes()).hexdigest() for a in assets}
    sums.update(sums_override or {})
    (dist / "SHA256SUMS.txt").write_text("".join(f"{h}  {n}\n" for n, h in sums.items()), encoding="utf-8")
    (dist / "release-assets.txt").write_text("".join(f"dist/{a.name}\n" for a in assets) + "dist/SHA256SUMS.txt\n",
                                             encoding="utf-8")
    return dist


@pytest.fixture(autouse=True)
def fake_reader(monkeypatch):
    pytest.importorskip("PyInstaller")
    import PyInstaller.archive.readers as readers

    monkeypatch.setattr(readers, "CArchiveReader", FakeReader)


def test_good_release_passes(tmp_path):
    assert C.check(make_dist(tmp_path), V) == []


@pytest.mark.parametrize("where", ["win", "setup", "payload"])
def test_any_codewalker_file_fails(tmp_path, where):
    bad = {"LeonidaV/tools/CodeWalker.Core.dll": b"x"}
    if where == "win":
        dist = make_dist(tmp_path, win_extra=bad)
        expect = f"in LeonidaV-{V}-win64.zip"
    elif where == "setup":
        dist = make_dist(tmp_path, setup_extra={"SharpDX.dll": b"x"})
        expect = f"in Leonida-V-Setup-{V}.exe:"
    else:
        other = tmp_path / "other.zip"
        with zipfile.ZipFile(other, "w") as z:
            z.writestr("LeonidaV/LeonidaV.exe", "MZ")
            z.writestr("LeonidaV/LeonidaRpf.exe", "MZ")
        dist = make_dist(tmp_path, payload=other.read_bytes())
        expect = "payload is not the released"   # a different zip inside the setup is caught first
    problems = C.check(dist, V)
    assert any(expect in p for p in problems), problems


def test_checksums_and_asset_list(tmp_path):
    dist = make_dist(tmp_path, sums_override={f"leonida-v-{V}.zip": "0" * 64})
    assert any("does not match" in p for p in C.check(dist, V))
    assert any("missing" in p for p in C.check(dist, "1.2.3"))  # names for another version: wrong list


def test_main_prints_and_fails(tmp_path, capsys):
    dist = make_dist(tmp_path, win_extra={"LeonidaV/SharpDX.Mathematics.dll": b"x"})
    import leonida

    real = leonida.__version__
    try:
        leonida.__version__ = V
        assert C.main([str(dist)]) == 1
    finally:
        leonida.__version__ = real
    out = capsys.readouterr().out
    assert "FAIL" in out and "SharpDX.Mathematics.dll" in out
