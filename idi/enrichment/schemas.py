"""Pydantic schemas for Haiku structured extraction output."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CrossAppEdge(BaseModel):
    """A single cross-app dependency edge extracted by Haiku."""

    source_op: str = Field(description="Source operation path: service/resource/operation")
    target_op: str = Field(description="Target operation path: service/resource/operation")
    fields: list[str] = Field(description="Field names that carry the dependency")
    source_fact: str | None = Field(
        default=None, description="facts:// URI for source field"
    )
    target_fact: str | None = Field(
        default=None, description="facts:// URI for target field"
    )
    evidence: str = Field(description="Why this edge exists (from Context7 snippet)")
    confidence: str = Field(default="medium", description="high, medium, or low")


class ServiceCrossDepExtraction(BaseModel):
    """Haiku extraction output for one service."""

    service: str
    edges: list[CrossAppEdge]
