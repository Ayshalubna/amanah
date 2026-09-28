"""Production middleware: security headers, rate limiting, request logging, warm start.

Kept dependency-free on purpose (no Redis): the demo runs as a single process, so an
in-memory sliding window is enough. Behind several replicas you would move the limiter
to a shared store.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("amanah")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(h)
    log.setLevel(os.getenv("AMANAH_LOG_LEVEL", "INFO"))

# Hugging Face shows Spaces inside an iframe on huggingface.co, so framing is allowed only from there.
FRAME_ANCESTORS = os.getenv("AMANAH_FRAME_ANCESTORS", "'self' https://huggingface.co https://*.hf.space")

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; "
       f"connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors {FRAME_ANCESTORS}")


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            resp.headers.setdefault("Content-Security-Policy", CSP)
        path = request.url.path
        if path.startswith("/fonts/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.endswith((".css", ".js")):
            resp.headers["Cache-Control"] = "public, max-age=300"
        elif path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp


class RateLimit(BaseHTTPMiddleware):
    """Per-client sliding window. Writes (POST) are limited harder than reads."""

    def __init__(self, app, reads_per_min: int = 240, writes_per_min: int = 30):
        super().__init__(app)
        self.limits = {"GET": reads_per_min, "POST": writes_per_min}
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self.lock = threading.Lock()

    async def dispatch(self, request: Request, call_next) -> Response:
        method = "POST" if request.method == "POST" else "GET"
        fwd = request.headers.get("x-forwarded-for", "")
        client = fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        with self.lock:
            q = self.hits[(client, method)]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.limits[method]:
                return JSONResponse({"detail": "Too many requests - please wait a minute and try again."},
                                    status_code=429, headers={"Retry-After": "60"})
            q.append(now)
        return await call_next(request)


class AccessLog(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse({"detail": "Internal error - the team has been notified."}, status_code=500)
        if request.url.path.startswith(("/api/", "/cases", "/screen")):
            log.info("%s %s %s %.0fms", request.method, request.url.path, resp.status_code,
                     (time.perf_counter() - t0) * 1000)
        return resp


def warm_up() -> None:
    """Load data, model, screening cache, SHAP and retriever before the first user arrives."""
    from . import graph, overview
    from .rag import get_retriever

    t0 = time.perf_counter()
    c = graph.ctx()
    overview.screening_all()
    c.model.explain(c.features.iloc[[0]])
    get_retriever()
    log.info("warm-up finished in %.1fs", time.perf_counter() - t0)
