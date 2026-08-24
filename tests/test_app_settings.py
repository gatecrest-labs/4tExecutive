import app.app_settings as settings_module
from app.app_settings import get_setting, set_setting


def test_get_setting_returns_default_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", tmp_path / "app_settings.json")
    assert get_setting("refresh_minutes", default=15) == 15


def test_set_setting_then_get_setting_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", tmp_path / "app_settings.json")
    set_setting("refresh_minutes", 30)
    assert get_setting("refresh_minutes") == 30
