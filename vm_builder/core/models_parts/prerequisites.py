"""Prerequisite-check models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PrereqResult(BaseModel):
    """Result of checking CLI prerequisites."""

    ok: bool
    bws_version: Optional[str] = None
    gh_version: Optional[str] = None
    error: Optional[str] = None
