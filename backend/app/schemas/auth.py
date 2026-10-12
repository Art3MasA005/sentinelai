from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[0-9][0-9 \-()]{6,19}$")
ROLES = ("Researcher", "Student", "Security analyst", "Supervisor", "Other")


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


class ProfileFields(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    phone: str | None = Field(None, max_length=24)
    country: str | None = Field(None, max_length=60)
    institution: str | None = Field(None, max_length=120)
    role: str | None = Field(None, max_length=40)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Enter your full name.")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        v = _clean(v)
        if v and not _PHONE.match(v):
            raise ValueError("Enter a phone number with country code, e.g. +8801712345678.")
        return v

    @field_validator("country", "institution", "role")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return _clean(v)


class SignupRequest(ProfileFields):
    email: str = Field(..., max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    phone: str = Field(..., max_length=24)
    remember: bool = True

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"[0-9]", v)):
            raise ValueError("Password needs at least 8 characters with letters and numbers.")
        return v


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=120)
    password: str = Field(..., max_length=128)
    remember: bool = False


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(..., min_length=20)
    remember: bool = True


class ProfileUpdate(ProfileFields):
    pass


class PasswordChange(BaseModel):
    current_password: str | None = None
    new_password: str = Field(..., min_length=8, max_length=128)


class User(BaseModel):
    id: int
    email: str
    name: str
    phone: str | None
    country: str | None
    institution: str | None
    role: str | None
    has_avatar: bool
    has_password: bool
    google_linked: bool
    # Google sign-ups start without phone etc.; the app asks for the rest once.
    profile_complete: bool
    created_at: datetime
    last_login_at: datetime | None


class Session(BaseModel):
    token: str
    expires_at: datetime
    user: User


class AuthConfig(BaseModel):
    auth_required: bool
    google_enabled: bool
    google_client_id: str | None
    google_desktop_enabled: bool
    roles: list[str]
