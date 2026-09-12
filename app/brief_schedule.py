"""Weekly Executive Brief send schedule config.

Stored at CONFIG_DIR / "brief_schedule.json", same atomic-read/write
convention as app.sources / app.smtp_client. Consumed once at scheduler
startup by app.collector.init_scheduler -- changing this config takes
effect on the next app restart (this repo's scheduler doesn't hot-reload
any of its interval/cron jobs, matching e.g. poll_all's fixed 1-minute
interval).
"""

from __future__ import annotations

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR

SCHEDULE_CONFIG_PATH = CONFIG_DIR / "brief_schedule.json"

DEFAULTS: dict = {
    "weekday": 0,  # 0=Monday .. 6=Sunday, matching APScheduler's CronTrigger day_of_week ints
    "hour": 8,
    "recipients": "",
    "enabled": False,
}


def get_brief_schedule_config() -> dict:
    data = read_json(SCHEDULE_CONFIG_PATH, default={})
    return {**DEFAULTS, **data}


def save_brief_schedule_config(cfg: dict) -> None:
    atomic_write_json(SCHEDULE_CONFIG_PATH, {**DEFAULTS, **cfg})


def _parse_recipients(recipients: str) -> list[str]:
    # Empty entries after stripping (e.g. a trailing/double comma) are
    # silently dropped rather than rejected -- this mirrors
    # app.smtp_client._parse_recipients's own comma-split convention, and
    # keeps a stray "a@b.com,,c@d.com" from being flagged as invalid when
    # every non-empty entry in it is actually fine.
    return [addr.strip() for addr in recipients.split(",") if addr.strip()]


def validate_schedule_config(cfg: dict) -> list[str]:
    """Return a list of human-readable error messages; empty list = valid."""
    errors: list[str] = []

    weekday = cfg.get("weekday")
    try:
        weekday_int = int(weekday)
    except (TypeError, ValueError):
        errors.append(f'"weekday" must be an integer 0-6 (Monday-Sunday), got {weekday!r}.')
    else:
        if not 0 <= weekday_int <= 6:
            errors.append(f'"weekday" must be 0-6 (Monday-Sunday), got {weekday_int}.')

    hour = cfg.get("hour")
    try:
        hour_int = int(hour)
    except (TypeError, ValueError):
        errors.append(f'"hour" must be an integer 0-23, got {hour!r}.')
    else:
        if not 0 <= hour_int <= 23:
            errors.append(f'"hour" must be 0-23, got {hour_int}.')

    recipients_raw = cfg.get("recipients") or ""
    recipients = _parse_recipients(recipients_raw)
    malformed = [addr for addr in recipients if "@" not in addr]
    if malformed:
        errors.append(f"Malformed recipient address(es): {', '.join(malformed)}.")

    if cfg.get("enabled") and not recipients:
        errors.append("At least one valid recipient is required when the schedule is enabled.")

    return errors
