import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logger import get_logger

logger = get_logger("middleware.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every incoming HTTP request with method, path, status, and latency."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()

        logger.info(
            "→ %s %s  [req_id=%s]",
            request.method,
            request.url.path,
            request_id,
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                "✗ %s %s  [req_id=%s]  %.2fms  UNHANDLED: %s",
                request.method,
                request.url.path,
                request_id,
                elapsed,
                exc,
                exc_info=True,
            )
            raise

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "← %s %s  [req_id=%s]  status=%d  %.2fms",
            request.method,
            request.url.path,
            request_id,
            response.status_code,
            elapsed,
        )

        response.headers["X-Request-ID"] = request_id
        return response
