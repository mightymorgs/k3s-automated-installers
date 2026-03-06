"""FastAPI audit middleware.

Logs every API request/response with automatic secrets redaction.
Skips health-check endpoints to reduce noise.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from vm_builder.core.audit import AuditLogger, redact_secrets

# Paths to skip (health checks, static assets)
_SKIP_PATHS = frozenset({
    "/api/v1/health",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
})


class AuditMiddleware(BaseHTTPMiddleware):
    """Middleware that logs all API requests with redacted secrets.

    Args:
        app: The ASGI application.
        audit_logger: AuditLogger instance for writing entries.
    """

    def __init__(self, app, audit_logger: AuditLogger) -> None:
        super().__init__(app)
        self.audit_logger = audit_logger

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        # Skip noisy endpoints
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # Skip non-API paths (static files, SPA routes)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Generate a short request ID for correlation across logs and error responses.
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        # Read request body (for POST/PUT/PATCH)
        request_body = None
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body_bytes = await request.body()
                if body_bytes:
                    request_body = body_bytes.decode("utf-8", errors="replace")
            except Exception:
                request_body = "<unreadable>"

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Read response body.
        # Starlette streaming responses do not expose a .body attribute
        # directly, so we consume the body_iterator and rebuild the
        # response with the captured content.
        response_body = None
        if hasattr(response, "body"):
            try:
                response_body = response.body.decode("utf-8", errors="replace")
            except Exception:
                response_body = None

        # Collect response body from streaming response
        if response_body is None:
            body_chunks: list[bytes] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, bytes):
                    body_chunks.append(chunk)
                else:
                    body_chunks.append(chunk.encode("utf-8"))
            response_body_bytes = b"".join(body_chunks)
            response_body = response_body_bytes.decode("utf-8", errors="replace")

            # Rebuild response with captured body so the client still
            # receives the full payload.
            from starlette.responses import Response as StarletteResponse
            response = StarletteResponse(
                content=response_body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Pre-redact body strings before they enter the audit logger.
        # This is necessary because the logger serializes the detail dict
        # to JSON (double-escaping inner quotes), which would prevent the
        # JSON key-value regex from matching escaped field names.
        redacted_request_body = redact_secrets(request_body) if request_body else request_body
        redacted_response_body = redact_secrets(response_body) if response_body else response_body

        self.audit_logger.log_api_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            request_body=redacted_request_body,
            response_body=redacted_response_body,
            duration_ms=duration_ms,
            request_id=request_id,
        )

        return response
