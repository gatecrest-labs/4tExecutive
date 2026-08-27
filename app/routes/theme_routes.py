"""Light/dark theme toggle, persisted as a cookie so the server renders the
correct data-theme attribute on the very first response — no client-side
flash of the wrong theme."""

from __future__ import annotations

from flask import Blueprint, redirect, request

bp = Blueprint("theme", __name__)

VALID_THEMES = {"light", "dark"}


def _is_safe_redirect_target(destination: str | None) -> bool:
    """Validate destination is a same-origin relative path.

    Rejects absolute URLs, protocol-relative URLs (//) and other off-site
    redirects. Only allows paths starting with /.
    """
    if not destination:
        return False
    # Reject protocol-relative URLs (//example.com) and absolute URLs
    if destination.startswith("//") or "://" in destination:
        return False
    # Only allow relative paths starting with /
    return destination.startswith("/")


@bp.route("/theme", methods=["POST"])
def set_theme():
    theme = request.form.get("theme")
    if theme not in VALID_THEMES:
        theme = "light"
    destination = request.form.get("next") or "/"
    # Validate destination to prevent open redirect attacks
    if not _is_safe_redirect_target(destination):
        destination = "/"
    response = redirect(destination)
    response.set_cookie("theme", theme, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response
