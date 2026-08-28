"""Widget RAG threshold resolution: WIDGET_CATALOG defaults, overridable by config/thresholds.json."""

from __future__ import annotations

from app.atomic_io import read_json
from app.config_paths import CONFIG_DIR

THRESHOLDS_PATH = CONFIG_DIR / "thresholds.json"


def get_thresholds(widget_type: str, catalog_default: dict | None) -> dict | None:
    """Return the RAG threshold spec for a widget type.

    config/thresholds.json (if present) is keyed by widget type and takes
    priority over WIDGET_CATALOG's own "rag" entry; a widget type with
    neither returns None (no RAG state — informational widget).
    """
    overrides = read_json(THRESHOLDS_PATH, default={})
    return overrides.get(widget_type, catalog_default)
