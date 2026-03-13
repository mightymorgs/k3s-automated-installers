"""Topological sort module for CRD Kind dependency ordering.

Takes 301+ detected refs from the CRD pipeline and produces deterministic
tier assignments for deployment ordering using Kahn's algorithm
with Tarjan's SCC cycle resolution.

CLI: python -m idi.generation.crd.topo_sort [--catalog-dir DIR] [--service SVC] [--global] [--write] [--verbose]
"""
from __future__ import annotations

import argparse
import heapq
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Literal

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.olm_loader import GVKRef
from idi.generation.dep_adapters.base import Output

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KindNode:
    """A node in the Kind-level dependency graph.

    One per CRD Kind, plus one per external reference target.
    Identity is the fully-qualified (group, kind) pair.
    """

    kind: str
    group: str
    service: str
    is_external: bool = False

    @property
    def gk(self) -> str:
        """Fully-qualified group/kind identifier.

        E.g. 'cert-manager.io/Certificate' or '/Secret' for core.
        """
        return f"{self.group}/{self.kind}"


@dataclass(frozen=True)
class DependencyEdge:
    """A directed consumption edge: source Kind depends on target Kind.

    Edge direction convention: source depends on target.
    'Certificate depends on Issuer' -> source_gk='cert-manager.io/Certificate',
    target_gk='cert-manager.io/Issuer'.
    """

    source_gk: str  # group/kind of the dependent
    target_gk: str  # group/kind of the prerequisite
    edge_type: Literal["hard", "soft", "optional"]
    source_field: str  # dot-path of the field that created this edge
    detection_source: str  # which detector produced this
    confidence: float


@dataclass(frozen=True)
class ProductionEdge:
    """A directed production edge: source Kind produces target Kind.

    Used for cross-service ordering (Certificate produces Secret).
    """

    source_gk: str  # group/kind of the producer
    target_gk: str  # group/kind of what is produced
    production_type: Literal["self", "side_effect", "rbac", "olm"]
    confidence: float
    detection_source: str  # provenance string


@dataclass
class SortTier:
    """A group of Kinds that can be applied in parallel (same deployment wave).

    Tier 0 = apply first (no unresolved hard dependencies).
    """

    tier: int
    kinds: list[str]  # list of gk strings, sorted deterministically
    scc_group: list[str] | None = None  # populated only if tier contains a collapsed SCC


@dataclass
class DependencyGraph:
    """Container for the full Kind-level dependency graph.

    Holds all nodes, both edge types, and the set of external Kinds.
    """

    nodes: dict[str, KindNode]  # keyed by gk string
    dependency_edges: list[DependencyEdge]
    production_edges: list[ProductionEdge]
    external_kinds: set[str]  # gk strings of always-external nodes


# Core K8s types that are always-external with in-degree 0.
# Group-qualified tuples prevent CRD collision (e.g. custom "Service" != core "Service").
# Empty string "" = core API group (apiVersion: v1).
# Note: KindRegistry uses group="core" for these; build_dependency_graph() handles mapping.
CORE_EXTERNAL_KINDS: frozenset[tuple[str, str]] = frozenset({
    ("", "Secret"),
    ("", "ConfigMap"),
    ("", "Service"),
    ("", "ServiceAccount"),
    ("", "Namespace"),
    ("", "PersistentVolumeClaim"),
    ("", "Endpoints"),
    ("networking.k8s.io", "Ingress"),
    ("networking.k8s.io", "IngressClass"),
    ("storage.k8s.io", "StorageClass"),
    ("scheduling.k8s.io", "PriorityClass"),
    ("rbac.authorization.k8s.io", "ClusterRole"),
    ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
    ("rbac.authorization.k8s.io", "Role"),
    ("rbac.authorization.k8s.io", "RoleBinding"),
})

# Edge type priority for deduplication: hard always wins.
_EDGE_TYPE_PRIORITY: dict[str, int] = {"hard": 3, "optional": 2, "soft": 1}

# Detection source suffixes allowed to produce hard edges.
# Only structurally-proven detectors qualify; weak heuristic
# detectors (parent_kind_name, enum_kind, fuzzy_kind_name) are
# demoted to soft even when the field is required.
_HARD_EDGE_SOURCES: frozenset[str] = frozenset({
    "structural_ref",
    "secret_key_selector",
    "ref_tuple",
    "kubernetes_ext_embedded",
    "kubernetes_ext_list_map",
    "operator_dict",
    "kind_registry",
    "array_ref",
    "cataloged_shape",
    "constraint_fk",
    "embedded_workload",
    "alm_label",
})


def _is_hard_eligible(detection_source: str) -> bool:
    """Check if detection source is allowed to produce hard edges."""
    suffix = detection_source.rsplit(":", 1)[-1] if ":" in detection_source else detection_source
    return suffix in _HARD_EDGE_SOURCES


_WEAK_DETECTION_SOURCES: frozenset[str] = frozenset({
    "parent_kind_name",
    "enum_kind",
    "fuzzy_kind_name",
})


def _is_weak_source(detection_source: str) -> bool:
    """Check if detection source is a weak (high-FP) detector."""
    suffix = detection_source.rsplit(":", 1)[-1] if ":" in detection_source else detection_source
    return suffix in _WEAK_DETECTION_SOURCES


def _filter_cross_ecosystem_edges(
    edges: list[DependencyEdge],
) -> list[DependencyEdge]:
    """Demote suspicious single-edge cross-ecosystem dependencies.

    A single weak edge between two API groups with no other connecting
    edges is demoted to optional (preserving the edge for visibility
    but reducing its influence on ordering).
    """
    # Group cross-group edges by (source_group, target_group).
    group_pair_edges: dict[tuple[str, str], list[int]] = {}
    for i, e in enumerate(edges):
        src_group = e.source_gk.split("/")[0]
        tgt_group = e.target_gk.split("/")[0]
        if src_group == tgt_group:
            continue
        pair = (src_group, tgt_group)
        group_pair_edges.setdefault(pair, []).append(i)

    # Demote single weak cross-group edges.
    demoted: set[int] = set()
    for _pair, indices in group_pair_edges.items():
        if len(indices) != 1:
            continue
        idx = indices[0]
        if _is_weak_source(edges[idx].detection_source):
            demoted.add(idx)

    if not demoted:
        return edges

    result: list[DependencyEdge] = []
    for i, e in enumerate(edges):
        if i in demoted:
            result.append(DependencyEdge(
                source_gk=e.source_gk, target_gk=e.target_gk,
                edge_type="optional", source_field=e.source_field,
                detection_source=e.detection_source, confidence=e.confidence,
            ))
        else:
            result.append(e)
    return result


_CROSS_SERVICE_DEMOTABLE_SOURCES = frozenset({
    "ref_detector:suffix_ref_tuple",
    "ref_detector:label_selector_ref",
    "ref_detector:polymorphic_ref",
})


def _filter_cross_service_cross_group_edges(
    edges: list[DependencyEdge],
    nodes: dict[str, KindNode],
) -> list[DependencyEdge]:
    """Demote weak/heuristic edges that cross both API group and service boundaries.

    Only demotes edges from heuristic detection sources (suffix_ref_tuple,
    label_selector_ref, polymorphic_ref, parent_kind_name, fuzzy_kind_name,
    enum_kind). Strong structural detectors (ref_tuple, ref, structural_ref)
    are left unchanged.

    Allows same-service cross-group edges (e.g., Flux's multiple API groups).
    Skips external nodes (core K8s resources).
    """
    result: list[DependencyEdge] = []
    for e in edges:
        src_group = e.source_gk.split("/")[0]
        tgt_group = e.target_gk.split("/")[0]

        if src_group == tgt_group:
            result.append(e)
            continue

        src_node = nodes.get(e.source_gk)
        tgt_node = nodes.get(e.target_gk)

        if src_node is None or tgt_node is None:
            result.append(e)
            continue

        # Don't demote edges involving external nodes (core K8s types).
        if src_node.is_external or tgt_node.is_external:
            result.append(e)
            continue

        if src_node.service == tgt_node.service:
            result.append(e)
            continue

        # Only demote heuristic detection sources.
        if e.detection_source not in _CROSS_SERVICE_DEMOTABLE_SOURCES:
            result.append(e)
            continue

        # Different group AND different service AND heuristic source -> demote.
        if e.edge_type == "optional":
            result.append(e)
        else:
            result.append(DependencyEdge(
                source_gk=e.source_gk, target_gk=e.target_gk,
                edge_type="optional", source_field=e.source_field,
                detection_source=e.detection_source, confidence=e.confidence,
            ))

    return result


# Regex to strip TLD from API group for service derivation.
_TLD_RE = re.compile(r"\.(io|dev|com|org|net|k8s\.io)$")


def _derive_service(group: str) -> str:
    """Derive a service name from a CRD API group string.

    'cert-manager.io' → 'cert-manager', 'traefik.io' → 'traefik'.
    Empty or 'core' → 'core'.
    """
    if not group or group == "core":
        return "core"
    stripped = _TLD_RE.sub("", group)
    return stripped.split(".")[0]


def _parse_fact_ref(fact_ref: str) -> tuple[str, str] | None:
    """Parse 'crdfacts://{group}/{kind}#field' → (group, kind), or None.

    The 'core' group is mapped to '' for consistency with CORE_EXTERNAL_KINDS.
    """
    if not fact_ref.startswith("crdfacts://"):
        return None
    path = fact_ref[len("crdfacts://"):]
    path = path.split("#")[0]  # strip fragment
    parts = path.split("/")
    if len(parts) != 2:
        return None
    group, kind = parts
    if group == "core":
        group = ""
    return (group, kind)


def build_dependency_graph(
    classified_fields: dict[tuple[str, str], list[ClassifiedField]],
    rbac_outputs: dict[str, list[Output]],
    olm_owned: dict[str, list[GVKRef]],
    side_effect_dict: dict[tuple[str, str], list[dict]],
    registry: KindRegistry,
    alm_edges: list[DependencyEdge] | None = None,
) -> DependencyGraph:
    """Build a Kind-level dependency graph from detection pipeline output.

    Args:
        classified_fields: Map of (group, kind) to list of ClassifiedField.
            Keys define the set of "internal" CRD Kinds.
        rbac_outputs: Map of service name to list of Output objects from RBAC adapter.
        olm_owned: Map of service name to list of GVKRef objects for OLM-owned Kinds.
        side_effect_dict: The OPERATOR_SIDE_EFFECTS dictionary (or subset).
        registry: KindRegistry for plural/group lookups.

    Returns:
        DependencyGraph with nodes, dependency_edges, production_edges, external_kinds.
    """
    nodes: dict[str, KindNode] = {}
    production_edges: list[ProductionEdge] = []
    raw_dep_edges: list[DependencyEdge] = []

    # Build set of OLM-owned gk strings for external-boundary check.
    olm_owned_gks: set[str] = set()
    for gvk_list in olm_owned.values():
        for gvk in gvk_list:
            olm_owned_gks.add(f"{gvk.group}/{gvk.kind}")

    # Step 1: Enumerate all CRD Kinds (internal nodes).
    internal_gks: set[str] = set()
    for (group, kind) in classified_fields:
        gk = f"{group}/{kind}"
        nodes[gk] = KindNode(kind=kind, group=group, service=_derive_service(group))
        internal_gks.add(gk)

    # Step 2: Identify external Kinds.
    external_kinds: set[str] = set()
    for (group, kind), fields in classified_fields.items():
        for cf in fields:
            if cf.role != "input_ref" or cf.target_kind is None:
                continue
            tg = cf.target_group or ""
            target_gk = f"{tg}/{cf.target_kind}"
            if target_gk in internal_gks:
                continue  # already internal
            if target_gk not in nodes:
                is_ext = (
                    (tg, cf.target_kind) in CORE_EXTERNAL_KINDS
                    or target_gk not in olm_owned_gks
                )
                nodes[target_gk] = KindNode(
                    kind=cf.target_kind, group=tg,
                    service=_derive_service(tg), is_external=is_ext,
                )
                if is_ext:
                    external_kinds.add(target_gk)

    # Step 3: Self-production axiom.
    for gk, node in nodes.items():
        if not node.is_external:
            production_edges.append(ProductionEdge(
                source_gk=gk, target_gk=gk,
                production_type="self", confidence=1.0,
                detection_source="self_production_axiom",
            ))

    # Step 4: Detection edges from ClassifiedFields.
    for (group, kind), fields in classified_fields.items():
        source_gk = f"{group}/{kind}"
        for cf in fields:
            if cf.role != "input_ref" or cf.target_kind is None:
                continue
            tg = cf.target_group or ""
            target_gk = f"{tg}/{cf.target_kind}"
            if target_gk == source_gk:
                continue  # skip self-loop edges
            if target_gk in external_kinds:
                edge_type: Literal["hard", "soft", "optional"] = "soft"
            elif cf.required and _is_hard_eligible(cf.detection_source):
                edge_type = "hard"
            elif cf.required:
                edge_type = "soft"  # required but from weak detector
            else:
                edge_type = "optional"
            raw_dep_edges.append(DependencyEdge(
                source_gk=source_gk, target_gk=target_gk,
                edge_type=edge_type, source_field=cf.field,
                detection_source=cf.detection_source, confidence=cf.confidence,
            ))

    # Step 4b: Promotion gate pass — promote qualified soft edges to hard.
    # Lazy import to avoid circular dependency (edge_promotion imports topo_sort types).
    from idi.generation.crd.edge_promotion import promote_soft_edges as _promote

    cf_index: dict[tuple[str, str, str], ClassifiedField] = {}
    for (group, kind), fields in classified_fields.items():
        source_gk = f"{group}/{kind}"
        for cf in fields:
            if cf.role == "input_ref" and cf.target_kind is not None:
                target_gk = f"{cf.target_group or ''}/{cf.target_kind}"
                cf_index[(source_gk, cf.field, target_gk)] = cf
    graph_stub = DependencyGraph(
        nodes=nodes,
        dependency_edges=[],
        production_edges=[],
        external_kinds=external_kinds,
    )
    raw_dep_edges = _promote(raw_dep_edges, cf_index, graph_stub)

    # Step 4c: Cross-service cross-group filter (runs AFTER promotion).
    raw_dep_edges = _filter_cross_service_cross_group_edges(raw_dep_edges, nodes)

    # Step 5: RBAC production edges.
    for service, outputs in rbac_outputs.items():
        service_nodes = [n for n in nodes.values() if n.service == service and not n.is_external]
        for out in outputs:
            parsed = _parse_fact_ref(out.fact_ref)
            if parsed is None:
                logger.warning("Unparseable RBAC fact_ref: %s", out.fact_ref)
                continue
            target_group, target_kind = parsed
            target_gk = f"{target_group}/{target_kind}"
            for sn in service_nodes:
                production_edges.append(ProductionEdge(
                    source_gk=sn.gk, target_gk=target_gk,
                    production_type="rbac",
                    confidence=out.priority / 3.0,
                    detection_source=out.source,
                ))

    # Step 6: OLM production edges.
    for _service, gvk_list in olm_owned.items():
        for gvk in gvk_list:
            gk = f"{gvk.group}/{gvk.kind}"
            production_edges.append(ProductionEdge(
                source_gk=gk, target_gk=gk,
                production_type="olm", confidence=0.9,
                detection_source="olm_deps:owned",
            ))

    # Step 7: Side-effect dictionary edges.
    for (group, kind), effects in side_effect_dict.items():
        source_gk = f"{group}/{kind}"
        for effect in effects:
            pg = effect["produces_group"]
            if pg == "core":
                pg = ""
            target_gk = f"{pg}/{effect['produces_kind']}"
            production_edges.append(ProductionEdge(
                source_gk=source_gk, target_gk=target_gk,
                production_type="side_effect", confidence=0.95,
                detection_source=f"side_effect_dict:{effect['field']}",
            ))

    # Step 7.5: ALM label edges (pre-classified as hard).
    if alm_edges:
        raw_dep_edges.extend(alm_edges)

    # Step 8: Deduplicate dependency edges.
    edge_groups: dict[tuple[str, str], list[DependencyEdge]] = {}
    for e in raw_dep_edges:
        key = (e.source_gk, e.target_gk)
        edge_groups.setdefault(key, []).append(e)

    deduped_edges: list[DependencyEdge] = []
    for _key, edges in edge_groups.items():
        winner = max(
            edges,
            key=lambda e: (_EDGE_TYPE_PRIORITY.get(e.edge_type, 0), e.confidence),
        )
        # Merge detection sources for provenance.
        sources = sorted({e.detection_source for e in edges})
        if len(sources) > 1:
            merged_source = ",".join(sources)
            winner = DependencyEdge(
                source_gk=winner.source_gk, target_gk=winner.target_gk,
                edge_type=winner.edge_type, source_field=winner.source_field,
                detection_source=merged_source, confidence=winner.confidence,
            )
        deduped_edges.append(winner)

    # Step 9: Cross-ecosystem suspicion filter.
    deduped_edges = _filter_cross_ecosystem_edges(deduped_edges)

    return DependencyGraph(
        nodes=nodes,
        dependency_edges=deduped_edges,
        production_edges=production_edges,
        external_kinds=external_kinds,
    )


def topological_sort(graph: DependencyGraph, *, _depth: int = 0) -> list[SortTier]:
    """Sort Kinds into deployment tiers using Kahn's algorithm on hard edges.

    Only hard DependencyEdges participate in the in-degree calculation.
    Soft and optional edges affect only within-tier ordering (fewer soft
    deps first, then lexicographic by gk string).

    External nodes are excluded from the output entirely.

    Args:
        graph: A fully constructed DependencyGraph from build_dependency_graph().

    Returns:
        A list of SortTier objects ordered by tier number. Each SortTier
        contains a deterministically-ordered list of gk strings.
        Returns [] if graph has no internal nodes.
    """
    if _depth > 3:
        logger.error("topological_sort recursion depth exceeded (>3); aborting cycle resolution")
        return []
    # Step 1: Filter to internal nodes only.
    internal_gks: set[str] = {
        gk for gk, node in graph.nodes.items()
        if not node.is_external and gk not in graph.external_kinds
    }
    if not internal_gks:
        return []

    # Step 2: Build hard-edge adjacency and in-degree.
    # Deduplicate and skip self-loops to avoid inflated in-degree counts.
    in_degree: dict[str, int] = {gk: 0 for gk in internal_gks}
    # forward_map: target -> [sources unblocked when target is placed]
    forward_map: dict[str, list[str]] = {gk: [] for gk in internal_gks}
    seen_hard: set[tuple[str, str]] = set()

    for edge in graph.dependency_edges:
        if edge.edge_type != "hard":
            continue
        if edge.source_gk == edge.target_gk:
            continue  # skip self-loops
        if edge.source_gk not in internal_gks or edge.target_gk not in internal_gks:
            continue
        pair = (edge.source_gk, edge.target_gk)
        if pair in seen_hard:
            continue
        seen_hard.add(pair)
        in_degree[edge.source_gk] += 1
        forward_map[edge.target_gk].append(edge.source_gk)

    # Step 3: Count soft + optional dependencies per node (for within-tier ordering).
    soft_count: dict[str, int] = {gk: 0 for gk in internal_gks}
    for edge in graph.dependency_edges:
        if edge.edge_type in ("soft", "optional") and edge.source_gk in internal_gks:
            soft_count[edge.source_gk] += 1

    # Step 4: Initialize heap with zero-degree nodes.
    heap: list[tuple[int, str]] = []
    for gk in internal_gks:
        if in_degree[gk] == 0:
            heapq.heappush(heap, (soft_count[gk], gk))

    # Step 5: Process tiers iteratively.
    tiers: list[SortTier] = []
    tier_num = 0

    while heap:
        # Drain current heap — all items form this tier.
        current_tier_nodes: list[str] = []
        while heap:
            _sc, gk = heapq.heappop(heap)
            current_tier_nodes.append(gk)

        tiers.append(SortTier(tier=tier_num, kinds=current_tier_nodes))

        # Collect next tier's zero-degree nodes.
        next_heap: list[tuple[int, str]] = []
        for placed_gk in current_tier_nodes:
            for dependent_gk in forward_map[placed_gk]:
                in_degree[dependent_gk] -= 1
                if in_degree[dependent_gk] == 0:
                    heapq.heappush(next_heap, (soft_count[dependent_gk], dependent_gk))

        heap = next_heap
        tier_num += 1

    # Step 6: Handle remaining nodes (cycle resolution).
    placed = {gk for tier in tiers for gk in tier.kinds}
    unplaced = internal_gks - placed
    if not unplaced:
        return tiers

    # Build a subgraph of unplaced nodes for cycle detection.
    sub_nodes = {gk: graph.nodes[gk] for gk in unplaced if gk in graph.nodes}
    sub_edges = [
        e for e in graph.dependency_edges
        if e.source_gk in unplaced and e.target_gk in unplaced
    ]
    subgraph = DependencyGraph(
        nodes=sub_nodes, dependency_edges=sub_edges,
        production_edges=graph.production_edges,
        external_kinds=graph.external_kinds,
    )
    sccs = detect_cycles(subgraph)
    if not sccs:
        return tiers

    # Separate trivial (self-loop) from non-trivial SCCs.
    trivial_gks: set[str] = set()
    nontrivial_sccs: list[list[str]] = []
    self_loop_pairs = {
        (e.source_gk, e.target_gk)
        for e in graph.dependency_edges
        if e.edge_type == "hard" and e.source_gk == e.target_gk
    }
    for scc in sccs:
        if len(scc) == 1 and (scc[0], scc[0]) in self_loop_pairs:
            trivial_gks.add(scc[0])
        else:
            nontrivial_sccs.append(scc)

    # SCC preferential ALM edge removal: remove exclusively-ALM edges
    # within non-trivial SCCs before condensation. ALM edges are more
    # likely to be false positives in cycles than structural edges.
    alm_removed = False
    for scc in nontrivial_sccs:
        scc_nodes = set(scc)
        to_remove: list[DependencyEdge] = []
        for e in subgraph.dependency_edges:
            if (
                e.source_gk in scc_nodes
                and e.target_gk in scc_nodes
                and e.detection_source == "olm_deps:alm_label"
            ):
                to_remove.append(e)
        if to_remove:
            remove_set = set(id(e) for e in to_remove)
            subgraph = DependencyGraph(
                nodes=subgraph.nodes,
                dependency_edges=[
                    e for e in subgraph.dependency_edges
                    if id(e) not in remove_set
                ],
                production_edges=subgraph.production_edges,
                external_kinds=subgraph.external_kinds,
            )
            alm_removed = True
            for e in to_remove:
                logger.info(
                    "Removed ALM edge from SCC: %s -> %s (%s)",
                    e.source_gk, e.target_gk, e.source_field,
                )

    if alm_removed:
        sccs = detect_cycles(subgraph)
        nontrivial_sccs = []
        for scc in sccs:
            if len(scc) == 1 and (scc[0], scc[0]) in self_loop_pairs:
                trivial_gks.add(scc[0])
            else:
                nontrivial_sccs.append(scc)
        if not nontrivial_sccs:
            # ALM removal resolved all cycles — re-sort the modified subgraph.
            sub_tiers = topological_sort(subgraph, _depth=_depth + 1)
            for st in sub_tiers:
                st.tier += tier_num
            tiers.extend(sub_tiers)
            return tiers

    # Log warnings for non-trivial SCCs.
    for scc in nontrivial_sccs:
        scc_set = set(scc)
        cycle_edges = [
            e for e in subgraph.dependency_edges
            if e.edge_type == "hard" and e.source_gk in scc_set and e.target_gk in scc_set
        ]
        edge_strs = [f"{e.source_gk} -> {e.target_gk} ({e.source_field})" for e in cycle_edges]
        logger.warning(
            "Circular dependency detected among: %s. Edges: %s",
            ", ".join(sorted(scc)), "; ".join(edge_strs),
        )

    # For trivial SCCs: just add them back to the sort as normal nodes.
    # Strip self-edges and re-sort the remaining unplaced set.
    # For non-trivial SCCs: condense and re-sort.
    if nontrivial_sccs:
        condensed, scc_map = condense_cycles(subgraph, nontrivial_sccs)
        # Add trivial nodes back (they're already in subgraph, just strip self-edges)
        for gk in trivial_gks:
            if gk not in condensed.nodes:
                condensed.nodes[gk] = sub_nodes[gk]
        # Strip self-loop edges in condensed graph
        condensed.dependency_edges = [
            e for e in condensed.dependency_edges
            if e.source_gk != e.target_gk
        ]
        sub_tiers = topological_sort(condensed, _depth=_depth + 1)
        # Expand representative nodes back to full SCC membership.
        for st in sub_tiers:
            expanded_kinds: list[str] = []
            scc_group_members: list[str] = []
            for gk in st.kinds:
                if gk in scc_map:
                    members = sorted(scc_map[gk])
                    expanded_kinds.extend(members)
                    scc_group_members.extend(members)
                else:
                    expanded_kinds.append(gk)
            st.kinds = expanded_kinds
            if scc_group_members:
                st.scc_group = sorted(scc_group_members)
            st.tier += tier_num
        tiers.extend(sub_tiers)
    else:
        # Only trivial SCCs — strip self-edges and re-sort unplaced nodes.
        trivial_edges = [
            e for e in sub_edges if e.source_gk != e.target_gk
        ]
        trivial_graph = DependencyGraph(
            nodes=sub_nodes, dependency_edges=trivial_edges,
            production_edges=graph.production_edges,
            external_kinds=graph.external_kinds,
        )
        sub_tiers = topological_sort(trivial_graph, _depth=_depth + 1)
        for st in sub_tiers:
            st.tier += tier_num
        tiers.extend(sub_tiers)

    return tiers


def detect_cycles(graph: DependencyGraph) -> list[list[str]]:
    """Find strongly connected components in the hard-edge subgraph.

    Uses an iterative path-based algorithm to avoid Python recursion limits.

    Returns a list of SCCs, where each SCC is a list of group/kind strings.
    Trivial SCCs (single node with no self-edge) are excluded.
    Only SCCs with actual cycles (self-loops or mutual deps) are returned.
    """
    # Build hard-edge adjacency for internal nodes only.
    internal_gks = {
        gk for gk, node in graph.nodes.items()
        if not node.is_external and gk not in graph.external_kinds
    }
    adj: dict[str, list[str]] = {gk: [] for gk in internal_gks}
    has_self_loop: set[str] = set()
    for edge in graph.dependency_edges:
        if edge.edge_type != "hard":
            continue
        if edge.source_gk not in internal_gks or edge.target_gk not in internal_gks:
            continue
        if edge.source_gk == edge.target_gk:
            has_self_loop.add(edge.source_gk)
            continue
        adj[edge.source_gk].append(edge.target_gk)

    # Iterative path-based SCC (Eppstein/ActiveState recipe adaptation).
    VISIT, VISITEDGE, POSTVISIT = 0, 1, 2

    index_counter = 0
    index_map: dict[str, int] = {}
    path: list[str] = []
    path_set: set[str] = set()
    boundaries: list[int] = []
    sccs: list[list[str]] = []

    for start in sorted(internal_gks):
        if start in index_map:
            continue

        stack: list[tuple[int, str, int]] = [(VISIT, start, 0)]

        while stack:
            op, node, edge_idx = stack.pop()

            if op == VISIT:
                if node in index_map:
                    continue
                index_map[node] = index_counter
                index_counter += 1
                boundaries.append(index_map[node])
                path.append(node)
                path_set.add(node)
                # Push POSTVISIT, then edges in reverse order.
                stack.append((POSTVISIT, node, 0))
                neighbors = adj[node]
                for i in range(len(neighbors) - 1, -1, -1):
                    stack.append((VISITEDGE, node, i))

            elif op == VISITEDGE:
                neighbor = adj[node][edge_idx]
                if neighbor not in index_map:
                    stack.append((VISIT, neighbor, 0))
                elif neighbor in path_set:
                    # Pop boundaries until we find one <= neighbor's index.
                    while boundaries and boundaries[-1] > index_map[neighbor]:
                        boundaries.pop()

            elif op == POSTVISIT:
                if boundaries and boundaries[-1] == index_map[node]:
                    boundaries.pop()
                    scc: list[str] = []
                    while True:
                        v = path.pop()
                        path_set.discard(v)
                        scc.append(v)
                        if v == node:
                            break
                    scc.sort()
                    sccs.append(scc)

    # Filter: keep only SCCs that represent actual cycles.
    # A single node is only an SCC if it has a self-loop.
    result = []
    for scc in sccs:
        if len(scc) == 1:
            if scc[0] in has_self_loop:
                result.append(scc)
        else:
            result.append(scc)

    return result


def condense_cycles(
    graph: DependencyGraph,
    sccs: list[list[str]],
) -> tuple[DependencyGraph, dict[str, list[str]]]:
    """Collapse non-trivial SCCs into representative nodes.

    For each SCC:
    1. Choose representative = lexicographically smallest gk string
    2. Remove all SCC member nodes from the graph
    3. Add representative node back
    4. Transfer all external edges to/from SCC members to the representative
    5. Remove intra-SCC edges

    Returns:
        - Condensed DependencyGraph (modified copy)
        - Mapping from representative gk → list of all member gks
    """
    # Build member → representative mapping.
    member_to_rep: dict[str, str] = {}
    scc_map: dict[str, list[str]] = {}
    for scc in sccs:
        rep = min(scc)
        scc_map[rep] = sorted(scc)
        for member in scc:
            member_to_rep[member] = rep

    # Build condensed nodes.
    new_nodes: dict[str, KindNode] = {}
    for gk, node in graph.nodes.items():
        if gk in member_to_rep:
            rep = member_to_rep[gk]
            if rep not in new_nodes:
                rep_node = graph.nodes[rep]
                new_nodes[rep] = rep_node
        else:
            new_nodes[gk] = node

    # Rewrite edges, removing intra-SCC edges. Prefer hard edge type on dedup.
    best_edge: dict[tuple[str, str], DependencyEdge] = {}
    for edge in graph.dependency_edges:
        src = member_to_rep.get(edge.source_gk, edge.source_gk)
        tgt = member_to_rep.get(edge.target_gk, edge.target_gk)
        if src == tgt:
            continue  # intra-SCC or self-loop
        pair = (src, tgt)
        if pair in best_edge:
            existing = best_edge[pair]
            if _EDGE_TYPE_PRIORITY.get(edge.edge_type, 0) > _EDGE_TYPE_PRIORITY.get(existing.edge_type, 0):
                best_edge[pair] = DependencyEdge(
                    source_gk=src, target_gk=tgt,
                    edge_type=edge.edge_type, source_field=edge.source_field,
                    detection_source=edge.detection_source, confidence=edge.confidence,
                )
        else:
            best_edge[pair] = DependencyEdge(
                source_gk=src, target_gk=tgt,
                edge_type=edge.edge_type, source_field=edge.source_field,
                detection_source=edge.detection_source, confidence=edge.confidence,
            )
    new_dep_edges = list(best_edge.values())

    condensed = DependencyGraph(
        nodes=new_nodes,
        dependency_edges=new_dep_edges,
        production_edges=graph.production_edges,
        external_kinds=graph.external_kinds,
    )
    return condensed, scc_map


# ---------------------------------------------------------------------------
# Catalog Writer — output functions (section 06)
# ---------------------------------------------------------------------------


def _sanitize_path_segment(segment: str) -> str:
    """Replace unsafe characters in path segments. Allow [A-Za-z0-9._-]."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", segment)


def _write_json(path: Path, data: dict) -> None:
    """Write canonical JSON: sorted keys, 2-space indent, trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def update_manifests_with_tiers(
    tiers: list[SortTier],
    catalog_root: Path,
) -> int:
    """Update manifest.json files with sort_tier field.

    Walks the catalog directory to find each Kind's manifest.json.
    For each Kind found in the tier list, reads the manifest, adds
    sort_tier, and writes back with canonical JSON formatting.

    Returns:
        Number of manifests updated.
    """
    # Build gk -> tier number lookup.
    gk_to_tier: dict[str, int] = {}
    for st in tiers:
        for gk in st.kinds:
            gk_to_tier[gk] = st.tier

    count = 0
    resolved_root = catalog_root.resolve()
    for manifest_path in catalog_root.rglob("manifest.json"):
        resolved = manifest_path.resolve()
        assert resolved.is_relative_to(resolved_root), (
            f"Path traversal: {manifest_path} is outside {catalog_root}"
        )
        try:
            data = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cannot read manifest %s: %s", manifest_path, exc)
            continue
        kind = data.get("kind", "")
        group = data.get("group", "")
        gk = f"{group}/{kind}"
        if gk not in gk_to_tier:
            continue
        data["sort_tier"] = gk_to_tier[gk]
        _write_json(manifest_path, data)
        count += 1

    return count


def write_service_ordering(
    service: str,
    tiers: list[SortTier],
    graph: DependencyGraph,
    catalog_root: Path,
    cycle_warnings: list[str] | None = None,
) -> Path:
    """Write ordering.json for a single service.

    Returns:
        Path to written ordering.json.
    """
    sanitized = _sanitize_path_segment(service)
    out_path = (catalog_root / sanitized / "ordering.json").resolve()
    assert out_path.is_relative_to(catalog_root.resolve()), (
        f"Path traversal: {out_path} is outside {catalog_root}"
    )

    sorted_tiers = sorted(tiers, key=lambda t: t.tier)
    tiers_data = []
    total_kinds = 0
    for st in sorted_tiers:
        entry: dict = {"tier": st.tier, "kinds": sorted(st.kinds)}
        if st.scc_group is not None:
            entry["scc_group"] = sorted(st.scc_group)
        tiers_data.append(entry)
        total_kinds += len(st.kinds)

    # Partition external kinds into core vs unknown, scoped to this service.
    # Only include externals that are targets of edges from this service's Kinds.
    service_gks = {gk for st in tiers for gk in st.kinds}
    referenced_externals: set[str] = set()
    for edge in graph.dependency_edges:
        if edge.source_gk in service_gks:
            tgt = graph.nodes.get(edge.target_gk)
            if tgt and (tgt.is_external or edge.target_gk in graph.external_kinds):
                referenced_externals.add(edge.target_gk)

    core_externals: list[str] = []
    unknown_externals: list[str] = []
    for gk in referenced_externals:
        node = graph.nodes[gk]
        if (node.group, node.kind) in CORE_EXTERNAL_KINDS:
            core_externals.append(gk)
        else:
            unknown_externals.append(gk)

    cycles_detected = sum(1 for st in sorted_tiers if st.scc_group is not None)
    doc = {
        "schema_version": "1.0",
        "service": service,
        "tiers": tiers_data,
        "sort_metadata": {
            "total_kinds": total_kinds,
            "total_tiers": len(sorted_tiers),
            "cycles_detected": cycles_detected,
            "cycle_warnings": cycle_warnings if cycle_warnings is not None else [],
            "external_kinds": sorted(core_externals),
            "unknown_external_kinds": sorted(unknown_externals),
        },
    }
    _write_json(out_path, doc)
    return out_path


def write_global_ordering(
    tiers: list[SortTier],
    graph: DependencyGraph,
    catalog_root: Path,
    cycle_warnings: list[str] | None = None,
) -> Path:
    """Write global-ordering.json for cross-service sort.

    Returns:
        Path to written global-ordering.json.
    """
    out_path = (catalog_root / "global-ordering.json").resolve()
    assert out_path.is_relative_to(catalog_root.resolve()), (
        f"Path traversal: {out_path} is outside {catalog_root}"
    )

    sorted_tiers = sorted(tiers, key=lambda t: t.tier)
    tiers_data = []
    total_kinds = 0
    for st in sorted_tiers:
        entry: dict = {"tier": st.tier, "kinds": sorted(st.kinds)}
        if st.scc_group is not None:
            entry["scc_group"] = sorted(st.scc_group)
        tiers_data.append(entry)
        total_kinds += len(st.kinds)

    # Collect services from graph nodes.
    services: set[str] = set()
    for node in graph.nodes.values():
        if not node.is_external:
            services.add(node.service)

    # Cross-service edges (sorted for deterministic output).
    cross_edges = []
    for edge in graph.dependency_edges:
        src_node = graph.nodes.get(edge.source_gk)
        tgt_node = graph.nodes.get(edge.target_gk)
        if src_node and tgt_node and src_node.service != tgt_node.service:
            cross_edges.append({
                "source": edge.source_gk,
                "target": edge.target_gk,
                "edge_type": edge.edge_type,
            })
    cross_edges.sort(key=lambda e: (e["source"], e["target"]))

    cycles_detected = sum(1 for st in sorted_tiers if st.scc_group is not None)
    doc = {
        "schema_version": "1.0",
        "tiers": tiers_data,
        "sort_metadata": {
            "total_kinds": total_kinds,
            "total_tiers": len(sorted_tiers),
            "cycles_detected": cycles_detected,
            "cycle_warnings": cycle_warnings if cycle_warnings is not None else [],
            "services": sorted(services),
            "cross_service_edges": cross_edges,
        },
    }
    _write_json(out_path, doc)
    return out_path


def write_sort_results(
    graph: DependencyGraph,
    tiers: list[SortTier],
    catalog_root: Path,
    cycle_warnings: list[str] | None = None,
    write_global: bool = True,
) -> dict[str, Path]:
    """Write all sort output files.

    Orchestrates manifest updates, per-service ordering, and global ordering.

    Returns:
        Dict mapping output type to written path.
    """
    result: dict[str, Path] = {}

    update_manifests_with_tiers(tiers, catalog_root)

    # Build tier_num -> SortTier lookup for SCC info.
    tier_lookup: dict[int, SortTier] = {st.tier: st for st in tiers}

    # Group tiers by service for per-service ordering files.
    # Per-service tiers use plain Kind names (not group-qualified).
    service_tier_map: dict[str, dict[int, list[str]]] = {}
    for st in tiers:
        for gk in st.kinds:
            node = graph.nodes.get(gk)
            if node is None or node.is_external:
                continue
            svc = node.service
            service_tier_map.setdefault(svc, {}).setdefault(st.tier, []).append(node.kind)

    for svc, tier_dict in service_tier_map.items():
        svc_tiers = []
        for tier_num in sorted(tier_dict):
            orig = tier_lookup.get(tier_num)
            scc_group = None
            if orig and orig.scc_group:
                # Filter SCC members to this service, using plain Kind names.
                svc_kind_set = set(tier_dict.get(tier_num, []))
                svc_scc = [
                    graph.nodes[gk].kind
                    for gk in orig.scc_group
                    if gk in graph.nodes and graph.nodes[gk].kind in svc_kind_set
                ]
                if svc_scc:
                    scc_group = svc_scc
            svc_tiers.append(SortTier(
                tier=tier_num, kinds=sorted(tier_dict[tier_num]), scc_group=scc_group,
            ))
        path = write_service_ordering(svc, svc_tiers, graph, catalog_root, cycle_warnings)
        result[svc] = path

    if write_global:
        path = write_global_ordering(tiers, graph, catalog_root, cycle_warnings)
        result["global"] = path

    return result


# ---------------------------------------------------------------------------
# CLI — catalog loader and entry point (section 07)
# ---------------------------------------------------------------------------


def _load_olm_owned(
    olm_cache_dir: Path,
    service_filter: str | None = None,
) -> dict[str, list[GVKRef]]:
    """Load OLM owned GVKs from disk cache.

    Scans olm_cache_dir for {service}/csv.yaml files, extracts owned GVKs
    using extract_gvk_dependencies(). No network calls — reads cache only.

    Args:
        olm_cache_dir: Path to OLM cache directory (e.g. catalog/specs/olm/).
        service_filter: If set, only load this service's OLM data.

    Returns:
        Dict mapping service name to list of owned GVKRef objects.
    """
    from idi.generation.crd.olm_loader import extract_gvk_dependencies

    result: dict[str, list[GVKRef]] = {}
    if not olm_cache_dir.is_dir():
        return result

    resolved_root = olm_cache_dir.resolve()
    for csv_path in sorted(olm_cache_dir.rglob("csv.yaml")):
        if not csv_path.resolve().is_relative_to(resolved_root):
            continue
        service = csv_path.parent.name
        if service_filter is not None and service != service_filter:
            continue
        try:
            import yaml
            csv_data = yaml.safe_load(csv_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Cannot read OLM cache %s: %s", csv_path, exc)
            continue
        if not isinstance(csv_data, dict):
            continue
        owned, _required = extract_gvk_dependencies(csv_data)
        if owned:
            result[service] = owned
            logger.debug("Loaded %d OLM owned GVKs for %s", len(owned), service)

    return result


def _load_catalog_for_sort(
    catalog_dir: Path,
    service_filter: str | None = None,
    olm_cache_dir: Path | None = None,
) -> dict:
    """Load catalog manifests and ref files for graph construction.

    Single-pass walk: reads manifests, ref files, and apply.json outputs
    in one traversal.

    Args:
        catalog_dir: Path to the CRD skills catalog directory.
        service_filter: If set, skip manifests where service != filter.
        olm_cache_dir: Path to OLM cache directory. If None, attempts
            auto-discovery from catalog_dir.

    Returns:
        Dict with keys:
            classified_fields: dict[(group, kind), list[ClassifiedField]]
            rbac_outputs: dict[str, list[Output]]
            olm_owned: dict[str, list[GVKRef]]
            side_effect_dict: dict[(group, kind), list[dict]]
            services: set[str] — all discovered service names
    """
    classified_fields: dict[tuple[str, str], list[ClassifiedField]] = {}
    rbac_outputs: dict[str, list[Output]] = {}
    services: set[str] = set()

    resolved_root = catalog_dir.resolve()
    for manifest_path in sorted(catalog_dir.rglob("manifest.json")):
        if not manifest_path.resolve().is_relative_to(resolved_root):
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cannot read manifest %s: %s", manifest_path, exc)
            continue

        kind = manifest.get("kind", "")
        group = manifest.get("group", "")
        service = manifest.get("service", "")
        if not kind or not group:
            continue
        if service_filter is not None and service != service_filter:
            continue

        services.add(service)
        key = (group, kind)
        fields: list[ClassifiedField] = []

        # Read ref files from refs/ sibling directory.
        refs_dir = manifest_path.parent / "refs"
        if refs_dir.is_dir():
            for ref_path in sorted(refs_dir.glob("*.json")):
                try:
                    ref = json.loads(ref_path.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                fields.append(ClassifiedField(
                    field=ref.get("field_path", ""),
                    role=ref.get("role", "input_ref"),
                    confidence=ref.get("confidence", 0.5),
                    field_type="string",
                    target_kind=ref.get("target_kind"),
                    target_group=ref.get("target_group"),
                    required=ref.get("required", False),
                    detection_source=ref.get("detection_source", "catalog"),
                ))

        classified_fields[key] = fields

        # Load RBAC outputs from operations/apply.json.
        apply_path = manifest_path.parent / "operations" / "apply.json"
        if apply_path.is_file():
            try:
                apply_data = json.loads(apply_path.read_text())
            except (json.JSONDecodeError, OSError):
                apply_data = {}
            for out_entry in apply_data.get("outputs", []):
                fact_ref = out_entry.get("fact_ref", "")
                if fact_ref:
                    rbac_outputs.setdefault(service, []).append(Output(
                        field=out_entry.get("field", out_entry.get("output", "")),
                        fact_ref=fact_ref,
                        source="catalog:apply.json",
                    ))

    # Load OLM owned GVKs from disk cache.
    if olm_cache_dir is None:
        # Auto-discover: if catalog_dir is catalog/skills/crd, try catalog/specs/olm
        candidate = catalog_dir.parent.parent / "specs" / "olm"
        if candidate.is_dir():
            olm_cache_dir = candidate
    olm_owned = _load_olm_owned(olm_cache_dir, service_filter) if olm_cache_dir else {}

    # Side effects: load from side_effect_registry if available.
    side_effect_dict: dict[tuple[str, str], list[dict]] = {}
    try:
        from idi.generation.crd.side_effect_registry import OPERATOR_SIDE_EFFECTS
        side_effect_dict = dict(OPERATOR_SIDE_EFFECTS)
    except ImportError:
        pass

    return {
        "classified_fields": classified_fields,
        "rbac_outputs": rbac_outputs,
        "olm_owned": olm_owned,
        "side_effect_dict": side_effect_dict,
        "services": services,
    }


def _cli_main(
    argv: list[str] | None = None,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    """CLI entry point for topological sort.

    Args:
        argv: Command-line arguments (None = sys.argv[1:]).
        stdout: Output stream (None = sys.stdout).
        stderr: Error stream (None = sys.stderr).

    Returns:
        Exit code (0 = success, 1 = error).
    """
    if stdout is None:
        stdout = sys.stdout
    if stderr is None:
        stderr = sys.stderr

    parser = argparse.ArgumentParser(
        description="Topological sort for CRD Kind deployment ordering",
    )
    parser.add_argument(
        "--service", type=str, default=None,
        help="Sort only this service (by name, e.g. cert-manager)",
    )
    parser.add_argument(
        "--global", dest="global_sort", action="store_true", default=False,
        help="Include cross-service global sort in output",
    )
    parser.add_argument(
        "--write", action="store_true", default=False,
        help="Write results to catalog files (manifests + ordering.json)",
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False,
        help="Include edge details and provenance in JSON output",
    )
    parser.add_argument(
        "--catalog-dir", type=str, default="catalog/skills/crd",
        help="Path to the CRD skills catalog directory",
    )
    parser.add_argument(
        "--olm-cache", type=str, default=None,
        help="Path to OLM cache directory (default: auto-discover from catalog-dir)",
    )
    args = parser.parse_args(argv)

    # Configure logging per-logger to avoid basicConfig idempotency issues.
    topo_logger = logging.getLogger("idi.generation.crd.topo_sort")
    if not topo_logger.handlers:
        handler = logging.StreamHandler(stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        topo_logger.addHandler(handler)
    topo_logger.setLevel(logging.DEBUG if args.verbose else logging.WARNING)

    catalog_dir = Path(args.catalog_dir)
    if not catalog_dir.is_dir():
        print(f"Error: catalog directory not found: {catalog_dir}", file=stderr)
        return 1

    olm_cache_dir = Path(args.olm_cache) if args.olm_cache else None

    # Load catalog data.
    catalog_data = _load_catalog_for_sort(
        catalog_dir, service_filter=args.service, olm_cache_dir=olm_cache_dir,
    )
    if not catalog_data["classified_fields"]:
        if args.service:
            all_data = _load_catalog_for_sort(catalog_dir, olm_cache_dir=olm_cache_dir)
            available = sorted(all_data["services"])
            print(
                f"Error: service '{args.service}' not found. "
                f"Available: {', '.join(available) if available else '(none)'}",
                file=stderr,
            )
            return 1
        print(f"Error: no manifests found in {catalog_dir}", file=stderr)
        return 1

    # Build graph and sort.
    registry = KindRegistry()

    # Pre-register OLM owned GVKs so Gate 5 (kind_to_plural) works.
    for service, owned_gvks in catalog_data["olm_owned"].items():
        for gvk in owned_gvks:
            registry.register(gvk.kind, gvk.plural, group=gvk.group, service=service)

    # Collect ALM label edges from OLM CSV data.
    from idi.generation.dep_adapters.olm_deps import OlmDepAdapter

    olm_adapter = OlmDepAdapter(registry=registry)
    alm_edges: list[DependencyEdge] = []
    olm_dir = str(olm_cache_dir) if olm_cache_dir else "catalog/specs/olm/"
    for service, owned_gvks in catalog_data["olm_owned"].items():
        alm_edges.extend(olm_adapter.detect_alm_label_edges(
            service, registry, cache_dir=olm_dir, owned_gvks=owned_gvks,
        ))

    graph = build_dependency_graph(
        classified_fields=catalog_data["classified_fields"],
        rbac_outputs=catalog_data["rbac_outputs"],
        olm_owned=catalog_data["olm_owned"],
        side_effect_dict=catalog_data["side_effect_dict"],
        registry=registry,
        alm_edges=alm_edges,
    )
    tiers = topological_sort(graph)

    # Write results to catalog if requested.
    if args.write:
        write_sort_results(graph, tiers, catalog_dir, write_global=args.global_sort)

    # Build output JSON.
    output = _build_output_json(graph, tiers, args.verbose, args.global_sort)
    print(json.dumps(output, indent=2, sort_keys=True), file=stdout)
    return 0


def _build_output_json(
    graph: DependencyGraph,
    tiers: list[SortTier],
    verbose: bool,
    include_global: bool,
) -> dict:
    """Build the JSON output structure for CLI."""
    # Pre-build edge index for verbose mode (O(E) instead of O(K*E)).
    edges_by_source: dict[str, list[DependencyEdge]] = {}
    if verbose:
        for e in graph.dependency_edges:
            edges_by_source.setdefault(e.source_gk, []).append(e)

    # Group tiers by service.
    service_tiers: dict[str, list[dict]] = {}
    service_cycles: dict[str, list[str]] = {}
    service_externals: dict[str, set[str]] = {}

    for st in tiers:
        for gk in st.kinds:
            node = graph.nodes.get(gk)
            if node is None or node.is_external:
                continue
            svc = node.service
            service_tiers.setdefault(svc, [])
            service_cycles.setdefault(svc, [])
            service_externals.setdefault(svc, set())

    # Build per-service tier data.
    for st in tiers:
        svc_kinds: dict[str, list[str]] = {}
        for gk in st.kinds:
            node = graph.nodes.get(gk)
            if node is None or node.is_external:
                continue
            svc_kinds.setdefault(node.service, []).append(node.kind)

        for svc, kinds in svc_kinds.items():
            tier_entry: dict = {"tier": st.tier, "kinds": sorted(kinds)}
            if verbose:
                edges = []
                for gk in st.kinds:
                    n = graph.nodes.get(gk)
                    if n is None or n.service != svc:
                        continue
                    for e in edges_by_source.get(gk, []):
                        edges.append({
                            "source": e.source_gk,
                            "target": e.target_gk,
                            "edge_type": e.edge_type,
                            "field": e.source_field,
                            "confidence": e.confidence,
                            "detection_source": e.detection_source,
                        })
                if edges:
                    tier_entry["edges"] = sorted(edges, key=lambda x: (x["source"], x["target"]))
            service_tiers[svc].append(tier_entry)

            if st.scc_group:
                svc_scc = [
                    graph.nodes[g].kind for g in st.scc_group
                    if g in graph.nodes and graph.nodes[g].service == svc
                ]
                if svc_scc:
                    service_cycles[svc].append(f"SCC: {', '.join(sorted(svc_scc))}")

    # Collect external kinds per service.
    for edge in graph.dependency_edges:
        src = graph.nodes.get(edge.source_gk)
        tgt = graph.nodes.get(edge.target_gk)
        if src and tgt and not src.is_external and (tgt.is_external or edge.target_gk in graph.external_kinds):
            service_externals.setdefault(src.service, set()).add(edge.target_gk)

    services_output: dict[str, dict] = {}
    for svc in sorted(service_tiers):
        services_output[svc] = {
            "tiers": sorted(service_tiers[svc], key=lambda t: t["tier"]),
            "cycles": service_cycles.get(svc, []),
            "external_kinds": sorted(service_externals.get(svc, set())),
        }

    result: dict = {"services": services_output}

    if include_global:
        global_tiers = []
        for st in sorted(tiers, key=lambda t: t.tier):
            entry: dict = {"tier": st.tier, "kinds": sorted(st.kinds)}
            if st.scc_group:
                entry["scc_group"] = sorted(st.scc_group)
            global_tiers.append(entry)

        cross_edges = []
        for edge in graph.dependency_edges:
            src = graph.nodes.get(edge.source_gk)
            tgt = graph.nodes.get(edge.target_gk)
            if src and tgt and src.service != tgt.service:
                cross_edges.append({
                    "source": edge.source_gk,
                    "target": edge.target_gk,
                    "edge_type": edge.edge_type,
                    "detection_source": edge.detection_source,
                })
        cross_edges.sort(key=lambda x: (x["source"], x["target"]))

        result["global"] = {
            "tiers": global_tiers,
            "cross_service_edges": cross_edges,
        }

    return result


if __name__ == "__main__":
    sys.exit(_cli_main())
