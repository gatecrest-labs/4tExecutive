# 4tExecutive Core App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 4tExecutive Flask app — config layout, local auth/groups, Admin tab (source registry + manual refresh), a scheduled collector with a SQLite cache, and a Dashboard tab with a predefined widget catalog and per-user layouts — fully testable with mocked source HTTP responses, no dependency on 4thealth/4tlog changes.

**Architecture:** Three layers inside one Flask app: (1) a source registry + APScheduler collector that polls each configured source's `/external/api/executive/summary` and writes snapshots to a local SQLite cache (`metrics.db`); (2) a widget-catalog data layer that reads only from that cache; (3) route/template layers for Dashboard (personalized, view/edit mode) and Admin (source CRUD, manual refresh), gated by `groups.json` `allowed_tabs`, matching 4thealth's blueprint/decorator conventions.

**Tech Stack:** Python 3.11+, Flask 3.x, bcrypt, APScheduler, requests, stdlib `sqlite3`, pytest, gunicorn (prod).

**Spec:** `docs/superpowers/specs/2026-08-24-4texecutive-design.md`

## Global Constraints

- Python `>=3.11`, Flask `>=3.1,<4` (matching 4thealth's `pyproject.toml` floor).
- All config lives under `config/`; real files gitignored, `config/examples/*.example.json` tracked. See spec "Config file layout".
- The web app never calls a source synchronously during a page render — all widget data comes from `metrics.db`. See spec "Architecture".
- Passwords are bcrypt-hashed; nothing plaintext in `config/users.json`.
- **Correction to the spec's `sources.json` example:** the `token` field stores the raw bearer token 4tExecutive presents to each source (not a hash) — 4tExecutive is the API *client* here, so it must have the literal token to send as `Authorization: Bearer <token>`. Hashing applies on the *source's* side to tokens it issues and validates (that's the source-side plan, not this one). Protect it via `config/` being gitignored and `chmod 700`, matching the spec's security section.
- Exceptions during a source poll are caught, logged, and degrade gracefully (never crash the scheduler loop) — matching 4thealth's documented "catch, log, degrade gracefully" convention (see its `pyproject.toml` `ruff` ignore comment for `BLE001`/`S110`/`S112`).
- No live-network tests against real source systems; collector tests mock `requests` calls.

**Scope decisions vs. the spec (YAGNI trims, noted for reviewers):**
- The spec's Admin bullet lists "source registry CRUD, users/groups, refresh intervals,
  token management, widget catalog config." This plan implements source **C**reate,
  **R**ead, **D**elete, and manual refresh (Task 13) — no web "edit source" form (an
  `update_source()` function exists in `app/sources.py` for future use, just no route
  yet). User/group management stays CLI-only via `manage_users.py` (Task 14), mirroring
  4thealth's own `manage_users.py`, rather than a web UI — `groups.json` is edited
  directly by an operator. The widget catalog is a static `WIDGET_CATALOG` dict in code
  (Task 9), not admin-editable. All four are reasonable v1 cuts; upgrading any of them
  to a full web UI is straightforward follow-up work once there's a concrete need.
- The spec's security section calls for verifying source TLS certs against
  `config/certs/`. This plan relies on `requests`' default system-trust-store
  verification (`poll_source` never disables verification) rather than wiring up a
  custom CA bundle — sufficient if sources use certs from a trusted CA; pinning to
  `config/certs/` is a small follow-up if sources use internal/self-signed CAs.

---

## File Structure

```
4tExecutive/
  app/
    __init__.py            # Flask app factory, blueprint registration, scheduler init
    config_paths.py        # CONFIG_DIR, EXAMPLES_DIR, bootstrap_config()
    atomic_io.py            # atomic_write_json(), read_json()
    auth.py                  # get_user(), verify_password(), hash_password()
    groups.py                 # get_user_groups(), user_has_tab()
    decorators.py              # login_required, tab_required(tab)
    app_settings.py             # get_setting(), set_setting()
    sources.py                   # source registry CRUD, source_headers()
    metrics_db.py                 # SQLite schema/access: snapshots, last_polled, layouts
    collector.py                   # poll_source(), poll_all(), poll_now(), init_scheduler()
    widgets.py                      # WIDGET_CATALOG, get_widget_value()
    layouts.py                       # get_layout(), save_layout()
    routes/
      __init__.py
      auth_routes.py                  # /login, /logout
      dashboard_routes.py              # /, /dashboard/edit, /dashboard/layout
      admin_routes.py                   # /admin/sources, /admin/sources/<id>/refresh
    templates/
      base.html
      login.html
      dashboard.html
      admin/
        sources.html
    static/
      css/app.css
  config/
    examples/
      users.example.json
      groups.example.json
      sources.example.json
      app_settings.example.json
  tests/
    conftest.py
    test_config_paths.py
    test_atomic_io.py
    test_auth.py
    test_groups.py
    test_app_settings.py
    test_sources.py
    test_metrics_db.py
    test_collector.py
    test_widgets.py
    test_layouts.py
    test_dashboard_routes.py
    test_admin_routes.py
  manage_users.py           # CLI: create/list/delete user, mirrors 4thealth's script
  pyproject.toml
  wsgi.py
  Dockerfile
  docker-compose.yml
  .gitignore
```

---

### Task 1: Project scaffolding & config bootstrap

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `app/__init__.py` (empty package marker for now — app factory comes in Task 5)
- Create: `app/config_paths.py`
- Create: `config/examples/users.example.json`
- Create: `config/examples/groups.example.json`
- Create: `config/examples/sources.example.json`
- Create: `config/examples/app_settings.example.json`
- Test: `tests/test_config_paths.py`
- Test: `tests/conftest.py`

**Interfaces:**
- Produces: `CONFIG_DIR: Path`, `EXAMPLES_DIR: Path`, `bootstrap_config() -> None` in `app/config_paths.py`. `bootstrap_config()` copies any `EXAMPLES_DIR/*.example.json` to `CONFIG_DIR/<name without .example>` if the target doesn't already exist.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "4texecutive"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "flask>=3.1.3,<4",
    "python-dotenv>=1.2.3",
    "requests>=2.34.2",
    "bcrypt>=5.0.0",
    "apscheduler>=3.11.3",
]

[project.optional-dependencies]
prod = ["gunicorn>=26.1.0"]

[tool.uv]
package = false

[dependency-groups]
dev = [
    "pytest>=9.1.1",
    "ruff>=0.16.3",
]
```

- [ ] **Step 2: Write `.gitignore`**

```
config/*.json
!config/examples/*.example.json
config/certs/
metrics.db
.env
__pycache__/
*.pyc
.venv/
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 3: Create `app/__init__.py` as an empty package marker**

```python
```

- [ ] **Step 4: Write the example config files**

`config/examples/users.example.json`:
```json
{
  "users": [
    {
      "username": "admin",
      "password_hash": "REPLACE_WITH_BCRYPT_HASH"
    }
  ]
}
```

`config/examples/groups.example.json`:
```json
{
  "executives": {
    "members": ["admin"],
    "allowed_tabs": ["dashboard"]
  },
  "administrators": {
    "members": ["admin"],
    "allowed_tabs": ["dashboard", "admin"]
  }
}
```

`config/examples/sources.example.json`:
```json
{
  "sources": []
}
```

`config/examples/app_settings.example.json`:
```json
{}
```

- [ ] **Step 5: Write the failing test for `bootstrap_config()`**

```python
# tests/test_config_paths.py
import json

from app.config_paths import bootstrap_config


def test_bootstrap_copies_missing_examples(tmp_config_dir):
    config_dir, examples_dir = tmp_config_dir
    (examples_dir / "sources.example.json").write_text(json.dumps({"sources": []}))

    bootstrap_config()

    assert (config_dir / "sources.json").exists()
    assert json.loads((config_dir / "sources.json").read_text()) == {"sources": []}


def test_bootstrap_does_not_overwrite_existing_file(tmp_config_dir):
    config_dir, examples_dir = tmp_config_dir
    (examples_dir / "sources.example.json").write_text(json.dumps({"sources": []}))
    (config_dir / "sources.json").write_text(json.dumps({"sources": [{"id": "keep-me"}]}))

    bootstrap_config()

    assert json.loads((config_dir / "sources.json").read_text()) == {
        "sources": [{"id": "keep-me"}]
    }
```

```python
# tests/conftest.py
import pytest

import app.config_paths as config_paths


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    examples_dir = config_dir / "examples"
    examples_dir.mkdir(parents=True)
    monkeypatch.setattr(config_paths, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_paths, "EXAMPLES_DIR", examples_dir)
    return config_dir, examples_dir
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_config_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config_paths'` (or `ImportError: cannot import name 'bootstrap_config'`)

- [ ] **Step 7: Write `app/config_paths.py`**

```python
"""Central config directory paths and first-run bootstrap."""

from __future__ import annotations

import shutil
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"
EXAMPLES_DIR = CONFIG_DIR / "examples"


def bootstrap_config() -> None:
    """Copy any missing config/examples/*.example.json to config/<name>.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not EXAMPLES_DIR.exists():
        return
    for example in EXAMPLES_DIR.glob("*.example.json"):
        target_name = example.name.replace(".example.json", ".json")
        target = CONFIG_DIR / target_name
        if not target.exists():
            shutil.copy(example, target)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_config_paths.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore app/__init__.py app/config_paths.py config/examples tests/test_config_paths.py tests/conftest.py
git commit -m "feat: scaffold project and add config bootstrap"
```

---

### Task 2: Atomic JSON I/O helpers

**Files:**
- Create: `app/atomic_io.py`
- Test: `tests/test_atomic_io.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `atomic_write_json(path: Path, data: dict) -> None`, `read_json(path: Path, default: dict | list | None = None) -> dict | list`. All later config-touching modules (`auth.py`, `groups.py`, `app_settings.py`, `sources.py`) use these.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_atomic_io.py
import json

from app.atomic_io import atomic_write_json, read_json


def test_atomic_write_json_creates_file(tmp_path):
    path = tmp_path / "data.json"
    atomic_write_json(path, {"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}


def test_atomic_write_json_overwrites_existing(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("old")
    atomic_write_json(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 2}


def test_read_json_returns_default_when_missing(tmp_path):
    path = tmp_path / "missing.json"
    assert read_json(path, default={}) == {}


def test_read_json_returns_default_on_corrupt_file(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json")
    assert read_json(path, default={"fallback": True}) == {"fallback": True}


def test_read_json_reads_existing_file(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"a": 1}))
    assert read_json(path) == {"a": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_atomic_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.atomic_io'`

- [ ] **Step 3: Write `app/atomic_io.py`**

```python
"""Atomic JSON file writes and defensive reads."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_atomic_io.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/atomic_io.py tests/test_atomic_io.py
git commit -m "feat: add atomic JSON read/write helpers"
```

---

### Task 3: Local auth (`users.json` + bcrypt)

**Files:**
- Create: `app/auth.py`
- Test: `tests/test_auth.py`
- Modify: `tests/conftest.py` (add `tmp_users_file` fixture)

**Interfaces:**
- Consumes: `app.atomic_io.read_json`, `app.config_paths.CONFIG_DIR`.
- Produces: `get_user(username: str) -> dict | None`, `verify_password(username: str, password: str) -> bool`, `hash_password(password: str) -> str`. Used by `routes/auth_routes.py` (Task 5) and `manage_users.py` (Task 13).

- [ ] **Step 1: Add fixture and write the failing tests**

```python
# tests/conftest.py — add this fixture
import json

import bcrypt
import pytest

import app.auth as auth_module


@pytest.fixture
def tmp_users_file(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    password_hash = bcrypt.hashpw(b"correct-horse", bcrypt.gensalt()).decode()
    users_path.write_text(
        json.dumps({"users": [{"username": "alice", "password_hash": password_hash}]})
    )
    monkeypatch.setattr(auth_module, "USERS_PATH", users_path)
    return users_path
```

```python
# tests/test_auth.py
from app.auth import get_user, hash_password, verify_password


def test_get_user_returns_matching_user(tmp_users_file):
    user = get_user("alice")
    assert user is not None
    assert user["username"] == "alice"


def test_get_user_returns_none_for_unknown_user(tmp_users_file):
    assert get_user("bob") is None


def test_verify_password_accepts_correct_password(tmp_users_file):
    assert verify_password("alice", "correct-horse") is True


def test_verify_password_rejects_wrong_password(tmp_users_file):
    assert verify_password("alice", "wrong-password") is False


def test_verify_password_rejects_unknown_user(tmp_users_file):
    assert verify_password("nobody", "anything") is False


def test_hash_password_produces_verifiable_hash():
    hashed = hash_password("new-password")
    import bcrypt

    assert bcrypt.checkpw(b"new-password", hashed.encode())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: Write `app/auth.py`**

```python
"""Local user store and bcrypt password verification."""

from __future__ import annotations

import bcrypt

from app.atomic_io import read_json
from app.config_paths import CONFIG_DIR

USERS_PATH = CONFIG_DIR / "users.json"


def _load_users() -> list[dict]:
    return read_json(USERS_PATH, default={"users": []}).get("users", [])


def get_user(username: str) -> dict | None:
    for user in _load_users():
        if user.get("username") == username:
            return user
    return None


def verify_password(username: str, password: str) -> bool:
    user = get_user(username)
    if user is None:
        return False
    return bcrypt.checkpw(password.encode(), user["password_hash"].encode())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_auth.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_auth.py tests/conftest.py
git commit -m "feat: add local bcrypt user auth"
```

---

### Task 4: Groups, tab gating, and route decorators

**Files:**
- Create: `app/groups.py`
- Create: `app/decorators.py`
- Test: `tests/test_groups.py`
- Modify: `tests/conftest.py` (add `tmp_groups_file` fixture)

**Interfaces:**
- Consumes: `app.atomic_io.read_json`, `app.config_paths.CONFIG_DIR`.
- Produces: `get_user_groups(username: str) -> list[str]`, `user_has_tab(username: str, tab: str) -> bool` in `app/groups.py`; `login_required(fn)`, `tab_required(tab: str)` decorator factory in `app/decorators.py`. Used by `routes/dashboard_routes.py` and `routes/admin_routes.py` (Tasks 11–12).

- [ ] **Step 1: Add fixture and write the failing tests**

```python
# tests/conftest.py — add this fixture
import app.groups as groups_module


@pytest.fixture
def tmp_groups_file(tmp_path, monkeypatch):
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps(
            {
                "executives": {"members": ["alice"], "allowed_tabs": ["dashboard"]},
                "administrators": {
                    "members": ["alice", "carol"],
                    "allowed_tabs": ["dashboard", "admin"],
                },
            }
        )
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)
    return groups_path
```

```python
# tests/test_groups.py
from app.groups import get_user_groups, user_has_tab


def test_get_user_groups_returns_all_groups_containing_user(tmp_groups_file):
    assert set(get_user_groups("alice")) == {"executives", "administrators"}


def test_get_user_groups_returns_empty_for_unknown_user(tmp_groups_file):
    assert get_user_groups("nobody") == []


def test_user_has_tab_true_when_any_group_allows_it(tmp_groups_file):
    assert user_has_tab("carol", "admin") is True


def test_user_has_tab_false_when_no_group_allows_it(tmp_groups_file):
    assert user_has_tab("carol", "dashboard") is False


def test_user_has_tab_false_for_unknown_user(tmp_groups_file):
    assert user_has_tab("nobody", "dashboard") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_groups.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.groups'`

- [ ] **Step 3: Write `app/groups.py`**

```python
"""Group membership and per-tab access control."""

from __future__ import annotations

from app.atomic_io import read_json
from app.config_paths import CONFIG_DIR

GROUPS_PATH = CONFIG_DIR / "groups.json"


def _load_groups() -> dict:
    return read_json(GROUPS_PATH, default={})


def get_user_groups(username: str) -> list[str]:
    groups = _load_groups()
    return [name for name, cfg in groups.items() if username in cfg.get("members", [])]


def user_has_tab(username: str, tab: str) -> bool:
    groups = _load_groups()
    for name in get_user_groups(username):
        if tab in groups.get(name, {}).get("allowed_tabs", []):
            return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_groups.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Write `app/decorators.py` (no dedicated unit test — covered by route tests in Tasks 11–12)**

```python
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
```

- [ ] **Step 6: Commit**

```bash
git add app/groups.py app/decorators.py tests/test_groups.py tests/conftest.py
git commit -m "feat: add group-based tab access control and route decorators"
```

---

### Task 5: App settings store

**Files:**
- Create: `app/app_settings.py`
- Test: `tests/test_app_settings.py`

**Interfaces:**
- Consumes: `app.atomic_io.read_json`, `app.atomic_io.atomic_write_json`, `app.config_paths.CONFIG_DIR`.
- Produces: `get_setting(key: str, default=None)`, `set_setting(key: str, value) -> None`. Used by Admin routes (Task 12) for things like default refresh interval.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_settings.py
import app.app_settings as settings_module
from app.app_settings import get_setting, set_setting


def test_get_setting_returns_default_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", tmp_path / "app_settings.json")
    assert get_setting("refresh_minutes", default=15) == 15


def test_set_setting_then_get_setting_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", tmp_path / "app_settings.json")
    set_setting("refresh_minutes", 30)
    assert get_setting("refresh_minutes") == 30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.app_settings'`

- [ ] **Step 3: Write `app/app_settings.py`**

```python
"""Simple key/value app settings backed by config/app_settings.json."""

from __future__ import annotations

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR

SETTINGS_PATH = CONFIG_DIR / "app_settings.json"


def get_setting(key: str, default=None):
    return read_json(SETTINGS_PATH, default={}).get(key, default)


def set_setting(key: str, value) -> None:
    settings = read_json(SETTINGS_PATH, default={})
    settings[key] = value
    atomic_write_json(SETTINGS_PATH, settings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app_settings.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/app_settings.py tests/test_app_settings.py
git commit -m "feat: add app settings key/value store"
```

---

### Task 6: Source registry

**Files:**
- Create: `app/sources.py`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `app.atomic_io.read_json`, `app.atomic_io.atomic_write_json`, `app.config_paths.CONFIG_DIR`.
- Produces: `list_sources() -> list[dict]`, `get_source(source_id: str) -> dict | None`, `add_source(id, system, name, base_url, token, poll_interval_minutes=15, enabled=True) -> dict`, `update_source(source_id: str, **fields) -> dict | None`, `delete_source(source_id: str) -> None`, `source_headers(source: dict) -> dict`. Used by `collector.py` (Task 7) and `routes/admin_routes.py` (Task 12).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sources.py
import pytest

import app.sources as sources_module
from app.sources import (
    add_source,
    delete_source,
    get_source,
    list_sources,
    source_headers,
    update_source,
)


@pytest.fixture(autouse=True)
def tmp_sources_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")


def test_list_sources_empty_by_default():
    assert list_sources() == []


def test_add_source_then_list_and_get():
    added = add_source(
        id="4thealth-east",
        system="4thealth",
        name="East DC",
        base_url="https://4thealth-east.internal:8100",
        token="secret-token",
    )
    assert added["poll_interval_minutes"] == 15
    assert added["enabled"] is True
    assert [s["id"] for s in list_sources()] == ["4thealth-east"]
    assert get_source("4thealth-east")["name"] == "East DC"


def test_add_source_rejects_duplicate_id():
    add_source(id="dup", system="4thealth", name="A", base_url="https://a", token="t")
    with pytest.raises(ValueError):
        add_source(id="dup", system="4thealth", name="B", base_url="https://b", token="t2")


def test_update_source_changes_fields():
    add_source(id="s1", system="4tlog", name="Log A", base_url="https://a", token="t")
    updated = update_source("s1", enabled=False, poll_interval_minutes=30)
    assert updated["enabled"] is False
    assert updated["poll_interval_minutes"] == 30


def test_update_source_returns_none_for_unknown_id():
    assert update_source("missing", enabled=False) is None


def test_delete_source_removes_it():
    add_source(id="s1", system="4tlog", name="Log A", base_url="https://a", token="t")
    delete_source("s1")
    assert list_sources() == []


def test_source_headers_builds_bearer_header():
    source = {"token": "abc123"}
    assert source_headers(source) == {"Authorization": "Bearer abc123"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sources'`

- [ ] **Step 3: Write `app/sources.py`**

```python
"""Source registry: named source instances 4tExecutive polls for metrics."""

from __future__ import annotations

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR

SOURCES_PATH = CONFIG_DIR / "sources.json"


def _load() -> list[dict]:
    return read_json(SOURCES_PATH, default={"sources": []}).get("sources", [])


def _save(sources: list[dict]) -> None:
    atomic_write_json(SOURCES_PATH, {"sources": sources})


def list_sources() -> list[dict]:
    return _load()


def get_source(source_id: str) -> dict | None:
    for source in _load():
        if source["id"] == source_id:
            return source
    return None


def add_source(
    id: str,
    system: str,
    name: str,
    base_url: str,
    token: str,
    poll_interval_minutes: int = 15,
    enabled: bool = True,
) -> dict:
    sources = _load()
    if any(s["id"] == id for s in sources):
        raise ValueError(f"source id already exists: {id}")
    record = {
        "id": id,
        "system": system,
        "name": name,
        "base_url": base_url,
        "token": token,
        "poll_interval_minutes": poll_interval_minutes,
        "enabled": enabled,
    }
    sources.append(record)
    _save(sources)
    return record


def update_source(source_id: str, **fields) -> dict | None:
    sources = _load()
    for source in sources:
        if source["id"] == source_id:
            source.update(fields)
            _save(sources)
            return source
    return None


def delete_source(source_id: str) -> None:
    sources = [s for s in _load() if s["id"] != source_id]
    _save(sources)


def source_headers(source: dict) -> dict:
    return {"Authorization": f"Bearer {source['token']}"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sources.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/sources.py tests/test_sources.py
git commit -m "feat: add source registry CRUD"
```

---

### Task 7: Metrics cache (SQLite)

**Files:**
- Create: `app/metrics_db.py`
- Test: `tests/test_metrics_db.py`

**Interfaces:**
- Consumes: stdlib `sqlite3`.
- Produces: `init_db() -> None`, `write_snapshot(source_id: str, metric_type: str, value: dict, collected_at: str) -> None`, `get_latest(source_id: str, metric_type: str) -> dict | None` (returns `{"value": dict, "collected_at": str}`), `get_history(source_id: str, metric_type: str, since: str) -> list[dict]`, `set_last_polled(source_id: str, collected_at: str) -> None`, `get_last_polled(source_id: str) -> str | None`, `get_layout(username: str) -> list[dict]`, `save_layout(username: str, widgets: list[dict]) -> None`. Used by `collector.py` (Task 8), `widgets.py` (Task 9), `layouts.py` (Task 10).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_metrics_db.py
import pytest

import app.metrics_db as metrics_db
from app.metrics_db import (
    get_history,
    get_last_polled,
    get_latest,
    get_layout,
    init_db,
    save_layout,
    set_last_polled,
    write_snapshot,
)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    init_db()


def test_write_snapshot_then_get_latest():
    write_snapshot("4thealth-east", "summary", {"hygiene_score": 92}, "2026-08-24T10:00:00Z")
    write_snapshot("4thealth-east", "summary", {"hygiene_score": 95}, "2026-08-24T10:15:00Z")

    latest = get_latest("4thealth-east", "summary")

    assert latest["value"] == {"hygiene_score": 95}
    assert latest["collected_at"] == "2026-08-24T10:15:00Z"


def test_get_latest_returns_none_when_no_data():
    assert get_latest("unknown-source", "summary") is None


def test_get_history_returns_snapshots_since_timestamp_ordered():
    write_snapshot("s1", "summary", {"v": 1}, "2026-08-24T08:00:00Z")
    write_snapshot("s1", "summary", {"v": 2}, "2026-08-24T09:00:00Z")
    write_snapshot("s1", "summary", {"v": 3}, "2026-08-24T10:00:00Z")

    history = get_history("s1", "summary", since="2026-08-24T08:30:00Z")

    assert [h["value"]["v"] for h in history] == [2, 3]


def test_last_polled_roundtrip():
    assert get_last_polled("s1") is None
    set_last_polled("s1", "2026-08-24T10:00:00Z")
    assert get_last_polled("s1") == "2026-08-24T10:00:00Z"


def test_layout_roundtrip():
    assert get_layout("alice") == []
    widgets = [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1"}]
    save_layout("alice", widgets)
    assert get_layout("alice") == widgets


def test_save_layout_overwrites_previous():
    save_layout("alice", [{"type": "a"}])
    save_layout("alice", [{"type": "b"}])
    assert get_layout("alice") == [{"type": "b"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_metrics_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.metrics_db'`

- [ ] **Step 3: Write `app/metrics_db.py`**

```python
"""SQLite-backed cache for collected metrics, poll state, and dashboard layouts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "metrics.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                source_id TEXT NOT NULL,
                metric_type TEXT NOT NULL,
                value_json TEXT NOT NULL,
                collected_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS last_polled (
                source_id TEXT PRIMARY KEY,
                collected_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS layouts (
                username TEXT PRIMARY KEY,
                widgets_json TEXT NOT NULL
            )
            """
        )


def write_snapshot(source_id: str, metric_type: str, value: dict, collected_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO snapshots (source_id, metric_type, value_json, collected_at) "
            "VALUES (?, ?, ?, ?)",
            (source_id, metric_type, json.dumps(value), collected_at),
        )


def get_latest(source_id: str, metric_type: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value_json, collected_at FROM snapshots "
            "WHERE source_id = ? AND metric_type = ? "
            "ORDER BY collected_at DESC LIMIT 1",
            (source_id, metric_type),
        ).fetchone()
    if row is None:
        return None
    return {"value": json.loads(row[0]), "collected_at": row[1]}


def get_history(source_id: str, metric_type: str, since: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT value_json, collected_at FROM snapshots "
            "WHERE source_id = ? AND metric_type = ? AND collected_at >= ? "
            "ORDER BY collected_at ASC",
            (source_id, metric_type, since),
        ).fetchall()
    return [{"value": json.loads(v), "collected_at": c} for v, c in rows]


def set_last_polled(source_id: str, collected_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO last_polled (source_id, collected_at) VALUES (?, ?) "
            "ON CONFLICT(source_id) DO UPDATE SET collected_at = excluded.collected_at",
            (source_id, collected_at),
        )


def get_last_polled(source_id: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT collected_at FROM last_polled WHERE source_id = ?", (source_id,)
        ).fetchone()
    return row[0] if row else None


def get_layout(username: str) -> list[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT widgets_json FROM layouts WHERE username = ?", (username,)
        ).fetchone()
    return json.loads(row[0]) if row else []


def save_layout(username: str, widgets: list[dict]) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO layouts (username, widgets_json) VALUES (?, ?) "
            "ON CONFLICT(username) DO UPDATE SET widgets_json = excluded.widgets_json",
            (username, json.dumps(widgets)),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_metrics_db.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/metrics_db.py tests/test_metrics_db.py
git commit -m "feat: add SQLite metrics cache, poll state, and layout storage"
```

---

### Task 8: Collector (scheduled polling)

**Files:**
- Create: `app/collector.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Consumes: `app.sources.list_sources`, `app.sources.get_source`, `app.sources.source_headers`, `app.metrics_db.write_snapshot`, `app.metrics_db.get_last_polled`, `app.metrics_db.set_last_polled`, `requests.get`.
- Produces: `poll_source(source: dict) -> bool`, `poll_all() -> None`, `poll_now(source_id: str) -> bool`, `init_scheduler(app) -> None`. `init_scheduler` is called from the app factory (Task 11); `poll_now` is called from the Admin "Refresh now" route (Task 12).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_collector.py
from unittest.mock import patch

import pytest
import requests

import app.metrics_db as metrics_db
import app.sources as sources_module
from app.collector import poll_all, poll_now, poll_source
from app.metrics_db import get_last_polled, get_latest, init_db


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    init_db()


def _source(**overrides):
    base = {
        "id": "4thealth-east",
        "system": "4thealth",
        "name": "East DC",
        "base_url": "https://4thealth-east.internal:8100",
        "token": "secret",
        "poll_interval_minutes": 15,
        "enabled": True,
    }
    base.update(overrides)
    return base


def test_poll_source_writes_snapshot_on_success():
    source = _source()
    response_json = {"hygiene_score": 92}

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = response_json

        result = poll_source(source)

    assert result is True
    latest = get_latest("4thealth-east", "summary")
    assert latest["value"] == response_json
    mock_get.assert_called_once()
    called_url = mock_get.call_args.args[0]
    assert called_url == "https://4thealth-east.internal:8100/external/api/executive/summary"
    assert mock_get.call_args.kwargs["headers"] == {"Authorization": "Bearer secret"}


def test_poll_source_returns_false_and_does_not_write_on_http_error():
    source = _source()

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 503
        mock_get.return_value.json.return_value = {}

        result = poll_source(source)

    assert result is False
    assert get_latest("4thealth-east", "summary") is None


def test_poll_source_returns_false_on_connection_error_and_does_not_raise():
    source = _source()

    with patch("app.collector.requests.get", side_effect=requests.ConnectionError("down")):
        result = poll_source(source)

    assert result is False


def test_poll_all_skips_disabled_sources():
    sources_module.add_source(**_source(enabled=False))

    with patch("app.collector.requests.get") as mock_get:
        poll_all()

    mock_get.assert_not_called()


def test_poll_all_skips_sources_not_yet_due():
    sources_module.add_source(**_source())
    from app.metrics_db import set_last_polled

    set_last_polled("4thealth-east", "2099-01-01T00:00:00Z")  # far future -> not due

    with patch("app.collector.requests.get") as mock_get:
        poll_all()

    mock_get.assert_not_called()


def test_poll_all_polls_due_sources():
    sources_module.add_source(**_source())

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"hygiene_score": 92}
        poll_all()

    mock_get.assert_called_once()
    assert get_last_polled("4thealth-east") is not None


def test_poll_now_ignores_due_check():
    sources_module.add_source(**_source())
    from app.metrics_db import set_last_polled

    set_last_polled("4thealth-east", "2099-01-01T00:00:00Z")

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"hygiene_score": 92}
        result = poll_now("4thealth-east")

    assert result is True
    mock_get.assert_called_once()


def test_poll_now_returns_false_for_unknown_source():
    assert poll_now("does-not-exist") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_collector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.collector'`

- [ ] **Step 3: Write `app/collector.py`**

```python
"""Scheduled polling of source systems into the local metrics cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests
from apscheduler.schedulers.background import BackgroundScheduler

from app.metrics_db import get_last_polled, set_last_polled, write_snapshot
from app.sources import get_source, list_sources, source_headers

REQUEST_TIMEOUT_SECONDS = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def poll_source(source: dict) -> bool:
    url = f"{source['base_url']}/external/api/executive/summary"
    try:
        response = requests.get(
            url, headers=source_headers(source), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException:
        return False

    if response.status_code != 200:
        return False

    write_snapshot(source["id"], "summary", response.json(), _now_iso())
    set_last_polled(source["id"], _now_iso())
    return True


def _is_due(source: dict) -> bool:
    last_polled = get_last_polled(source["id"])
    if last_polled is None:
        return True
    last_dt = datetime.strptime(last_polled, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    interval = timedelta(minutes=source["poll_interval_minutes"])
    return datetime.now(timezone.utc) >= last_dt + interval


def poll_all() -> None:
    for source in list_sources():
        if not source.get("enabled", True):
            continue
        if not _is_due(source):
            continue
        poll_source(source)


def poll_now(source_id: str) -> bool:
    source = get_source(source_id)
    if source is None:
        return False
    return poll_source(source)


def init_scheduler(app) -> None:
    scheduler = BackgroundScheduler()
    scheduler.add_job(poll_all, "interval", minutes=1, id="poll_all")
    scheduler.start()
    app.extensions["scheduler"] = scheduler
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_collector.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add app/collector.py tests/test_collector.py
git commit -m "feat: add scheduled source collector"
```

---

### Task 9: Widget catalog

**Files:**
- Create: `app/widgets.py`
- Test: `tests/test_widgets.py`

**Interfaces:**
- Consumes: `app.metrics_db.get_latest`, `app.metrics_db.get_history`.
- Produces: `WIDGET_CATALOG: dict[str, dict]` (keyed by widget type, each entry has `label: str`, `source_system: str`, `metric_type: str`, `field: str`, `default_size: str`), `get_widget_value(widget_instance: dict) -> dict | None` (returns `{"value": ..., "collected_at": str}` or `None` if no data cached yet). Used by `routes/dashboard_routes.py` (Task 11) and `layouts.py` (Task 10, for validation).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_widgets.py
import pytest

import app.metrics_db as metrics_db
from app.metrics_db import init_db, write_snapshot
from app.widgets import WIDGET_CATALOG, get_widget_value


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    init_db()


def test_catalog_contains_expected_widget_types():
    assert "4thealth.hygiene_score" in WIDGET_CATALOG
    assert "4thealth.version_compliance" in WIDGET_CATALOG
    assert "4tlog.log_volume_trend" in WIDGET_CATALOG
    entry = WIDGET_CATALOG["4thealth.hygiene_score"]
    assert entry["source_system"] == "4thealth"
    assert entry["metric_type"] == "summary"


def test_get_widget_value_returns_field_from_latest_snapshot():
    write_snapshot("4thealth-east", "summary", {"hygiene_score": 92}, "2026-08-24T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "4thealth-east"}

    result = get_widget_value(widget)

    assert result == {"value": 92, "collected_at": "2026-08-24T10:00:00Z"}


def test_get_widget_value_returns_none_when_no_snapshot_yet():
    widget = {"type": "4thealth.hygiene_score", "source_instance": "unpolled-source"}
    assert get_widget_value(widget) is None


def test_get_widget_value_raises_for_unknown_widget_type():
    widget = {"type": "not.a.real.widget", "source_instance": "x"}
    with pytest.raises(KeyError):
        get_widget_value(widget)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_widgets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.widgets'`

- [ ] **Step 3: Write `app/widgets.py`**

```python
"""Predefined widget catalog and data lookup for the Dashboard tab."""

from __future__ import annotations

from app.metrics_db import get_latest

WIDGET_CATALOG: dict[str, dict] = {
    "4thealth.hygiene_score": {
        "label": "Hygiene Score",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "hygiene_score",
        "default_size": "1x1",
    },
    "4thealth.version_compliance": {
        "label": "Device Version Compliance %",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "version_compliance_pct",
        "default_size": "1x1",
    },
    "4thealth.pending_config_diffs": {
        "label": "Pending Config Diffs",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "pending_config_diff_count",
        "default_size": "1x1",
    },
    "4thealth.last_backup_status": {
        "label": "Last Backup Status",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "last_backup_status",
        "default_size": "1x1",
    },
    "4thealth.firewall_online_count": {
        "label": "Firewalls Online",
        "source_system": "4thealth",
        "metric_type": "summary",
        "field": "firewall_online_count",
        "default_size": "1x1",
    },
    "4tlog.faz_health": {
        "label": "FortiAnalyzer Health",
        "source_system": "4tlog",
        "metric_type": "summary",
        "field": "faz_health",
        "default_size": "2x1",
    },
    "4tlog.log_volume_trend": {
        "label": "Log Volume Trend",
        "source_system": "4tlog",
        "metric_type": "summary",
        "field": "log_volume_trend",
        "default_size": "2x2",
    },
}


def get_widget_value(widget_instance: dict) -> dict | None:
    entry = WIDGET_CATALOG[widget_instance["type"]]
    latest = get_latest(widget_instance["source_instance"], entry["metric_type"])
    if latest is None:
        return None
    return {
        "value": latest["value"].get(entry["field"]),
        "collected_at": latest["collected_at"],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_widgets.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/widgets.py tests/test_widgets.py
git commit -m "feat: add predefined widget catalog"
```

---

### Task 10: Dashboard layouts

**Files:**
- Create: `app/layouts.py`
- Test: `tests/test_layouts.py`

**Interfaces:**
- Consumes: `app.metrics_db.get_layout`, `app.metrics_db.save_layout`, `app.widgets.WIDGET_CATALOG`.
- Produces: `get_layout(username: str) -> list[dict]`, `save_layout(username: str, widgets: list[dict]) -> None` (raises `ValueError` if any widget's `type` isn't in `WIDGET_CATALOG`). Used by `routes/dashboard_routes.py` (Task 11).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_layouts.py
import pytest

import app.metrics_db as metrics_db
from app.layouts import get_layout, save_layout
from app.metrics_db import init_db


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    init_db()


def test_get_layout_empty_by_default():
    assert get_layout("alice") == []


def test_save_and_get_layout_roundtrip():
    widgets = [
        {"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}
    ]
    save_layout("alice", widgets)
    assert get_layout("alice") == widgets


def test_save_layout_rejects_unknown_widget_type():
    widgets = [{"type": "not.real", "source_instance": "s1", "size": "1x1"}]
    with pytest.raises(ValueError):
        save_layout("alice", widgets)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_layouts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.layouts'`

- [ ] **Step 3: Write `app/layouts.py`**

```python
"""Per-user dashboard layout storage, validated against the widget catalog."""

from __future__ import annotations

from app.metrics_db import get_layout as _get_layout
from app.metrics_db import save_layout as _save_layout
from app.widgets import WIDGET_CATALOG


def get_layout(username: str) -> list[dict]:
    return _get_layout(username)


def save_layout(username: str, widgets: list[dict]) -> None:
    for widget in widgets:
        if widget["type"] not in WIDGET_CATALOG:
            raise ValueError(f"unknown widget type: {widget['type']}")
    _save_layout(username, widgets)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_layouts.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/layouts.py tests/test_layouts.py
git commit -m "feat: add per-user dashboard layout storage with catalog validation"
```

---

### Task 11: App factory, auth routes, and templates base

**Files:**
- Create: `app/routes/__init__.py`
- Create: `app/routes/auth_routes.py`
- Modify: `app/__init__.py` (app factory)
- Create: `app/templates/base.html`
- Create: `app/templates/login.html`
- Create: `app/static/css/app.css`
- Test: `tests/test_auth_routes.py`

**Interfaces:**
- Consumes: `app.auth.verify_password`, `app.config_paths.bootstrap_config`, `app.collector.init_scheduler`.
- Produces: `create_app(testing: bool = False) -> Flask` in `app/__init__.py`. Used by `wsgi.py` (Task 14) and every route test from here on (via a shared `client` fixture).

- [ ] **Step 1: Add a shared Flask test-client fixture**

```python
# tests/conftest.py — add this fixture
from app import create_app


@pytest.fixture
def app(tmp_config_dir, tmp_path, monkeypatch):
    import app.metrics_db as metrics_db_module

    monkeypatch.setattr(metrics_db_module, "DB_PATH", tmp_path / "metrics.db")
    flask_app = create_app(testing=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_auth_routes.py
import json

import app.auth as auth_module


def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Login" in response.data


def test_login_with_valid_credentials_redirects_and_sets_session(client, tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    users_path.write_text(
        json.dumps(
            {"users": [{"username": "alice", "password_hash": _hash("secret")}]}
        )
    )
    monkeypatch.setattr(auth_module, "USERS_PATH", users_path)

    response = client.post(
        "/login", data={"username": "alice", "password": "secret"}, follow_redirects=False
    )

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["username"] == "alice"


def test_login_with_invalid_credentials_shows_error(client, tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    users_path.write_text(
        json.dumps({"users": [{"username": "alice", "password_hash": _hash("secret")}]})
    )
    monkeypatch.setattr(auth_module, "USERS_PATH", users_path)

    response = client.post("/login", data={"username": "alice", "password": "wrong"})

    assert response.status_code == 200
    assert b"Invalid" in response.data


def test_logout_clears_session(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    response = client.get("/logout", follow_redirects=False)

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert "username" not in sess


def _hash(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_auth_routes.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_app' from 'app'`

- [ ] **Step 4: Write `app/routes/__init__.py`**

```python
```

- [ ] **Step 5: Write `app/routes/auth_routes.py`**

```python
"""Login and logout routes."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.auth import verify_password

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_password(username, password):
            session["username"] = username
            return redirect(url_for("dashboard.index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("auth.login"))
```

- [ ] **Step 6: Write `app/templates/base.html`**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>4tExecutive</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/app.css') }}">
</head>
<body>
  <nav>
    <a href="{{ url_for('dashboard.index') }}">Dashboard</a>
    {% if session.username and user_has_tab(session.username, 'admin') %}
      <a href="{{ url_for('admin.sources') }}">Admin</a>
    {% endif %}
    {% if session.username %}
      <a href="{{ url_for('auth.logout') }}">Logout</a>
    {% endif %}
  </nav>
  <main>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 7: Write `app/templates/login.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Login</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post">
  <label>Username <input type="text" name="username"></label>
  <label>Password <input type="password" name="password"></label>
  <button type="submit">Log in</button>
</form>
{% endblock %}
```

- [ ] **Step 8: Write `app/static/css/app.css`**

```css
body { font-family: system-ui, sans-serif; margin: 0; }
nav { padding: 0.75rem 1rem; border-bottom: 1px solid #ddd; }
nav a { margin-right: 1rem; }
main { padding: 1rem; }
.error { color: #b00020; }
```

- [ ] **Step 9: Write `app/__init__.py` app factory**

```python
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

    flask_app.jinja_env.globals["user_has_tab"] = user_has_tab

    if not testing:
        from app.collector import init_scheduler

        init_scheduler(flask_app)

    return flask_app
```

Note: `dashboard.index` and `admin.sources` endpoints referenced in `base.html` don't exist yet — they're registered in Tasks 12–13. This task's tests only exercise `/login` and `/logout`, so `base.html`'s `url_for` calls for those endpoints aren't hit yet, but `create_app` will raise `BuildError` once `base.html` is rendered before those blueprints exist. To keep Task 11 self-contained and its tests green, register a minimal placeholder `dashboard` blueprint here too:

- [ ] **Step 10: Add a placeholder dashboard blueprint so `base.html` can resolve `url_for('dashboard.index')`**

```python
# app/routes/auth_routes.py — no change; placeholder lives in a new tiny module
```

```python
# app/routes/dashboard_routes.py (placeholder — real implementation replaces this in Task 12)
"""Dashboard routes (placeholder until Task 12)."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    return "placeholder"
```

Register it in `create_app` right after the auth blueprint:

```python
    from app.routes.dashboard_routes import bp as dashboard_bp

    flask_app.register_blueprint(dashboard_bp)
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `pytest tests/test_auth_routes.py -v`
Expected: PASS (4 tests)

- [ ] **Step 12: Commit**

```bash
git add app/__init__.py app/routes tests/test_auth_routes.py tests/conftest.py app/templates app/static
git commit -m "feat: add app factory, login/logout routes, and base template"
```

---

### Task 12: Dashboard routes (view + edit mode)

**Files:**
- Modify: `app/routes/dashboard_routes.py` (replace placeholder from Task 11)
- Create: `app/templates/dashboard.html`
- Test: `tests/test_dashboard_routes.py`

**Interfaces:**
- Consumes: `app.decorators.tab_required`, `app.layouts.get_layout`, `app.layouts.save_layout`, `app.widgets.WIDGET_CATALOG`, `app.widgets.get_widget_value`.
- Produces: routes `GET /` (view mode), `GET /dashboard/edit` (edit mode, shows catalog), `POST /dashboard/layout` (saves layout, JSON body). Consumed only by the browser/tests — no other module depends on these.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dashboard_routes.py
import json

import app.groups as groups_module
import app.metrics_db as metrics_db


def _login(client, username="alice"):
    with client.session_transaction() as sess:
        sess["username"] = username


def _allow_dashboard_tab(monkeypatch, tmp_path, username="alice"):
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"executives": {"members": [username], "allowed_tabs": ["dashboard"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_dashboard_requires_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302


def test_dashboard_requires_dashboard_tab(client, tmp_path, monkeypatch):
    _login(client)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)

    response = client.get("/")

    assert response.status_code == 403


def test_dashboard_renders_saved_widgets(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"hygiene_score": 88}, "2026-08-24T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"Hygiene Score" in response.data
    assert b"88" in response.data


def test_edit_page_lists_catalog(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/dashboard/edit")

    assert response.status_code == 200
    assert b"Hygiene Score" in response.data


def test_post_layout_saves_and_can_be_read_back(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    payload = [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}]

    response = client.post("/dashboard/layout", json=payload)

    assert response.status_code == 204
    from app.layouts import get_layout

    assert get_layout("alice") == payload


def test_post_layout_rejects_unknown_widget_type(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.post("/dashboard/layout", json=[{"type": "bogus", "source_instance": "s1"}])

    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: FAIL (403/404 mismatches — real routes don't exist yet, only the Task 11 placeholder)

- [ ] **Step 3: Replace `app/routes/dashboard_routes.py`**

```python
"""Dashboard routes: personalized view and edit modes."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, session

from app.decorators import tab_required
from app.layouts import get_layout, save_layout
from app.widgets import WIDGET_CATALOG, get_widget_value

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@tab_required("dashboard")
def index():
    layout = get_layout(session["username"])
    widgets = []
    for widget in layout:
        entry = WIDGET_CATALOG[widget["type"]]
        widgets.append(
            {
                **widget,
                "label": entry["label"],
                "data": get_widget_value(widget),
            }
        )
    return render_template("dashboard.html", widgets=widgets, edit_mode=False, catalog=None)


@bp.route("/dashboard/edit")
@tab_required("dashboard")
def edit():
    layout = get_layout(session["username"])
    return render_template(
        "dashboard.html", widgets=layout, edit_mode=True, catalog=WIDGET_CATALOG
    )


@bp.route("/dashboard/layout", methods=["POST"])
@tab_required("dashboard")
def update_layout():
    widgets = request.get_json(silent=True)
    if widgets is None:
        return jsonify({"error": "expected a JSON array of widgets"}), 400
    try:
        save_layout(session["username"], widgets)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return "", 204
```

- [ ] **Step 4: Write `app/templates/dashboard.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Dashboard</h1>
{% if edit_mode %}
  <p>Edit mode — available widgets:</p>
  <ul>
    {% for type, entry in catalog.items() %}
      <li>{{ entry.label }} ({{ entry.source_system }})</li>
    {% endfor %}
  </ul>
{% endif %}
<div class="widget-grid">
  {% for widget in widgets %}
    <div class="widget widget-{{ widget.size|default('1x1') }}">
      <h3>{{ widget.label }}</h3>
      {% if widget.data %}
        <p class="widget-value">{{ widget.data.value }}</p>
        <p class="widget-updated">as of {{ widget.data.collected_at }}</p>
      {% else %}
        <p class="widget-empty">No data yet</p>
      {% endif %}
    </div>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add app/routes/dashboard_routes.py app/templates/dashboard.html tests/test_dashboard_routes.py
git commit -m "feat: add dashboard view/edit routes and template"
```

---

### Task 13: Admin routes (source registry + manual refresh)

**Files:**
- Create: `app/routes/admin_routes.py`
- Create: `app/templates/admin/sources.html`
- Modify: `app/__init__.py` (register admin blueprint)
- Test: `tests/test_admin_routes.py`

**Interfaces:**
- Consumes: `app.decorators.tab_required`, `app.sources.list_sources`, `app.sources.add_source`, `app.sources.update_source`, `app.sources.delete_source`, `app.collector.poll_now`.
- Produces: routes `GET /admin/sources` (list + add form), `POST /admin/sources` (add), `POST /admin/sources/<id>/delete`, `POST /admin/sources/<id>/refresh`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_admin_routes.py
import json
from unittest.mock import patch

import app.groups as groups_module
import app.sources as sources_module


def _login_as_admin(client, tmp_path, monkeypatch, username="carol"):
    with client.session_transaction() as sess:
        sess["username"] = username
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"administrators": {"members": [username], "allowed_tabs": ["admin"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_admin_requires_admin_tab(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"
    response = client.get("/admin/sources")
    assert response.status_code == 403


def test_admin_sources_page_lists_sources(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(
        id="4thealth-east", system="4thealth", name="East DC",
        base_url="https://a", token="t",
    )

    response = client.get("/admin/sources")

    assert response.status_code == 200
    assert b"East DC" in response.data


def test_add_source_via_post(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post(
        "/admin/sources",
        data={
            "id": "4tlog-main",
            "system": "4tlog",
            "name": "Main FAZ",
            "base_url": "https://4tlog.internal",
            "token": "secret",
            "poll_interval_minutes": "20",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert sources_module.get_source("4tlog-main")["name"] == "Main FAZ"


def test_delete_source(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(id="s1", system="4thealth", name="A", base_url="https://a", token="t")

    response = client.post("/admin/sources/s1/delete", follow_redirects=False)

    assert response.status_code == 302
    assert sources_module.get_source("s1") is None


def test_refresh_source_triggers_poll_now(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(id="s1", system="4thealth", name="A", base_url="https://a", token="t")

    with patch("app.routes.admin_routes.poll_now") as mock_poll_now:
        mock_poll_now.return_value = True
        response = client.post("/admin/sources/s1/refresh", follow_redirects=False)

    assert response.status_code == 302
    mock_poll_now.assert_called_once_with("s1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_routes.py -v`
Expected: FAIL — `404 NOT FOUND` (blueprint not registered) or `ModuleNotFoundError`

- [ ] **Step 3: Write `app/routes/admin_routes.py`**

```python
"""Admin routes: source registry management and manual refresh."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from app.collector import poll_now
from app.decorators import tab_required
from app.sources import add_source, delete_source, list_sources

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/sources", methods=["GET"])
@tab_required("admin")
def sources():
    return render_template("admin/sources.html", sources=list_sources())


@bp.route("/sources", methods=["POST"])
@tab_required("admin")
def add_source_route():
    add_source(
        id=request.form["id"],
        system=request.form["system"],
        name=request.form["name"],
        base_url=request.form["base_url"],
        token=request.form["token"],
        poll_interval_minutes=int(request.form.get("poll_interval_minutes", 15)),
    )
    return redirect(url_for("admin.sources"))


@bp.route("/sources/<source_id>/delete", methods=["POST"])
@tab_required("admin")
def delete_source_route(source_id):
    delete_source(source_id)
    return redirect(url_for("admin.sources"))


@bp.route("/sources/<source_id>/refresh", methods=["POST"])
@tab_required("admin")
def refresh_source_route(source_id):
    poll_now(source_id)
    return redirect(url_for("admin.sources"))
```

- [ ] **Step 4: Write `app/templates/admin/sources.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Admin — Sources</h1>
<table>
  <thead><tr><th>ID</th><th>System</th><th>Name</th><th>Enabled</th><th></th></tr></thead>
  <tbody>
    {% for source in sources %}
    <tr>
      <td>{{ source.id }}</td>
      <td>{{ source.system }}</td>
      <td>{{ source.name }}</td>
      <td>{{ source.enabled }}</td>
      <td>
        <form method="post" action="{{ url_for('admin.refresh_source_route', source_id=source.id) }}" style="display:inline">
          <button type="submit">Refresh now</button>
        </form>
        <form method="post" action="{{ url_for('admin.delete_source_route', source_id=source.id) }}" style="display:inline">
          <button type="submit">Delete</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<h2>Add source</h2>
<form method="post" action="{{ url_for('admin.add_source_route') }}">
  <label>ID <input name="id"></label>
  <label>System <input name="system" placeholder="4thealth / 4tlog"></label>
  <label>Name <input name="name"></label>
  <label>Base URL <input name="base_url"></label>
  <label>Token <input name="token" type="password"></label>
  <label>Poll interval (minutes) <input name="poll_interval_minutes" value="15"></label>
  <button type="submit">Add</button>
</form>
{% endblock %}
```

- [ ] **Step 5: Register the admin blueprint in `app/__init__.py`**

Add alongside the existing blueprint registrations in `create_app`:

```python
    from app.routes.admin_routes import bp as admin_bp

    flask_app.register_blueprint(admin_bp)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_admin_routes.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests across all tasks so far)

- [ ] **Step 8: Commit**

```bash
git add app/routes/admin_routes.py app/templates/admin app/__init__.py tests/test_admin_routes.py
git commit -m "feat: add admin source registry routes and template"
```

---

### Task 14: `manage_users.py` CLI

**Files:**
- Create: `manage_users.py`
- Test: `tests/test_manage_users.py`

**Interfaces:**
- Consumes: `app.auth.hash_password`, `app.atomic_io.read_json`, `app.atomic_io.atomic_write_json`, `app.config_paths.CONFIG_DIR`.
- Produces: a CLI with `create <username> <password>`, `delete <username>`, `list` subcommands (mirrors 4thealth's `manage_users.py` shape — used by an operator, not by the app itself, so no other module depends on it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_manage_users.py
import json

import pytest

import manage_users
from app.atomic_io import read_json


@pytest.fixture(autouse=True)
def tmp_users(tmp_path, monkeypatch):
    monkeypatch.setattr(manage_users, "USERS_PATH", tmp_path / "users.json")


def test_create_adds_a_user():
    manage_users.create_user("alice", "secret")
    users = read_json(manage_users.USERS_PATH)["users"]
    assert users[0]["username"] == "alice"
    import bcrypt

    assert bcrypt.checkpw(b"secret", users[0]["password_hash"].encode())


def test_create_rejects_duplicate_username():
    manage_users.create_user("alice", "secret")
    with pytest.raises(ValueError):
        manage_users.create_user("alice", "other")


def test_delete_removes_user():
    manage_users.create_user("alice", "secret")
    manage_users.delete_user("alice")
    assert read_json(manage_users.USERS_PATH)["users"] == []


def test_list_users_returns_usernames():
    manage_users.create_user("alice", "secret")
    manage_users.create_user("bob", "secret2")
    assert manage_users.list_users() == ["alice", "bob"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_manage_users.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'manage_users'`

- [ ] **Step 3: Write `manage_users.py`**

```python
#!/usr/bin/env python3
"""CLI for managing config/users.json — create, delete, list users."""

from __future__ import annotations

import argparse
import sys

from app.atomic_io import atomic_write_json, read_json
from app.auth import hash_password
from app.config_paths import CONFIG_DIR

USERS_PATH = CONFIG_DIR / "users.json"


def _load() -> list[dict]:
    return read_json(USERS_PATH, default={"users": []}).get("users", [])


def _save(users: list[dict]) -> None:
    atomic_write_json(USERS_PATH, {"users": users})


def create_user(username: str, password: str) -> None:
    users = _load()
    if any(u["username"] == username for u in users):
        raise ValueError(f"user already exists: {username}")
    users.append({"username": username, "password_hash": hash_password(password)})
    _save(users)


def delete_user(username: str) -> None:
    users = [u for u in _load() if u["username"] != username]
    _save(users)


def list_users() -> list[str]:
    return [u["username"] for u in _load()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage 4tExecutive users")
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create")
    create_parser.add_argument("username")
    create_parser.add_argument("password")

    delete_parser = sub.add_parser("delete")
    delete_parser.add_argument("username")

    sub.add_parser("list")

    args = parser.parse_args()

    if args.command == "create":
        create_user(args.username, args.password)
        print(f"Created user: {args.username}")
    elif args.command == "delete":
        delete_user(args.username)
        print(f"Deleted user: {args.username}")
    elif args.command == "list":
        for username in list_users():
            print(username)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_manage_users.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add manage_users.py tests/test_manage_users.py
git commit -m "feat: add manage_users.py CLI"
```

---

### Task 15: Docker/deployment files

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `wsgi.py`

**Interfaces:**
- Consumes: `app.create_app`.
- Produces: a runnable container image and compose service. No unit tests (deployment config) — verified manually per Step 4 below.

- [ ] **Step 1: Write `wsgi.py`**

```python
"""WSGI entrypoint for gunicorn."""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8200)
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache .[prod]

COPY app ./app
COPY manage_users.py wsgi.py ./
COPY config/examples ./config/examples

EXPOSE 8200

CMD ["gunicorn", "-b", "0.0.0.0:8200", "wsgi:app"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    image: 4texecutive:latest
    container_name: 4texecutive
    restart: unless-stopped
    ports:
      - "8200:8200"
    env_file:
      - .env
    volumes:
      - ./config:/app/config:rw
      - ./metrics.db:/app/metrics.db:rw
    healthcheck:
      test:
        - CMD
        - python3
        - -c
        - "import urllib.request; urllib.request.urlopen('http://localhost:8200/login', timeout=5)"
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

- [ ] **Step 4: Write `.env.example`**

```
SECRET_KEY=change-me-to-a-random-value
```

- [ ] **Step 5: Verify the image builds**

Run: `docker compose build`
Expected: build succeeds with no errors

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml wsgi.py .env.example
git commit -m "feat: add Docker deployment files"
```

---

### Task 16: Demo seed script for visual QA

**Files:**
- Create: `seed_demo_data.py`
- Test: `tests/test_seed_demo_data.py`

**Purpose:** Task 15 gives you a runnable container, but an empty one — no
users, no sources, no cached metrics, so the Dashboard renders nothing and
there's nothing to log in with. This task adds a script that populates
`config/` and `metrics.db` with a demo login and a full page of fake widget
data — covering every catalog entry and all three widget sizes — purely so
you can look at the real rendered page. It writes metrics snapshots
directly (bypassing the collector/HTTP layer entirely), so it works with no
network access and no running source systems.

**Interfaces:**
- Consumes: `app.config_paths.bootstrap_config`, `app.metrics_db.init_db`,
  `app.metrics_db.write_snapshot`, `app.sources.add_source`,
  `app.layouts.save_layout`, `app.atomic_io.atomic_write_json`,
  `app.groups.GROUPS_PATH`, `manage_users.create_user`,
  `app.widgets.WIDGET_CATALOG`.
- Produces: `seed() -> None`, run via `python seed_demo_data.py`. Nothing
  else depends on this — it's a standalone dev/demo tool, not imported by
  the app.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_demo_data.py
import app.groups as groups_module
import app.metrics_db as metrics_db
import app.sources as sources_module
import manage_users
from app.config_paths import bootstrap_config
from app.layouts import get_layout
from app.metrics_db import get_latest, init_db
from app.widgets import WIDGET_CATALOG
from seed_demo_data import DEMO_PASSWORD, DEMO_USERNAME, seed


def _patch_all_paths(tmp_path, monkeypatch):
    import app.config_paths as config_paths_module

    config_dir = tmp_path / "config"
    monkeypatch.setattr(config_paths_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_paths_module, "EXAMPLES_DIR", config_dir / "examples")
    monkeypatch.setattr(groups_module, "GROUPS_PATH", config_dir / "groups.json")
    monkeypatch.setattr(sources_module, "SOURCES_PATH", config_dir / "sources.json")
    monkeypatch.setattr(manage_users, "USERS_PATH", config_dir / "users.json")

    import app.auth as auth_module

    monkeypatch.setattr(auth_module, "USERS_PATH", config_dir / "users.json")
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    (config_dir / "examples").mkdir(parents=True)
    init_db()


def test_seed_creates_demo_user(tmp_path, monkeypatch):
    _patch_all_paths(tmp_path, monkeypatch)
    seed()
    assert DEMO_USERNAME in manage_users.list_users()


def test_seed_grants_dashboard_and_admin_tabs(tmp_path, monkeypatch):
    _patch_all_paths(tmp_path, monkeypatch)
    seed()
    from app.groups import user_has_tab

    assert user_has_tab(DEMO_USERNAME, "dashboard") is True
    assert user_has_tab(DEMO_USERNAME, "admin") is True


def test_seed_adds_sources(tmp_path, monkeypatch):
    _patch_all_paths(tmp_path, monkeypatch)
    seed()
    assert len(sources_module.list_sources()) >= 2


def test_seed_populates_a_snapshot_for_every_catalog_entry(tmp_path, monkeypatch):
    _patch_all_paths(tmp_path, monkeypatch)
    seed()
    from app.widgets import get_widget_value

    layout = get_layout(DEMO_USERNAME)
    assert len(layout) == len(WIDGET_CATALOG)
    for widget in layout:
        assert get_widget_value(widget) is not None


def test_seed_layout_uses_varied_sizes(tmp_path, monkeypatch):
    _patch_all_paths(tmp_path, monkeypatch)
    seed()
    sizes = {widget["size"] for widget in get_layout(DEMO_USERNAME)}
    assert sizes == {"1x1", "2x1", "2x2"}


def test_seed_is_idempotent(tmp_path, monkeypatch):
    _patch_all_paths(tmp_path, monkeypatch)
    seed()
    seed()  # must not raise on duplicate user/source ids
    assert manage_users.list_users().count(DEMO_USERNAME) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed_demo_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'seed_demo_data'`

- [ ] **Step 3: Write `seed_demo_data.py`**

```python
#!/usr/bin/env python3
"""Populate config/ and metrics.db with fake data for visual QA.

Run with: python seed_demo_data.py
Then: docker compose up --build, and log in at http://localhost:8200
with DEMO_USERNAME / DEMO_PASSWORD (printed below).

Writes metrics snapshots directly — no network calls, no real source
systems required.
"""

from __future__ import annotations

from datetime import datetime, timezone

import app.sources as sources_module
import manage_users
from app.atomic_io import atomic_write_json
from app.config_paths import bootstrap_config
from app.groups import GROUPS_PATH
from app.layouts import save_layout
from app.metrics_db import init_db, write_snapshot
from app.widgets import WIDGET_CATALOG

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo-password-123"

_DEMO_SOURCES = [
    {
        "id": "demo-4thealth",
        "system": "4thealth",
        "name": "Demo — 4thealth (HQ)",
        "base_url": "https://demo-4thealth.invalid:8100",
    },
    {
        "id": "demo-4tlog",
        "system": "4tlog",
        "name": "Demo — 4tlog (HQ)",
        "base_url": "https://demo-4tlog.invalid:8100",
    },
]

_DEMO_SNAPSHOT_VALUES = {
    "demo-4thealth": {
        "hygiene_score": 94,
        "version_compliance_pct": 88,
        "pending_config_diff_count": 3,
        "last_backup_status": "OK — 2026-08-23T02:00:00Z",
        "firewall_online_count": 12,
    },
    "demo-4tlog": {
        "faz_health": "Healthy (2 of 2 targets up)",
        "log_volume_trend": "12.4M events/day (+3% week over week)",
    },
}

_SIZE_CYCLE = ["1x1", "2x1", "2x2"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed() -> None:
    bootstrap_config()
    init_db()

    if DEMO_USERNAME not in manage_users.list_users():
        manage_users.create_user(DEMO_USERNAME, DEMO_PASSWORD)

    atomic_write_json(
        GROUPS_PATH,
        {
            "demo": {
                "members": [DEMO_USERNAME],
                "allowed_tabs": ["dashboard", "admin"],
            }
        },
    )

    for demo_source in _DEMO_SOURCES:
        if sources_module.get_source(demo_source["id"]) is None:
            sources_module.add_source(
                id=demo_source["id"],
                system=demo_source["system"],
                name=demo_source["name"],
                base_url=demo_source["base_url"],
                token="demo-token-not-a-real-secret",
                enabled=False,  # demo hosts don't exist; avoid noisy failed polls
            )
        write_snapshot(
            demo_source["id"], "summary", _DEMO_SNAPSHOT_VALUES[demo_source["id"]], _now_iso()
        )

    layout = []
    for index, (widget_type, entry) in enumerate(WIDGET_CATALOG.items()):
        source_id = "demo-4thealth" if entry["source_system"] == "4thealth" else "demo-4tlog"
        layout.append(
            {
                "type": widget_type,
                "source_instance": source_id,
                "size": _SIZE_CYCLE[index % len(_SIZE_CYCLE)],
                "date_range": "30d",
            }
        )
    save_layout(DEMO_USERNAME, layout)

    print(f"Seeded demo data. Log in with username={DEMO_USERNAME!r} password={DEMO_PASSWORD!r}")


if __name__ == "__main__":
    seed()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_seed_demo_data.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add seed_demo_data.py tests/test_seed_demo_data.py
git commit -m "feat: add demo data seed script for visual QA"
```

---

## Post-plan checklist

- [ ] Run the full test suite once more: `pytest -v` — all tests pass
- [ ] Run `ruff check .` and fix any lint issues
- [ ] Visual QA in a container, using seeded demo data:
  ```bash
  cp .env.example .env   # edit SECRET_KEY if you like
  python seed_demo_data.py   # creates config/ and metrics.db on the host,
                              # which docker-compose then bind-mounts in —
                              # this also avoids Docker creating an empty
                              # directory where metrics.db should be a file
  docker compose up --build
  ```
  Then open `http://localhost:8200/login`, log in with the
  `username`/`password` printed by `seed_demo_data.py`, and check:
  - **Dashboard tab**: every widget in the catalog renders with a value
    and an "as of" timestamp, across all three sizes (1x1/2x1/2x2), so you
    can eyeball the grid layout and styling.
  - **Admin tab**: both demo sources are listed (shown as disabled, since
    their URLs are fake — clicking "Refresh now" on one is a good way to
    see the "source unreachable, degrade gracefully" behavior in
    `app/collector.py` in action without it crashing anything).
  - Add a real source in Admin pointing at nothing reachable, confirm
    "Refresh now" doesn't 500.
  - `docker compose down` when finished; rerun `python seed_demo_data.py`
    any time to reset/replenish demo data (it's idempotent).
