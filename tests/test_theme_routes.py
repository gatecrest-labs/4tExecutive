def test_theme_defaults_to_light(client):
    response = client.get("/login")
    assert b'data-theme="light"' in response.data


def test_post_theme_sets_cookie_and_flips_rendered_attribute(client):
    response = client.post(
        "/theme", data={"theme": "dark", "next": "/login"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert b'data-theme="dark"' in response.data


def test_theme_cookie_persists_across_requests(client):
    client.post("/theme", data={"theme": "dark", "next": "/login"})
    response = client.get("/login")
    assert b'data-theme="dark"' in response.data


def test_post_theme_rejects_invalid_value(client):
    response = client.post(
        "/theme", data={"theme": "purple", "next": "/login"}, follow_redirects=True
    )
    assert b'data-theme="light"' in response.data


def test_post_theme_rejects_absolute_url_redirect(client):
    response = client.post(
        "/theme",
        data={"theme": "dark", "next": "https://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers.get("Location")
    assert location == "/"


def test_post_theme_rejects_protocol_relative_url_redirect(client):
    response = client.post(
        "/theme",
        data={"theme": "dark", "next": "//evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers.get("Location")
    assert location == "/"
