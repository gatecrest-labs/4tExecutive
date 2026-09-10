"""Domain scorecard: rolls the widget catalog's metrics up into six graded
domains (availability, posture, vulnerability, hygiene, logging, lifecycle)
for the scorecard landing page.

Vulnerability and Lifecycle have no real 4tExecutive metrics yet (they land
with PSIRT/hardware-EOS in a later wave) — they always score None and render
"not yet measured".

Aggregation reads metric_points exclusively (never raw snapshots), summed or
averaged across every enabled source of a domain's source_system, so "now"
and "a baseline N days ago" are the same code path at two different
timestamps. See docs/architecture.md for the full design.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR
from app.metrics_db import get_metric_latest_at_or_before, insert_metric_points
from app.sources import list_sources
from app.thresholds import get_thresholds
from app.widgets import WIDGET_CATALOG, baseline_cutoff, rag_state

SCORING_PATH = CONFIG_DIR / "scoring.json"

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# name -> {label, system} — system is None for domains with no real metrics yet.
DOMAINS: dict[str, dict] = {
    "availability": {"label": "Availability", "system": "4thealth"},
    "posture": {"label": "Config Posture", "system": "4thealth"},
    "vulnerability": {"label": "Vulnerability", "system": None},
    "hygiene": {"label": "Policy Hygiene", "system": "4thealth"},
    "logging": {"label": "Logging & Visibility", "system": "4tlog"},
    "lifecycle": {"label": "Lifecycle & Support", "system": None},
}

# Member metrics shown on each domain's detail-page table, with the
# direction used to look up an existing WIDGET_CATALOG RAG threshold (see
# _metric_rag) — informational entries with no matching widget just render
# without a RAG state.
MEMBER_METRICS: dict[str, list[dict]] = {
    "availability": [
        {"key": "firewall_online_count", "label": "Firewalls online"},
        {"key": "firewall_managed_count", "label": "Firewalls managed"},
    ],
    "posture": [
        {"key": "hygiene_score", "label": "Hygiene score (fleet avg)"},
        {"key": "version_compliance_pct", "label": "Version compliance (fleet avg)"},
        {"key": "device_review.devices_with_failures", "label": "Devices with failures"},
    ],
    "vulnerability": [],
    "hygiene": [
        {"key": "rule_hygiene.rule_findings_total", "label": "Rule findings"},
        {"key": "rule_count_total", "label": "Total rules"},
    ],
    "logging": [
        {"key": "devices_silent", "label": "Silent devices"},
        {"key": "faz_disk_used_pct", "label": "FortiAnalyzer disk used % (worst)"},
    ],
    "lifecycle": [],
}

DEFAULT_SCORING: dict = {
    "domain_weights": {
        "availability": 20,
        "posture": 25,
        "vulnerability": 20,
        "hygiene": 15,
        "logging": 10,
        "lifecycle": 10,
    },
    "domains": {
        "availability": {"target": 95},
        "posture": {
            "hygiene_weight": 0.5,
            "version_weight": 0.3,
            "per_failing_device": 1,
            "failing_device_cap": 20,
            "target": 90,
        },
        "hygiene": {
            "points_per_1000_findings": 0.5,
            "findings_cap": 40,
            "target": 85,
        },
        "logging": {
            "points_per_silent_device": 3,
            "silent_cap": 40,
            "disk_warn_threshold": 70,
            "disk_penalty_per_pct": 1,
            "target": 90,
        },
    },
}


def get_scoring_config() -> dict:
    """DEFAULT_SCORING, deep-merged with config/scoring.json overrides (same
    override-on-top-of-catalog-defaults pattern as app/thresholds.py)."""
    overrides = read_json(SCORING_PATH, default={})
    config = copy.deepcopy(DEFAULT_SCORING)
    for name, weight in (overrides.get("domain_weights") or {}).items():
        if name in config["domain_weights"]:
            config["domain_weights"][name] = weight
    for name, params in (overrides.get("domains") or {}).items():
        if name in config["domains"]:
            config["domains"][name].update(params)
    return config


def save_scoring_config(config: dict) -> None:
    atomic_write_json(SCORING_PATH, config)


def grade_for(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def rag_for_grade(grade: str | None) -> str | None:
    if grade is None:
        return None
    if grade == "F":
        return "red"
    if grade in ("C", "D"):
        return "amber"
    return "green"


def _now_iso(now: datetime) -> str:
    return now.strftime(ISO_FORMAT)


def _enabled_sources(system: str) -> list[dict]:
    return [s for s in list_sources() if s.get("system") == system and s.get("enabled", True)]


def _fleet_sum(system: str, metric_key: str, ts_iso: str) -> float | None:
    total = 0.0
    found = False
    for source in _enabled_sources(system):
        point = get_metric_latest_at_or_before(source["id"], metric_key, ts_iso)
        if point is not None:
            total += point["value"]
            found = True
    return total if found else None


def _fleet_max(system: str, metric_key: str, ts_iso: str) -> float | None:
    values = [
        point["value"]
        for source in _enabled_sources(system)
        if (point := get_metric_latest_at_or_before(source["id"], metric_key, ts_iso)) is not None
    ]
    return max(values) if values else None


def _fleet_weighted_avg(system: str, value_key: str, weight_key: str, ts_iso: str) -> float | None:
    weighted_sum = 0.0
    weight_total = 0.0
    plain_values = []
    for source in _enabled_sources(system):
        value_point = get_metric_latest_at_or_before(source["id"], value_key, ts_iso)
        if value_point is None:
            continue
        plain_values.append(value_point["value"])
        weight_point = get_metric_latest_at_or_before(source["id"], weight_key, ts_iso)
        weight = weight_point["value"] if weight_point is not None else 0.0
        weighted_sum += value_point["value"] * weight
        weight_total += weight
    if not plain_values:
        return None
    if weight_total > 0:
        return weighted_sum / weight_total
    return sum(plain_values) / len(plain_values)


def _domain_inputs(name: str, ts_iso: str) -> dict[str, float | None]:
    system = DOMAINS[name]["system"]
    if system is None:
        return {}
    if name == "availability":
        return {
            "firewall_online_count": _fleet_sum(system, "firewall_online_count", ts_iso),
            "firewall_managed_count": _fleet_sum(system, "firewall_managed_count", ts_iso),
        }
    if name == "posture":
        return {
            "hygiene_score": _fleet_weighted_avg(system, "hygiene_score", "firewall_managed_count", ts_iso),
            "version_compliance_pct": _fleet_weighted_avg(
                system, "version_compliance_pct", "firewall_managed_count", ts_iso
            ),
            "device_review.devices_with_failures": _fleet_sum(
                system, "device_review.devices_with_failures", ts_iso
            ),
        }
    if name == "hygiene":
        return {
            "rule_hygiene.rule_findings_total": _fleet_sum(system, "rule_hygiene.rule_findings_total", ts_iso),
            "rule_count_total": _fleet_sum(system, "rule_count_total", ts_iso),
        }
    if name == "logging":
        return {
            "devices_silent": _fleet_sum(system, "devices_silent", ts_iso),
            "faz_disk_used_pct": _fleet_max(system, "faz_disk_used_pct", ts_iso),
        }
    return {}


def _score_availability(inputs: dict, params: dict) -> tuple[float | None, str | None, str | None]:
    online = inputs.get("firewall_online_count")
    managed = inputs.get("firewall_managed_count")
    if online is None or managed is None or managed == 0:
        return None, None, None
    pct = max(0.0, min(100.0, round(online / managed * 100, 1)))
    why = f"{online:.0f}/{managed:.0f} online"
    explanation = f"Availability = online / managed × 100 = {online:.0f} / {managed:.0f} × 100 = {pct}."
    return pct, why, explanation


def _score_posture(inputs: dict, params: dict) -> tuple[float | None, str | None, str | None]:
    hygiene = inputs.get("hygiene_score")
    compliance = inputs.get("version_compliance_pct")
    failures = inputs.get("device_review.devices_with_failures")
    if hygiene is None and compliance is None and failures is None:
        return None, None, None
    hygiene = 100.0 if hygiene is None else hygiene
    compliance = 100.0 if compliance is None else compliance
    failures = failures or 0.0
    hygiene_penalty = (100.0 - hygiene) * params["hygiene_weight"]
    compliance_penalty = (100.0 - compliance) * params["version_weight"]
    failure_penalty = min(failures * params["per_failing_device"], params["failing_device_cap"])
    score = max(0.0, min(100.0, round(100.0 - hygiene_penalty - compliance_penalty - failure_penalty, 1)))
    why = f"{failures:.0f} devices with failures · hygiene {hygiene:.0f}"
    explanation = (
        f"Start at 100. Subtract (100−hygiene)×{params['hygiene_weight']} = "
        f"(100−{hygiene:.0f})×{params['hygiene_weight']} = {hygiene_penalty:.1f}; "
        f"(100−compliance)×{params['version_weight']} = (100−{compliance:.0f})×{params['version_weight']} "
        f"= {compliance_penalty:.1f}; failing devices {failures:.0f}×{params['per_failing_device']} "
        f"capped at {params['failing_device_cap']} = {failure_penalty:.1f}. Score = {score}."
    )
    return score, why, explanation


def _score_hygiene(inputs: dict, params: dict) -> tuple[float | None, str | None, str | None]:
    findings = inputs.get("rule_hygiene.rule_findings_total")
    rules = inputs.get("rule_count_total")
    if findings is None or rules is None or rules == 0:
        return None, None, None
    rate_per_1000 = findings / rules * 1000
    penalty = min(rate_per_1000 * params["points_per_1000_findings"], params["findings_cap"])
    score = max(0.0, min(100.0, round(100.0 - penalty, 1)))
    why = f"{findings:.0f} findings in {rules:.0f} rules"
    explanation = (
        f"Start at 100. Findings per 1000 rules = {findings:.0f}/{rules:.0f}×1000 = {rate_per_1000:.1f}; "
        f"×{params['points_per_1000_findings']} capped at {params['findings_cap']} = {penalty:.1f}. "
        f"Score = {score}."
    )
    return score, why, explanation


def _score_logging(inputs: dict, params: dict) -> tuple[float | None, str | None, str | None]:
    silent = inputs.get("devices_silent")
    disk = inputs.get("faz_disk_used_pct")
    if silent is None and disk is None:
        return None, None, None
    silent = silent or 0.0
    disk = 0.0 if disk is None else disk
    silent_penalty = min(silent * params["points_per_silent_device"], params["silent_cap"])
    disk_penalty = max(0.0, disk - params["disk_warn_threshold"]) * params["disk_penalty_per_pct"]
    score = max(0.0, min(100.0, round(100.0 - silent_penalty - disk_penalty, 1)))
    why = f"{silent:.0f} silent devices · FAZ disk {disk:.0f}%"
    explanation = (
        f"Start at 100. Silent devices {silent:.0f}×{params['points_per_silent_device']} capped at "
        f"{params['silent_cap']} = {silent_penalty:.1f}; disk {disk:.0f}% over "
        f"{params['disk_warn_threshold']}% ×{params['disk_penalty_per_pct']} = {disk_penalty:.1f}. "
        f"Score = {score}."
    )
    return score, why, explanation


_SCORERS = {
    "availability": _score_availability,
    "posture": _score_posture,
    "hygiene": _score_hygiene,
    "logging": _score_logging,
}


def compute_domain(name: str, *, compare_to: str = "7d", now: datetime | None = None) -> dict:
    spec = DOMAINS[name]
    now = now or datetime.now(UTC)
    result = {
        "name": name,
        "label": spec["label"],
        "score": None,
        "grade": None,
        "rag": None,
        "why": None,
        "explanation": None,
        "delta": None,
        "inputs": {},
        "target": None,
    }
    if spec["system"] is None:
        return result

    config = get_scoring_config()
    params = config["domains"].get(name, {})
    now_iso = _now_iso(now)
    now_inputs = _domain_inputs(name, now_iso)
    score, why, explanation = _SCORERS[name](now_inputs, params)

    result.update(
        {
            "score": score,
            "grade": grade_for(score),
            "why": why,
            "explanation": explanation,
            "inputs": now_inputs,
            "target": params.get("target"),
        }
    )
    result["rag"] = rag_for_grade(result["grade"])

    if score is not None:
        baseline_iso = _now_iso(baseline_cutoff(compare_to, now))
        baseline_inputs = _domain_inputs(name, baseline_iso)
        baseline_score, _, _ = _SCORERS[name](baseline_inputs, params)
        if baseline_score is not None:
            result["delta"] = round(score - baseline_score, 1)

    return result


def compute_overall(*, compare_to: str = "7d", now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    config = get_scoring_config()
    weights = config["domain_weights"]
    domain_results = {name: compute_domain(name, compare_to=compare_to, now=now) for name in DOMAINS}

    measured = [(name, r) for name, r in domain_results.items() if r["score"] is not None]
    overall_score = None
    if measured:
        weight_sum = sum(weights.get(name, 0) for name, _ in measured)
        if weight_sum > 0:
            overall_score = round(
                sum(r["score"] * weights.get(name, 0) for name, r in measured) / weight_sum, 1
            )

    overall_delta = None
    baseline_measured = [
        (name, r["score"] - r["delta"])
        for name, r in domain_results.items()
        if r["score"] is not None and r["delta"] is not None
    ]
    if overall_score is not None and baseline_measured:
        weight_sum = sum(weights.get(name, 0) for name, _ in baseline_measured)
        if weight_sum > 0:
            baseline_overall = sum(s * weights.get(name, 0) for name, s in baseline_measured) / weight_sum
            overall_delta = round(overall_score - baseline_overall, 1)

    rag_order = {"red": 0, "amber": 1, "green": 2}
    measured_rags = [r["rag"] for r in domain_results.values() if r["rag"] is not None]
    overall_rag = min(measured_rags, key=lambda r: rag_order[r]) if measured_rags else None

    return {
        "score": overall_score,
        "grade": grade_for(overall_score),
        "rag": overall_rag,
        "delta": overall_delta,
        "domains": domain_results,
    }


def store_domain_scores(now: datetime | None = None) -> None:
    """Compute every domain's current score and persist it to metric_points
    under the synthetic fleet source id "_fleet" (same convention as "_self"
    for host metrics), so a sparkline history accumulates over time. Run from
    the scheduler alongside poll_all."""
    now = now or datetime.now(UTC)
    points = {}
    for name in DOMAINS:
        result = compute_domain(name, now=now)
        if result["score"] is not None:
            points[f"domain.{name}"] = result["score"]
    if points:
        insert_metric_points("_fleet", _now_iso(now), points)


def _metric_rag(metric_key: str, value: float | None) -> str | None:
    """Reuse an existing WIDGET_CATALOG RAG threshold for a member metric, if
    one of its entries already scores this exact metric_key. Metrics with no
    matching widget (e.g. a fleet size count) render without a RAG state."""
    if value is None:
        return None
    for entry in WIDGET_CATALOG.values():
        if entry.get("metric_key", entry["field"]) == metric_key:
            thresholds = get_thresholds(entry["field"], entry.get("rag"))
            if thresholds is not None:
                return rag_state(value, thresholds)
    return None


def domain_member_table(name: str, *, compare_to: str = "7d", now: datetime | None = None) -> list[dict]:
    if DOMAINS[name]["system"] is None:
        return []
    now = now or datetime.now(UTC)
    now_iso = _now_iso(now)
    baseline_iso = _now_iso(baseline_cutoff(compare_to, now))
    now_inputs = _domain_inputs(name, now_iso)
    baseline_inputs = _domain_inputs(name, baseline_iso)

    rows = []
    for member in MEMBER_METRICS[name]:
        key = member["key"]
        now_value = now_inputs.get(key)
        baseline_value = baseline_inputs.get(key)
        delta = round(now_value - baseline_value, 2) if now_value is not None and baseline_value is not None else None
        rows.append(
            {
                "key": key,
                "label": member["label"],
                "now": now_value,
                "delta": delta,
                "rag": _metric_rag(key, now_value),
            }
        )
    return rows
