"""BWS-write convenience logger method."""

from __future__ import annotations

from typing import Any


def log_bws_write(
    self,
    operation: str,
    key: str,
    value: Any = None,
    duration_ms: int = 0,
) -> None:
    """Log one BWS create/edit/delete operation."""
    self.log(
        "bws_write",
        {
            "operation": operation,
            "key": key,
            "value": value,
        },
        duration_ms=duration_ms,
    )
