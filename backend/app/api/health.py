"""Liveness and readiness probes, plus Prometheus metrics.

/healthz : the process is up (used by Docker to restart a wedged container)
/readyz  : dependencies reachable (used by the load balancer to route traffic)
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.db import engine
from app.observability import render_metrics
from app.services.kv import get_kv

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response):
    checks = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "down"
    checks["cache"] = "ok" if get_kv().ping() else "down"
    ready = all(v == "ok" for v in checks.values())
    response.status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "degraded", "checks": checks}


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    # nginx does not proxy /metrics publicly; it is scraped on the internal network only.
    body, content_type = render_metrics()
    return Response(body, media_type=content_type)
