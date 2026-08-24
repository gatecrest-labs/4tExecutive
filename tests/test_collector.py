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
