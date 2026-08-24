"""Dashboard routes (placeholder until Task 12)."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    return "placeholder"
