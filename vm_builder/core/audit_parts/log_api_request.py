"""API-request convenience logger method."""

from __future__ import annotations

from typing import Any


def log_api_request(
    self,
    method: str,
    path: str,
    status_code: int,
    request_body: Any = None,
    response_body: Any = None,
    duration_ms: int = 0,
    request_id: str | None = None,
) -> None:
    """Log one FastAPI request/response pair."""
    detail: dict[str, Any] = {
        "method": method,
        "path": path,
        "status_code": status_code,
        "request_body": request_body,
        "response_body": response_body,
    }
    if request_id is not None:
        detail["request_id"] = request_id
    self.log(
        "api_request",
        detail,
        duration_ms=duration_ms,
    )
