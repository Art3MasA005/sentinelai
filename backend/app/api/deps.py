from __future__ import annotations

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.services.auth import AuthService
from app.services.errors import ServiceError
from app.services.experiments import ExperimentService
from app.storage.repository import Repository


def get_repo(settings: Settings = Depends(get_settings)) -> Repository:
    return Repository(settings.db_path)


def get_experiments(settings: Settings = Depends(get_settings), repo: Repository = Depends(get_repo)) -> ExperimentService:
    return ExperimentService(settings, repo)


def get_auth(settings: Settings = Depends(get_settings), repo: Repository = Depends(get_repo)) -> AuthService:
    return AuthService(settings, repo)


def _token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    # Browser downloads (exports) cannot set headers, so they may pass the token as a query parameter.
    if request.url.path.endswith(("/export", "/figures")):
        return request.query_params.get("token")
    return None


def optional_user(request: Request, auth: AuthService = Depends(get_auth)) -> dict | None:
    token = _token(request)
    found = auth.user_for_token(token)
    if found is None:
        return None
    user, _ = found
    user["_token"] = token
    return user


def require_user(user: dict | None = Depends(optional_user)) -> dict:
    if user is None:
        raise ServiceError("Sign in required.", 401)
    return user


def guard(user: dict | None = Depends(optional_user), settings: Settings = Depends(get_settings)) -> dict | None:
    """Router-level guard: enforces sign-in only when SENTINEL_AUTH_REQUIRED is on."""
    if settings.auth_required and user is None:
        raise ServiceError("Sign in required.", 401)
    return user


def actor(user: dict | None = Depends(optional_user)) -> str | None:
    """Display name recorded in audit trails (alert triage, policy history)."""
    return user["name"] if user else None
