"""Predefined widget catalog and data lookup for the Dashboard tab."""

from __future__ import annotations

import math
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
    # 40 = 2x the realistic worst-case age: 4tlog's 5-minute logstats collection
    # interval plus 4tExecutive's own default 15-minute poll interval (this
    # timestamp only advances when 4tExecutive polls the source), not just
    # 4tlog's internal collection cadence.
    "4tlog.log_volume_trend": ("log_stats_collected_at", 40),
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
        "description": "Overall configuration hygiene score across the managed fleet, from the latest hygiene sweep.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "hygiene_score",
        # Taller than 1x1 so the gauge (arc + needle + value) has room to
        # render legibly instead of being squashed by the standard card height.
        "default_size": "1x2",
        "rag": {"direction": "higher", "green": 90, "amber": 75},
    },
    "4thealth.version_compliance": {
        "label": "Device Version Compliance %",
        "description": "Percentage of managed firewalls running an approved, non-EOL FortiOS version.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "version_compliance_pct",
        "default_size": "1x2",
        "rag": {"direction": "higher", "green": 95, "amber": 85},
    },
    "4thealth.pending_config_diffs": {
        "label": "Pending Config Diffs",
        "description": "Number of devices with configuration changes detected but not yet reviewed.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "pending_config_diff_count",
        "default_size": "1x1",
        "rag": {"direction": "lower", "green": 0, "amber": 5},
    },
    "4thealth.last_backup_status": {
        "label": "App Config Backup",
        "description": "Result of the most recent 4thealth-plus application configuration backup.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "last_backup_status",
        "default_size": "1x1",
        "rag": {"direction": "string_ok"},
    },
    "4thealth.firewall_online_count": {
        "label": "Firewalls Online",
        "description": "Count of managed firewalls currently reachable and reporting in.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_online_count",
        "default_size": "1x1",
        "chart_type": "line",
    },
    "4thealth.firewall_managed_count": {
        "label": "Total Managed Firewalls",
        "description": "Total number of firewalls under management, tracked over the last 30 days.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_managed_count",
        # Taller than 1x1 — a 30-day line chart plus its range/delta/updated
        # labels doesn't fit in a standard 120px-tall card without the SVG
        # collapsing to 0 height.
        "default_size": "1x2",
        "chart_type": "line",
        "fixed_range": "30d",
    },
    "4thealth.fleet_availability": {
        "label": "Fleet Availability",
        "description": "Share of managed firewalls online, as a percentage of the total fleet.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_online_count",
        "default_size": "1x1",
        "chart_type": "line",
        "rag": {"direction": "ratio", "green": 100, "amber": 90},
    },
    "4thealth.rule_count_total": {
        "label": "Total Rules",
        "description": "Total firewall policy rule count across the managed fleet, tracked over the last 30 days.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "rule_count_total",
        # Same reasoning as firewall_managed_count above.
        "default_size": "1x2",
        "chart_type": "line",
        "fixed_range": "30d",
    },
    "4thealth.adom_count": {
        "label": "ADOMs Configured",
        "description": "Number of Administrative Domains configured on the managed FortiManager.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "adom_count",
        "default_size": "1x1",
    },
    "4thealth.version_breakdown": {
        "label": "FortiOS Versions",
        "description": "Distribution of FortiOS firmware versions across the managed fleet; EOL versions highlighted.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "version_breakdown",
        "default_size": "2x2",
        "chart_type": "bar",
    },
    "4thealth.device_review_posture": {
        "label": "Configuration Posture",
        "description": "Devices passing vs. failing configuration review checks, with the top failing checks listed.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "device_review",
        "default_size": "2x2",
        "chart_type": "bar",
        "rag": {"direction": "higher", "green": 0, "amber": 0},
    },
    "4thealth.ai_usage_24h": {
        "label": "AI Usage (24h)",
        "description": "AI assistant connections and estimated cost over the trailing 24 hours.",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "ai_usage_24h",
        "default_size": "2x2",
        "chart_type": "line",
    },
    "4thealth.rule_hygiene": {
        "label": "Rule Hygiene",
        "description": "Firewall rule hygiene findings from the latest sweep, grouped by finding type (shadowed, unhit, etc).",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "rule_hygiene",
        "default_size": "2x2",
        "chart_type": "bar",
    },
    "4texecutive.cpu_percent": {
        "label": "Host CPU",
        "description": "CPU utilization of the 4tExecutive host container.",
        "source_system": "4texecutive",
        "metric_type": "summary",
        "field": "cpu_percent",
        "default_size": "1x1",
        "chart_type": "line",
    },
    "4texecutive.memory_percent": {
        "label": "Host Memory",
        "description": "Memory utilization of the 4tExecutive host container.",
        "source_system": "4texecutive",
        "metric_type": "summary",
        "field": "memory_percent",
        "default_size": "1x1",
        "chart_type": "line",
    },
    "4texecutive.disk_percent": {
        "label": "Host Disk",
        "description": "Disk utilization of the 4tExecutive host container.",
        "source_system": "4texecutive",
        "metric_type": "summary",
        "field": "disk_percent",
        "default_size": "1x1",
        "chart_type": "line",
    },
    "4tlog.faz_health": {
        "label": "FortiAnalyzer Health",
        "description": "Current health status of the connected FortiAnalyzer instance.",
        "source_system": "4tlog",
        "metric_type": "summary",
        # 4tlog never emits a single "faz_health" field — it reports
        # faz_targets_healthy/faz_targets_total/faz_disk_used_pct instead
        # (see docs/integrations.md). get_widget_value special-cases this
        # widget type to compose those three into one display value, so
        # "field" here is unused but kept for catalog-entry consistency.
        "field": "faz_targets_healthy",
        "default_size": "2x1",
    },
    "4tlog.log_volume_trend": {
        "label": "Log Volume Trend",
        "description": "Log ingestion rate (events/sec) received by 4tlog over time.",
        "source_system": "4tlog",
        "metric_type": "summary",
        "field": "log_volume_events_per_sec",
        "default_size": "2x2",
        "chart_type": "line",
    },
    "4tlog.silent_devices": {
        "label": "Silent Devices",
        "description": "Devices actively logging vs. gone silent (no logs received recently).",
        "source_system": "4tlog",
        "metric_type": "summary",
        "field": "devices_logging",
        "default_size": "2x2",
        "chart_type": "bar",
        "rag": {"direction": "higher", "green": 0, "amber": 0},
    },
}

# Section titles for grouping dashboard widgets by their source system, in
# the order sections should render. Systems not listed here (there are none
# today, but a future catalog entry could add one) render after these, in
# first-seen order, titled by their raw system name.
SECTION_TITLES: dict[str, str] = {
    "4tlog": "4tlog",
    "4thealth": "4thealth-plus",
    "4texecutive": "4tExecutive",
}


def group_by_system(widgets: list[dict]) -> list[dict]:
    """Bucket annotated widgets into titled sections by their catalog source_system.

    Each widget dict is expected to carry an "index" key already (the
    dashboard route stamps this before grouping) so per-widget DOM anchors
    survive being nested inside per-section grids. Returns a list of
    {"system", "title", "widgets"} dicts, ordered per SECTION_TITLES with any
    unlisted systems appended afterward in first-seen order.
    """
    buckets: dict[str, list[dict]] = {}
    for widget in widgets:
        system = WIDGET_CATALOG[widget["type"]]["source_system"]
        buckets.setdefault(system, []).append(widget)

    sections = []
    for system in SECTION_TITLES:
        if system in buckets:
            sections.append({"system": system, "title": SECTION_TITLES[system], "widgets": buckets.pop(system)})
    for system, widgets_in_bucket in buckets.items():
        sections.append({"system": system, "title": SECTION_TITLES.get(system, system), "widgets": widgets_in_bucket})
    return sections


def default_layout() -> list[dict]:
    """Auto-generated fallback shown when a user has no saved layout: one
    widget per catalog entry x each enabled source whose system matches, so
    the dashboard shows everything currently configured instead of being
    blank until someone builds a real per-user editor. Host metrics
    (4texecutive.*) are excluded — they live on the Admin > System page,
    not the executive dashboard.

    Four widgets are conditional. The AI usage widget is only included when
    the source's latest snapshot reports ai_enabled: true, since most 4thealth
    instances won't have AI turned on and an always-empty tile isn't useful
    default clutter. The rollup widgets (device_review_posture, rule_hygiene,
    silent_devices) are only included when the latest snapshot actually
    carries that rollup — a source release that hasn't shipped the rollup yet
    would otherwise get a tile reading "No data yet" forever, changing its
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
            elif widget_type in (
                "4thealth.device_review_posture",
                "4thealth.rule_hygiene",
                "4tlog.silent_devices",
            ):
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


# Widget types whose value is meaningless (reads as 0/null) until the
# named sweep job has completed at least once — see docs/integrations.md's
# "absent/null until the first scheduled ... rollup run" note. Rather than
# rendering a misleading red 0, get_widget_value reports these as pending.
_PENDING_SWEEP_STATUS_KEY: dict[str, str] = {
    "4thealth.hygiene_score": "hygiene_sweep_status",
    "4thealth.version_compliance": "device_sweep_status",
}


def _faz_health_value(payload: dict) -> str | None:
    """Compose FortiAnalyzer Health's display value from the three fields
    4tlog actually sends (there is no single "faz_health" field — see the
    comment on the 4tlog.faz_health catalog entry)."""
    healthy = payload.get("faz_targets_healthy")
    total = payload.get("faz_targets_total")
    if healthy is None or total is None:
        return None
    value = f"{healthy}/{total} healthy"
    disk_pct = payload.get("faz_disk_used_pct")
    if disk_pct is not None:
        value += f" · {disk_pct}% disk"
    return value


def get_widget_value(widget_instance: dict) -> dict | None:
    entry = WIDGET_CATALOG[widget_instance["type"]]
    latest = get_latest(widget_instance["source_instance"], entry["metric_type"])
    if latest is None:
        return None
    if widget_instance["type"] == "4tlog.faz_health":
        value = _faz_health_value(latest["value"])
    else:
        value = latest["value"].get(entry["field"])
    result = {
        "value": value,
        "collected_at": latest["collected_at"],
    }
    stale = _is_stale(latest["value"], widget_instance["type"])
    if stale is not None:
        result["stale"] = stale
    # "ok" is the real completion value both sweeps report (see
    # 4thealth-plus's executive_summary_cache.py) — {pending, running, ok,
    # error}. "completed" never occurs; comparing against it here previously
    # meant every finished sweep still read as pending.
    status_key = _PENDING_SWEEP_STATUS_KEY.get(widget_instance["type"])
    if status_key and not result["value"] and latest["value"].get(status_key) != "ok":
        result["pending"] = True
        return result
    return _attach_rag(widget_instance["type"], entry, result)


def _gauge_point(cx: float, cy: float, r: float, value: float, max_value: float) -> tuple[float, float]:
    """Point on the gauge's semicircle rim for value, sweeping left (0) to right (max_value) over the top."""
    angle = math.radians(180 - (value / max_value) * 180)
    return cx + r * math.cos(angle), cy - r * math.sin(angle)


def gauge_geometry(value: float | None, green: float, amber: float, max_value: float = 100) -> dict:
    """Compute SVG geometry for a red/amber/green semicircle gas gauge.

    Bands are drawn low-to-high as red [0, amber), amber [amber, green),
    green [green, max_value], matching the "higher is better" RAG direction
    used by hygiene_score and version_compliance_pct.
    """
    cx, cy, r = 100.0, 95.0, 80.0
    band_bounds = [0, amber, green, max_value]
    colors = ["var(--status-failed)", "var(--status-amber)", "var(--status-ok)"]
    bands = []
    for start_v, end_v, color in zip(band_bounds, band_bounds[1:], colors):
        if end_v <= start_v:
            continue
        x1, y1 = _gauge_point(cx, cy, r, start_v, max_value)
        x2, y2 = _gauge_point(cx, cy, r, end_v, max_value)
        bands.append({"path": f"M {x1:.2f} {y1:.2f} A {r:.0f} {r:.0f} 0 0 1 {x2:.2f} {y2:.2f}", "color": color})
    clamped = max(0.0, min(max_value, value)) if value is not None else 0.0
    needle_x, needle_y = _gauge_point(cx, cy, 65.0, clamped, max_value)
    return {"cx": cx, "cy": cy, "needle_x": round(needle_x, 2), "needle_y": round(needle_y, 2), "bands": bands}


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

        if widget_instance["type"] == "4tlog.silent_devices":
            devices_logging = latest["value"].get("devices_logging")
            devices_silent = latest["value"].get("devices_silent")
            if devices_logging is None and devices_silent is None:
                return _attach_rag(
                    widget_instance["type"], entry, _empty_bar(widget_instance["type"])
                )
            devices_logging = devices_logging or 0
            devices_silent = devices_silent or 0
            result = {
                "chart": "bar",
                "data": {"Logging": devices_logging, "Silent": devices_silent},
                "collected_at": latest["collected_at"],
            }
            result["rag"] = "red" if devices_silent > 0 else "green"
            return result

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

        if widget_instance["type"] == "4thealth.rule_hygiene":
            findings_by_type = (latest["value"].get("rule_hygiene") or {}).get("rule_findings_by_type") or {}
            if not findings_by_type:
                return _attach_rag(
                    widget_instance["type"], entry, _empty_bar(widget_instance["type"])
                )
            # snake_case check names (e.g. "missing_security_profile") read
            # as run-on text under a narrow bar slot; humanizing them doesn't
            # fully prevent the longest ones from needing the chart's
            # rotate_labels angling, but it shortens and clarifies every one.
            # missing_security_profile is 4thealth-plus's one check name long
            # enough (see app/hygiene.py's CHECKS dict there) to still crowd
            # its neighbor even rotated, so it gets an explicit short label.
            label_overrides = {"missing_security_profile": "Missing Profile"}
            data = {
                label_overrides.get(k, k.replace("_", " ").title()): v
                for k, v in findings_by_type.items()
            }
            return {"chart": "bar", "data": data, "collected_at": latest["collected_at"]}

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

    # Some widgets (Total Rules, Total Managed Firewalls) always chart a
    # fixed lookback regardless of the page-wide range, since a single-day
    # window makes a slow-moving fleet-size metric look flat/meaningless.
    effective_range_key = entry.get("fixed_range", range_key)
    range_delta = RANGES.get(effective_range_key, RANGES[DEFAULT_RANGE])
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
                "range_label": effective_range_key,
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
        # The range the delta was actually computed over — normally the
        # page-wide range_key, but a fixed_range widget (Total Rules, Total
        # Managed Firewalls) always charts 30d regardless of the page range,
        # so its delta label needs to say so rather than lying about it.
        "range_label": effective_range_key,
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


def _current_summary(data: dict | None) -> str | None:
    """One-line "Current: ..." snippet summarizing a widget's latest data, for
    the info-icon tooltip. Returns None when there's nothing to show (no data
    yet, or a pending-first-sweep widget)."""
    if not data or data.get("pending"):
        return None
    if data.get("chart") == "line":
        points = data.get("points") or []
        return f"Current: {points[-1][1]}" if points else None
    if data.get("chart") == "bar":
        bar_data = data.get("data") or {}
        return "Current: " + ", ".join(f"{k} {v}" for k, v in bar_data.items()) if bar_data else None
    value = data.get("value")
    if value is None:
        return None
    if isinstance(value, dict):
        return "Current: " + ", ".join(f"{k} {v}" for k, v in value.items())
    return f"Current: {value}"


def annotate(widget: dict, *, with_data: bool, range_key: str = DEFAULT_RANGE) -> dict:
    entry = WIDGET_CATALOG[widget["type"]]
    annotated = {
        **widget,
        "label": entry["label"],
        "description": entry["description"],
        "source_name": source_name(widget["source_instance"]),
    }
    if with_data:
        annotated["data"] = get_widget_series(widget, range_key)
        annotated["current_summary"] = _current_summary(annotated["data"])
    return annotated
