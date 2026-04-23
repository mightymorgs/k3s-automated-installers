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


# ── Gate G-CRD5: Depth Sanity Check ─────────────────────────

_MAX_PROMOTION_DEPTH = 4


def gate_crd5_depth(
    edge: DependencyEdge,
    source_cf: ClassifiedField,
    graph: DependencyGraph,
) -> CrdGateResult:
    """G-CRD5: Reject edges from deeply nested fields (depth > 4 under spec)."""
    parts = source_cf.field.split(".")
    depth = len(parts) - 1 if parts[0] == "spec" else len(parts)
    if depth > _MAX_PROMOTION_DEPTH:
        return CrdGateResult("G-CRD5", False, f"depth={depth} > {_MAX_PROMOTION_DEPTH}")
    return CrdGateResult("G-CRD5", True, f"depth={depth}")


# ── Gate G-CRD6: Confidence Floor ───────────────────────────

_PROMOTION_CONFIDENCE_FLOOR = 0.75


def gate_crd6_confidence(
    edge: DependencyEdge,
    source_cf: ClassifiedField,
    graph: DependencyGraph,
) -> CrdGateResult:
    """G-CRD6: Reject edges below minimum confidence threshold."""
    if edge.confidence < _PROMOTION_CONFIDENCE_FLOOR:
        return CrdGateResult("G-CRD6", False, f"conf={edge.confidence} < {_PROMOTION_CONFIDENCE_FLOOR}")
    return CrdGateResult("G-CRD6", True, f"conf={edge.confidence}")


# ── Gate registry ────────────────────────────────────────────

_CRD_PROMOTION_GATES = [
    gate_crd1_intra_service,
    gate_crd2_field_type,
    gate_crd3_ref_shape,
    gate_crd4_not_discriminator,
    gate_crd5_depth,
    gate_crd6_confidence,
]


# ── Promotion runner ─────────────────────────────────────────


def promote_soft_edges(
    edges: list[DependencyEdge],
    classified_fields_index: dict[tuple[str, str, str], ClassifiedField],
    graph: DependencyGraph,
) -> list[DependencyEdge]:
    """Promote qualified soft/optional intra-service edges to hard.

    For each non-hard edge, looks up its ClassifiedField and runs all
    6 gates. If ALL gates pass, the edge is promoted to hard. Otherwise
    the original edge is kept unchanged.

    Args:
        edges: Raw dependency edges from Step 4.
        classified_fields_index: Keyed by (source_gk, field_path, target_gk).
        graph: Partially-built graph with nodes populated.

    Returns:
        New list with promoted edges.
    """
    promoted: list[DependencyEdge] = []
    for edge in edges:
        if edge.edge_type == "hard":
            promoted.append(edge)
            continue

        cf = classified_fields_index.get(
            (edge.source_gk, edge.source_field, edge.target_gk),
        )
        if cf is None:
            promoted.append(edge)
            continue

        results = [gate(edge, cf, graph) for gate in _CRD_PROMOTION_GATES]
        all_pass = all(r.keep for r in results)

        if all_pass:
            promoted.append(DependencyEdge(
                source_gk=edge.source_gk,
                target_gk=edge.target_gk,
                edge_type="hard",
                source_field=edge.source_field,
                detection_source=edge.detection_source,
                confidence=edge.confidence,
            ))
            logger.info(
                "PROMOTED %s -> %s [%s] gates=%s",
                edge.source_gk, edge.target_gk, edge.detection_source,
                " ".join(f"{r.gate}:OK" for r in results),
            )
        else:
            promoted.append(edge)
            failed = [r for r in results if not r.keep]
            logger.debug(
                "KEPT-SOFT %s -> %s [%s] failed=%s",
                edge.source_gk, edge.target_gk, edge.detection_source,
                " ".join(f"{r.gate}:{r.reason}" for r in failed),
            )

    return promoted
