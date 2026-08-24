"""Flask app factory for 4tExecutive."""

from __future__ import annotations

import os

from flask import Flask

from app.config_paths import bootstrap_config
from app.groups import user_has_tab

# Matches the placeholder value shipped in .env.example — if an operator copies
# .env.example to .env without changing it, we must refuse to boot rather than
# sign session cookies with a publicly known key.
_PLACEHOLDER_SECRET_KEY = "change-me-to-a-random-value"


def _resolve_cookie_secure() -> bool:
    """Mirror 4thealth's convention: auto-enable Secure cookies when TLS cert
    files are present, override with COOKIE_SECURE=true|false."""
    cert = os.environ.get("SSL_CERT", "certs/cert.pem")
    key = os.environ.get("SSL_KEY", "certs/key.pem")
    ssl_active = os.path.exists(cert) and os.path.exists(key)
    setting = os.environ.get("COOKIE_SECURE", "auto").lower()
    return setting == "true" or (setting == "auto" and ssl_active)


def create_app(testing: bool = False) -> Flask:
    flask_app = Flask(__name__)

    if testing:
        flask_app.secret_key = "dev-only-change-me"
    else:
        secret_key = os.environ.get("SECRET_KEY")
        if not secret_key or secret_key == _PLACEHOLDER_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY environment variable must be set to a real secret "
                "value (not the .env.example placeholder) before starting the "
                "app outside of testing mode."
            )
        flask_app.secret_key = secret_key

    flask_app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    flask_app.config["SESSION_COOKIE_SECURE"] = _resolve_cookie_secure()
    flask_app.testing = testing

    if not testing:
        bootstrap_config()

    from app.metrics_db import init_db

    init_db()

    from app.routes.auth_routes import bp as auth_bp

    flask_app.register_blueprint(auth_bp)

    from app.routes.dashboard_routes import bp as dashboard_bp

    flask_app.register_blueprint(dashboard_bp)

    from app.routes.admin_routes import bp as admin_bp

    flask_app.register_blueprint(admin_bp)

    flask_app.jinja_env.globals["user_has_tab"] = user_has_tab

    if not testing:
        from app.collector import init_scheduler

        init_scheduler(flask_app)

    return flask_app
