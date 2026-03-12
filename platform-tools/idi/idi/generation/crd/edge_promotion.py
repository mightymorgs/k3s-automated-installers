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


# ── Gate G-CRD1: Intra-Service Scope ────────────────────────


def gate_crd1_intra_service(
    edge: DependencyEdge,
    source_cf: ClassifiedField,
    graph: DependencyGraph,
) -> CrdGateResult:
    """G-CRD1: Only promote edges where source and target are same service."""
    src_node = graph.nodes.get(edge.source_gk)
    tgt_node = graph.nodes.get(edge.target_gk)
    if src_node is None or tgt_node is None:
        return CrdGateResult("G-CRD1", False, "node not found")
    if tgt_node.is_external:
        return CrdGateResult("G-CRD1", False, "target is external")
    if not src_node.service or not tgt_node.service:
        return CrdGateResult("G-CRD1", False, "missing service")
    if src_node.service != tgt_node.service:
        return CrdGateResult(
            "G-CRD1", False,
            f"cross-service: {src_node.service} -> {tgt_node.service}",
        )
    return CrdGateResult("G-CRD1", True, "same service")


# ── Gate G-CRD2: Field Type Validation ──────────────────────

_PROMOTABLE_FIELD_TYPES: frozenset[str] = frozenset({"string", "array"})


def gate_crd2_field_type(
    edge: DependencyEdge,
    source_cf: ClassifiedField,
    graph: DependencyGraph,
) -> CrdGateResult:
    """G-CRD2: Only promote edges from string or array fields."""
    ft = source_cf.field_type
    if ft in _PROMOTABLE_FIELD_TYPES:
        return CrdGateResult("G-CRD2", True, f"type={ft}")
    return CrdGateResult("G-CRD2", False, f"non-ref type: {ft}")


# ── Gate G-CRD3: Ref-Shape Sibling Evidence (Non-Blocking) ──


def gate_crd3_ref_shape(
    edge: DependencyEdge,
    source_cf: ClassifiedField,
    graph: DependencyGraph,
) -> CrdGateResult:
    """G-CRD3: Informational gate — always passes (non-blocking)."""
    return CrdGateResult("G-CRD3", True, "ref-shape sibling check (non-blocking)")


# ── Gate G-CRD4: Discriminator / List-Map Key Exclusion ─────


def gate_crd4_not_discriminator(
    edge: DependencyEdge,
    source_cf: ClassifiedField,
    graph: DependencyGraph,
) -> CrdGateResult:
    """G-CRD4: Reject edges from list-map key fields."""
    if "list_map" in source_cf.detection_source:
        return CrdGateResult("G-CRD4", False, "list-map key")
    return CrdGateResult("G-CRD4", True, "not discriminator")
