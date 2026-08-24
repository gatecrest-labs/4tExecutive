"""Flask app factory for 4tExecutive."""

from __future__ import annotations

import os

from flask import Flask

from app.config_paths import bootstrap_config
from app.groups import user_has_tab


def create_app(testing: bool = False) -> Flask:
    flask_app = Flask(__name__)
    flask_app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
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
