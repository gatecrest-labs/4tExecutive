"""Dashboard routes: the Trend Board and the (currently unused-by-any-page)
saved-layout edit/save endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint, Response, jsonify, make_response, render_template, request, session

from app.board import DOMAIN_ORDER, build_rows, rows_to_csv
from app.decorators import tab_required
from app.domains import DOMAINS
from app.events import positioned_ticks
from app.layouts import get_layout, save_layout
from app.metrics_db import get_events
from app.sources import list_sources
from app.widgets import (
    BASELINES,
    DEFAULT_COMPARE_TO,
    DEFAULT_SPARKLINE,
    SPARKLINE_WINDOWS,
    WIDGET_CATALOG,
    annotate,
    default_layout,
    group_by_system,
)

bp = Blueprint("dashboard", __name__)

SORT_KEYS = ("status", "delta", "name")
DEFAULT_SORT = "status"


def _resolve_compare_to() -> str:
    compare_to = request.cookies.get("compare_to") or DEFAULT_COMPARE_TO
    return compare_to if compare_to in BASELINES else DEFAULT_COMPARE_TO


def _resolve_sparkline() -> str:
    """Resolve the sparkline window: a `?range=` value that happens to also be
    a valid sparkline window (30d/90d/1y) is an alias for it (see the
    metric-points design), otherwise falls back to the sparkline cookie, then
    the default.
    """
    query_range = request.args.get("range")
    if query_range in SPARKLINE_WINDOWS:
        return query_range
    sparkline = request.cookies.get("sparkline") or DEFAULT_SPARKLINE
    return sparkline if sparkline in SPARKLINE_WINDOWS else DEFAULT_SPARKLINE


def _resolve_domain_filter() -> str | None:
    domain_filter = request.args.get("domain") or request.cookies.get("domain_filter")
    return domain_filter if domain_filter in DOMAIN_ORDER else None


def _resolve_source_filter() -> str | None:
    valid_ids = {s["id"] for s in list_sources()}
    source_filter = request.args.get("source") or request.cookies.get("source_filter")
    return source_filter if source_filter in valid_ids else None


def _resolve_sort() -> str:
    sort = request.args.get("sort", DEFAULT_SORT)
    return sort if sort in SORT_KEYS else DEFAULT_SORT


def _board_context():
    compare_to = _resolve_compare_to()
    sparkline = _resolve_sparkline()
    domain_filter = _resolve_domain_filter()
    source_filter = _resolve_source_filter()
    sort = _resolve_sort()
    rows = build_rows(
        compare_to=compare_to,
        sparkline=sparkline,
        domain_filter=domain_filter,
        source_filter=source_filter,
        sort=sort,
    )
    since = (datetime.now(UTC) - SPARKLINE_WINDOWS[sparkline]).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = get_events(since=since)
    for row in rows:
        row_events = [e for e in events if e["source_id"] == row["source_instance"] and e["metric_key"] == row["metric_key"]]
        row["ticks"] = positioned_ticks(row["series"], row_events, width=240)
    return {
        "rows": rows,
        "compare_to": compare_to,
        "sparkline": sparkline,
        "domain_filter": domain_filter,
        "source_filter": source_filter,
        "sort": sort,
    }


def _set_board_cookies(response) -> None:
    if request.args.get("range") and request.args["range"] in SPARKLINE_WINDOWS:
        response.set_cookie("sparkline", request.args["range"], max_age=60 * 60 * 24 * 365, samesite="Lax")
    if request.args.get("domain"):
        response.set_cookie("domain_filter", request.args["domain"], max_age=60 * 60 * 24 * 365, samesite="Lax")
    if request.args.get("source"):
        response.set_cookie("source_filter", request.args["source"], max_age=60 * 60 * 24 * 365, samesite="Lax")


@bp.route("/board")
@tab_required("dashboard")
def index():
    context = _board_context()
    domains = [{"name": name, "label": DOMAINS[name]["label"]} for name in DOMAIN_ORDER]
    response = make_response(
        render_template(
            "board.html",
            **context,
            domains=domains,
            sources=list_sources(),
        )
    )
    _set_board_cookies(response)
    return response


@bp.route("/board.csv")
@tab_required("dashboard")
def board_csv():
    context = _board_context()
    response = Response(rows_to_csv(context["rows"]), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=trend-board.csv"
    return response


@bp.route("/dashboard/edit")
@tab_required("dashboard")
def edit():
    layout = get_layout(session["username"]) or default_layout()
    widgets = [annotate(widget, with_data=False) for widget in layout]
    for i, widget in enumerate(widgets, start=1):
        widget["index"] = i
    return render_template(
        "dashboard.html", sections=group_by_system(widgets), edit_mode=True, catalog=WIDGET_CATALOG
    )


@bp.route("/dashboard/layout", methods=["POST"])
@tab_required("dashboard")
def update_layout():
    # CSRF-protected like every other POST route (see app/__init__.py). No JS
    # calls this yet; when the edit-mode UI is wired up, send the token from
    # the `csrf-token` <meta> tag in base.html as an `X-CSRFToken` header.
    widgets = request.get_json(silent=True)
    if widgets is None:
        return jsonify({"error": "expected a JSON array of widgets"}), 400
    if not isinstance(widgets, list) or not all(
        isinstance(widget, dict) and isinstance(widget.get("type"), str) for widget in widgets
    ):
        return jsonify({"error": "expected a JSON array of widget objects with a 'type'"}), 400
    try:
        save_layout(session["username"], widgets)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return "", 204
