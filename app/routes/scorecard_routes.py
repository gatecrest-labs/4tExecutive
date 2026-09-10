"""Scorecard routes: the domain-graded landing page and per-domain drill-down."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import Blueprint, abort, jsonify, render_template, request

from app.decorators import tab_required
from app.domains import DOMAINS, compute_domain, compute_overall, domain_member_table
from app.events import event_domain, positioned_ticks
from app.metrics_db import get_events, get_metric_series
from app.widgets import downsample_series

bp = Blueprint("scorecard", __name__)

DETAIL_WINDOWS: dict[str, timedelta] = {
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "1y": timedelta(days=365),
}
DEFAULT_DETAIL_WINDOW = "90d"
SPARKLINE_LOOKBACK_DAYS = 90
WHAT_CHANGED_DAYS = 7
DEFAULT_EVENTS_DAYS = 30


def _domain_sparkline(name: str) -> list[dict]:
    since = (datetime.now(UTC) - timedelta(days=SPARKLINE_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    series = get_metric_series("_fleet", f"domain.{name}", since)
    return downsample_series(series, max_points=90)


def _what_changed() -> list[dict]:
    since = (datetime.now(UTC) - timedelta(days=WHAT_CHANGED_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = get_events(since=since)
    for event in events:
        event["domain"] = event_domain(event)
    return events


def _threshold_cross_events(since: str, domain: str) -> list[dict]:
    return [
        e for e in get_events(since=since) if e["kind"] == "threshold_cross" and e["detail"].get("domain") == domain
    ]


@bp.route("/")
@tab_required("dashboard")
def index():
    overall = compute_overall()
    sparkline_since = (datetime.now(UTC) - timedelta(days=SPARKLINE_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cards = []
    for name in DOMAINS:
        result = overall["domains"][name]
        sparkline = _domain_sparkline(name)
        ticks = positioned_ticks(sparkline, _threshold_cross_events(sparkline_since, name), width=240)
        cards.append({**result, "sparkline": sparkline, "ticks": ticks})
    return render_template("scorecard.html", overall=overall, cards=cards, what_changed=_what_changed())


@bp.route("/domain/<name>")
@tab_required("dashboard")
def detail(name):
    if name not in DOMAINS:
        abort(404)
    window = request.args.get("window", DEFAULT_DETAIL_WINDOW)
    if window not in DETAIL_WINDOWS:
        window = DEFAULT_DETAIL_WINDOW
    since = (datetime.now(UTC) - DETAIL_WINDOWS[window]).strftime("%Y-%m-%dT%H:%M:%SZ")
    series = downsample_series(get_metric_series("_fleet", f"domain.{name}", since), max_points=120)
    ticks = positioned_ticks(series, _threshold_cross_events(since, name), width=600)

    result = compute_domain(name)
    members = domain_member_table(name)
    return render_template(
        "domain_detail.html",
        domain=result,
        members=members,
        series=series,
        ticks=ticks,
        window=window,
        windows=list(DETAIL_WINDOWS),
    )


@bp.route("/events")
@tab_required("dashboard")
def events_json():
    days = request.args.get("days", DEFAULT_EVENTS_DAYS, type=int) or DEFAULT_EVENTS_DAYS
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return jsonify(get_events(since=since))
