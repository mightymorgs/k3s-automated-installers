"""Data models for RepoService."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class RepoStatus(BaseModel):
    """Result of a repo sync operation."""

    available: bool
    action: Optional[str] = None
    error: Optional[str] = None
    repo_dir: Optional[str] = None
