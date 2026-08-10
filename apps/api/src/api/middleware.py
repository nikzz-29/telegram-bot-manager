"""Per-request logging context.

Every log line emitted while handling a request carries the same `request_id`,
so a Mini App bug report with one id is enough to pull the whole story out of
the log stream.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from shared.logging import bind_contextvars, clear_update_context, get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request fields to structlog contextvars and log the access line."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # An id supplied by a proxy is reused so one trace spans both hops.
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        clear_update_context()
        bind_contextvars(request_id=request_id, method=request.method, path=request.url.path)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The exception handler renders the body; this only closes the line.
            logger.warning(
                "api.request_failed", duration_ms=round((time.perf_counter() - started) * 1000, 2)
            )
            clear_update_context()
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        # DECISION: health checks are not logged. A container platform polls
        # `/health` every few seconds, and burying real traffic under that noise
        # makes the log stream useless exactly when it is needed.
        if request.url.path not in {"/health", "/ready"}:
            logger.info("api.request", status=response.status_code, duration_ms=duration_ms)
        response.headers[REQUEST_ID_HEADER] = request_id
        clear_update_context()
        return response


__all__ = ["REQUEST_ID_HEADER", "RequestContextMiddleware"]
