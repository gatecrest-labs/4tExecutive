import datetime

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.sso_verify as sso_verify_module

BANNER = "Your account has no tabs assigned. Contact an administrator."


def _write_test_keypair(tmp_path, monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_path = tmp_path / "sso_public_key.pem"
    public_key_path.write_bytes(public_pem)
    monkeypatch.setattr(sso_verify_module, "PUBLIC_KEY_PATH", public_key_path)
    return private_key


def _sso_token(private_key, **overrides):
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": "alice",
        "aud": "4texecutive",
        "iss": "4tsuite",
        "iat": now,
        "nbf": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="EdDSA")


def test_zero_grant_sso_user_lands_on_banner_page_not_bare_403(
    client, tmp_path, monkeypatch, tmp_groups_file
):
    key = _write_test_keypair(tmp_path, monkeypatch)
    token = _sso_token(key, sub="mallory")  # in no group
    response = client.get(f"/sso/login?token={token}", follow_redirects=True)
    assert response.status_code == 200
    assert BANNER in response.get_data(as_text=True)


def test_zero_grant_user_hitting_board_directly_gets_the_banner(
    client, tmp_path, monkeypatch, tmp_groups_file
):
    key = _write_test_keypair(tmp_path, monkeypatch)
    client.get(f"/sso/login?token={_sso_token(key, sub='mallory')}")
    response = client.get("/board", follow_redirects=True)
    assert response.status_code == 403  # still denied; the page just explains why
    assert BANNER in response.get_data(as_text=True)


def test_user_with_some_tabs_still_gets_403_on_a_tab_they_lack(
    client, tmp_path, monkeypatch, tmp_groups_file
):
    key = _write_test_keypair(tmp_path, monkeypatch)
    client.get(f"/sso/login?token={_sso_token(key, sub='alice')}")
    # No fixture group grants the "brief" tab, so alice (who has other tabs)
    # must still get the plain 403, not the no-access page.
    response = client.get("/brief")
    assert response.status_code == 403


def test_no_access_page_requires_a_session(client):
    response = client.get("/no-access", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_json_clients_get_the_plain_403(client, tmp_path, monkeypatch, tmp_groups_file):
    key = _write_test_keypair(tmp_path, monkeypatch)
    client.get(f"/sso/login?token={_sso_token(key, sub='mallory')}")
    response = client.get("/board", headers={"Accept": "application/json"})
    assert response.status_code == 403
    assert BANNER not in response.get_data(as_text=True)
