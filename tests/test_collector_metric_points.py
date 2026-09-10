"""Tests for collector.py writing derived metric_points alongside snapshots."""

from unittest.mock import patch

import pytest

import app.sources as sources_module
from app import metrics_db
from app.collector import _run_domain_scores, poll_self, poll_source
from app.crypto import encrypt_token
from app.metrics_db import get_metric_series, init_db
from app.sources import add_source


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
        "token": encrypt_token("secret"),
        "poll_interval_minutes": 15,
        "enabled": True,
    }
    base.update(overrides)
    return base


def test_poll_source_writes_metric_points_on_success():
    source = _source()

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"hygiene_score": 92}

        poll_source(source)

    series = get_metric_series("4thealth-east", "hygiene_score", since="2000-01-01T00:00:00Z")
    assert len(series) == 1
    assert series[0]["value"] == 92.0


def test_poll_source_does_not_write_metric_points_on_http_error():
    source = _source()

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 503
        mock_get.return_value.json.return_value = {"hygiene_score": 92}

        poll_source(source)

    series = get_metric_series("4thealth-east", "hygiene_score", since="2000-01-01T00:00:00Z")
    assert series == []


def test_poll_self_writes_metric_points():
    with patch("app.collector.psutil") as mock_psutil:
        mock_psutil.cpu_percent.return_value = 12.5
        mock_psutil.virtual_memory.return_value.percent = 40.0
        mock_psutil.disk_usage.return_value.percent = 55.0

        poll_self()

    series = get_metric_series("_self", "cpu_percent", since="2000-01-01T00:00:00Z")
    assert len(series) == 1
    assert series[0]["value"] == 12.5


def test_run_domain_scores_writes_fleet_domain_points():
    from app.metrics_db import insert_metric_points

    add_source(
        id="s1",
        system="4thealth",
        name="s1",
        base_url="https://example.internal",
        token="secret",
    )
    insert_metric_points("s1", "2026-08-27T10:00:00Z", {"firewall_online_count": 10.0, "firewall_managed_count": 10.0})

    _run_domain_scores()

    series = get_metric_series("_fleet", "domain.availability", since="2000-01-01T00:00:00Z")
    assert len(series) == 1
    assert series[0]["value"] == 100.0


def test_run_domain_scores_swallows_errors(monkeypatch):
    import app.collector as collector_module

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(collector_module, "store_domain_scores", _boom)

    _run_domain_scores()  # must not raise
