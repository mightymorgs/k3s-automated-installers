"""Registry refresh models."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class RefreshStatus(str, Enum):
    """Outcome of a registry refresh request."""

    REFRESHED = "refreshed"
    ALREADY_IN_PROGRESS = "already_in_progress"
    COOLDOWN_ACTIVE = "cooldown_active"
    ERROR = "error"


class RefreshResult(BaseModel):
    """Result of a registry refresh operation."""

    status: RefreshStatus
    commit_sha: Optional[str] = None
    apps_count: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None
