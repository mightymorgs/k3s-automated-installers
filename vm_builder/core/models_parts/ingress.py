"""Ingress validation models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class IngressValidateRequest(BaseModel):
    """Request to validate ingress configuration."""

    mode: str
    domain: Optional[str] = None


class IngressValidateResult(BaseModel):
    """Result of ingress validation."""

    valid: bool
    error: Optional[str] = None
    warnings: list[str] = []
