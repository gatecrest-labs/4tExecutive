"""Trend Board: one row per (metric widget, source), grouped by domain,
sortable and filterable, with a CSV export sharing the same row-building
logic as the HTML page.

Unlike the old per-user dashboard, the board is a fixed, comprehensive view
(every WIDGET_CATALOG entry x each enabled matching source, same universe as
default_layout()'s fallback) — sort/filter replace manual widget placement.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from app.domains import DOMAINS
from app.metric_extract import by_adom_metric_key
from app.metrics_db import get_metric_latest_at_or_before
from app.thresholds import get_thresholds
from app.widgets import WIDGET_CATALOG, annotate, baseline_cutoff, default_layout, source_name

DOMAIN_ORDER: list[str] = list(DOMAINS)

# Presentation-only grouping for the board — distinct from app.domains'
# MEMBER_METRICS (which lists only the fleet-score *inputs* for the
# Scorecard). Every catalog widget not on 4texecutive (host metrics, shown
# on Admin > System instead) is assigned here so every board row has a
# group. A widget can display under a different domain here than it scores
# under in domains.py when that's the better fit for browsing.
WIDGET_DOMAIN: dict[str, str] = {
    "4thealth.firewall_online_count": "availability",
    "4thealth.firewall_managed_count": "availability",
    "4thealth.fleet_availability": "availability",
    "4thealth.pending_config_diffs": "availability",
    "4thealth.last_backup_status": "availability",
    "4thealth.adom_count": "availability",
    "4thealth.devices_out_of_sync": "availability",
    "4thealth.admin_changes_24h": "availability",
    "4thealth.hygiene_score": "posture",
    "4thealth.version_compliance": "posture",
    "4thealth.device_review_posture": "posture",
    "4thealth.rule_count_total": "hygiene",
    "4thealth.rule_hygiene": "hygiene",
    "4thealth.version_breakdown": "lifecycle",
    "4thealth.ai_usage_24h": "logging",
    "4tlog.faz_health": "logging",
    "4tlog.log_volume_trend": "logging",
    "4tlog.silent_devices": "logging",
}

_STATUS_ORDER = {"red": 0, "amber": 1, "green": 2, "gray": 3, None: 4}

CSV_FIELDS = ["Domain", "Metric", "Source", "Now", "Delta (selected)", "Delta (30d)", "Target", "As Of", "Status"]


def _unit_for(entry: dict) -> str | None:
    metric_key = entry.get("metric_key", entry["field"])
    return "%" if metric_key.endswith("_pct") else None


def _target_and_progress(entry: dict, thresholds: dict | None, value: float | None):
    direction = entry["direction"]
    if thresholds is None or direction not in ("higher", "lower") or value is None:
        return None, None
    green = thresholds.get("green")
    amber = thresholds.get("amber")
    if direction == "higher":
        if green is None or green <= 0:
            return green, None
        return green, max(0.0, min(1.0, value / green))
    if amber is None or amber <= 0:
        return green, None
    return green, max(0.0, min(1.0, 1 - value / amber))


def _delta_and_better_vs(source_id: str, metric_key: str, direction: str, now_value, window: str, now_dt: datetime):
    if now_value is None:
        return None, None
    cutoff_iso = baseline_cutoff(window, now_dt).strftime("%Y-%m-%dT%H:%M:%SZ")
    point = get_metric_latest_at_or_before(source_id, metric_key, cutoff_iso)
    if point is None:
        return None, None
    delta = round(now_value - point["value"], 2)
    better = None
    if direction == "higher":
        better = delta > 0
    elif direction == "lower":
        better = delta < 0
    return delta, better


def _build_row(
    widget: dict, *, compare_to: str, sparkline: str, now_dt: datetime, adom: str | None = None
) -> dict:
    widget_type = widget["type"]
    entry = WIDGET_CATALOG[widget_type]
    metric_key = entry.get("metric_key", entry["field"])
    effective_metric_key = metric_key
    if adom:
        effective_metric_key = by_adom_metric_key(metric_key, adom) or metric_key
    annotated = annotate(widget, with_data=True, compare_to=compare_to, sparkline=sparkline, adom=adom)
    data = annotated.get("data") or {}
    thresholds = get_thresholds(widget_type, entry.get("rag"))
    now_value = data.get("now")

    target, progress = _target_and_progress(entry, thresholds, now_value)
    delta_30d, better_30d = _delta_and_better_vs(
        widget["source_instance"], effective_metric_key, entry["direction"], now_value, "30d", now_dt
    )

    status = data.get("rag")
    if status is None and thresholds is None:
        status = "gray"

    domain = WIDGET_DOMAIN.get(widget_type)
    return {
        "widget_type": widget_type,
        "metric_key": metric_key,
        "domain": domain,
        "domain_label": DOMAINS[domain]["label"] if domain else "Other",
        "label": entry["label"],
        "description": entry["description"],
        "source_instance": widget["source_instance"],
        "source_name": source_name(widget["source_instance"]),
        "unit": _unit_for(entry),
        "now": now_value,
        "delta_compare_to": data.get("baseline_delta"),
        "better_compare_to": data.get("better"),
        "delta_30d": delta_30d,
        "better_30d": better_30d,
        "direction": entry["direction"],
        "series": data.get("series") or [],
        "target": target,
        "progress": progress,
        "status": status,
        "stale": bool(data.get("stale")),
        "collected_at": data.get("collected_at"),
        "adom_scoped": bool(adom) and effective_metric_key != metric_key,
    }


def _sort_key(sort: str):
    if sort == "delta":
        return lambda r: -(abs(r["delta_compare_to"]) if r["delta_compare_to"] is not None else -1)
    if sort == "name":
        return lambda r: r["label"].lower()
    return lambda r: (_STATUS_ORDER.get(r["status"], 4), r["label"].lower())


def build_rows(
    *,
    compare_to: str,
    sparkline: str,
    domain_filter: str | None = None,
    source_filter: str | None = None,
    sort: str = "status",
    now: datetime | None = None,
    adom: str | None = None,
) -> list[dict]:
    now_dt = now or datetime.now(UTC)
    rows = [
        _build_row(widget, compare_to=compare_to, sparkline=sparkline, now_dt=now_dt, adom=adom)
        for widget in default_layout()
        if widget["type"] in WIDGET_DOMAIN
    ]
    if domain_filter:
        rows = [r for r in rows if r["domain"] == domain_filter]
    if source_filter:
        rows = [r for r in rows if r["source_instance"] == source_filter]

    domain_index = {name: i for i, name in enumerate(DOMAIN_ORDER)}
    within_domain_key = _sort_key(sort)
    rows.sort(key=lambda r: (domain_index.get(r["domain"], len(DOMAIN_ORDER)), within_domain_key(r)))
    return rows


def rows_to_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "Domain": row["domain_label"],
                "Metric": row["label"],
                "Source": row["source_name"],
                "Now": row["now"],
                "Delta (selected)": row["delta_compare_to"],
                "Delta (30d)": row["delta_30d"],
                "Target": row["target"],
                "As Of": row["collected_at"],
                "Status": row["status"],
            }
        )
    return buffer.getvalue()
