"""Request id, access log, metrics and security headers, as one pure ASGI middleware
(BaseHTTPMiddleware would buffer the SSE stream)."""
from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging_setup import log_event, request_id_var, user_id_var
from app.observability import HTTP_LATENCY, HTTP_REQUESTS

log = logging.getLogger("quarry.access")

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),  # API responses only
    (b"cache-control", b"no-store"),
]
_ID_RE = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def route_template(path: str) -> str:
    """Collapse ids so metrics labels have low cardinality."""
    return _ID_RE.sub("/{id}", path)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode()[:64]
        rid = incoming if re.fullmatch(r"[A-Za-z0-9\-]{8,64}", incoming or "") else uuid.uuid4().hex
        request_id_var.set(rid)
        user_id_var.set("-")
        started = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                hdrs = list(message.get("headers", []))
                existing = {k.lower() for k, _ in hdrs}
                hdrs += [(k, v) for k, v in _SECURITY_HEADERS if k not in existing]
                hdrs.append((b"x-request-id", rid.encode()))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            route = route_template(scope["path"])
            method = scope["method"]
            if route not in ("/healthz", "/readyz", "/metrics"):
                HTTP_REQUESTS.labels(method, route, str(status_holder["code"])).inc()
                HTTP_LATENCY.labels(method, route).observe(elapsed)
                log_event(log, "request", method=method, path=route, status=status_holder["code"],
                          ms=int(elapsed * 1000))
