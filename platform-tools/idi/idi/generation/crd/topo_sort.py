"""Topological sort module for CRD Kind dependency ordering.

Takes 301+ detected refs from the CRD pipeline and produces deterministic
tier assignments for deployment ordering using Kahn's algorithm
with Tarjan's SCC cycle resolution.
"""
from __future__ import annotations

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
