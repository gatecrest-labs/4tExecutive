import pytest

import app.sources as sources_module
from app.crypto import encrypt_token
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
    assert added["verify_tls"] is True
    assert [s["id"] for s in list_sources()] == ["4thealth-east"]
    assert get_source("4thealth-east")["name"] == "East DC"


def test_add_source_can_disable_tls_verification():
    added = add_source(
        id="self-signed", system="4thealth", name="Lab", base_url="https://a",
        token="t", verify_tls=False,
    )
    assert added["verify_tls"] is False


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
    source = {"token": encrypt_token("abc123")}
    assert source_headers(source) == {"Authorization": "Bearer abc123"}


def test_add_source_stores_token_encrypted_not_plaintext():
    add_source(id="s1", system="4thealth", name="A", base_url="https://a", token="super-secret")

    stored = get_source("s1")
    assert stored["token"] != "super-secret"
    assert "super-secret" not in stored["token"]
    assert source_headers(stored) == {"Authorization": "Bearer super-secret"}


def test_update_source_encrypts_new_token():
    add_source(id="s1", system="4thealth", name="A", base_url="https://a", token="old-token")

    update_source("s1", token="new-token")

    stored = get_source("s1")
    assert "new-token" not in stored["token"]
    assert source_headers(stored) == {"Authorization": "Bearer new-token"}
