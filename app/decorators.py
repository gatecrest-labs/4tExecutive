"""Route guards for login and tab-level access control."""

from __future__ import annotations

from functools import wraps

from flask import abort, redirect, session, url_for

from app.groups import user_has_tab


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)

    return wrapper


def tab_required(tab: str):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if not user_has_tab(session["username"], tab):
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
