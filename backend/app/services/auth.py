"""Local accounts: PBKDF2 password hashes, opaque session tokens (stored hashed), Google ID-token sign-in.

Accounts live only in the local SQLite database. The one network call is verifying a Google ID token
with Google's tokeninfo endpoint when someone signs in with Google.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.schemas.auth import ProfileFields, SignupRequest, User
from app.services.errors import ServiceError
from app.storage.repository import Repository, utcnow

PBKDF2_ITERATIONS = 600_000
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60
AVATAR_MAX_BYTES = 2 * 1024 * 1024
_AVATAR_TYPES = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg"}

_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


# ---------- passwords ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(PBKDF2_ITERATIONS, base64.b64encode(salt).decode(),
                                           base64.b64encode(digest).decode())


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(calc, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- brute-force guard (per email, in memory) ----------

def _check_lockout(email: str) -> None:
    now = time.monotonic()
    with _failures_lock:
        recent = [t for t in _failures.get(email, []) if now - t < LOCKOUT_SECONDS]
        _failures[email] = recent
        if len(recent) >= MAX_FAILURES:
            wait = int(LOCKOUT_SECONDS - (now - recent[0])) + 1
            raise ServiceError(f"Too many failed attempts. Try again in {wait} s.", 429)


def _record_failure(email: str) -> None:
    with _failures_lock:
        _failures.setdefault(email, []).append(time.monotonic())


def _clear_failures(email: str) -> None:
    with _failures_lock:
        _failures.pop(email, None)


# ---------- views ----------

def to_user(row: dict) -> User:
    return User(
        id=row["id"], email=row["email"], name=row["name"], phone=row["phone"], country=row["country"],
        institution=row["institution"], role=row["role"], has_avatar=bool(row["avatar_file"]),
        has_password=bool(row["password_hash"]), google_linked=bool(row["google_sub"]),
        profile_complete=bool(row["phone"]), created_at=row["created_at"], last_login_at=row["last_login_at"],
    )


class AuthService:
    def __init__(self, settings: Settings, repo: Repository):
        self.settings = settings
        self.repo = repo

    # ---------- sessions ----------
    def _new_session(self, user_id: int, remember: bool, client: str | None) -> dict:
        token = secrets.token_urlsafe(32)
        hours = self.settings.session_hours_remember if remember else self.settings.session_hours
        expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
        self.repo.create_session(_hash_token(token), user_id, expires, (client or "")[:200] or None)
        self.repo.update_user(user_id, last_login_at=utcnow())
        return {"token": token, "expires_at": expires, "user": to_user(self.repo.user_by("id", user_id))}

    def user_for_token(self, token: str | None) -> tuple[dict, str] | None:
        if not token:
            return None
        return self.repo.session_user(_hash_token(token))

    def logout(self, token: str) -> None:
        self.repo.delete_session(_hash_token(token))

    # ---------- email / password ----------
    def signup(self, req: SignupRequest, client: str | None) -> dict:
        if self.repo.user_by("email", req.email):
            raise ServiceError("An account with this email already exists. Log in instead.", 409)
        user_id = self.repo.create_user({
            "email": req.email, "password_hash": hash_password(req.password), "name": req.name, "phone": req.phone,
            "country": req.country, "institution": req.institution, "role": req.role, "created_at": utcnow(),
        })
        return self._new_session(user_id, req.remember, client)

    def login(self, email: str, password: str, remember: bool, client: str | None) -> dict:
        email = email.strip().lower()
        _check_lockout(email)
        row = self.repo.user_by("email", email)
        if row is None or not verify_password(password, row["password_hash"]):
            _record_failure(email)
            if row is not None and not row["password_hash"] and row["google_sub"]:
                raise ServiceError("This account uses Google sign-in. Continue with Google instead.", 401)
            raise ServiceError("Email or password is incorrect.", 401)
        _clear_failures(email)
        return self._new_session(row["id"], remember, client)

    # ---------- Google ----------
    def _verify_google(self, id_token: str) -> dict:
        audiences = {a for a in (self.settings.google_client_id, self.settings.google_desktop_client_id) if a}
        if not audiences:
            raise ServiceError("Google sign-in is not configured on this backend (SENTINEL_GOOGLE_CLIENT_ID).", 501)
        url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": id_token})
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                info = json.loads(resp.read().decode())
        except urllib.error.HTTPError:
            raise ServiceError("Google rejected this sign-in token. Please try again.", 401) from None
        except (urllib.error.URLError, TimeoutError):
            raise ServiceError("Cannot reach Google to verify the sign-in (internet needed).", 503) from None
        if info.get("aud") not in audiences:
            raise ServiceError("Google token was issued for a different app.", 401)
        if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise ServiceError("Unexpected Google token issuer.", 401)
        if str(info.get("email_verified")).lower() != "true":
            raise ServiceError("Your Google email is not verified.", 401)
        return info

    def google_login(self, id_token: str, remember: bool, client: str | None, info: dict | None = None) -> dict:
        info = info or self._verify_google(id_token)
        sub, email = info["sub"], info["email"].strip().lower()
        row = self.repo.user_by("google_sub", sub) or self.repo.user_by("email", email)
        if row is None:
            user_id = self.repo.create_user({
                "email": email, "name": info.get("name") or email.split("@")[0], "google_sub": sub,
                "created_at": utcnow(),
            })
        else:
            user_id = row["id"]
            if not row["google_sub"]:
                self.repo.update_user(user_id, google_sub=sub)  # link Google to an existing email account
        return self._new_session(user_id, remember, client)

    def exchange_desktop_code(self, code: str, redirect_uri: str, code_verifier: str) -> str:
        """Windows build: trade an OAuth authorization code (PKCE, loopback redirect) for an ID token."""
        s = self.settings
        if not (s.google_desktop_client_id and s.google_desktop_client_secret):
            raise ServiceError("Desktop Google sign-in is not configured (SENTINEL_GOOGLE_DESKTOP_CLIENT_*).", 501)
        body = urllib.parse.urlencode({
            "code": code, "client_id": s.google_desktop_client_id, "client_secret": s.google_desktop_client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": code_verifier,
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())["id_token"]
        except (urllib.error.URLError, KeyError, TimeoutError):
            raise ServiceError("Could not complete Google sign-in.", 401) from None

    # ---------- profile ----------
    def update_profile(self, user_id: int, p: ProfileFields) -> User:
        self.repo.update_user(user_id, name=p.name, phone=p.phone, country=p.country, institution=p.institution,
                              role=p.role)
        return to_user(self.repo.user_by("id", user_id))

    def change_password(self, user: dict, current: str | None, new: str, keep_token: str) -> None:
        if user["password_hash"] and not verify_password(current or "", user["password_hash"]):
            raise ServiceError("Current password is incorrect.", 401)
        self.repo.update_user(user["id"], password_hash=hash_password(new))
        self.repo.delete_user_sessions(user["id"], keep=_hash_token(keep_token))

    def save_avatar(self, user_id: int, data: bytes) -> User:
        if len(data) > AVATAR_MAX_BYTES:
            raise ServiceError("Photo must be 2 MB or smaller.", 413)
        ext = next((e for magic, e in _AVATAR_TYPES.items() if data.startswith(magic)), None)
        if ext is None:
            raise ServiceError("Photo must be a PNG or JPEG image.", 415)
        folder: Path = self.settings.avatars_dir
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(f"user-{user_id}.*"):
            old.unlink(missing_ok=True)
        name = f"user-{user_id}.{ext}"
        (folder / name).write_bytes(data)
        self.repo.update_user(user_id, avatar_file=name)
        return to_user(self.repo.user_by("id", user_id))

    def avatar_path(self, user_id: int) -> Path | None:
        row = self.repo.user_by("id", user_id)
        if not row or not row["avatar_file"]:
            return None
        p = self.settings.avatars_dir / row["avatar_file"]
        return p if p.exists() else None
