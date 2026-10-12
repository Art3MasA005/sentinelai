"""Local accounts: signup/login/sessions, lockout, profile, avatar, Google flow and route guarding."""

import pytest

from app.services import auth as auth_svc
from tests.test_api import API

USER = {
    "name": "Ayesha Rahman",
    "email": "Ayesha@Example.org",
    "phone": "+8801712345678",
    "password": "secret123",
    "country": "Bangladesh",
    "institution": "BUET",
    "role": "Researcher",
}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def session(client):
    r = client.post(f"{API}/auth/signup", json=USER)
    assert r.status_code == 201, r.text
    return r.json()


def test_password_hashing_roundtrip():
    h = auth_svc.hash_password("secret123")
    assert h.startswith("pbkdf2_sha256$") and "secret123" not in h
    assert auth_svc.verify_password("secret123", h)
    assert not auth_svc.verify_password("secret124", h)
    assert not auth_svc.verify_password("x", None)


def test_signup_returns_session_and_normalizes(session):
    u = session["user"]
    assert u["email"] == "ayesha@example.org" and u["name"] == "Ayesha Rahman"
    assert u["profile_complete"] and u["has_password"] and not u["google_linked"]
    assert session["token"] and len(session["token"]) > 30


@pytest.mark.parametrize("patch, msg", [
    ({"password": "short1"}, "at least 8"),
    ({"password": "onlyletters"}, "letters and numbers"),
    ({"email": "nope"}, "valid email"),
    ({"phone": "abc"}, "country code"),
    ({"name": " "}, "name"),
])
def test_signup_validation(client, patch, msg):
    r = client.post(f"{API}/auth/signup", json={**USER, "email": "other@example.org", **patch})
    assert r.status_code == 422
    assert msg.lower() in r.text.lower()


def test_duplicate_email_rejected(client, session):
    r = client.post(f"{API}/auth/signup", json=USER)
    assert r.status_code == 409


def test_login_me_logout(client, session):
    r = client.post(f"{API}/auth/login", json={"email": "AYESHA@example.org ", "password": "secret123"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert client.get(f"{API}/auth/me", headers=_h(token)).json()["email"] == "ayesha@example.org"
    assert client.post(f"{API}/auth/logout", headers=_h(token)).status_code == 200
    assert client.get(f"{API}/auth/me", headers=_h(token)).status_code == 401
    assert client.get(f"{API}/auth/me").status_code == 401


def test_wrong_password_and_lockout(client, session):
    email = "lock@example.org"
    client.post(f"{API}/auth/signup", json={**USER, "email": email})
    for _ in range(auth_svc.MAX_FAILURES):
        assert client.post(f"{API}/auth/login", json={"email": email, "password": "bad"}).status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": email, "password": USER["password"]})
    assert r.status_code == 429  # locked even with the right password
    auth_svc._clear_failures(email)
    assert client.post(f"{API}/auth/login", json={"email": email, "password": USER["password"]}).status_code == 200


def test_profile_update_password_and_avatar(client, session):
    token = client.post(f"{API}/auth/login", json={"email": USER["email"], "password": "secret123"}).json()["token"]
    r = client.put(f"{API}/auth/me", headers=_h(token), json={**USER, "institution": "DU", "role": "Student"})
    assert r.json()["institution"] == "DU"
    assert client.put(f"{API}/auth/me/avatar", headers=_h(token), content=b"GIF89a....").status_code == 415
    assert client.put(f"{API}/auth/me/avatar", headers=_h(token), content=PNG).json()["has_avatar"]
    assert client.get(f"{API}/auth/me/avatar", headers=_h(token)).content == PNG
    r = client.post(f"{API}/auth/me/password", headers=_h(token),
                    json={"current_password": "wrong", "new_password": "newpass99"})
    assert r.status_code == 401
    r = client.post(f"{API}/auth/me/password", headers=_h(token),
                    json={"current_password": "secret123", "new_password": "newpass99"})
    assert r.status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": USER["email"], "password": "newpass99"}).status_code == 200


def test_google_signin_creates_then_reuses_account(client, env, monkeypatch):
    from app.services.auth import AuthService
    from app.storage.repository import Repository

    svc = AuthService(env, Repository(env.db_path))
    info = {"sub": "g-123", "email": "g.user@gmail.com", "name": "G User", "email_verified": "true"}
    first = svc.google_login("tok", True, "test", info=info)
    assert first["user"].google_linked and not first["user"].profile_complete  # phone still needed
    again = svc.google_login("tok", True, "test", info=info)
    assert again["user"].id == first["user"].id
    # An existing password account with the same email gets linked, not duplicated.
    linked = svc.google_login("tok", True, "test", info={**info, "sub": "g-999", "email": "ayesha@example.org"})
    assert linked["user"].email == "ayesha@example.org" and linked["user"].google_linked


def test_google_endpoint_requires_configuration(client):
    cfg = client.get(f"{API}/auth/config").json()
    assert cfg["google_enabled"] is False and "Researcher" in cfg["roles"]
    r = client.post(f"{API}/auth/google", json={"id_token": "x" * 40})
    assert r.status_code == 501


def test_guard_enforces_sign_in_when_enabled(client, env, session):
    assert client.get(f"{API}/experiments").status_code == 200  # off by default
    env.auth_required = True
    try:
        assert client.get(f"{API}/experiments").status_code == 401
        assert client.get(f"{API}/health").status_code == 200  # stays public
        token = client.post(f"{API}/auth/login", json={"email": USER["email"], "password": "newpass99"}).json()["token"]
        assert client.get(f"{API}/experiments", headers=_h(token)).status_code == 200
    finally:
        env.auth_required = False
