import json

import bcrypt
import pytest

import app.auth as auth_module
import app.config_paths as config_paths


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
