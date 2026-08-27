"""Predefined widget catalog and data lookup for the Dashboard tab."""

from __future__ import annotations

from app.metrics_db import get_latest
from app.sources import list_sources

WIDGET_CATALOG: dict[str, dict] = {
    "4thealth.hygiene_score": {
        "label": "Hygiene Score",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "hygiene_score",
        "default_size": "1x1",
    },
    "4thealth.version_compliance": {
        "label": "Device Version Compliance %",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "version_compliance_pct",
        "default_size": "1x1",
    },
    "4thealth.pending_config_diffs": {
        "label": "Pending Config Diffs",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "pending_config_diff_count",
        "default_size": "1x1",
    },
    "4thealth.last_backup_status": {
        "label": "Last Backup Status",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "last_backup_status",
        "default_size": "1x1",
    },
    "4thealth.firewall_online_count": {
        "label": "Firewalls Online",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_online_count",
        "default_size": "1x1",
    },
    "4thealth.firewall_managed_count": {
        "label": "Firewalls Managed",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_managed_count",
        "default_size": "1x1",
    },
    "4thealth.rule_count_total": {
        "label": "Total Rules",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "rule_count_total",
        "default_size": "1x1",
    },
    "4thealth.adom_count": {
        "label": "ADOMs Configured",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "adom_count",
        "default_size": "1x1",
    },
    "4tlog.faz_health": {
        "label": "FortiAnalyzer Health",
        "source_system": "4tlog",
        "metric_type": "summary",
        "field": "faz_health",
        "default_size": "2x1",
    },
    "4tlog.log_volume_trend": {
        "label": "Log Volume Trend",
        "source_system": "4tlog",
        "metric_type": "summary",
        "field": "log_volume_trend",
        "default_size": "2x2",
    },
}


def default_layout() -> list[dict]:
    """Auto-generated fallback shown when a user has no saved layout: one
    widget per catalog entry x each enabled source whose system matches, so
    the dashboard shows everything currently configured instead of being
    blank until someone builds a real per-user editor."""
    widgets = []
    for widget_type, entry in WIDGET_CATALOG.items():
        for source in list_sources():
            if source.get("system") == entry["source_system"] and source.get("enabled", True):
                widgets.append(
                    {
                        "type": widget_type,
                        "source_instance": source["id"],
                        "size": entry["default_size"],
                        "date_range": "30d",
                    }
                )
    return widgets


def get_widget_value(widget_instance: dict) -> dict | None:
    entry = WIDGET_CATALOG[widget_instance["type"]]
    latest = get_latest(widget_instance["source_instance"], entry["metric_type"])
    if latest is None:
        return None
    return {
        "value": latest["value"].get(entry["field"]),
        "collected_at": latest["collected_at"],
    }
