"""The CLI never crashes on characters the console's code page can't encode (1.0.0's self-update did on '→')."""
from __future__ import annotations

import io
import sys

from leonida import cli


def test_safe_console_replaces_unencodable_characters(monkeypatch):
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", out)
    cli._safe_console()
    print("1.0.0 → 1.0.1")
    out.flush()
    assert raw.getvalue().decode("cp1252").startswith("1.0.0 ? 1.0.1")


def test_safe_console_leaves_utf8_and_odd_streams_alone(monkeypatch):
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="utf-8", errors="strict")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", io.StringIO())  # no reconfigure(): must not raise
    cli._safe_console()
    print("→")
    out.flush()
    assert raw.getvalue().decode("utf-8").startswith("→")
    assert out.errors == "strict"
