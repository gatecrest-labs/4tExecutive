"""Simple key/value app settings backed by config/app_settings.json."""

from __future__ import annotations

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR

SETTINGS_PATH = CONFIG_DIR / "app_settings.json"


def get_setting(key: str, default=None):
    return read_json(SETTINGS_PATH, default={}).get(key, default)


def set_setting(key: str, value) -> None:
    settings = read_json(SETTINGS_PATH, default={})
    settings[key] = value
    atomic_write_json(SETTINGS_PATH, settings)
