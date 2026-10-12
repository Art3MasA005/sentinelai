from __future__ import annotations

import platform
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import APP_VERSION, Settings, get_settings
from app.ml.profiles import BUILTIN_PROFILES
from app.services.exports import LIBRARIES, package_version
from app.storage.db import closing, connect
from app.workers import manager

router = APIRouter(tags=["health"])
_STARTED = time.monotonic()


class Check(BaseModel):
    ok: bool
    detail: str


class Health(BaseModel):
    status: str  # "ok" | "degraded"
    version: str
    time: datetime
    uptime_seconds: float
    checks: dict[str, Check]
    active_workers: int
    paths: dict[str, str]
    python: str
    libraries: dict[str, str | None]
    profiles: list[str]
    mode: str
    auth_required: bool


@router.get("/health", response_model=Health)
def health(settings: Settings = Depends(get_settings)) -> Health:
    checks: dict[str, Check] = {}
    try:
        with closing(connect(settings.db_path)) as c:
            c.execute("SELECT 1 FROM runs LIMIT 1").fetchall()
        checks["database"] = Check(ok=True, detail=str(settings.db_path))
    except Exception as e:  # noqa: BLE001
        checks["database"] = Check(ok=False, detail=f"{type(e).__name__}: {e}")
    for name, path in (("datasets_dir", settings.datasets_dir), ("results_dir", settings.results_dir)):
        ok = path.is_dir()
        checks[name] = Check(ok=ok, detail=str(path) if ok else f"missing: {path}")
    return Health(
        status="ok" if all(c.ok for c in checks.values()) else "degraded",
        version=APP_VERSION,
        time=datetime.now(timezone.utc),
        uptime_seconds=round(time.monotonic() - _STARTED, 1),
        checks=checks,
        active_workers=manager.active_workers(),
        paths={"datasets_dir": str(settings.datasets_dir), "results_dir": str(settings.results_dir),
               "configs_dir": str(settings.configs_dir), "db_path": str(settings.db_path)},
        python=platform.python_version(),
        libraries={p: package_version(p) for p in LIBRARIES},
        profiles=list(BUILTIN_PROFILES),
        mode="local research console (offline replay only; no live capture, no blocking)",
        auth_required=settings.auth_required,
    )
