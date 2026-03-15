"""HelmContext — the pipeline's state object, threaded through every stage."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from idi.generation.helm.models import (
    AnnotationInfo,
    HelmEdge,
    HelmFact,
    HelmSignal,
    SchemaInfo,
)

if TYPE_CHECKING:
    from idi.generation.crd.kind_registry import KindRegistry


@dataclass
class HelmContext:
    """Pipeline state threaded through every stage.

    Inputs are set at construction time. Output lists are populated
    by successive pipeline stages.
    """

    # Inputs
    chart_name: str
    chart_version: str
    app_version: str
    repository: str
    values: dict[str, Any]
    chart_meta: dict[str, Any]
    values_text: str

    # Shared resources
    kind_registry: Any  # KindRegistry or mock — typed as Any to avoid hard import

    # Pre-loaded enrichment sources
    schema_overrides: dict[tuple[str, ...], SchemaInfo] = field(default_factory=dict)
    annotations: dict[tuple[str, ...], AnnotationInfo] = field(default_factory=dict)
    chart_conditions: dict[str, str] = field(default_factory=dict)

    # Pipeline outputs (populated by stages)
    facts: list[HelmFact] = field(default_factory=list)
    edges: list[HelmEdge] = field(default_factory=list)
    signals: list[HelmSignal] = field(default_factory=list)
    library_deps: list[str] = field(default_factory=list)
    subchart_deps: list[dict] = field(default_factory=list)
