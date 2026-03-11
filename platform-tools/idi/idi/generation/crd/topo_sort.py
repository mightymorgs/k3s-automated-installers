"""Topological sort module for CRD Kind dependency ordering.

Takes 301+ detected refs from the CRD pipeline and produces deterministic
tier assignments for deployment ordering using Kahn's algorithm
with Tarjan's SCC cycle resolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


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
