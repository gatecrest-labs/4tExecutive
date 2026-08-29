"""Tests for local_time: rendering UTC timestamps in the configured display timezone."""

from __future__ import annotations

from app.local_time import format_local, is_valid_timezone


def test_is_valid_timezone_accepts_real_iana_name():
    assert is_valid_timezone("America/Chicago") is True


def test_is_valid_timezone_rejects_garbage():
    assert is_valid_timezone("Not/A_Real_Zone") is False


def test_is_valid_timezone_accepts_utc():
    assert is_valid_timezone("UTC") is True


def test_format_local_converts_to_target_timezone():
    # 2026-08-29T17:14:38Z is 12:14:38 CDT (UTC-5, daylight saving in August).
    result = format_local("2026-08-29T17:14:38Z", "America/Chicago")
    assert result == "2026-08-29 12:14:38 CDT"


def test_format_local_handles_offset_suffix_instead_of_z():
    result = format_local("2026-08-29T17:14:38+00:00", "America/Chicago")
    assert result == "2026-08-29 12:14:38 CDT"


def test_format_local_defaults_to_utc_display():
    result = format_local("2026-08-29T17:14:38Z", "UTC")
    assert result == "2026-08-29 17:14:38 UTC"


def test_format_local_falls_back_to_utc_for_invalid_timezone():
    result = format_local("2026-08-29T17:14:38Z", "Not/A_Real_Zone")
    assert result == "2026-08-29 17:14:38 UTC"


def test_format_local_returns_none_unchanged():
    assert format_local(None, "UTC") is None


def test_format_local_returns_unparseable_string_unchanged():
    assert format_local("not-a-timestamp", "UTC") == "not-a-timestamp"


def test_format_local_handles_microseconds_in_source_timestamp():
    result = format_local("2026-08-29T17:14:38.123456+00:00", "America/Chicago")
    assert result == "2026-08-29 12:14:38 CDT"
