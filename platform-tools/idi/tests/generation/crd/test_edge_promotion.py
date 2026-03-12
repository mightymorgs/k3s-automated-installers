"""Tests for CRD edge promotion gates."""
from __future__ import annotations

from idi.generation.crd.edge_promotion import CrdGateResult
from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.topo_sort import (
    DependencyEdge,
    DependencyGraph,
    KindNode,
)


# ── Test helpers ─────────────────────────────────────────────


def _make_graph(**overrides) -> DependencyGraph:
    """Build a DependencyGraph with cloudnative-pg-like nodes."""
    nodes = {
        "postgresql.cnpg.io/Cluster": KindNode(
            kind="Cluster", group="postgresql.cnpg.io", service="cloudnative-pg",
        ),
        "postgresql.cnpg.io/Backup": KindNode(
            kind="Backup", group="postgresql.cnpg.io", service="cloudnative-pg",
        ),
        "postgresql.cnpg.io/Pooler": KindNode(
            kind="Pooler", group="postgresql.cnpg.io", service="cloudnative-pg",
        ),
        "postgresql.cnpg.io/Database": KindNode(
            kind="Database", group="postgresql.cnpg.io", service="cloudnative-pg",
        ),
        "postgresql.cnpg.io/ScheduledBackup": KindNode(
            kind="ScheduledBackup", group="postgresql.cnpg.io", service="cloudnative-pg",
        ),
        "/StorageClass": KindNode(
            kind="StorageClass", group="", service="core", is_external=True,
        ),
        "traefik.io/IngressRoute": KindNode(
            kind="IngressRoute", group="traefik.io", service="traefik",
        ),
    }
    nodes.update(overrides.get("extra_nodes", {}))
    return DependencyGraph(
        nodes=nodes,
        dependency_edges=[],
        production_edges=[],
        external_kinds={"/StorageClass"},
    )


def _make_cf(
    field: str = "spec.cluster.name",
    field_type: str = "string",
    confidence: float = 0.8,
    detection_source: str = "parent_kind_name",
    required: bool = False,
    target_kind: str = "Cluster",
    target_group: str = "postgresql.cnpg.io",
    **kwargs,
) -> ClassifiedField:
    """Build a ClassifiedField with sensible defaults for promotion tests."""
    return ClassifiedField(
        field=field,
        role="input_ref",
        confidence=confidence,
        field_type=field_type,
        target_kind=target_kind,
        target_group=target_group,
        required=required,
        detection_source=detection_source,
        **kwargs,
    )


def _make_edge(
    source_gk: str = "postgresql.cnpg.io/Backup",
    target_gk: str = "postgresql.cnpg.io/Cluster",
    edge_type: str = "soft",
    source_field: str = "spec.cluster.name",
    detection_source: str = "parent_kind_name",
    confidence: float = 0.8,
) -> DependencyEdge:
    """Build a DependencyEdge with sensible defaults for promotion tests."""
    return DependencyEdge(
        source_gk=source_gk,
        target_gk=target_gk,
        edge_type=edge_type,
        source_field=source_field,
        detection_source=detection_source,
        confidence=confidence,
    )


# ── CrdGateResult tests ─────────────────────────────────────


class TestCrdGateResult:
    """Tests for CrdGateResult dataclass."""

    def test_stores_gate_keep_reason(self):
        r = CrdGateResult(gate="G-CRD1", keep=True, reason="test")
        assert r.gate == "G-CRD1"
        assert r.keep is True
        assert r.reason == "test"

    def test_passing_gate(self):
        r = CrdGateResult(gate="G-CRD1", keep=True, reason="same service")
        assert r.keep is True

    def test_failing_gate(self):
        r = CrdGateResult(gate="G-CRD1", keep=False, reason="target is external")
        assert r.keep is False
