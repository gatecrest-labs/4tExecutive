"""Dashboard routes: personalized view and edit modes."""

from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint, jsonify, make_response, render_template, request, session

from app.decorators import tab_required
from app.layouts import get_layout, save_layout
from app.sources import get_source
from app.widgets import DEFAULT_RANGE, RANGES, WIDGET_CATALOG, annotate, default_layout

bp = Blueprint("dashboard", __name__)


def _resolve_range() -> str:
    range_key = request.args.get("range") or request.cookies.get("range") or DEFAULT_RANGE
    return range_key if range_key in RANGES else DEFAULT_RANGE


def _posture(widgets: list[dict]) -> dict | None:
    """Aggregate already-computed per-widget RAG state and freshness into one summary row.

    No new queries — reads widget["data"]["rag"] / ["collected_at"] from the
    already-annotated widget list. Returns None when no widget in the layout
    carries a RAG state (nothing to summarize).
    """
    rag_widgets = [(i, w) for i, w in enumerate(widgets, start=1) if w.get("data") and w["data"].get("rag")]
    if not rag_widgets:
        return None

    reds = [i for i, w in rag_widgets if w["data"]["rag"] == "red"]
    ambers = [i for i, w in rag_widgets if w["data"]["rag"] == "amber"]
    overall = "Critical" if reds else "Attention" if ambers else "OK"
    first_offender_index = reds[0] if reds else (ambers[0] if ambers else None)

    timestamps = [w["data"]["collected_at"] for w in widgets if w.get("data") and w["data"].get("collected_at")]
    oldest_minutes_ago = None
    stale = False
    if timestamps:
        oldest = min(timestamps)
        oldest_dt = datetime.fromisoformat(oldest)
        oldest_minutes_ago = round((datetime.now(UTC) - oldest_dt).total_seconds() / 60)
        longest_interval = max(
            (get_source(w["source_instance"]) or {}).get("poll_interval_minutes", 15) for w in widgets
        )
        stale = oldest_minutes_ago > 2 * longest_interval

    return {
        "overall": overall,
        "critical_count": len(reds),
        "attention_count": len(ambers),
        "oldest_minutes_ago": oldest_minutes_ago,
        "stale": stale,
        "first_offender_index": first_offender_index,
    }


@bp.route("/")
@tab_required("dashboard")
def index():
    # Falls back to one widget per catalog entry x enabled matching source
    # when the user hasn't saved a custom layout, so the dashboard shows
    # everything currently configured instead of being blank by default —
    # see app/widgets.py:default_layout.
    range_key = _resolve_range()
    layout = get_layout(session["username"]) or default_layout()
    widgets = [annotate(widget, with_data=True, range_key=range_key) for widget in layout]
    posture = _posture(widgets)
    response = make_response(
        render_template(
            "dashboard.html",
            widgets=widgets,
            edit_mode=False,
            catalog=None,
            range_key=range_key,
            posture=posture,
        )
    )
    if request.args.get("range"):
        response.set_cookie("range", range_key, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


@bp.route("/dashboard/edit")
@tab_required("dashboard")
def edit():
    layout = get_layout(session["username"]) or default_layout()
    widgets = [annotate(widget, with_data=False) for widget in layout]
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
