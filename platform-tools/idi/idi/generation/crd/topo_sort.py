"""Topological sort module for CRD Kind dependency ordering.

Takes 301+ detected refs from the CRD pipeline and produces deterministic
tier assignments for deployment ordering using Kahn's algorithm
with Tarjan's SCC cycle resolution.
"""
from __future__ import annotations

import heapq
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

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
            elif cf.required:
                edge_type = "hard"
            else:
                edge_type = "optional"
            raw_dep_edges.append(DependencyEdge(
                source_gk=source_gk, target_gk=target_gk,
                edge_type=edge_type, source_field=cf.field,
                detection_source=cf.detection_source, confidence=cf.confidence,
            ))

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

    # Log warnings for non-trivial SCCs.
    for scc in nontrivial_sccs:
        scc_set = set(scc)
        cycle_edges = [
            e for e in graph.dependency_edges
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
