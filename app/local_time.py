"""Render UTC timestamps in the operator-configured display timezone.

Every timestamp 4tExecutive stores (snapshot collected_at, per-field-group
freshness, rollup timestamps) is UTC. The `timezone` app setting
(app/app_settings.py, default "UTC") controls how those get *displayed* —
storage and computation stay UTC-only, only the Jinja `local_time` filter
(registered in app/__init__.py) converts for rendering.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "UTC"


def is_valid_timezone(tz_name: str) -> bool:
    """Return True if tz_name is a real IANA timezone (e.g. "America/Chicago")."""
    try:
        ZoneInfo(tz_name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def format_local(iso_ts: str | None, tz_name: str) -> str:
    """Format a UTC ISO-8601 timestamp string in tz_name as "YYYY-MM-DD HH:MM:SS TZ".

    Returns the original string unchanged if it can't be parsed, or if
    tz_name isn't a valid timezone -- displaying something is always better
    than a 500 from a malformed/unexpected timestamp string.
    """
    if not iso_ts:
        return iso_ts
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return iso_ts
    if dt.tzinfo is None:
        from datetime import UTC

        dt = dt.replace(tzinfo=UTC)
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
