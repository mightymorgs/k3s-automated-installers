"""Tests for CRD topological sort data types and constants."""
from __future__ import annotations

import pytest

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.olm_loader import GVKRef
from idi.generation.crd.topo_sort import (
    CORE_EXTERNAL_KINDS,
    DependencyEdge,
    DependencyGraph,
    KindNode,
    ProductionEdge,
    SortTier,
    build_dependency_graph,
)
from idi.generation.dep_adapters.base import Output


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


# ---------------------------------------------------------------------------
# Section 02: Graph Construction
# ---------------------------------------------------------------------------

def _cf(
    field: str = "spec.ref",
    role: str = "input_ref",
    target_kind: str | None = "Issuer",
    target_group: str | None = "cert-manager.io",
    required: bool = True,
    confidence: float = 0.9,
    detection_source: str = "detect_ref",
) -> ClassifiedField:
    """Helper to build ClassifiedField with sensible defaults."""
    return ClassifiedField(
        field=field,
        role=role,
        confidence=confidence,
        field_type="string",
        target_kind=target_kind,
        target_group=target_group,
        required=required,
        detection_source=detection_source,
    )


def _build(**overrides):
    """Call build_dependency_graph with defaults for unset params."""
    defaults = dict(
        classified_fields={},
        rbac_outputs={},
        olm_owned={},
        side_effect_dict={},
        registry=KindRegistry(),
    )
    defaults.update(overrides)
    return build_dependency_graph(**defaults)


class TestBuildDependencyGraph:

    def test_nodes_created_for_all_crd_kinds(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Issuer"): [],
            ("cert-manager.io", "Certificate"): [],
        })
        assert "cert-manager.io/Issuer" in g.nodes
        assert "cert-manager.io/Certificate" in g.nodes
        assert not g.nodes["cert-manager.io/Issuer"].is_external
        assert not g.nodes["cert-manager.io/Certificate"].is_external

    def test_core_external_kinds_marked_external(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Secret", target_group=""),
            ],
        })
        assert "/Secret" in g.nodes
        assert g.nodes["/Secret"].is_external is True

    def test_unknown_crd_target_becomes_external(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="SomeUnknownCRD", target_group="unknown.io"),
            ],
        })
        assert "unknown.io/SomeUnknownCRD" in g.nodes
        assert g.nodes["unknown.io/SomeUnknownCRD"].is_external is True

    def test_self_production_edges_injected(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Issuer"): [],
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Secret", target_group=""),
            ],
        })
        self_prods = [e for e in g.production_edges if e.production_type == "self"]
        # One per internal node (Issuer, Certificate), none for external (Secret)
        internal_gks = {e.source_gk for e in self_prods}
        assert "cert-manager.io/Issuer" in internal_gks
        assert "cert-manager.io/Certificate" in internal_gks
        assert "/Secret" not in internal_gks
        for e in self_prods:
            assert e.source_gk == e.target_gk
            assert e.confidence == 1.0

    def test_required_input_ref_creates_hard_edge(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io", required=True),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        hard_edges = [e for e in g.dependency_edges if e.edge_type == "hard"]
        assert len(hard_edges) == 1
        assert hard_edges[0].source_gk == "cert-manager.io/Certificate"
        assert hard_edges[0].target_gk == "cert-manager.io/Issuer"

    def test_optional_input_ref_creates_optional_edge(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io", required=False),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        opt_edges = [e for e in g.dependency_edges if e.edge_type == "optional"]
        assert len(opt_edges) == 1

    def test_ref_to_external_creates_soft_edge(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Secret", target_group="", required=True),
            ],
        })
        soft_edges = [e for e in g.dependency_edges if e.edge_type == "soft"]
        assert len(soft_edges) == 1
        assert soft_edges[0].target_gk == "/Secret"

    def test_rbac_output_creates_production_edge(self):
        g = _build(
            classified_fields={("cert-manager.io", "Certificate"): []},
            rbac_outputs={
                "cert-manager": [
                    Output(field="create", fact_ref="crdfacts://core/Secret#name", source="rbac_deps", priority=2),
                ],
            },
        )
        rbac_prods = [e for e in g.production_edges if e.production_type == "rbac"]
        assert len(rbac_prods) == 1
        assert rbac_prods[0].source_gk == "cert-manager.io/Certificate"
        assert rbac_prods[0].target_gk == "/Secret"

    def test_olm_owned_creates_production_edge(self):
        g = _build(
            classified_fields={("cert-manager.io", "Certificate"): []},
            olm_owned={
                "cert-manager": [
                    GVKRef(kind="Certificate", group="cert-manager.io", version="v1", plural="certificates"),
                ],
            },
        )
        olm_prods = [e for e in g.production_edges if e.production_type == "olm"]
        assert len(olm_prods) == 1
        assert olm_prods[0].confidence == 0.9

    def test_side_effect_dict_creates_production_edge(self):
        g = _build(
            classified_fields={("cert-manager.io", "Certificate"): []},
            side_effect_dict={
                ("cert-manager.io", "Certificate"): [
                    {"field": "spec.secretName", "produces_kind": "Secret", "produces_group": "core"},
                ],
            },
        )
        se_prods = [e for e in g.production_edges if e.production_type == "side_effect"]
        assert len(se_prods) == 1
        assert se_prods[0].target_gk == "/Secret"
        assert se_prods[0].confidence == 0.95

    def test_edge_dedup_keeps_highest_confidence(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(field="spec.issuerRef", target_kind="Issuer", target_group="cert-manager.io", confidence=0.8),
                _cf(field="spec.issuerRef2", target_kind="Issuer", target_group="cert-manager.io", confidence=0.9),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        cert_to_issuer = [
            e for e in g.dependency_edges
            if e.source_gk == "cert-manager.io/Certificate" and e.target_gk == "cert-manager.io/Issuer"
        ]
        assert len(cert_to_issuer) == 1
        assert cert_to_issuer[0].confidence == 0.9

    def test_edge_dedup_prefers_hard_over_soft(self):
        """Hard edge wins even with lower confidence."""
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(field="spec.ref1", target_kind="Issuer", target_group="cert-manager.io",
                    required=True, confidence=0.8),
                _cf(field="spec.ref2", target_kind="Issuer", target_group="cert-manager.io",
                    required=False, confidence=0.95),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        cert_to_issuer = [
            e for e in g.dependency_edges
            if e.source_gk == "cert-manager.io/Certificate" and e.target_gk == "cert-manager.io/Issuer"
        ]
        assert len(cert_to_issuer) == 1
        assert cert_to_issuer[0].edge_type == "hard"

    def test_kind_collision_separate_nodes(self):
        g = _build(classified_fields={
            ("custom.knative.dev", "Service"): [],
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Service", target_group=""),
            ],
        })
        assert "custom.knative.dev/Service" in g.nodes
        assert not g.nodes["custom.knative.dev/Service"].is_external
        assert "/Service" in g.nodes
        assert g.nodes["/Service"].is_external is True

    def test_config_fields_ignored(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(role="config_field", target_kind="Issuer", target_group="cert-manager.io"),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        assert len(g.dependency_edges) == 0

    def test_service_derived_from_group(self):
        g = _build(classified_fields={
            ("cert-manager.io", "Issuer"): [],
            ("external-secrets.io", "SecretStore"): [],
        })
        assert g.nodes["cert-manager.io/Issuer"].service == "cert-manager"
        assert g.nodes["external-secrets.io/SecretStore"].service == "external-secrets"

    def test_empty_classified_fields(self):
        """Edge case 4: empty input → empty graph."""
        g = _build()
        assert g.nodes == {}
        assert g.dependency_edges == []
        assert g.production_edges == []
        assert g.external_kinds == set()

    def test_self_loop_edges_filtered(self):
        """A ClassifiedField referencing its own Kind should not create a dependency edge."""
        g = _build(classified_fields={
            ("cert-manager.io", "Issuer"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io"),
            ],
        })
        assert len(g.dependency_edges) == 0
