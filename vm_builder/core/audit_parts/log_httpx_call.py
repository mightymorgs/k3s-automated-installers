"""HTTP-call convenience logger method."""

from __future__ import annotations

from typing import Any


def log_httpx_call(
    self,
    method: str,
    url: str,
    status_code: int | None = None,
    headers: dict[str, str] | None = None,
    request_body: Any = None,
    response_body: Any = None,
    duration_ms: int = 0,
) -> None:
    """Log one outbound HTTP call (GitHub/Tailscale/etc)."""
    self.log(
        "httpx_call",
        {
            "method": method,
            "url": url,
            "status_code": status_code,
            "headers": headers,
            "request_body": request_body,
            "response_body": response_body,
        },
        duration_ms=duration_ms,
    )
