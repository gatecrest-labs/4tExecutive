"""Derived metric-point extraction: flattens a source's summary payload into
the uniform (metric_key -> float) time series stored in metric_points.

Every scalar WIDGET_CATALOG reads today gets a registry entry keyed by its
catalog "field" name, plus the nested rollup scalars and derived metrics
listed in the metric_points design (device_review.*, rule_hygiene.*,
devices_silent, faz_disk_used_pct, fleet_availability_pct). A composite dict
field with no single sensible scalar (version_breakdown, device_review,
ai_usage_24h, rule_hygiene) still gets a registry entry — so every catalog
field is covered — but its extractor always returns None; its useful
children are extracted separately by their own dotted-path keys.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.metrics_db import (
    downsample_metric_points,
    init_db,
    insert_metric_points,
    iter_all_snapshots,
    prune_metric_points_older_than,
    prune_snapshots_older_than,
)
from app.sources import list_sources

logger = logging.getLogger(__name__)

SNAPSHOT_RETENTION_DAYS = 90
METRIC_POINTS_RETENTION_DAYS = 396  # ~13 months


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _last_backup_status(payload: dict) -> float | None:
    status = payload.get("last_backup_status")
    if not isinstance(status, str):
        return None
    return 1.0 if status.strip().lower().startswith("ok") else 0.0


def _fleet_availability_pct(payload: dict) -> float | None:
    online = _num(payload.get("firewall_online_count"))
    total = _num(payload.get("firewall_managed_count"))
    if online is None or total is None or total == 0:
        return None
    return round(online / total * 100, 2)


def _nested(*path: str) -> Callable[[dict], float | None]:
    def extractor(payload: dict) -> float | None:
        value = payload
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return _num(value)

    return extractor


def _no_scalar(_payload: dict) -> float | None:
    return None


# Fixed metric_key -> extractor registry. Keys matching a WIDGET_CATALOG
# "field" value cover every widget scalar; the rest are the nested rollup
# scalars and derived metrics named explicitly in the design.
EXTRACTORS: dict[str, Callable[[dict], float | None]] = {
    "hygiene_score": _nested("hygiene_score"),
    "version_compliance_pct": _nested("version_compliance_pct"),
    "pending_config_diff_count": _nested("pending_config_diff_count"),
    "last_backup_status": _last_backup_status,
    "firewall_online_count": _nested("firewall_online_count"),
    "firewall_managed_count": _nested("firewall_managed_count"),
    "rule_count_total": _nested("rule_count_total"),
    "adom_count": _nested("adom_count"),
    "cpu_percent": _nested("cpu_percent"),
    "memory_percent": _nested("memory_percent"),
    "disk_percent": _nested("disk_percent"),
    "faz_targets_healthy": _nested("faz_targets_healthy"),
    "log_volume_events_per_sec": _nested("log_volume_events_per_sec"),
    "devices_logging": _nested("devices_logging"),
    # Composite dict fields with no single scalar: registered so every
    # catalog field is covered, but never produce a fabricated number.
    "version_breakdown": _no_scalar,
    "device_review": _no_scalar,
    "ai_usage_24h": _no_scalar,
    "rule_hygiene": _no_scalar,
    # Named explicitly in the design, not tied to a catalog "field".
    "devices_silent": _nested("devices_silent"),
    "faz_disk_used_pct": _nested("faz_disk_used_pct"),
    "device_review.devices_with_failures": _nested("device_review", "devices_with_failures"),
    "device_review.findings_by_severity.critical": _nested(
        "device_review", "findings_by_severity", "critical"
    ),
    "device_review.findings_by_severity.high": _nested(
        "device_review", "findings_by_severity", "high"
    ),
    "device_review.findings_by_severity.medium": _nested(
        "device_review", "findings_by_severity", "medium"
    ),
    "device_review.findings_by_severity.low": _nested(
        "device_review", "findings_by_severity", "low"
    ),
    "rule_hygiene.rule_findings_total": _nested("rule_hygiene", "rule_findings_total"),
    # Derived.
    "fleet_availability_pct": _fleet_availability_pct,
}


def _extract_rule_findings_by_type(payload: dict) -> dict[str, float]:
    """Dynamic extractor: one point per finding-type key actually present in
    the payload, since the set of check names varies (see module docstring).
    """
    findings = (payload.get("rule_hygiene") or {}).get("rule_findings_by_type")
    if not isinstance(findings, dict):
        return {}
    result = {}
    for check_name, count in findings.items():
        value = _num(count)
        if value is not None:
            result[f"rule_hygiene.rule_findings_by_type.{check_name}"] = value
    return result


def extract_all(payload: dict) -> dict[str, float]:
    """Run every extractor against payload, returning {metric_key: value} with
    None results and dynamic keys with no data dropped."""
    points = {}
    for metric_key, extractor in EXTRACTORS.items():
        value = extractor(payload)
        if value is not None:
            points[metric_key] = value
    points.update(_extract_rule_findings_by_type(payload))
    return points


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def backfill() -> None:
    """One-time walk of every existing snapshot into metric_points.

    Safe to re-run: insert_metric_points upserts on (source_id, metric_key,
    ts), so a repeated backfill just re-derives the same values.
    """
    for snapshot in iter_all_snapshots():
        points = extract_all(snapshot["value"])
        insert_metric_points(snapshot["source_id"], snapshot["collected_at"], points)


def apply_retention() -> None:
    """Daily retention pass: prune old raw snapshots, downsample metric_points
    older than 90 days to one point per day, and drop metric_points past 13
    months. Run from the scheduler (see app/collector.py)."""
    now = datetime.now(UTC)
    snapshot_cutoff = (now - timedelta(days=SNAPSHOT_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    downsample_cutoff = snapshot_cutoff
    metric_points_cutoff = (now - timedelta(days=METRIC_POINTS_RETENTION_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    prune_snapshots_older_than(snapshot_cutoff)
    downsample_metric_points(downsample_cutoff)
    prune_metric_points_older_than(metric_points_cutoff)


def _cli_backfill() -> None:
    init_db()
    total_sources = len(list_sources())
    logger.info("Backfilling metric_points from existing snapshots (%d sources)", total_sources)
    backfill()
    logger.info("Backfill complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true", help="Backfill metric_points from existing snapshots")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.backfill:
        _cli_backfill()
    else:
        parser.print_help()
