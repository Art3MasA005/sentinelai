"""FastAPI application. Run: `python -m app.cli serve` (binds to localhost by default)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, datasets, experiments, health, ops
from app.api.deps import guard
from app.config import API_PREFIX, APP_VERSION, get_settings
from app.services import ops as ops_service
from app.services.errors import ServiceError
from app.storage.db import init_db
from app.storage.repository import Repository
from app.workers import manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db(settings.db_path)
    repo = Repository(settings.db_path)
    ops_service.ensure_default_policy(repo)
    manager.reconcile(repo)
    from app.services.experiments import ExperimentService

    ExperimentService(settings, repo).dispatch()  # resume the queue left by a previous API process
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SentinelAI API",
        version=APP_VERSION,
        description="Local research backend for drift-aware open-world intrusion detection (offline replay only).",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Run-Id", "X-Data-Origin", "X-Config-Hash"],
    )

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    for module in (health, auth):  # public
        app.include_router(module.router, prefix=API_PREFIX)
    for module in (datasets, experiments, ops):  # sign-in enforced when SENTINEL_AUTH_REQUIRED=true
        app.include_router(module.router, prefix=API_PREFIX, dependencies=[Depends(guard)])
    return app


app = create_app()
