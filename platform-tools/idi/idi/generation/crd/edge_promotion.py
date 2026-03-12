"""CRD edge promotion gates — post-detection validation for soft/optional edges.

Mirrors the REST pipeline's ``verify.py`` programmatic gate architecture.
Each gate evaluates a single signal and returns a CrdGateResult indicating
whether the edge should be promoted from soft/optional to hard.

All 6 gates must pass for promotion. Any single failure preserves the
original edge type.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.topo_sort import DependencyEdge, DependencyGraph

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrdGateResult:
    """Result of applying a promotion gate to a CRD dependency edge."""

    gate: str   # "G-CRD1", "G-CRD2", etc.
    keep: bool  # True = passes gate (eligible for promotion)
    reason: str  # Human-readable explanation
