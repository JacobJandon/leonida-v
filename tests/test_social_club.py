"""Rockstar's Social Club check before a play test (leonida.detect.social_club_problem)."""

from __future__ import annotations

from leonida.detect import SOCIAL_CLUB_FILES, social_club_problem


def test_complete_social_club_is_fine(tmp_path):
    for f in SOCIAL_CLUB_FILES:
        (tmp_path / f).write_bytes(b"x")
    assert social_club_problem(tmp_path) is None


def test_empty_or_missing_social_club(tmp_path):
    """2026-11-27: after a restart the owner's Social Club folder was empty during Rockstar's own update, and the
    play test only said HANG."""
    msg = social_club_problem(tmp_path)
    assert msg and "isn't installed" in msg and "Rockstar Games Launcher" in msg
    assert "isn't installed" in social_club_problem(tmp_path / "nope")


def test_partly_missing_social_club(tmp_path):
    (tmp_path / "socialclub.dll").write_bytes(b"x")
    (tmp_path / "libcef.dll").write_bytes(b"x")
    assert "missing resources.pak" in social_club_problem(tmp_path)
