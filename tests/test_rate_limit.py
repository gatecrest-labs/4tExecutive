"""Rate limiting is disabled for the shared `app`/`client` fixtures
(testing=True) so other test files aren't throttled by shared per-process
limiter state. This test forces it back on against a throwaway app instance
to verify the login route is actually protected against brute force.
"""

from app import create_app


def test_login_is_rate_limited_after_repeated_attempts(tmp_config_dir, tmp_path, monkeypatch):
    import app.metrics_db as metrics_db_module

    monkeypatch.setattr(metrics_db_module, "DB_PATH", tmp_path / "metrics.db")
    flask_app = create_app(testing=True, enable_rate_limit=True)
    client = flask_app.test_client()

    responses = [
        client.post("/login", data={"username": "alice", "password": "wrong"})
        for _ in range(11)
    ]

    assert responses[-1].status_code == 429
    assert all(r.status_code == 200 for r in responses[:10])
