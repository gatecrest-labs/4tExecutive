from unittest.mock import patch

import pytest
import requests

import app.sources as sources_module
from app import metrics_db
from app.collector import poll_all, poll_now, poll_source
from app.crypto import encrypt_token
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
        "token": encrypt_token("secret"),
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


def test_poll_source_logs_warning_on_request_exception():
    source = _source()

    with (
        patch("app.collector.requests.get", side_effect=requests.ConnectionError("down")),
        patch("app.collector.logger") as mock_logger,
    ):
        result = poll_source(source)

    assert result is False
    mock_logger.warning.assert_called_once()
    call_args = mock_logger.warning.call_args
    assert "4thealth-east" in str(call_args)
    assert "down" in str(call_args)


def test_poll_source_logs_warning_on_http_error():
    source = _source()

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 503
        with patch("app.collector.logger") as mock_logger:
            result = poll_source(source)

    assert result is False
    mock_logger.warning.assert_called_once()
    call_args = mock_logger.warning.call_args
    assert "4thealth-east" in str(call_args)
    assert "503" in str(call_args)


def test_poll_source_catches_malformed_json_and_returns_false():
    source = _source()

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.side_effect = ValueError("Invalid JSON")

        result = poll_source(source)

    assert result is False
    assert get_latest("4thealth-east", "summary") is None


def test_poll_source_catches_write_snapshot_error_and_returns_false():
    source = _source()
    response_json = {"hygiene_score": 92}

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = response_json
        with patch("app.collector.write_snapshot", side_effect=OSError("DB error")):
            result = poll_source(source)

    assert result is False


def test_poll_source_catches_set_last_polled_error_and_returns_false():
    source = _source()
    response_json = {"hygiene_score": 92}

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = response_json
        with patch("app.collector.set_last_polled", side_effect=OSError("DB error")):
            result = poll_source(source)

    assert result is False


def test_poll_all_continues_after_failed_source():
    sources_module.add_source(**_source(id="source-1"))
    sources_module.add_source(**_source(id="source-2"))

    with patch("app.collector.requests.get") as mock_get:
        # First source fails, second succeeds
        responses = [
            Exception("Connection error"),
            type("MockResponse", (), {"status_code": 200, "json": lambda: {"score": 50}})(),
        ]
        mock_get.side_effect = responses

        # Should not raise, should continue to second source
        poll_all()

    # Second source should have been attempted despite first failing
    assert mock_get.call_count == 2


def test_poll_source_raises_no_keyerror_when_base_url_missing():
    source = _source()
    del source["base_url"]

    # Should not raise KeyError; should be caught and reported as a failed poll.
    result = poll_source(source)

    assert result is False


def test_poll_all_continues_when_source_missing_poll_interval_minutes():
    sources_module.add_source(**_source(id="bad-source"))
    sources_module.add_source(**_source(id="good-source"))
    from app.metrics_db import set_last_polled

    # _is_due only reads poll_interval_minutes once there's a prior
    # last_polled timestamp to compare against.
    set_last_polled("bad-source", "2020-01-01T00:00:00Z")

    # Corrupt the first source's record (simulating bad on-disk data) so
    # _is_due raises a KeyError for it.
    all_sources = sources_module.list_sources()
    for s in all_sources:
        if s["id"] == "bad-source":
            del s["poll_interval_minutes"]
    sources_module._save(all_sources)  # simulating corrupted config on disk

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"score": 50}
        poll_all()

    # good-source should still have been polled despite bad-source's corrupt record.
    mock_get.assert_called_once()


def test_poll_source_records_last_polled_on_http_error():
    source = _source()

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 503
        poll_source(source)

    assert get_last_polled("4thealth-east") is not None


def test_poll_source_records_last_polled_on_connection_error():
    source = _source()

    with patch("app.collector.requests.get", side_effect=requests.ConnectionError("down")):
        poll_source(source)

    assert get_last_polled("4thealth-east") is not None


def test_poll_all_does_not_retry_down_source_before_interval_elapses():
    sources_module.add_source(**_source())

    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = 503
        poll_all()

    assert mock_get.call_count == 1

    # A second poll_all pass immediately after should NOT retry, since
    # poll_interval_minutes (15) has not elapsed since the failed attempt.
    with patch("app.collector.requests.get") as mock_get_second:
        poll_all()

    mock_get_second.assert_not_called()
