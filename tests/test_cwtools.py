"""CodeWalker at first use (leonida/cwtools.py), the release's no-CodeWalker guard, and the localhost-only GitHub
API override. Fakes only: nothing is downloaded and no .NET build runs."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

from leonida import cwtools
from leonida.cli import main

ROOT = Path(__file__).resolve().parent.parent


def source_zip(path: Path, extra: dict[str, bytes] | None = None) -> Path:
    files = {"CodeWalker.Core/CodeWalker.Core.csproj": b"<Project/>", "CodeWalker.Core/GameFiles/RpfFile.cs": b"// x",
             "CodeWalker/Program.cs": b"// the app itself: not unpacked", "Notice.txt": b"notice", **(extra or {})}
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(f"CodeWalker-{cwtools.COMMIT}/{name}", data)
    return path


class Fakes:
    def __init__(self, tmp: Path):
        self.tmp, self.fetched, self.ran = tmp, [], []

    def fetch(self, url, dest, progress):
        self.fetched.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".ps1"):
            dest.write_text("# dotnet-install", encoding="utf-8")
        else:
            source_zip(dest)
        return dest

    def run(self, cmd, env):
        self.ran.append(cmd)
        if cmd[0] == "powershell":                     # the SDK script: makes dotnet.exe
            out = Path(cmd[cmd.index("-InstallDir") + 1])
            (out / "dotnet.exe").write_bytes(b"MZ")
            return
        out = Path(cmd[cmd.index("-o") + 1])           # dotnet build -o <staged>
        out.mkdir(parents=True, exist_ok=True)
        for name in ("LeonidaRpf.exe", "CodeWalker.Core.dll", "SharpDX.dll", "LeonidaRpf.pdb"):
            (out / name).write_bytes(name.encode())


def test_prepare_fetches_records_and_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(cwtools, "find_sdk", lambda: None)
    f = Fakes(tmp_path)
    state = tmp_path / "state"
    said = []
    exe = cwtools.prepare(state, fetch=f.fetch, run=f.run, say=said.append)
    assert exe == state / "tools" / "LeonidaRpf" / "LeonidaRpf.exe" and exe.is_file()
    assert f.fetched == [cwtools.SOURCE_URL.format(commit=cwtools.COMMIT), cwtools.DOTNET_INSTALL]
    src = state / "tools" / "CodeWalker" / "src"
    assert (src / "CodeWalker.Core" / "GameFiles" / "RpfFile.cs").is_file() and not (src / "CodeWalker").exists()
    record = json.loads((state / "tools" / "CodeWalker" / "source.json").read_text())
    zip_path = state / "tools" / "CodeWalker" / record["file"]
    assert record["author"] == "dexyfex" and record["commit"] == cwtools.COMMIT
    assert record["sha256"] == cwtools.sha256(zip_path) and record["size"] == zip_path.stat().st_size
    build_cmd = f.ran[-1]
    assert build_cmd[1] == "build" and f"-p:CodeWalkerSrc={src.resolve()}" in build_cmd
    helper = json.loads((state / "tools" / "LeonidaRpf" / "helper.json").read_text())
    assert helper["codewalker_commit"] == cwtools.COMMIT and helper["codewalker_source_sha256"] == record["sha256"]
    assert set(helper["files"]) == {"LeonidaRpf.exe", "CodeWalker.Core.dll", "SharpDX.dll"}  # .pdb dropped
    assert any("SHA-256" in s for s in said)
    lines = cwtools.describe(state)
    assert lines[0].startswith("RPF helper: ") and any(record["sha256"] in line for line in lines)
    # a second run: source and SDK are there, only the build runs again
    f2 = Fakes(tmp_path)
    cwtools.prepare(state, fetch=f2.fetch, run=f2.run, say=said.append)
    assert f2.fetched == [] and len(f2.ran) == 1


def test_plan_says_what_would_be_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(cwtools, "find_sdk", lambda: None)
    lines = cwtools.plan(tmp_path)
    assert "dexyfex" in lines[0] and cwtools.COMMIT[:10] in lines[0] and "github.com/dexyfex" in lines[0]
    assert any("Microsoft's .NET 8 SDK" in line for line in lines) and any("nuget.org" in line for line in lines)
    monkeypatch.setattr(cwtools, "find_sdk", lambda: Path("dotnet.exe"))
    assert not any(".NET 8 SDK" in line for line in cwtools.plan(tmp_path))


def test_unsafe_or_wrong_source_zip_is_refused(tmp_path):
    f = Fakes(tmp_path)

    def evil(url, dest, progress):
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w") as z:
            z.writestr("top/CodeWalker.Core/../../../escape.txt", "x")
        return dest

    with pytest.raises(cwtools.ToolsError, match="Unsafe path"):
        cwtools.fetch_source(tmp_path / "s", fetch=evil, say=lambda m: None)

    def empty(url, dest, progress):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"not a zip")
        return dest

    with pytest.raises(cwtools.ToolsError, match="not a zip"):
        cwtools.fetch_source(tmp_path / "s2", fetch=empty, say=lambda m: None)
    assert f.fetched == []


def test_build_without_output_fails_cleanly(tmp_path):
    with pytest.raises(cwtools.ToolsError, match="LeonidaRpf.exe is missing"):
        cwtools.build(tmp_path, Path("dotnet.exe"), tmp_path / "src", run=lambda cmd, env: None, say=lambda m: None)
    assert not (tmp_path / "tools" / "LeonidaRpf.new").exists()


def test_the_helper_source_ships_without_codewalker():
    project = cwtools.project_dir()
    assert {p.name for p in project.iterdir() if p.is_file()} >= set(cwtools.PROJECT_FILES)
    spec = (ROOT / "build" / "leonida.spec").read_text(encoding="utf-8")
    assert '"leonida/rpfhelper"' in spec and "CodeWalker.Core.dll" not in spec


def test_cli_tools_status_and_asks_first(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cwtools, "find_sdk", lambda: None)
    st = ["--state-dir", str(tmp_path / "st")]
    assert main([*st, "tools", "codewalker", "--status"]) == 0
    assert "RPF helper: not built yet" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda q: "n")
    monkeypatch.setattr(cwtools, "prepare", lambda *a, **k: pytest.fail("must not download without a yes"))
    assert main([*st, "tools", "codewalker"]) == 1
    out = capsys.readouterr().out
    assert "doesn't ship CodeWalker" in out and "dexyfex" in out and "Nothing was downloaded." in out


# ------------------------------------------------------------------------------------ release guard / API
def test_release_refuses_codewalker_files(tmp_path):
    sys.path.insert(0, str(ROOT / "build"))
    import build_exe

    ok = tmp_path / "ok.zip"
    with zipfile.ZipFile(ok, "w") as z:
        z.writestr("leonida-v/build/codewalker/LeonidaRpf/Program.cs", "// ours")
        z.writestr("LeonidaV/_internal/leonida/rpfhelper/LeonidaRpf.csproj", "<Project/>")
    build_exe.check_no_codewalker(ok)
    for bad_name in ("LeonidaV/CodeWalker.Core.dll", "leonida-v/build/codewalker/bin/LeonidaRpf.exe",
                     "x/SharpDX.dll", "leonida-v/build/codewalker/.cw-src/Notice.txt"):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr(bad_name, "x")
        with pytest.raises(SystemExit, match="CodeWalker"):
            build_exe.check_no_codewalker(bad)
    assert any(__import__("re").fullmatch(p, "Leonida-V-Setup-1.0.0rc2.exe") for p in build_exe.ASSET_PATTERNS)


def test_github_api_override_only_for_localhost(monkeypatch):
    from leonida import downloader  # the module isn't reloaded: that would make new exception classes

    monkeypatch.setenv("LEONIDA_GITHUB_API", "http://127.0.0.1:8123/api/")
    assert downloader._github_api() == "http://127.0.0.1:8123/api"
    monkeypatch.setenv("LEONIDA_GITHUB_API", "https://not-github.example/api")
    assert downloader._github_api() == "https://api.github.com"
    monkeypatch.delenv("LEONIDA_GITHUB_API")
    assert downloader._github_api() == "https://api.github.com"


def test_find_and_get_sdk(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setattr(cwtools.shutil, "which", lambda name: None)
    assert cwtools.find_sdk() is None
    monkeypatch.setattr(cwtools.shutil, "which", lambda name: "C:/dotnet/dotnet.exe")

    def sdks(text):
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=text, stderr="")

    monkeypatch.setattr(cwtools.subprocess, "run", sdks("6.0.400 [C:\\dotnet\\sdk]\n"))
    assert cwtools.find_sdk() is None                                   # too old
    monkeypatch.setattr(cwtools.subprocess, "run", sdks("6.0.400 [x]\n8.0.404 [x]\n"))
    assert cwtools.find_sdk() == Path("C:/dotnet/dotnet.exe")

    def broken(*a, **k):
        raise OSError("no")

    monkeypatch.setattr(cwtools.subprocess, "run", broken)
    assert cwtools.find_sdk() is None
    assert cwtools.get_sdk(tmp_path, dotnet=Path("X:/d.exe")) == Path("X:/d.exe")
    monkeypatch.setattr(cwtools, "find_sdk", lambda: Path("C:/dotnet/dotnet.exe"))
    assert cwtools.get_sdk(tmp_path) == Path("C:/dotnet/dotnet.exe")
    monkeypatch.setattr(cwtools, "find_sdk", lambda: None)
    local = tmp_path / "tools" / "dotnet" / "dotnet.exe"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"MZ")
    assert cwtools.get_sdk(tmp_path) == local                          # the portable one from an earlier run
    assert cwtools.describe(tmp_path / "empty") == ["RPF helper: not built yet"]
