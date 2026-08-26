import json

import bcrypt
import pytest

import app.auth as auth_module
import app.groups as groups_module
from app import config_paths, create_app


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    examples_dir = config_dir / "examples"
    examples_dir.mkdir(parents=True)
    monkeypatch.setattr(config_paths, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_paths, "EXAMPLES_DIR", examples_dir)
    return config_dir, examples_dir


@pytest.fixture
def tmp_users_file(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    password_hash = bcrypt.hashpw(b"correct-horse", bcrypt.gensalt()).decode()
    users_path.write_text(
        json.dumps({"users": [{"username": "alice", "password_hash": password_hash}]})
    )
    monkeypatch.setattr(auth_module, "USERS_PATH", users_path)
    return users_path


@pytest.fixture
def tmp_groups_file(tmp_path, monkeypatch):
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps(
            {
                "executives": {"members": ["alice"], "allowed_tabs": ["dashboard"]},
                "administrators": {
                    "members": ["alice"],
                    "allowed_tabs": ["dashboard", "admin"],
                },
                "developers": {"members": ["carol"], "allowed_tabs": ["admin"]},
            }
        )
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)
    return groups_path


@pytest.fixture
def app(tmp_config_dir, tmp_path, monkeypatch):
    import app.metrics_db as metrics_db_module

    monkeypatch.setattr(metrics_db_module, "DB_PATH", tmp_path / "metrics.db")
    flask_app = create_app(testing=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
