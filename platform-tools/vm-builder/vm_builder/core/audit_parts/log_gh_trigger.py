"""GitHub workflow-trigger convenience logger method."""

from __future__ import annotations


def log_gh_trigger(
    self,
    workflow: str,
    params: dict[str, str],
    duration_ms: int = 0,
) -> None:
    """Log one gh workflow run trigger event."""
    self.log(
        "gh_trigger",
        {
            "workflow": workflow,
            "params": params,
        },
        duration_ms=duration_ms,
    )
