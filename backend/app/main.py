"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as SATimeoutError

from app.api import auth, conversations, datasets, health
from app.config import get_settings
from app.db import Base, engine
from app.logging_setup import configure_logging
from app.middleware import RequestContextMiddleware

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    s.validate_for_production()
    Path(s.storage_dir).mkdir(parents=True, exist_ok=True)
    if s.database_url.startswith("sqlite"):
        Path("data").mkdir(exist_ok=True)
        Base.metadata.create_all(engine)  # dev/test convenience; Postgres uses Alembic migrations
    log.info("startup complete", extra={"fields": {"env": s.app_env, "llm": s.llm_provider}})
    yield


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    app = FastAPI(
        title=f"{s.app_name} API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if s.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if s.app_env != "production" else None,
    )
    app.add_middleware(RequestContextMiddleware)
    if s.cors_origin_list:
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                           allow_methods=["GET", "POST", "PATCH", "DELETE"],
                           allow_headers=["content-type", "x-csrf-token", "x-request-id"])

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # Return the first problem in plain words; never echo the full input back.
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
        return JSONResponse(status_code=422, content={"detail": f"{field}: {first.get('msg', 'invalid value')}"})

    @app.exception_handler(SATimeoutError)
    async def _pool_exhausted(_: Request, exc: SATimeoutError):
        # Load shedding: tell clients (and nginx's retry logic) to back off briefly.
        log.warning("db pool exhausted, shedding request")
        return JSONResponse(status_code=503, content={"detail": "The service is busy. Please retry in a moment."},
                            headers={"Retry-After": "2"})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.error("unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal error. It has been logged."})

    for router in (health.router, auth.router, datasets.router, conversations.router):
        app.include_router(router)
    return app


app = create_app()
