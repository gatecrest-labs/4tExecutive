"""Weekly Executive Brief: pure data assembly for app/templates/brief.html.

See docs/superpowers/plans/2026-09-12-wave4-executive-brief.md for the
design doc this module implements (sections 1, 2, 6, 7 plus the relevant
parts of section 8 -- SMTP/PDF/scheduler/Admin>Reports are a later agent's
responsibility and are NOT implemented here).

Kept free of Flask imports (pure data + string logic), matching
app/domains.py's/app/devices.py's separation of data logic from routes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domains import DOMAINS, compute_overall, get_scoring_config
from app.metrics_db import (
    get_brief_asks,
    get_events,
    get_latest,
    get_metric_latest_at_or_before,
    get_metric_series,
)
from app.sources import list_sources
from app.widgets import downsample_series, source_name

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# scorecard.html has no textual RAG-state vocabulary of its own -- it only
# ever renders `rag-{{ rag }}` CSS classes plus raw score/grade numbers, so
# there is no existing wording to "reuse" here. This mapping is new copy
# introduced for the brief's status line, following the wording sketched in
# the plan doc / design-b mockup (word/class per RAG state). Documented here
# as an assumption for a later reviewer rather than invented silently.
STATUS_WORD: dict[str | None, str] = {
    "green": "All clear",
    "amber": "Attention required",
    "red": "Action needed",
    None: "Not yet measured",
}
STATUS_CLASS: dict[str | None, str] = {
    "green": "good",
    "amber": "warn",
    "red": "crit",
    None: "unknown",
}


def _now_iso(now: datetime) -> str:
    return now.strftime(ISO_FORMAT)


def week_key_for(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def build_status_sentence(events: list[dict], domain_deltas: dict[str, float | None]) -> str:
    """Pure function -- see plan section 1/8 for the exact scenarios this
    must handle. Never raises, never returns an empty string."""
    events = events or []
    domain_deltas = domain_deltas or {}

    criticals = [e for e in events if e.get("severity") == "critical"]
    warnings_ = [e for e in events if e.get("severity") == "warning"]
    improving = [
        DOMAINS[name]["label"]
        for name, delta in domain_deltas.items()
        if delta is not None and delta > 0 and name in DOMAINS
    ]
    degrading = [
        DOMAINS[name]["label"]
        for name, delta in domain_deltas.items()
        if delta is not None and delta < 0 and name in DOMAINS
    ]

    if not criticals and not warnings_ and not degrading:
        return (
            "All monitored domains are within target and no new critical or "
            "attention items were recorded this week."
        )

    # First sentence: critical + attention clauses, joined "and" per the
    # mockup's shape ("{n} new critical item(s) ({top title}) and {n}
    # attention items."), each clause omitted entirely when its count is 0.
    lead_parts = []
    if criticals:
        n = len(criticals)
        top_title = criticals[0].get("title") or "an unnamed item"
        lead_parts.append(f"{n} new critical item{'s' if n != 1 else ''} ({top_title})")
    if warnings_:
        n = len(warnings_)
        lead_parts.append(f"{n} attention item{'s' if n != 1 else ''}")

    sentences = []
    if lead_parts:
        sentences.append(" and ".join(lead_parts) + ".")

    # Second sentence: "{domains} improving; {domains} degrading."
    if improving or degrading:
        trend_parts = []
        if improving:
            trend_parts.append(f"{', '.join(improving)} improving")
        if degrading:
            trend_parts.append(f"{', '.join(degrading)} degrading")
        sentences.append("; ".join(trend_parts) + ".")

    return " ".join(sentences)


def _enabled_sources(system: str) -> list[dict]:
    return [s for s in list_sources() if s.get("system") == system and s.get("enabled", True)]


def _fleet_sum(system: str, metric_key: str, ts_iso: str) -> float | None:
    """Mirrors app.domains._fleet_sum's point-in-time fleet aggregation --
    duplicated (not imported) since that helper is private to the scorer;
    kept intentionally tiny and side-by-side with its sibling."""
    total = 0.0
    found = False
    for source in _enabled_sources(system):
        point = get_metric_latest_at_or_before(source["id"], metric_key, ts_iso)
        if point is not None:
            total += point["value"]
            found = True
    return total if found else None


def _fleet_metric_series(system: str, metric_key: str, since_iso: str, max_points: int = 7) -> list[dict]:
    """Per-day fleet sum of a metric across every enabled source of `system`,
    for a tile sparkline. For each source, takes that source's last point of
    each calendar day (its series is ASC-ordered by ts, so the last write
    wins), then sums across sources for that day -- an approximation of
    app.domains._fleet_sum's point-in-time aggregation applied once per day
    instead of just at "now"."""
    per_day: dict[str, dict[str, float]] = {}
    for source in _enabled_sources(system):
        series = get_metric_series(source["id"], metric_key, since_iso)
        last_of_day: dict[str, float] = {}
        for point in series:
            last_of_day[point["ts"][:10]] = point["value"]
        for day, value in last_of_day.items():
            per_day.setdefault(day, {})[source["id"]] = value
    points = [
        {"ts": f"{day}T00:00:00Z", "value": sum(values.values())}
        for day, values in sorted(per_day.items())
    ]
    return downsample_series(points, max_points=max_points)


def _tile(
    *,
    label: str,
    value: float | None,
    unit: str,
    rag: str | None,
    delta: float | None,
    better: bool | None,
    series: list[dict],
) -> dict:
    return {
        "label": label,
        "value": value,
        "unit": unit,
        "rag": rag,
        "delta": delta,
        "better": better,
        "series": series,
    }


def _build_tiles(overall: dict, now: datetime, since_7d_iso: str, baseline_iso: str) -> list[dict]:
    tiles = []

    availability = overall["domains"]["availability"]
    tiles.append(
        _tile(
            label="Availability",
            value=availability["score"],
            unit="%",
            rag=availability["rag"],
            delta=availability["delta"],
            better=(availability["delta"] > 0) if availability["delta"] is not None else None,
            series=downsample_series(
                get_metric_series("_fleet", "domain.availability", since_7d_iso), max_points=7
            ),
        )
    )

    posture = overall["domains"]["posture"]
    tiles.append(
        _tile(
            label="Posture score",
            value=posture["score"],
            unit="/100",
            rag=posture["rag"],
            delta=posture["delta"],
            better=(posture["delta"] > 0) if posture["delta"] is not None else None,
            series=downsample_series(get_metric_series("_fleet", "domain.posture", since_7d_iso), max_points=7),
        )
    )

    vulnerability = overall["domains"]["vulnerability"]
    vuln_inputs = vulnerability["inputs"] or {}
    now_critical = vuln_inputs.get("psirt.devices_critical") or 0
    now_kev = vuln_inputs.get("psirt.kev_exposed_devices") or 0
    now_top = max(now_critical, now_kev)
    baseline_critical = _fleet_sum("4thealth", "psirt.devices_critical", baseline_iso) or 0
    baseline_kev = _fleet_sum("4thealth", "psirt.kev_exposed_devices", baseline_iso) or 0
    baseline_top = max(baseline_critical, baseline_kev)
    vuln_delta = now_top - baseline_top
    tiles.append(
        _tile(
            label="Vulnerable devices",
            value=now_top,
            unit="devices",
            rag=vulnerability["rag"],
            delta=vuln_delta,
            better=vuln_delta < 0 if vuln_delta != 0 or now_top or baseline_top else None,
            # Sparkline tracks the KEV/critical union's dominant contributor
            # (devices_critical) -- kev_exposed_devices is rare/usually a
            # subset in practice, and charting both series' per-day max would
            # add real complexity for a glance sparkline. Documented
            # simplification, not a scoring change (the tile's own number
            # above still uses the true max()).
            series=_fleet_metric_series("4thealth", "psirt.devices_critical", since_7d_iso),
        )
    )

    logging_domain = overall["domains"]["logging"]
    now_silent = _fleet_sum("4tlog", "devices_silent", _now_iso(now)) or 0
    baseline_silent = _fleet_sum("4tlog", "devices_silent", baseline_iso)
    silent_delta = (now_silent - baseline_silent) if baseline_silent is not None else None
    tiles.append(
        _tile(
            label="Silent devices",
            value=now_silent,
            unit="devices",
            rag=logging_domain["rag"],
            delta=silent_delta,
            better=(silent_delta < 0) if silent_delta is not None else None,
            series=_fleet_metric_series("4tlog", "devices_silent", since_7d_iso),
        )
    )

    hygiene = overall["domains"]["hygiene"]
    now_findings = _fleet_sum("4thealth", "rule_hygiene.rule_findings_total", _now_iso(now)) or 0
    baseline_findings = _fleet_sum("4thealth", "rule_hygiene.rule_findings_total", baseline_iso)
    findings_delta = (now_findings - baseline_findings) if baseline_findings is not None else None
    tiles.append(
        _tile(
            label="Hygiene findings",
            value=now_findings,
            unit="findings",
            rag=hygiene["rag"],
            delta=findings_delta,
            better=(findings_delta < 0) if findings_delta is not None else None,
            series=_fleet_metric_series("4thealth", "rule_hygiene.rule_findings_total", since_7d_iso),
        )
    )

    return tiles


def _posture_panels() -> dict:
    """device_review / firmware / change_control rollups, read from the
    first enabled 4thealth source whose latest snapshot carries each key --
    mirrors app.domains.get_infra_devices's "read the latest snapshot
    directly" pattern for rollups that aren't single fleet scalars. Not
    merged/summed across multiple 4thealth sources (an assumption -- most
    deployments run one 4thealth-plus instance; a true multi-source rollup
    merge is left for later if it's ever needed). Each sub-dict stays None
    (never a fabricated zero) when no enabled source's latest snapshot has
    that key at all.
    """
    device_review = None
    firmware = None
    change_control = None
    for source in list_sources():
        if not source.get("enabled", True) or source.get("system") != "4thealth":
            continue
        snapshot = get_latest(source["id"], "summary")
        if snapshot is None:
            continue
        value = snapshot["value"]
        if device_review is None and isinstance(value.get("device_review"), dict):
            device_review = value["device_review"]
        if firmware is None and (
            value.get("version_compliance_pct") is not None or isinstance(value.get("version_breakdown"), dict)
        ):
            firmware = {
                "version_compliance_pct": value.get("version_compliance_pct"),
                "version_breakdown": value.get("version_breakdown"),
            }
        if change_control is None and isinstance(value.get("change_control"), dict):
            change_control = value["change_control"]
    return {"device_review": device_review, "firmware": firmware, "change_control": change_control}


def _freshness_note() -> str:
    """Short source-freshness note for the masthead -- a nice-to-have, not a
    new subsystem, so this just reuses app.collector.poll_status per enabled
    source rather than promoting a new public staleness primitive."""
    from app.collector import poll_status

    sources = [s for s in list_sources() if s.get("enabled", True)]
    if not sources:
        return "No sources configured yet."
    statuses = [poll_status(s["id"]) for s in sources]
    not_ok = [s for s in statuses if s["status"] != "ok"]
    if not not_ok:
        return "All sources current."
    if len(not_ok) == len(sources):
        return "No sources currently reporting."
    return f"{len(not_ok)} of {len(sources)} source(s) not reporting current data."


def build_brief(*, now: datetime | None = None) -> dict:
    """Assemble everything app/templates/brief.html needs for one render.
    Must not crash on a freshly-initialized empty DB -- every field is
    either a sane default or None/[]/omits its panel. See plan section 1."""
    now = now or datetime.now(UTC)
    week_end = now.date()
    week_start = week_end - timedelta(days=6)
    since_7d_iso = _now_iso(now - timedelta(days=7))
    since_30d_iso = _now_iso(now - timedelta(days=30))
    baseline_iso = since_7d_iso  # compare_to="7d" IS "vs the prior 7 days" -- see plan section 1.

    overall = compute_overall(compare_to="7d", now=now)
    events = get_events(since=since_7d_iso)
    domain_deltas = {name: overall["domains"][name]["delta"] for name in DOMAINS}
    status_sentence = build_status_sentence(events, domain_deltas)

    week_key = week_key_for(now)
    scoring = get_scoring_config()

    decisions = []
    for event in events:
        if event.get("severity") != "critical":
            continue
        decisions.append(
            {
                "id": event["id"],
                "ts": event["ts"],
                "title": event["title"],
                "severity": event["severity"],
                "source_name": source_name(event["source_id"]) if event.get("source_id") else None,
                "detail": event["detail"],
            }
        )

    return {
        "week_start": week_start,
        "week_end": week_end,
        "week_key": week_key,
        "generated_at": now,
        "overall": overall,
        "status_sentence": status_sentence,
        "status_word": STATUS_WORD.get(overall["rag"], STATUS_WORD[None]),
        "status_class": STATUS_CLASS.get(overall["rag"], STATUS_CLASS[None]),
        "freshness_note": _freshness_note(),
        "tiles": _build_tiles(overall, now, since_7d_iso, baseline_iso),
        "decisions": decisions,
        "asks": get_brief_asks(week_key),
        "posture_panels": _posture_panels(),
        "trends": {
            "posture": {
                "points": downsample_series(
                    get_metric_series("_fleet", "domain.posture", since_30d_iso), max_points=30
                ),
                "target": scoring["domains"].get("posture", {}).get("target"),
            },
            "logging": {
                "points": downsample_series(
                    get_metric_series("_fleet", "domain.logging", since_30d_iso), max_points=30
                ),
                "target": scoring["domains"].get("logging", {}).get("target"),
            },
        },
    }
