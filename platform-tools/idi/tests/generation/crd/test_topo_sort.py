"""Tests for CRD topological sort data types and constants."""
from __future__ import annotations

import pytest

from idi.generation.crd.topo_sort import (
    CORE_EXTERNAL_KINDS,
    DependencyEdge,
    DependencyGraph,
    KindNode,
    ProductionEdge,
    SortTier,
)


class TestKindNode:
    """Tests for KindNode dataclass."""

    def test_gk_property_group_kind_format(self):
        node = KindNode(kind="Certificate", group="cert-manager.io", service="cert-manager")
        assert node.gk == "cert-manager.io/Certificate"

    def test_gk_empty_group_core(self):
        node = KindNode(kind="Secret", group="", service="core")
        assert node.gk == "/Secret"

    def test_stores_all_fields(self):
        node = KindNode(kind="Issuer", group="cert-manager.io", service="cert-manager", is_external=True)
        assert node.kind == "Issuer"
        assert node.group == "cert-manager.io"
        assert node.service == "cert-manager"
        assert node.is_external is True

    def test_is_external_defaults_false(self):
        node = KindNode(kind="Certificate", group="cert-manager.io", service="cert-manager")
        assert node.is_external is False

    def test_equality_all_fields(self):
        """Two KindNodes with same fields are equal; different is_external makes them unequal."""
        a = KindNode(kind="Issuer", group="cert-manager.io", service="cert-manager")
        b = KindNode(kind="Issuer", group="cert-manager.io", service="cert-manager")
        assert a == b
        c = KindNode(kind="Issuer", group="cert-manager.io", service="cert-manager", is_external=True)
        assert a != c

    def test_frozen_immutability(self):
        node = KindNode(kind="Issuer", group="cert-manager.io", service="cert-manager")
        with pytest.raises(AttributeError):
            node.kind = "Other"  # type: ignore[misc]


class TestDependencyEdge:
    """Tests for DependencyEdge dataclass."""

    def test_stores_group_qualified_gks(self):
        edge = DependencyEdge(
            source_gk="cert-manager.io/Certificate",
            target_gk="cert-manager.io/Issuer",
            edge_type="hard",
            source_field="spec.issuerRef",
            detection_source="detect_ref",
            confidence=0.9,
        )
        assert edge.source_gk == "cert-manager.io/Certificate"
        assert edge.target_gk == "cert-manager.io/Issuer"

    def test_edge_type_values(self):
        for et in ("hard", "soft", "optional"):
            edge = DependencyEdge(
                source_gk="a/A", target_gk="b/B",
                edge_type=et, source_field="f", detection_source="d", confidence=0.5,
            )
            assert edge.edge_type == et

    def test_all_fields_populated(self):
        edge = DependencyEdge(
            source_gk="cert-manager.io/Certificate",
            target_gk="cert-manager.io/Issuer",
            edge_type="hard",
            source_field="spec.issuerRef",
            detection_source="detect_ref",
            confidence=0.9,
        )
        assert edge.source_field == "spec.issuerRef"
        assert edge.detection_source == "detect_ref"
        assert edge.confidence == 0.9


class TestProductionEdge:
    """Tests for ProductionEdge dataclass."""

    def test_self_production(self):
        edge = ProductionEdge(
            source_gk="cert-manager.io/Issuer",
            target_gk="cert-manager.io/Issuer",
            production_type="self",
            confidence=1.0,
            detection_source="axiom",
        )
        assert edge.source_gk == edge.target_gk
        assert edge.production_type == "self"
        assert edge.confidence == 1.0

    def test_production_type_values(self):
        for pt in ("self", "side_effect", "rbac", "olm"):
            edge = ProductionEdge(
                source_gk="a/A", target_gk="a/A",
                production_type=pt, confidence=0.8, detection_source="test",
            )
            assert edge.production_type == pt


class TestSortTier:
    """Tests for SortTier dataclass."""

    def test_normal_tier_no_scc(self):
        tier = SortTier(tier=0, kinds=["cert-manager.io/Issuer", "cert-manager.io/ClusterIssuer"])
        assert tier.tier == 0
        assert len(tier.kinds) == 2
        assert tier.scc_group is None

    def test_scc_tier(self):
        tier = SortTier(
            tier=2,
            kinds=["a.io/A", "a.io/B"],
            scc_group=["a.io/A", "a.io/B"],
        )
        assert tier.scc_group == ["a.io/A", "a.io/B"]


class TestDependencyGraph:
    """Tests for DependencyGraph container dataclass."""

    def test_empty_graph(self):
        g = DependencyGraph(
            nodes={}, dependency_edges=[], production_edges=[], external_kinds=set(),
        )
        assert g.nodes == {}
        assert g.dependency_edges == []
        assert g.production_edges == []
        assert g.external_kinds == set()

    def test_stores_nodes_and_edges(self):
        node = KindNode(kind="Issuer", group="cert-manager.io", service="cert-manager")
        dep = DependencyEdge(
            source_gk="cert-manager.io/Certificate",
            target_gk="cert-manager.io/Issuer",
            edge_type="hard", source_field="spec.issuerRef",
            detection_source="detect_ref", confidence=0.9,
        )
        prod = ProductionEdge(
            source_gk="cert-manager.io/Issuer",
            target_gk="cert-manager.io/Issuer",
            production_type="self", confidence=1.0, detection_source="axiom",
        )
        g = DependencyGraph(
            nodes={"cert-manager.io/Issuer": node},
            dependency_edges=[dep],
            production_edges=[prod],
            external_kinds={"/Secret"},
        )
        assert len(g.nodes) == 1
        assert len(g.dependency_edges) == 1
        assert len(g.production_edges) == 1
        assert "/Secret" in g.external_kinds


class TestCoreExternalKinds:
    """Tests for CORE_EXTERNAL_KINDS constant."""

    def test_contains_tuples(self):
        for entry in CORE_EXTERNAL_KINDS:
            assert isinstance(entry, tuple)
            assert len(entry) == 2

    def test_secret_present(self):
        assert ("", "Secret") in CORE_EXTERNAL_KINDS

    def test_configmap_present(self):
        assert ("", "ConfigMap") in CORE_EXTERNAL_KINDS

    def test_custom_secret_not_present(self):
        assert ("custom.io", "Secret") not in CORE_EXTERNAL_KINDS

    def test_count_15_entries(self):
        assert len(CORE_EXTERNAL_KINDS) == 15

    def test_immutable(self):
        with pytest.raises(AttributeError):
            CORE_EXTERNAL_KINDS.add(("test", "Test"))  # type: ignore[attr-defined]

    def test_expected_api_groups(self):
        assert ("networking.k8s.io", "Ingress") in CORE_EXTERNAL_KINDS
        assert ("networking.k8s.io", "IngressClass") in CORE_EXTERNAL_KINDS
        assert ("rbac.authorization.k8s.io", "ClusterRole") in CORE_EXTERNAL_KINDS
        assert ("rbac.authorization.k8s.io", "ClusterRoleBinding") in CORE_EXTERNAL_KINDS
        assert ("rbac.authorization.k8s.io", "Role") in CORE_EXTERNAL_KINDS
        assert ("rbac.authorization.k8s.io", "RoleBinding") in CORE_EXTERNAL_KINDS
        assert ("storage.k8s.io", "StorageClass") in CORE_EXTERNAL_KINDS
        assert ("scheduling.k8s.io", "PriorityClass") in CORE_EXTERNAL_KINDS

    def test_all_strings(self):
        for group, kind in CORE_EXTERNAL_KINDS:
            assert isinstance(group, str)
            assert isinstance(kind, str)
