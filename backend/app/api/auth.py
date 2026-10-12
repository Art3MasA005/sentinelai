from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.deps import get_auth, require_user
from app.config import Settings, get_settings
from app.schemas.auth import (ROLES, AuthConfig, GoogleLoginRequest, LoginRequest, PasswordChange, ProfileUpdate,
                              Session, SignupRequest, User)
from app.schemas.common import Message
from app.services.auth import AuthService, to_user
from app.services.errors import ServiceError

router = APIRouter(prefix="/auth", tags=["auth"])


def _client(request: Request) -> str:
    return request.headers.get("x-sentinel-client") or request.headers.get("user-agent", "")


@router.get("/config", response_model=AuthConfig)
def config(settings: Settings = Depends(get_settings)):
    """Public: what the login screen should offer."""
    return AuthConfig(
        auth_required=settings.auth_required,
        google_enabled=bool(settings.google_client_id),
        google_client_id=settings.google_client_id or None,
        google_desktop_enabled=bool(settings.google_desktop_client_id and settings.google_desktop_client_secret),
        roles=list(ROLES),
    )


@router.post("/signup", response_model=Session, status_code=201)
def signup(req: SignupRequest, request: Request, auth: AuthService = Depends(get_auth)):
    return auth.signup(req, _client(request))


@router.post("/login", response_model=Session)
def login(req: LoginRequest, request: Request, auth: AuthService = Depends(get_auth)):
    return auth.login(req.email, req.password, req.remember, _client(request))


@router.post("/google", response_model=Session)
def google(req: GoogleLoginRequest, request: Request, auth: AuthService = Depends(get_auth)):
    """Sign in (or sign up) with a Google ID token; verified with Google before any account is touched."""
    return auth.google_login(req.id_token, req.remember, _client(request))


class DesktopCode(BaseModel):
    code: str
    redirect_uri: str
    code_verifier: str
    remember: bool = True


@router.post("/google/desktop", response_model=Session)
def google_desktop(req: DesktopCode, request: Request, auth: AuthService = Depends(get_auth)):
    """Windows build: finish the browser (loopback + PKCE) flow; the client secret stays on the backend."""
    id_token = auth.exchange_desktop_code(req.code, req.redirect_uri, req.code_verifier)
    return auth.google_login(id_token, req.remember, _client(request))


@router.post("/logout", response_model=Message)
def logout(user=Depends(require_user), auth: AuthService = Depends(get_auth)):
    auth.logout(user["_token"])
    return Message(message="Signed out.")


@router.get("/me", response_model=User)
def me(user=Depends(require_user)):
    return to_user(user)


@router.put("/me", response_model=User)
def update_me(req: ProfileUpdate, user=Depends(require_user), auth: AuthService = Depends(get_auth)):
    return auth.update_profile(user["id"], req)


@router.post("/me/password", response_model=Message)
def change_password(req: PasswordChange, user=Depends(require_user), auth: AuthService = Depends(get_auth)):
    auth.change_password(user, req.current_password, req.new_password, user["_token"])
    return Message(message="Password updated. Other sessions were signed out.")


@router.put("/me/avatar", response_model=User)
async def upload_avatar(request: Request, user=Depends(require_user), auth: AuthService = Depends(get_auth)):
    """Raw PNG/JPEG bytes in the request body (max 2 MB)."""
    data = await request.body()
    if not data:
        raise ServiceError("Empty upload.", 400)
    return auth.save_avatar(user["id"], data)


@router.get("/me/avatar")
def get_avatar(user=Depends(require_user), auth: AuthService = Depends(get_auth)):
    path = auth.avatar_path(user["id"])
    if path is None:
        raise ServiceError("No profile photo.", 404)
    return FileResponse(path, headers={"Cache-Control": "no-store"})
