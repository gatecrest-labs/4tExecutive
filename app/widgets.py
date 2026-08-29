"""Predefined widget catalog and data lookup for the Dashboard tab."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.metrics_db import get_history, get_latest
from app.sources import get_source, list_sources
from app.thresholds import get_thresholds


def _downsample(points: list[tuple[str, float]], max_points: int = 80) -> list[tuple[str, float]]:
    """Downsample a list of (label, value) tuples to at most max_points by averaging buckets.

    If the input has max_points or fewer points, returns unchanged.
    Otherwise, divides points into max_points buckets and returns one averaged point per bucket.
    Uses the label from the first point in each bucket.
    Averages are rounded to integers if all values in the bucket are integers, else to 2 decimals.
    """
    n = len(points)
    if n <= max_points:
        return points
    bucketed = []
    for i in range(max_points):
        start = (i * n) // max_points
        end = ((i + 1) * n) // max_points
        chunk = points[start:end]
        if not chunk:
            continue
        values = [v for _, v in chunk]
        avg = sum(values) / len(values)
        if all(isinstance(v, int) for v in values):
            avg = round(avg)
        else:
            avg = round(avg, 2)
        bucketed.append((chunk[0][0], avg))
    return bucketed


# Maps a widget type to the payload's per-field-group freshness key and the
# threshold (minutes) past which that group's data is considered stale --
# 2x the group's expected refresh interval, per design doc section 8.
_FIELD_GROUP_FRESHNESS: dict[str, tuple[str, int]] = {
    "4thealth.hygiene_score": ("hygiene_sweep_collected_at", 120),
    "4thealth.version_compliance": ("device_sweep_collected_at", 30),
    "4thealth.pending_config_diffs": ("device_sweep_collected_at", 30),
    "4thealth.fleet_availability": ("device_sweep_collected_at", 30),
    "4thealth.firewall_online_count": ("device_sweep_collected_at", 30),
    "4thealth.firewall_managed_count": ("device_sweep_collected_at", 30),
    "4thealth.rule_count_total": ("rule_count_collected_at", 120),
    "4thealth.rule_hygiene": ("hygiene_sweep_collected_at", 120),
    "4thealth.device_review_posture": ("device_review", 2880),
}


def _is_stale(value: dict, widget_type: str) -> bool | None:
    """Return whether the widget type's underlying field group is stale, or
    None if this widget type has no known field-group freshness key."""
    freshness_key = _FIELD_GROUP_FRESHNESS.get(widget_type)
    if freshness_key is None:
        return None
    key, threshold_minutes = freshness_key
    if key == "device_review":
        collected_at = (value.get("device_review") or {}).get("collected_at")
    else:
        collected_at = value.get(key)
    if not collected_at:
        return None
    try:
        collected_dt = datetime.fromisoformat(collected_at)
    except ValueError:
        return None
    age_minutes = (datetime.now(UTC) - collected_dt).total_seconds() / 60
    return age_minutes > threshold_minutes


WIDGET_CATALOG: dict[str, dict] = {
    "4thealth.hygiene_score": {
        "label": "Hygiene Score",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "hygiene_score",
        "default_size": "1x1",
        "rag": {"direction": "higher", "green": 90, "amber": 75},
    },
    "4thealth.version_compliance": {
        "label": "Device Version Compliance %",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "version_compliance_pct",
        "default_size": "1x1",
        "rag": {"direction": "higher", "green": 95, "amber": 85},
    },
    "4thealth.pending_config_diffs": {
        "label": "Pending Config Diffs",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "pending_config_diff_count",
        "default_size": "1x1",
        "rag": {"direction": "lower", "green": 0, "amber": 5},
    },
    "4thealth.last_backup_status": {
        "label": "App Config Backup",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "last_backup_status",
        "default_size": "1x1",
        "rag": {"direction": "string_ok"},
    },
    "4thealth.firewall_online_count": {
        "label": "Firewalls Online",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_online_count",
        "default_size": "1x1",
        "chart_type": "line",
    },
    "4thealth.firewall_managed_count": {
        "label": "Total Managed Firewalls",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_managed_count",
        "default_size": "1x1",
        "chart_type": "line",
    },
    "4thealth.fleet_availability": {
        "label": "Fleet Availability",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_online_count",
        "default_size": "1x1",
        "chart_type": "line",
        "rag": {"direction": "ratio", "green": 100, "amber": 90},
    },
    "4thealth.rule_count_total": {
        "label": "Total Rules",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "rule_count_total",
        "default_size": "1x1",
        "chart_type": "line",
    },
    "4thealth.adom_count": {
        "label": "ADOMs Configured",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "adom_count",
        "default_size": "1x1",
    },
    "4thealth.version_breakdown": {
        "label": "FortiOS Versions",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "version_breakdown",
        "default_size": "2x2",
        "chart_type": "bar",
    },
    "4thealth.device_review_posture": {
        "label": "Configuration Posture",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "device_review",
        "default_size": "2x2",
        "chart_type": "bar",
        "rag": {"direction": "higher", "green": 0, "amber": 0},
    },
    "4thealth.ai_usage_24h": {
        "label": "AI Usage (24h)",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "ai_usage_24h",
        "default_size": "2x2",
        "chart_type": "line",
    },
    "4thealth.rule_hygiene": {
        "label": "Rule Hygiene",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "rule_hygiene",
        "default_size": "2x2",
        "chart_type": "line",
    },
    "4texecutive.cpu_percent": {
        "label": "Host CPU",
        "source_system": "4texecutive",
        "metric_type": "summary",
        "field": "cpu_percent",
        "default_size": "1x1",
        "chart_type": "line",
    },
    "4texecutive.memory_percent": {
        "label": "Host Memory",
        "source_system": "4texecutive",
        "metric_type": "summary",
        "field": "memory_percent",
        "default_size": "1x1",
        "chart_type": "line",
    },
    "4texecutive.disk_percent": {
        "label": "Host Disk",
        "source_system": "4texecutive",
        "metric_type": "summary",
        "field": "disk_percent",
        "default_size": "1x1",
        "chart_type": "line",
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
    blank until someone builds a real per-user editor. Host metrics
    (4texecutive.*) are excluded — they live on the Admin > System page,
    not the executive dashboard.

    Three widgets are conditional. The AI usage widget is only included when
    the source's latest snapshot reports ai_enabled: true, since most 4thealth
    instances won't have AI turned on and an always-empty tile isn't useful
    default clutter. The Tier 2 rollup widgets (device_review_posture,
    rule_hygiene) are only included when the latest snapshot actually carries
    that rollup — a 4thealth+ release that hasn't shipped Tier 2 would
    otherwise get two tiles reading "No data yet" forever, changing its
    dashboard for the worse just because 4tExecutive upgraded.

    A user who manually saves a layout containing any of them still sees it
    regardless (falls back to "No data yet" like any other widget with a
    missing field) — these skips only affect the auto-generated default.
    """
    widgets = []
    for widget_type, entry in WIDGET_CATALOG.items():
        if widget_type == "4thealth.firewall_online_count":
            continue
        for source in list_sources():
            if source.get("system") != entry["source_system"] or not source.get("enabled", True):
                continue
            if widget_type == "4thealth.ai_usage_24h":
                latest = get_latest(source["id"], entry["metric_type"])
                if latest is None or not latest["value"].get("ai_enabled"):
                    continue
            elif widget_type in ("4thealth.device_review_posture", "4thealth.rule_hygiene"):
                latest = get_latest(source["id"], entry["metric_type"])
                if latest is None or latest["value"].get(entry["field"]) is None:
                    continue
            widgets.append(
                {
                    "type": widget_type,
                    "source_instance": source["id"],
                    "size": entry["default_size"],
                    "date_range": "30d",
                }
            )

    return widgets


def _rag_state(value, thresholds: dict) -> str | None:
    """Classify value as green/amber/red per a threshold spec, or None if unclassifiable."""
    if value is None:
        return None
    direction = thresholds["direction"]
    if direction == "string_ok":
        return "green" if isinstance(value, str) and value.strip().lower().startswith("ok") else "red"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    green = thresholds.get("green")
    amber = thresholds.get("amber")
    if direction in ("higher", "ratio"):
        if green is not None and value >= green:
            return "green"
        if amber is not None and value >= amber:
            return "amber"
        return "red"
    if direction == "lower":
        if green is not None and value <= green:
            return "green"
        if amber is not None and value <= amber:
            return "amber"
        return "red"
    return None


def _attach_rag(widget_type: str, entry: dict, result: dict, *, line_rag_value=None) -> dict:
    """Add a "rag" key to result when the widget type has RAG thresholds and a classifiable value.

    Reads the value to classify from result["value"] (get_widget_value shape)
    or, for line charts, line_rag_value — the caller's raw latest numeric
    reading from before any downsampling averaged it away, since a
    bucket-averaged point can mask (or fabricate) a threshold crossing that
    the actual latest snapshot doesn't show.
    """
    thresholds = get_thresholds(widget_type, entry.get("rag"))
    if thresholds is None:
        return result
    if "value" in result:
        value = result["value"]
    elif result.get("chart") == "line":
        value = line_rag_value
    else:
        return result
    result["rag"] = _rag_state(value, thresholds)
    return result


def get_widget_value(widget_instance: dict) -> dict | None:
    entry = WIDGET_CATALOG[widget_instance["type"]]
    latest = get_latest(widget_instance["source_instance"], entry["metric_type"])
    if latest is None:
        return None
    result = {
        "value": latest["value"].get(entry["field"]),
        "collected_at": latest["collected_at"],
    }
    stale = _is_stale(latest["value"], widget_instance["type"])
    if stale is not None:
        result["stale"] = stale
    return _attach_rag(widget_instance["type"], entry, result)


RANGES: dict[str, timedelta] = {
    "4h": timedelta(hours=4),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "14d": timedelta(days=14),
    "30d": timedelta(days=30),
}
DEFAULT_RANGE = "1d"


def _empty_bar(widget_type: str) -> dict:
    """No-data payload for a bar widget, carrying that widget's full key set.

    Every no-data path for a given widget type returns the same keys as its
    populated path, so callers never have to guess which of them is missing:
    eol_versions belongs to version_breakdown, top_failing_checks and
    rollup_collected_at to device_review_posture.
    """
    empty = {"chart": "bar", "data": {}, "collected_at": None}
    if widget_type == "4thealth.version_breakdown":
        empty["eol_versions"] = []
    elif widget_type == "4thealth.device_review_posture":
        empty["top_failing_checks"] = []
        empty["rollup_collected_at"] = None
    return empty


def get_widget_series(widget_instance: dict, range_key: str) -> dict | None:
    """Return chart-ready data for a widget, or fall back to get_widget_value.

    Widgets without a chart_type in the catalog return the same shape as
    get_widget_value. "bar" widgets always chart the latest snapshot
    (range_key is ignored). "line" widgets chart history within range_key,
    downsampled to at most 80 points via _downsample.
    """
    entry = WIDGET_CATALOG[widget_instance["type"]]
    chart_type = entry.get("chart_type")
    if chart_type is None:
        return get_widget_value(widget_instance)

    source_id = widget_instance["source_instance"]

    if chart_type == "bar":
        latest = get_latest(source_id, entry["metric_type"])
        if latest is None:
            return _attach_rag(
                widget_instance["type"], entry, _empty_bar(widget_instance["type"])
            )

        if widget_instance["type"] == "4thealth.device_review_posture":
            device_review = latest["value"].get("device_review")
            if not device_review:
                return _attach_rag(
                    widget_instance["type"], entry, _empty_bar(widget_instance["type"])
                )
            reviewed = device_review.get("devices_reviewed") or 0
            failing = device_review.get("devices_with_failures") or 0
            result = {
                "chart": "bar",
                "data": {"Passing": reviewed - failing, "Failing": failing},
                "top_failing_checks": device_review.get("top_failing_checks") or [],
                # collected_at is the 4tExecutive poll time, like every other
                # widget — the dashboard posture strip aggregates it to judge
                # poll freshness. The rollup's own timestamp is legitimately up
                # to 48h old by design, so it gets its own key instead.
                "collected_at": latest["collected_at"],
                "rollup_collected_at": device_review.get("collected_at"),
            }
            critical = (device_review.get("findings_by_severity") or {}).get("critical") or 0
            result["rag"] = "red" if critical > 0 else "green"
            return result

        raw = latest["value"].get(entry["field"]) or {}
        if widget_instance["type"] == "4thealth.version_breakdown":
            data = {}
            eol_versions = []
            for version, entry_value in raw.items():
                if isinstance(entry_value, dict):
                    count = entry_value.get("count")
                    eol = bool(entry_value.get("eol"))
                else:
                    count = entry_value
                    eol = False
                # Drop entries whose count isn't a real number — the bar_chart
                # macro divides by max(values), so a None or a string here
                # raises a Jinja TypeError that takes down the whole dashboard
                # route, not just this tile. Same numeric-safety idiom the line
                # chart path uses when filtering history points.
                if not isinstance(count, (int, float)) or isinstance(count, bool):
                    continue
                data[version] = count
                if eol:
                    eol_versions.append(version)
            return _attach_rag(
                widget_instance["type"],
                entry,
                {"chart": "bar", "data": data, "eol_versions": eol_versions, "collected_at": latest["collected_at"]},
            )

        return _attach_rag(
            widget_instance["type"],
            entry,
            {"chart": "bar", "data": raw, "collected_at": latest["collected_at"]},
        )

    range_delta = RANGES.get(range_key, RANGES[DEFAULT_RANGE])
    since = (datetime.now(UTC) - range_delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    history = get_history(source_id, entry["metric_type"], since)
    if not history:
        return _attach_rag(
            widget_instance["type"],
            entry,
            {
                "chart": "line",
                "points": [],
                "min": None,
                "max": None,
                "extra_label": None,
                "delta": None,
                "breakdown": None,
                "by_feature": None,
                "collected_at": None,
            },
        )

    extra_label = None
    breakdown = None
    by_feature = None
    if widget_instance["type"] == "4thealth.ai_usage_24h":
        points = [
            (h["collected_at"], (h["value"].get("ai_usage_24h") or {}).get("ai_connection_count_24h"))
            for h in history
        ]
        cost = (history[-1]["value"].get("ai_usage_24h") or {}).get("ai_estimated_cost_24h_usd")
        if cost is not None:
            extra_label = f"${cost:.2f} est. cost (24h)"
        by_feature = history[-1]["value"].get("ai_usage_by_feature")
    elif widget_instance["type"] == "4thealth.fleet_availability":
        points = []
        for h in history:
            online = h["value"].get("firewall_online_count")
            total = h["value"].get("firewall_managed_count")
            if isinstance(online, (int, float)) and isinstance(total, (int, float)) and total:
                points.append((h["collected_at"], round(online / total * 100, 1)))
        latest_online = history[-1]["value"].get("firewall_online_count")
        latest_total = history[-1]["value"].get("firewall_managed_count")
        if isinstance(latest_online, (int, float)) and isinstance(latest_total, (int, float)) and latest_total:
            extra_label = f"{latest_online} / {latest_total} ({round(latest_online / latest_total * 100)}%)"
    elif widget_instance["type"] == "4thealth.rule_hygiene":
        points = [
            (h["collected_at"], (h["value"].get("rule_hygiene") or {}).get("rule_findings_total"))
            for h in history
        ]
        breakdown = (history[-1]["value"].get("rule_hygiene") or {}).get("rule_findings_by_type")
    else:
        points = [(h["collected_at"], h["value"].get(entry["field"])) for h in history]

    points = [
        (t, v) for t, v in points if v is not None and isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    latest_numeric_value = points[-1][1] if points else None
    points = _downsample(points)
    values = [v for _, v in points]
    delta = round(values[-1] - values[0], 2) if len(values) >= 2 else None

    stale = _is_stale(history[-1]["value"], widget_instance["type"])
    result = {
        "chart": "line",
        "points": points,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "extra_label": extra_label,
        "delta": delta,
        "breakdown": breakdown,
        "by_feature": by_feature,
        "collected_at": history[-1]["collected_at"],
    }
    if stale is not None:
        result["stale"] = stale
    return _attach_rag(widget_instance["type"], entry, result, line_rag_value=latest_numeric_value)


def source_name(source_instance: str) -> str:
    source = get_source(source_instance)
    return source["name"] if source else source_instance


def annotate(widget: dict, *, with_data: bool, range_key: str = DEFAULT_RANGE) -> dict:
    entry = WIDGET_CATALOG[widget["type"]]
    annotated = {
        **widget,
        "label": entry["label"],
        "source_name": source_name(widget["source_instance"]),
    }
    if with_data:
        annotated["data"] = get_widget_series(widget, range_key)
    return annotated
