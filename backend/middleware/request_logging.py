"""
HTTP request logging with request IDs.
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from services.log_context import reset_request_context, set_log_user_id, set_request_context

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        request_token = set_request_context(request_id)
        user_token = set_log_user_id(None)
        started = time.monotonic()

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            logger.exception("request failed method=%s path=%s", request.method, request.url.path)
            raise
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            user_id = getattr(request.state, "user_id", "-")
            set_log_user_id(user_id)
            logger.info(
                "request completed method=%s path=%s status=%s duration_ms=%s user=%s",
                request.method,
                request.url.path,
                status_code,
                duration_ms,
                user_id,
            )
            reset_request_context(request_token, user_token)
