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
