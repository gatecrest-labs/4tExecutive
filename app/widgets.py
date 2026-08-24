"""Predefined widget catalog and data lookup for the Dashboard tab."""

from __future__ import annotations

from app.metrics_db import get_latest

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


def get_widget_value(widget_instance: dict) -> dict | None:
    entry = WIDGET_CATALOG[widget_instance["type"]]
    latest = get_latest(widget_instance["source_instance"], entry["metric_type"])
    if latest is None:
        return None
    return {
        "value": latest["value"].get(entry["field"]),
        "collected_at": latest["collected_at"],
    }
