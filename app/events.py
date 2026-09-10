"""Change detection: compares a poll's before/after state and records events.

Three detectors, each comparing a "before" and "after" snapshot the caller
(app/collector.py) captures at the right times relative to the poll/write:

- rag_change: a WIDGET_CATALOG entry's RAG state changed, using the exact
  same get_widget_series()-based RAG computation the rest of the app
  displays — no new RAG logic.
- rollup_delta: one of a fixed set of rollup counts moved by more than its
  configured threshold (config/events.json, overriding sane defaults).
- threshold_cross: a Scorecard domain's fleet score crossed its configured
  target (config/scoring.json) — distinct from rag_change, which is
  per-widget, not per-domain.

source_failed/source_recovered are recorded directly by the collector next
to its existing poll_errors bookkeeping (see record_source_failed/recovered
below) since that transition is already tracked there.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR
from app.domains import DOMAINS, get_scoring_config
from app.metric_extract import EXTRACTORS
from app.metrics_db import insert_event
from app.widgets import DEFAULT_RANGE, WIDGET_CATALOG, get_widget_series

EVENTS_CONFIG_PATH = CONFIG_DIR / "events.json"

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

DEFAULT_ROLLUP_THRESHOLDS: dict[str, float] = {
    "devices_silent": 3,
    "device_review.findings_by_severity.critical": 0,
    "pending_config_diff_count": 3,
}

ROLLUP_LABELS: dict[str, str] = {
    "devices_silent": "Silent devices",
    "device_review.findings_by_severity.critical": "Critical findings",
    "pending_config_diff_count": "Pending config diffs",
}


def get_events_config() -> dict:
    overrides = read_json(EVENTS_CONFIG_PATH, default={})
    config = {"rollup_thresholds": dict(DEFAULT_ROLLUP_THRESHOLDS)}
    config["rollup_thresholds"].update(overrides.get("rollup_thresholds") or {})
    return config


def save_events_config(config: dict) -> None:
    atomic_write_json(EVENTS_CONFIG_PATH, config)


def _widget_types_for_system(system: str) -> list[str]:
    return [wt for wt, entry in WIDGET_CATALOG.items() if entry["source_system"] == system]


def capture_rag_snapshot(source_id: str, system: str) -> dict[str, str | None]:
    """RAG state for every catalog widget of `system`, read live from
    whatever's currently the latest snapshot for source_id. Called by the
    collector both before and after writing a new snapshot."""
    snapshot = {}
    for widget_type in _widget_types_for_system(system):
        series = get_widget_series({"type": widget_type, "source_instance": source_id}, DEFAULT_RANGE)
        snapshot[widget_type] = (series or {}).get("rag")
    return snapshot


def _rag_severity(rag: str | None) -> str:
    if rag == "red":
        return "critical"
    if rag == "amber":
        return "warning"
    return "info"


def build_rag_change_events(source: dict, before_rag: dict, after_rag: dict) -> list[dict]:
    events = []
    for widget_type, after in after_rag.items():
        before = before_rag.get(widget_type)
        if before == after:
            continue
        entry = WIDGET_CATALOG[widget_type]
        events.append(
            {
                "source_id": source["id"],
                "metric_key": entry.get("metric_key", entry["field"]),
                "kind": "rag_change",
                "severity": _rag_severity(after),
                "title": f"{entry['label']} turned {after or 'unclassified'}",
                "detail": {"widget_type": widget_type, "before": before, "after": after},
            }
        )
    return events


def build_rollup_delta_events(source: dict, before_payload: dict | None, after_payload: dict | None) -> list[dict]:
    if not before_payload or not after_payload:
        return []
    thresholds = get_events_config()["rollup_thresholds"]
    events = []
    for metric_key, label in ROLLUP_LABELS.items():
        before_value = EXTRACTORS[metric_key](before_payload)
        after_value = EXTRACTORS[metric_key](after_payload)
        if before_value is None or after_value is None:
            continue
        delta = after_value - before_value
        threshold = thresholds.get(metric_key, 0)
        if abs(delta) <= threshold:
            continue
        direction = "increased" if delta > 0 else "decreased"
        events.append(
            {
                "source_id": source["id"],
                "metric_key": metric_key,
                "kind": "rollup_delta",
                "severity": "warning" if delta > 0 else "info",
                "title": f"{label} {direction} by {abs(delta):.0f} to {after_value:.0f}",
                "detail": {"before": before_value, "after": after_value, "delta": delta, "threshold": threshold},
            }
        )
    return events


def build_threshold_cross_events(before_scores: dict[str, float | None], after_scores: dict[str, float | None]) -> list[dict]:
    config = get_scoring_config()
    events = []
    for name, after_score in after_scores.items():
        before_score = before_scores.get(name)
        if before_score is None or after_score is None:
            continue
        target = config["domains"].get(name, {}).get("target")
        if target is None:
            continue
        crossed_below = before_score >= target > after_score
        crossed_above = before_score < target <= after_score
        if not (crossed_below or crossed_above):
            continue
        events.append(
            {
                "source_id": None,
                "metric_key": f"domain.{name}",
                "kind": "threshold_cross",
                "severity": "critical" if crossed_below else "info",
                "title": f"{DOMAINS[name]['label']} score crossed its target ({after_score} vs target {target})",
                "detail": {"domain": name, "before": before_score, "after": after_score, "target": target},
            }
        )
    return events


def detect_and_record(
    *,
    source: dict,
    before_rag: dict,
    after_rag: dict,
    before_payload: dict | None,
    after_payload: dict | None,
    before_domain_scores: dict,
    after_domain_scores: dict,
    now: datetime | None = None,
) -> list[dict]:
    """Run all three detectors and persist whatever they find. Returns the
    (unsaved-shape) event dicts that were recorded, for tests/callers that
    want to inspect them without a round-trip through get_events()."""
    now_iso = (now or datetime.now(UTC)).strftime(ISO_FORMAT)
    events = (
        build_rag_change_events(source, before_rag, after_rag)
        + build_rollup_delta_events(source, before_payload, after_payload)
        + build_threshold_cross_events(before_domain_scores, after_domain_scores)
    )
    for event in events:
        insert_event(ts=now_iso, **event)
    return events


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, ISO_FORMAT).replace(tzinfo=UTC)


def positioned_ticks(points: list[dict], events: list[dict], width: float) -> list[dict]:
    """Map each event's ts onto an x pixel position (0..width) along a
    metric_points-shaped series, for drawing as a tick mark on the same
    chart. Events outside the series' time range are dropped — nothing to
    anchor them to."""
    if len(points) < 2:
        return []
    start = _parse_ts(points[0]["ts"])
    end = _parse_ts(points[-1]["ts"])
    span = (end - start).total_seconds()
    if span <= 0:
        return []
    ticks = []
    for event in events:
        event_dt = _parse_ts(event["ts"])
        if event_dt < start or event_dt > end:
            continue
        fraction = (event_dt - start).total_seconds() / span
        ticks.append({"x": round(fraction * width, 2), "title": event["title"]})
    return ticks


def record_source_failed(source: dict, error: str, now: datetime | None = None) -> None:
    now_iso = (now or datetime.now(UTC)).strftime(ISO_FORMAT)
    insert_event(
        ts=now_iso,
        source_id=source["id"],
        metric_key=None,
        kind="source_failed",
        severity="critical",
        title=f"{source['name']} stopped responding",
        detail={"error": error},
    )


_ROLLUP_DOMAIN: dict[str, str] = {
    "devices_silent": "logging",
    "device_review.findings_by_severity.critical": "posture",
    "pending_config_diff_count": "availability",
}


def event_domain(event: dict) -> str | None:
    """Which Scorecard domain (if any) an event's "What changed" link should
    point at. threshold_cross events already carry their domain; rag_change
    and rollup_delta map through board.py's/this module's fixed mappings;
    source_failed/recovered have no domain (link nowhere)."""
    if event["kind"] == "threshold_cross":
        return event["detail"].get("domain")
    if event["kind"] == "rag_change":
        from app.board import WIDGET_DOMAIN

        return WIDGET_DOMAIN.get(event["detail"].get("widget_type"))
    if event["kind"] == "rollup_delta":
        return _ROLLUP_DOMAIN.get(event["metric_key"])
    return None


def record_source_recovered(source: dict, now: datetime | None = None) -> None:
    now_iso = (now or datetime.now(UTC)).strftime(ISO_FORMAT)
    insert_event(
        ts=now_iso,
        source_id=source["id"],
        metric_key=None,
        kind="source_recovered",
        severity="info",
        title=f"{source['name']} recovered",
        detail={},
    )
