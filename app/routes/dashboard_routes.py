"""Dashboard routes: personalized view and edit modes."""

from __future__ import annotations

from flask import Blueprint, jsonify, make_response, render_template, request, session

from app.decorators import tab_required
from app.layouts import get_layout, save_layout
from app.sources import get_source
from app.widgets import DEFAULT_RANGE, RANGES, WIDGET_CATALOG, default_layout, get_widget_series

bp = Blueprint("dashboard", __name__)


def _source_name(source_instance: str) -> str:
    source = get_source(source_instance)
    return source["name"] if source else source_instance


def _annotate(widget: dict, *, with_data: bool, range_key: str = DEFAULT_RANGE) -> dict:
    entry = WIDGET_CATALOG[widget["type"]]
    annotated = {
        **widget,
        "label": entry["label"],
        "source_name": _source_name(widget["source_instance"]),
    }
    if with_data:
        annotated["data"] = get_widget_series(widget, range_key)
    return annotated


def _resolve_range() -> str:
    range_key = request.args.get("range") or request.cookies.get("range") or DEFAULT_RANGE
    return range_key if range_key in RANGES else DEFAULT_RANGE


@bp.route("/")
@tab_required("dashboard")
def index():
    # Falls back to one widget per catalog entry x enabled matching source
    # when the user hasn't saved a custom layout, so the dashboard shows
    # everything currently configured instead of being blank by default —
    # see app/widgets.py:default_layout.
    range_key = _resolve_range()
    layout = get_layout(session["username"]) or default_layout()
    widgets = [_annotate(widget, with_data=True, range_key=range_key) for widget in layout]
    response = make_response(
        render_template(
            "dashboard.html",
            widgets=widgets,
            edit_mode=False,
            catalog=None,
            range_key=range_key,
            ranges=list(RANGES),
        )
    )
    if request.args.get("range"):
        response.set_cookie("range", range_key, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


@bp.route("/dashboard/edit")
@tab_required("dashboard")
def edit():
    layout = get_layout(session["username"]) or default_layout()
    widgets = [_annotate(widget, with_data=False) for widget in layout]
    return render_template(
        "dashboard.html", widgets=widgets, edit_mode=True, catalog=WIDGET_CATALOG
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
