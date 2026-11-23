from tests.conftest import PASSWORD, make_client, signup


def test_register_sets_secure_session_cookies(client):
    r = client.post("/api/auth/register",
                    json={"email": "Alice@Example.com", "full_name": "  Alice   Smith ", "password": PASSWORD})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "alice@example.com" and body["full_name"] == "Alice Smith"
    assert "password" not in str(body) and "hash" not in str(body)
    cookies = r.headers.get_list("set-cookie")
    access = next(c for c in cookies if c.startswith("quarry_access="))
    assert "HttpOnly" in access and "SameSite=strict" in access and "Path=/api" in access
    refresh = next(c for c in cookies if c.startswith("quarry_refresh="))
    assert "Path=/api/auth" in refresh and "HttpOnly" in refresh
    csrf = next(c for c in cookies if c.startswith("quarry_csrf="))
    assert "HttpOnly" not in csrf


def test_duplicate_email_rejected(client):
    u = signup(client)
    with make_client() as other:
        r = other.post("/api/auth/register", json={"email": u["email"], "full_name": "X", "password": PASSWORD})
    assert r.status_code == 409


def test_weak_password_rejected(client):
    r = client.post("/api/auth/register", json={"email": "w@example.com", "full_name": "W", "password": "abc"})
    assert r.status_code == 422 and "at least 10" in r.json()["detail"]


def test_login_logout_cycle():
    with make_client() as c:
        u = signup(c)
    with make_client() as c:
        assert c.get("/api/auth/me").status_code == 401
        r = c.post("/api/auth/login", json={"email": u["email"], "password": u["password"]})
        assert r.status_code == 200
        c.headers["x-csrf-token"] = c.cookies["quarry_csrf"]
        assert c.get("/api/auth/me").json()["email"] == u["email"]
        assert c.post("/api/auth/logout").status_code == 204
        assert c.get("/api/auth/me").status_code == 401


def test_wrong_password_is_generic():
    with make_client() as c:
        u = signup(c)
    with make_client() as c:
        bad_pw = c.post("/api/auth/login", json={"email": u["email"], "password": "Wrong-pass-123"})
        no_user = c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Wrong-pass-123"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()  # no user enumeration through messages


def test_refresh_rotates_token():
    with make_client() as c:
        signup(c)
        old = c.cookies.get("quarry_refresh")
        r = c.post("/api/auth/refresh")
        assert r.status_code == 200
        assert c.cookies.get("quarry_refresh") != old


def test_logout_revokes_refresh_token():
    with make_client() as c:
        signup(c)
        stolen = c.cookies.get("quarry_refresh")
        csrf = c.cookies.get("quarry_csrf")
        c.post("/api/auth/logout")
    with make_client() as attacker:
        attacker.cookies.set("quarry_refresh", stolen, path="/api/auth")
        attacker.cookies.set("quarry_csrf", csrf)
        r = attacker.post("/api/auth/refresh", headers={"x-csrf-token": csrf})
    assert r.status_code == 401


def test_change_password_signs_out_other_sessions():
    with make_client() as a:
        u = signup(a)
        other_refresh = a.cookies.get("quarry_refresh")
        r = a.post("/api/auth/change-password",
                   json={"current_password": u["password"], "new_password": "Brand-new-pass-77"})
        assert r.status_code == 204
        a.headers["x-csrf-token"] = a.cookies["quarry_csrf"]
        assert a.get("/api/auth/me").status_code == 200  # current device stays signed in
    with make_client() as b:
        b.cookies.set("quarry_refresh", other_refresh, path="/api/auth")
        b.cookies.set("quarry_csrf", "t")
        assert b.post("/api/auth/refresh", headers={"x-csrf-token": "t"}).status_code == 401
        assert b.post("/api/auth/login", json={"email": u["email"], "password": u["password"]}).status_code == 401
        assert b.post("/api/auth/login",
                      json={"email": u["email"], "password": "Brand-new-pass-77"}).status_code == 200


def test_refresh_keeps_csrf_token_stable_for_other_tabs():
    with make_client() as c:
        signup(c)
        before = c.cookies.get("quarry_csrf")
        assert c.post("/api/auth/refresh").status_code == 200
        assert c.cookies.get("quarry_csrf") == before
        assert c.post("/api/conversations", json={}).status_code == 201  # old header still valid
