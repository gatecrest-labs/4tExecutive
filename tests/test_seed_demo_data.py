import app.groups as groups_module
import app.sources as sources_module
import manage_users
from app import metrics_db
from app.layouts import get_layout
from app.metrics_db import init_db
from app.widgets import WIDGET_CATALOG
from seed_demo_data import DEMO_USERNAME, seed


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
