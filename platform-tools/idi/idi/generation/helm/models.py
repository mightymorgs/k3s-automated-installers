"""Core data models for the Helm extractor pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Vocabulary constants
# ---------------------------------------------------------------------------

VALID_SHAPES = frozenset({"identity", "addressability", "credential", "config"})

VALID_SIGNAL_TYPES = frozenset({
    "secret_binding",
    "pvc_binding",
    "configmap_binding",
    "role_binding",
    "serviceaccount_binding",
    "unknown_binding",
    "external_service_dependency",
    "subchart_dependency",
})

VALID_RESOURCE_TYPES = frozenset({
    "Secret",
    "PersistentVolumeClaim",
    "ConfigMap",
    "Role",
    "ServiceAccount",
    "Service",
    "Chart",
    "Unknown",
})


# ---------------------------------------------------------------------------
# Classification record
# ---------------------------------------------------------------------------

@dataclass
class Classification:
    """A single classification attempt — all attempts are logged, not just winners."""

    field: str           # "shape", "semantic_type", "is_toggle", "signal"
    value: str
    method: str          # One of the method taxonomy values
    confidence: float    # 0.50 - 0.95
    evidence: str


# ---------------------------------------------------------------------------
# HelmFact
# ---------------------------------------------------------------------------

@dataclass
class HelmFact:
    """A single configurable value extracted from values.yaml."""

    # Identity
    path: str
    path_segments: list[str]
    uri: str

    # Value
    default_value: Any
    type: str
    semantic_type: str
    has_template: bool
    default_empty: bool
    default_truncated: bool

    # Classification (winning values)
    shape: str
    format: str | None
    required: bool
    enum: list[str] | None
    description: str | None

    # Toggle/feature context
    is_toggle: bool
    conditional_on: str | None
    feature: str | None

    # Cross-app
    cross_app_signal: str | None

    # Audit trail
    classifications: list[Classification] = field(default_factory=list)
    source: str = "heuristic_default"
    confidence: float = 0.50
    needs_review: bool = True


# ---------------------------------------------------------------------------
# HelmEdge
# ---------------------------------------------------------------------------

@dataclass
class HelmEdge:
    """An intra-chart dependency edge (toggle gating)."""

    source: str
    target: str
    type: str            # "DEPENDS_ON"
    method: str
    confidence: float
    evidence: str
    conditional_value: str | None
    needs_review: bool


# ---------------------------------------------------------------------------
# HelmSignal
# ---------------------------------------------------------------------------

@dataclass
class HelmSignal:
    """A cross-chart signal detected in values.yaml."""

    uri: str
    path: str
    signal_type: str
    resource_type: str
    evidence: str
    method: str
    confidence: float
    related_facts: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Enrichment source models
# ---------------------------------------------------------------------------

@dataclass
class SchemaInfo:
    """Information extracted from values.schema.json for a single path."""

    type: str | None
    format: str | None
    enum: list[str] | None
    required: bool
    description: str | None
    default: Any
    write_only: bool
    pattern: str | None


@dataclass
class AnnotationInfo:
    """Information extracted from structured annotations for a single path."""

    type: str | None
    description: str | None
    enum: list[str] | None
    source: str          # "bitnami_param", "dadav_schema", "helm_docs"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_fact(fact: HelmFact) -> list[str]:
    """Return list of validation errors (empty if valid)."""
    errors: list[str] = []
    if fact.shape not in VALID_SHAPES:
        errors.append(
            f"Invalid shape '{fact.shape}' for fact '{fact.path}'. "
            f"Valid: {sorted(VALID_SHAPES)}"
        )
    return errors


def validate_signal(signal: HelmSignal) -> list[str]:
    """Return list of validation errors (empty if valid)."""
    errors: list[str] = []
    if signal.signal_type not in VALID_SIGNAL_TYPES:
        errors.append(
            f"Invalid signal_type '{signal.signal_type}' for signal '{signal.path}'. "
            f"Valid: {sorted(VALID_SIGNAL_TYPES)}"
        )
    if signal.resource_type not in VALID_RESOURCE_TYPES:
        errors.append(
            f"Invalid resource_type '{signal.resource_type}' for signal '{signal.path}'. "
            f"Valid: {sorted(VALID_RESOURCE_TYPES)}"
        )
    return errors
