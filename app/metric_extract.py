"""Derived metric-point extraction: flattens a source's summary payload into
the uniform (metric_key -> float) time series stored in metric_points.

Every scalar WIDGET_CATALOG reads today gets a registry entry keyed by its
catalog "field" name, plus the nested rollup scalars and derived metrics
listed in the metric_points design (device_review.*, rule_hygiene.*,
psirt.*, change_control.*, devices_silent, faz_disk_used_pct,
fleet_availability_pct). A composite dict field with no single sensible
scalar (version_breakdown, device_review, ai_usage_24h, rule_hygiene,
psirt, psirt.top_advisory, change_control, change_control.admin_changes_by_user)
still gets a registry entry — so every catalog field is covered — but its
extractor always returns None; its useful children are extracted
separately by their own dotted-path keys.
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


def _devices_on_eol_version(payload: dict) -> float | None:
    """Sum of per-version device counts flagged "eol": true in
    version_breakdown -- a derived scalar since version_breakdown itself is
    a composite {version: {count, eol}} dict with no single number."""
    breakdown = payload.get("version_breakdown")
    if not isinstance(breakdown, dict):
        return None
    total_eol = 0.0
    found = False
    for info in breakdown.values():
        if not isinstance(info, dict):
            continue
        count = _num(info.get("count"))
        if count is None:
            continue
        found = True
        if info.get("eol"):
            total_eol += count
    return total_eol if found else None


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


# Per-ADOM breakdown (4thealth-plus schema_version 2's "by_adom" key).
# Every field this repo can meaningfully filter the Board/Scorecard by,
# per ADOM.
BY_ADOM_FIELDS = [
    "firewalls_total",
    "firewall_online_count",
    "version_compliance_pct",
    "pending_config_diff_count",
    "devices_with_failures",
]

# Fleet-wide metric_key (as read by WIDGET_CATALOG / app.domains) -> the
# corresponding field name inside each ADOM's entry in "by_adom". Only
# metrics with a genuine per-ADOM breakdown appear here — anything else
# keeps showing its fleet-wide value even when an ADOM filter is active
# (see by_adom_metric_key()). Note "firewall_managed_count" (the fleet-wide
# name) maps to "firewalls_total" (the by_adom field name) — 4thealth-plus
# uses that name intentionally for the per-ADOM breakdown; it is not a typo.
BY_ADOM_FIELD_MAP: dict[str, str] = {
    "firewall_managed_count": "firewalls_total",
    "firewall_online_count": "firewall_online_count",
    "version_compliance_pct": "version_compliance_pct",
    "pending_config_diff_count": "pending_config_diff_count",
    "device_review.devices_with_failures": "devices_with_failures",
}


def by_adom_metric_key(metric_key: str, adom: str) -> str | None:
    """The metric_points key holding *adom*'s value for a fleet-wide
    metric_key, or None if that metric has no per-ADOM breakdown."""
    field = BY_ADOM_FIELD_MAP.get(metric_key)
    if field is None:
        return None
    return f"by_adom.{adom}.{field}"


def _extract_by_adom(payload: dict) -> dict[str, float]:
    """One metric_point per (ADOM, field) in "by_adom" — dynamic like
    _extract_rule_findings_by_type since the set of ADOMs varies."""
    by_adom = payload.get("by_adom")
    if not isinstance(by_adom, dict):
        return {}
    result: dict[str, float] = {}
    for adom, metrics in by_adom.items():
        if not isinstance(metrics, dict):
            continue
        for field in BY_ADOM_FIELDS:
            value = _num(metrics.get(field))
            if value is not None:
                result[f"by_adom.{adom}.{field}"] = value
    return result


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
    # Change-control (4thealth-plus schema_version 2, app.change_control_cache
    # + app.executive_summary_cache's device sweep).
    "change_control": _no_scalar,
    "change_control.devices_out_of_sync": _nested("change_control", "devices_out_of_sync"),
    "change_control.admin_changes_24h": _nested("change_control", "admin_changes_24h"),
    "change_control.admin_changes_by_user": _no_scalar,
    # Lifecycle / hardware EOS (4thealth-plus schema_version 2,
    # app.model_eos + app.executive_summary_cache's device sweep).
    "lifecycle": _no_scalar,
    "lifecycle.devices_hw_eos": _nested("lifecycle", "devices_hw_eos"),
    "lifecycle.devices_hw_eos_12m": _nested("lifecycle", "devices_hw_eos_12m"),
    "lifecycle.models_unknown": _no_scalar,
    # License status (4thealth-plus, app.license_status_cache's daily sweep).
    "license_status": _no_scalar,
    "license_status.devices_licensed": _nested("license_status", "devices_licensed"),
    "license_status.devices_expired": _nested("license_status", "devices_expired"),
    "license_status.devices_unknown": _nested("license_status", "devices_unknown"),
    "license_status.details": _no_scalar,
    "devices_on_eol_version": _devices_on_eol_version,
    # Per-ADOM breakdown and management-plane infra — both composite,
    # dynamically-shaped fields with no single scalar of their own; see
    # _extract_by_adom() for by_adom's dynamic per-ADOM keys.
    "by_adom": _no_scalar,
    "infra": _no_scalar,
    # PSIRT fleet exposure (4thealth-plus schema_version 2, app.psirt_store).
    "psirt": _no_scalar,
    "psirt.open_advisories": _nested("psirt", "open_advisories"),
    "psirt.devices_critical": _nested("psirt", "devices_critical"),
    "psirt.devices_high": _nested("psirt", "devices_high"),
    "psirt.devices_medium": _nested("psirt", "devices_medium"),
    "psirt.devices_critical_mitigated": _nested("psirt", "devices_critical_mitigated"),
    "psirt.kev_exposed_devices": _nested("psirt", "kev_exposed_devices"),
    "psirt.mean_days_to_remediate_90d": _nested("psirt", "mean_days_to_remediate_90d"),
    "psirt.top_advisory": _no_scalar,
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
    points.update(_extract_by_adom(payload))
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
    parser.add_argument(
        "--backfill", action="store_true", help="Backfill metric_points from existing snapshots"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.backfill:
        _cli_backfill()
    else:
        parser.print_help()
