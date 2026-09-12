"""Brief routes: GET /brief (the weekly executive brief) and POST /brief/asks.

Tab convention: app.decorators.tab_required(tab) checks an arbitrary string
against whatever tabs a user's group(s) list in config/groups.json's
"allowed_tabs" (see app/groups.py) -- it's a generic, open-ended vocabulary,
not a fixed enum. "brief" (view the brief) and "brief_edit" (edit the "asks
for leadership" list) are two NEW tab strings introduced here, following the
exact same pattern "dashboard"/"admin" already use elsewhere. No other code
change is needed to grant them -- an operator just adds the string to a
group's allowed_tabs in groups.json (see docs/customizing-dashboard.md).
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.brief import build_brief, week_key_for
from app.decorators import tab_required
from app.groups import user_has_tab
from app.metrics_db import save_brief_asks

bp = Blueprint("brief", __name__)


@bp.route("/brief")
@tab_required("brief")
def index():
    brief = build_brief()
    can_edit_asks = user_has_tab(session["username"], "brief_edit")
    return render_template("brief.html", brief=brief, can_edit_asks=can_edit_asks)


@bp.route("/brief/asks", methods=["POST"])
@tab_required("brief_edit")
def save_asks():
    # week_key comes from a hidden form field (the week being edited) rather
    # than being recomputed from "now" here, so a stale page submit (open
    # Sunday night, submit Monday morning) still targets the week the user
    # was actually looking at.
    week_key = request.form.get("week_key") or week_key_for()
    asks = [a.strip() for a in request.form.getlist("ask") if a.strip()]
    save_brief_asks(week_key, asks, session["username"])
    return redirect(url_for("brief.index"))
