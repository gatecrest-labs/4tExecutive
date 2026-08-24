"""Dashboard routes: personalized view and edit modes."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, session

from app.decorators import tab_required
from app.layouts import get_layout, save_layout
from app.widgets import WIDGET_CATALOG, get_widget_value

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@tab_required("dashboard")
def index():
    layout = get_layout(session["username"])
    widgets = []
    for widget in layout:
        entry = WIDGET_CATALOG[widget["type"]]
        widgets.append(
            {
                **widget,
                "label": entry["label"],
                "data": get_widget_value(widget),
            }
        )
    return render_template("dashboard.html", widgets=widgets, edit_mode=False, catalog=None)


@bp.route("/dashboard/edit")
@tab_required("dashboard")
def edit():
    layout = get_layout(session["username"])
    widgets = [
        {**widget, "label": WIDGET_CATALOG[widget["type"]]["label"]} for widget in layout
    ]
    return render_template(
        "dashboard.html", widgets=widgets, edit_mode=True, catalog=WIDGET_CATALOG
    )


@bp.route("/dashboard/layout", methods=["POST"])
@tab_required("dashboard")
def update_layout():
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
