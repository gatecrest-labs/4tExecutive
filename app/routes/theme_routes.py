"""Light/dark theme toggle, persisted as a cookie so the server renders the
correct data-theme attribute on the very first response — no client-side
flash of the wrong theme."""

from __future__ import annotations

from flask import Blueprint, redirect, request

bp = Blueprint("theme", __name__)

VALID_THEMES = {"light", "dark"}


@bp.route("/theme", methods=["POST"])
def set_theme():
    theme = request.form.get("theme")
    if theme not in VALID_THEMES:
        theme = "light"
    destination = request.form.get("next") or "/"
    response = redirect(destination)
    response.set_cookie("theme", theme, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response
