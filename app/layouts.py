"""Per-user dashboard layout storage, validated against the widget catalog."""

from __future__ import annotations

from app.metrics_db import get_layout as _get_layout
from app.metrics_db import save_layout as _save_layout
from app.widgets import WIDGET_CATALOG


def get_layout(username: str) -> list[dict]:
    return _get_layout(username)


def save_layout(username: str, widgets: list[dict]) -> None:
    for widget in widgets:
        if widget["type"] not in WIDGET_CATALOG:
            raise ValueError(f"unknown widget type: {widget['type']}")
    _save_layout(username, widgets)
