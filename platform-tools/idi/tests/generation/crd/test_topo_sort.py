"""Tests for CRD topological sort data types and constants."""
from __future__ import annotations

import io
import json

import pytest

from idi.generation.crd.field_classifier import ClassifiedField, classify_fields
from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.olm_loader import GVKRef
from idi.generation.crd.side_effect_registry import OPERATOR_SIDE_EFFECTS
from idi.generation.crd.topo_sort import (
    CORE_EXTERNAL_KINDS,
    DependencyEdge,
    DependencyGraph,
    KindNode,
    ProductionEdge,
    SortTier,
    _cli_main,
    _load_catalog_for_sort,
    _load_olm_owned,
    _sanitize_path_segment,
    _write_json,
    build_dependency_graph,
    topological_sort,
    update_manifests_with_tiers,
    write_global_ordering,
    write_service_ordering,
    write_sort_results,
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
    detection_source: str = "ref_detector:structural_ref",
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


# ---------------------------------------------------------------------------
# Hard-Edge Source Gate Tests
# ---------------------------------------------------------------------------


class TestHardEdgeSourceGate:
    """Tests for detection-source allowlist that governs hard edges."""

    def test_structural_ref_required_creates_hard_edge(self):
        """structural_ref + required=True → hard edge."""
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io",
                    required=True, detection_source="ref_detector:structural_ref"),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        hard = [e for e in g.dependency_edges if e.edge_type == "hard"]
        assert len(hard) == 1

    def test_parent_kind_name_required_creates_soft_edge(self):
        """parent_kind_name + required=True → soft (NOT hard)."""
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io",
                    required=True, detection_source="ref_detector:parent_kind_name"),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        hard = [e for e in g.dependency_edges if e.edge_type == "hard"]
        soft = [e for e in g.dependency_edges if e.edge_type == "soft"]
        assert len(hard) == 0
        assert len(soft) == 1

    def test_enum_kind_required_creates_soft_edge(self):
        """enum_kind + required=True → soft (NOT hard)."""
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io",
                    required=True, detection_source="ref_detector:enum_kind"),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        hard = [e for e in g.dependency_edges if e.edge_type == "hard"]
        soft = [e for e in g.dependency_edges if e.edge_type == "soft"]
        assert len(hard) == 0
        assert len(soft) == 1

    def test_secret_key_selector_required_creates_hard_edge(self):
        """secret_key_selector + required=True → hard edge."""
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Secret", target_group="",
                    required=True, detection_source="ref_detector:secret_key_selector"),
            ],
        })
        # Secret is external → soft edge regardless
        # Use internal target instead
        g2 = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io",
                    required=True, detection_source="ref_detector:secret_key_selector"),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        hard = [e for e in g2.dependency_edges if e.edge_type == "hard"]
        assert len(hard) == 1

    def test_ref_tuple_required_creates_hard_edge(self):
        """ref_tuple + required=True → hard edge."""
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io",
                    required=True, detection_source="ref_detector:ref_tuple"),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        hard = [e for e in g.dependency_edges if e.edge_type == "hard"]
        assert len(hard) == 1

    def test_prefixed_detection_source_still_hard(self):
        """crd_dep:ref_detector:structural_ref (prefixed) → hard edge."""
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io",
                    required=True, detection_source="crd_dep:ref_detector:structural_ref"),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        hard = [e for e in g.dependency_edges if e.edge_type == "hard"]
        assert len(hard) == 1

    def test_not_required_any_source_creates_optional(self):
        """required=False from any detection source → optional edge."""
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Issuer", target_group="cert-manager.io",
                    required=False, detection_source="ref_detector:structural_ref"),
            ],
            ("cert-manager.io", "Issuer"): [],
        })
        opt = [e for e in g.dependency_edges if e.edge_type == "optional"]
        assert len(opt) == 1

    def test_external_target_always_soft(self):
        """External target → soft edge regardless of detection source."""
        g = _build(classified_fields={
            ("cert-manager.io", "Certificate"): [
                _cf(target_kind="Secret", target_group="",
                    required=True, detection_source="ref_detector:structural_ref"),
            ],
        })
        soft = [e for e in g.dependency_edges if e.edge_type == "soft"]
        assert len(soft) == 1
        assert soft[0].target_gk == "/Secret"


# ---------------------------------------------------------------------------
# Section 03: Kahn's Topological Sort
# ---------------------------------------------------------------------------

def _make_graph(
    nodes: list[tuple[str, str, str]],  # (group, kind, service)
    hard_edges: list[tuple[str, str]] | None = None,  # (source_gk, target_gk)
    soft_edges: list[tuple[str, str]] | None = None,
    optional_edges: list[tuple[str, str]] | None = None,
    external_gks: set[str] | None = None,
) -> DependencyGraph:
    """Build a minimal DependencyGraph for sort testing."""
    node_map: dict[str, KindNode] = {}
    ext = external_gks or set()
    for group, kind, service in nodes:
        gk = f"{group}/{kind}"
        node_map[gk] = KindNode(
            kind=kind, group=group, service=service,
            is_external=gk in ext,
        )

    dep_edges: list[DependencyEdge] = []
    for src, tgt in (hard_edges or []):
        dep_edges.append(DependencyEdge(
            source_gk=src, target_gk=tgt, edge_type="hard",
            source_field="spec.ref", detection_source="test",
            confidence=0.9,
        ))
    for src, tgt in (soft_edges or []):
        dep_edges.append(DependencyEdge(
            source_gk=src, target_gk=tgt, edge_type="soft",
            source_field="spec.ref", detection_source="test",
            confidence=0.7,
        ))
    for src, tgt in (optional_edges or []):
        dep_edges.append(DependencyEdge(
            source_gk=src, target_gk=tgt, edge_type="optional",
            source_field="spec.ref", detection_source="test",
            confidence=0.6,
        ))

    return DependencyGraph(
        nodes=node_map,
        dependency_edges=dep_edges,
        production_edges=[],
        external_kinds=ext,
    )


class TestTopologicalSort:
    """Tests for topological_sort() — Kahn's algorithm."""

    def test_empty_graph(self):
        """topological_sort on a graph with no nodes returns an empty list of tiers."""

        g = DependencyGraph(
            nodes={}, dependency_edges=[], production_edges=[], external_kinds=set(),
        )
        assert topological_sort(g) == []

    def test_single_kind_no_deps(self):
        """A lone Kind with no dependency edges lands in Tier 0."""

        g = _make_graph(
            nodes=[("cert-manager.io", "Issuer", "cert-manager")],
        )
        result = topological_sort(g)
        assert len(result) == 1
        assert result[0].tier == 0
        assert "cert-manager.io/Issuer" in result[0].kinds

    def test_linear_chain(self):
        """A→B→C (A depends on B, B depends on C) → Tier 0: C, Tier 1: B, Tier 2: A."""

        g = _make_graph(
            nodes=[
                ("x.io", "A", "x"), ("x.io", "B", "x"), ("x.io", "C", "x"),
            ],
            hard_edges=[("x.io/A", "x.io/B"), ("x.io/B", "x.io/C")],
        )
        result = topological_sort(g)
        assert len(result) == 3
        assert result[0].kinds == ["x.io/C"]
        assert result[1].kinds == ["x.io/B"]
        assert result[2].kinds == ["x.io/A"]

    def test_edge_direction(self):
        """If A depends on B, B appears in a lower-numbered tier than A."""

        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x")],
            hard_edges=[("x.io/A", "x.io/B")],
        )
        result = topological_sort(g)
        # Find tiers for A and B
        tier_of = {}
        for t in result:
            for gk in t.kinds:
                tier_of[gk] = t.tier
        assert tier_of["x.io/B"] < tier_of["x.io/A"]

    def test_cert_manager_ordering(self):
        """Issuer/ClusterIssuer at Tier 0, Certificate at Tier 1 (depends on Issuer)."""

        g = _make_graph(
            nodes=[
                ("cert-manager.io", "Issuer", "cert-manager"),
                ("cert-manager.io", "ClusterIssuer", "cert-manager"),
                ("cert-manager.io", "Certificate", "cert-manager"),
            ],
            hard_edges=[("cert-manager.io/Certificate", "cert-manager.io/Issuer")],
        )
        result = topological_sort(g)
        assert result[0].tier == 0
        assert "cert-manager.io/Issuer" in result[0].kinds
        assert "cert-manager.io/ClusterIssuer" in result[0].kinds
        assert result[1].tier == 1
        assert result[1].kinds == ["cert-manager.io/Certificate"]

    def test_external_secrets_ordering(self):
        """SecretStore at Tier 0, ExternalSecret at Tier 1 (depends on SecretStore)."""

        g = _make_graph(
            nodes=[
                ("external-secrets.io", "SecretStore", "external-secrets"),
                ("external-secrets.io", "ExternalSecret", "external-secrets"),
            ],
            hard_edges=[
                ("external-secrets.io/ExternalSecret", "external-secrets.io/SecretStore"),
            ],
        )
        result = topological_sort(g)
        assert result[0].kinds == ["external-secrets.io/SecretStore"]
        assert result[1].kinds == ["external-secrets.io/ExternalSecret"]

    def test_traefik_self_loops_at_tier_zero(self):
        """After self-loops are removed, Middleware and TraefikService go to Tier 0.
        IngressRoute depends on both, so it goes to Tier 1."""

        g = _make_graph(
            nodes=[
                ("traefik.io", "Middleware", "traefik"),
                ("traefik.io", "TraefikService", "traefik"),
                ("traefik.io", "IngressRoute", "traefik"),
            ],
            hard_edges=[
                ("traefik.io/IngressRoute", "traefik.io/Middleware"),
                ("traefik.io/IngressRoute", "traefik.io/TraefikService"),
            ],
        )
        result = topological_sort(g)
        assert result[0].tier == 0
        assert "traefik.io/Middleware" in result[0].kinds
        assert "traefik.io/TraefikService" in result[0].kinds
        assert result[1].tier == 1
        assert result[1].kinds == ["traefik.io/IngressRoute"]

    def test_determinism(self):
        """Run topological_sort 10 times on the same graph. Assert identical results."""

        g = _make_graph(
            nodes=[
                ("x.io", "A", "x"), ("x.io", "B", "x"), ("x.io", "C", "x"),
                ("x.io", "D", "x"), ("x.io", "E", "x"),
            ],
            hard_edges=[
                ("x.io/A", "x.io/B"), ("x.io/B", "x.io/C"),
                ("x.io/D", "x.io/E"),
            ],
            soft_edges=[("x.io/A", "x.io/D")],
        )
        first = topological_sort(g)
        for _ in range(9):
            assert topological_sort(g) == first

    def test_tier_internal_ordering(self):
        """Within a tier, kinds with fewer soft deps come first. Ties broken by gk."""

        # All three at Tier 0 (no hard deps). B has 2 soft, C has 1, A has 0.
        g = _make_graph(
            nodes=[
                ("x.io", "A", "x"), ("x.io", "B", "x"), ("x.io", "C", "x"),
                ("y.io", "T1", "y"), ("y.io", "T2", "y"),  # soft targets
            ],
            soft_edges=[
                ("x.io/B", "y.io/T1"), ("x.io/B", "y.io/T2"),
                ("x.io/C", "y.io/T1"),
            ],
        )
        result = topological_sort(g)
        # Tier 0 should contain all 5 nodes (no hard edges)
        tier0 = result[0]
        # Within tier 0, order by (soft_count, gk):
        # A=0, T1=0, T2=0, C=1, B=2
        # Ties broken lexicographically: x.io/A, y.io/T1, y.io/T2, x.io/C, x.io/B
        assert tier0.kinds.index("x.io/A") < tier0.kinds.index("x.io/C")
        assert tier0.kinds.index("x.io/C") < tier0.kinds.index("x.io/B")

    def test_external_nodes_excluded(self):
        """External nodes never appear in any SortTier."""

        g = _make_graph(
            nodes=[
                ("x.io", "A", "x"), ("x.io", "B", "x"),
                ("", "Secret", "core"),
            ],
            hard_edges=[("x.io/A", "x.io/B")],
            external_gks={"/Secret"},
        )
        result = topological_sort(g)
        all_kinds = [gk for tier in result for gk in tier.kinds]
        assert "/Secret" not in all_kinds

    def test_soft_edges_ignored_for_tier_placement(self):
        """A node with only soft edges still lands at Tier 0."""

        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x")],
            soft_edges=[("x.io/A", "x.io/B")],
        )
        result = topological_sort(g)
        # Both should be at Tier 0 since soft edges don't affect in-degree
        assert len(result) == 1
        assert result[0].tier == 0
        assert "x.io/A" in result[0].kinds
        assert "x.io/B" in result[0].kinds

    def test_optional_edges_ignored_for_tier_placement(self):
        """A node with only optional edges still lands at Tier 0."""
        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x")],
            optional_edges=[("x.io/A", "x.io/B")],
        )
        result = topological_sort(g)
        assert len(result) == 1
        assert result[0].tier == 0
        assert "x.io/A" in result[0].kinds
        assert "x.io/B" in result[0].kinds

    def test_duplicate_hard_edges_handled(self):
        """Duplicate hard edges between same pair don't corrupt tier placement."""
        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x")],
            hard_edges=[("x.io/A", "x.io/B"), ("x.io/A", "x.io/B")],
        )
        result = topological_sort(g)
        all_kinds = [gk for tier in result for gk in tier.kinds]
        assert all_kinds.count("x.io/A") == 1
        assert all_kinds.count("x.io/B") == 1
        assert result[0].kinds == ["x.io/B"]
        assert result[1].kinds == ["x.io/A"]

    def test_cycle_resolved_both_placed(self):
        """A 2-node cycle: both nodes placed in same tier via SCC resolution."""
        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x")],
            hard_edges=[("x.io/A", "x.io/B"), ("x.io/B", "x.io/A")],
        )
        result = topological_sort(g)
        all_kinds = {gk for tier in result for gk in tier.kinds}
        assert "x.io/A" in all_kinds
        assert "x.io/B" in all_kinds

    def test_cycle_with_sortable_nodes_all_placed(self):
        """Sortable and cyclic nodes are all placed after SCC resolution."""
        g = _make_graph(
            nodes=[
                ("x.io", "A", "x"), ("x.io", "B", "x"),
                ("x.io", "C", "x"), ("x.io", "D", "x"),
            ],
            hard_edges=[
                ("x.io/C", "x.io/D"), ("x.io/D", "x.io/C"),
                ("x.io/A", "x.io/B"),
            ],
        )
        result = topological_sort(g)
        placed = {gk for tier in result for gk in tier.kinds}
        assert "x.io/B" in placed
        assert "x.io/A" in placed
        assert "x.io/C" in placed
        assert "x.io/D" in placed

    def test_self_loop_hard_edge_skipped(self):
        """A self-loop hard edge is stripped; the node lands at Tier 0."""
        g = _make_graph(
            nodes=[("x.io", "A", "x")],
            hard_edges=[("x.io/A", "x.io/A")],
        )
        result = topological_sort(g)
        assert len(result) == 1
        assert result[0].kinds == ["x.io/A"]


# ---------------------------------------------------------------------------
# Section 04: Tarjan's SCC / Cycle Resolution
# ---------------------------------------------------------------------------


class TestDetectCycles:
    """Tests for detect_cycles() — iterative path-based SCC algorithm."""

    def test_no_cycles_returns_empty(self):
        """A linear chain (A→B→C) has no cycles."""
        from idi.generation.crd.topo_sort import detect_cycles

        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x"), ("x.io", "C", "x")],
            hard_edges=[("x.io/A", "x.io/B"), ("x.io/B", "x.io/C")],
        )
        assert detect_cycles(g) == []

    def test_self_loop_detected_as_trivial_scc(self):
        """A self-loop (Middleware→Middleware) is detected as a trivial SCC."""
        from idi.generation.crd.topo_sort import detect_cycles

        g = _make_graph(
            nodes=[("traefik.io", "Middleware", "traefik")],
            hard_edges=[("traefik.io/Middleware", "traefik.io/Middleware")],
        )
        sccs = detect_cycles(g)
        assert len(sccs) == 1
        assert sccs[0] == ["traefik.io/Middleware"]

    def test_two_node_cycle(self):
        """A→B→A is detected as a non-trivial SCC."""
        from idi.generation.crd.topo_sort import detect_cycles

        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x")],
            hard_edges=[("x.io/A", "x.io/B"), ("x.io/B", "x.io/A")],
        )
        sccs = detect_cycles(g)
        assert len(sccs) == 1
        assert sorted(sccs[0]) == ["x.io/A", "x.io/B"]

    def test_multiple_independent_sccs(self):
        """Two separate cycles {A→B→A} and {C→D→C} detected independently."""
        from idi.generation.crd.topo_sort import detect_cycles

        g = _make_graph(
            nodes=[
                ("x.io", "A", "x"), ("x.io", "B", "x"),
                ("y.io", "C", "y"), ("y.io", "D", "y"),
            ],
            hard_edges=[
                ("x.io/A", "x.io/B"), ("x.io/B", "x.io/A"),
                ("y.io/C", "y.io/D"), ("y.io/D", "y.io/C"),
            ],
        )
        sccs = detect_cycles(g)
        assert len(sccs) == 2
        scc_sets = [set(scc) for scc in sccs]
        assert {"x.io/A", "x.io/B"} in scc_sets
        assert {"y.io/C", "y.io/D"} in scc_sets

    def test_soft_edges_ignored_for_cycle_detection(self):
        """Soft edges do not create cycles."""
        from idi.generation.crd.topo_sort import detect_cycles

        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x")],
            hard_edges=[("x.io/A", "x.io/B")],
            soft_edges=[("x.io/B", "x.io/A")],
        )
        assert detect_cycles(g) == []


class TestCycleResolution:
    """Tests for cycle resolution integrated with topological_sort()."""

    def test_trivial_scc_stripped_kind_in_normal_sort(self):
        """Middleware self-loop is stripped; Middleware appears at correct tier.
        Trivial SCCs should NOT have scc_group set."""
        g = _make_graph(
            nodes=[
                ("traefik.io", "Middleware", "traefik"),
                ("traefik.io", "IngressRoute", "traefik"),
            ],
            hard_edges=[
                ("traefik.io/Middleware", "traefik.io/Middleware"),
                ("traefik.io/IngressRoute", "traefik.io/Middleware"),
            ],
        )
        result = topological_sort(g)
        placed = {gk for tier in result for gk in tier.kinds}
        assert "traefik.io/Middleware" in placed
        assert "traefik.io/IngressRoute" in placed
        # Middleware should be in a lower tier
        tier_of = {}
        for t in result:
            for gk in t.kinds:
                tier_of[gk] = t.tier
        assert tier_of["traefik.io/Middleware"] < tier_of["traefik.io/IngressRoute"]
        # Trivial SCC should NOT have scc_group
        mw_tier = [t for t in result if "traefik.io/Middleware" in t.kinds][0]
        assert mw_tier.scc_group is None

    def test_nontrivial_scc_placed_in_same_tier_with_scc_group(self):
        """A→B→A cycle: both placed in same tier with scc_group set."""
        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x")],
            hard_edges=[("x.io/A", "x.io/B"), ("x.io/B", "x.io/A")],
        )
        result = topological_sort(g)
        assert len(result) == 1
        assert "x.io/A" in result[0].kinds
        assert "x.io/B" in result[0].kinds
        assert result[0].scc_group is not None
        assert sorted(result[0].scc_group) == ["x.io/A", "x.io/B"]

    def test_scc_representative_is_lex_smallest(self):
        """After condensation, representative is the lex-smallest gk."""
        from idi.generation.crd.topo_sort import condense_cycles

        g = _make_graph(
            nodes=[("z.io", "Z", "z"), ("y.io", "Y", "y"), ("x.io", "X", "x")],
            hard_edges=[
                ("z.io/Z", "y.io/Y"), ("y.io/Y", "x.io/X"), ("x.io/X", "z.io/Z"),
            ],
        )
        sccs = [["z.io/Z", "y.io/Y", "x.io/X"]]
        condensed, scc_map = condense_cycles(g, sccs)
        # Representative should be lex smallest: x.io/X
        assert "x.io/X" in condensed.nodes
        assert "y.io/Y" not in condensed.nodes
        assert "z.io/Z" not in condensed.nodes
        assert sorted(scc_map["x.io/X"]) == ["x.io/X", "y.io/Y", "z.io/Z"]

    def test_scc_tier_propagation(self):
        """C depends on SCC{A,B} → A and B same tier, C in higher tier."""
        g = _make_graph(
            nodes=[
                ("x.io", "A", "x"), ("x.io", "B", "x"), ("x.io", "C", "x"),
            ],
            hard_edges=[
                ("x.io/A", "x.io/B"), ("x.io/B", "x.io/A"),
                ("x.io/C", "x.io/A"),
            ],
        )
        result = topological_sort(g)
        tier_of = {}
        for t in result:
            for gk in t.kinds:
                tier_of[gk] = t.tier
        assert tier_of["x.io/A"] == tier_of["x.io/B"]
        assert tier_of["x.io/C"] > tier_of["x.io/A"]

    def test_cycle_warning_logged(self, caplog):
        """Non-trivial SCC emits a warning with member names and edge details."""
        import logging
        g = _make_graph(
            nodes=[("x.io", "A", "x"), ("x.io", "B", "x")],
            hard_edges=[("x.io/A", "x.io/B"), ("x.io/B", "x.io/A")],
        )
        with caplog.at_level(logging.WARNING, logger="idi.generation.crd.topo_sort"):
            topological_sort(g)
        assert any("x.io/A" in r.message and "x.io/B" in r.message for r in caplog.records)
        # Should include edge details (source_field)
        assert any("spec.ref" in r.message for r in caplog.records)

    def test_multiple_sccs_in_sort(self):
        """Two independent cycles both placed with separate scc_group values."""
        g = _make_graph(
            nodes=[
                ("x.io", "A", "x"), ("x.io", "B", "x"),
                ("y.io", "C", "y"), ("y.io", "D", "y"),
            ],
            hard_edges=[
                ("x.io/A", "x.io/B"), ("x.io/B", "x.io/A"),
                ("y.io/C", "y.io/D"), ("y.io/D", "y.io/C"),
            ],
        )
        result = topological_sort(g)
        all_kinds = {gk for tier in result for gk in tier.kinds}
        assert {"x.io/A", "x.io/B", "y.io/C", "y.io/D"} == all_kinds
        scc_tiers = [t for t in result if t.scc_group is not None]
        assert len(scc_tiers) >= 1
        # Verify each SCC has its own scc_group with correct members
        all_scc_members = []
        for t in scc_tiers:
            all_scc_members.extend(t.scc_group)
        assert sorted(all_scc_members) == ["x.io/A", "x.io/B", "y.io/C", "y.io/D"]


# ---------------------------------------------------------------------------
# Catalog Writer — Section 06
# ---------------------------------------------------------------------------


def _make_manifest(kind: str, group: str, service: str) -> dict:
    """Build a minimal but realistic manifest.json for testing."""
    return {
        "schema_version": "2.0",
        "kind": kind,
        "group": group,
        "version": "v1",
        "plural": kind.lower() + "s",
        "scope": "Namespaced",
        "service": service,
        "description": f"A {kind} resource",
        "operations": [],
        "refs": [],
        "outputs": [],
        "fields": [],
        "status_conditions": [],
        "content_hash": "abc123",
    }


def _setup_catalog(tmp_path, manifests: list[dict]) -> None:
    """Write manifest.json files in expected catalog layout."""
    for m in manifests:
        svc = m["service"]
        grp = m["group"]
        kind = m["kind"]
        d = tmp_path / svc / grp / svc / kind
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(
            json.dumps(m, indent=2, sort_keys=True) + "\n"
        )


def _simple_graph(
    kinds: list[tuple[str, str, str]],
    hard_edges: list[tuple[str, str]] | None = None,
    externals: list[tuple[str, str, str]] | None = None,
) -> DependencyGraph:
    """Build a simple graph for catalog writer tests.

    kinds: list of (kind, group, service)
    """
    nodes = {}
    for kind, group, service in kinds:
        gk = f"{group}/{kind}"
        nodes[gk] = KindNode(kind=kind, group=group, service=service)
    for kind, group, service in (externals or []):
        gk = f"{group}/{kind}"
        nodes[gk] = KindNode(kind=kind, group=group, service=service, is_external=True)
    dep_edges = []
    for src, tgt in (hard_edges or []):
        dep_edges.append(DependencyEdge(
            source_gk=src, target_gk=tgt, edge_type="hard",
            source_field="test", detection_source="test", confidence=0.9,
        ))
    ext_set = {f"{g}/{k}" for k, g, s in (externals or [])}
    return DependencyGraph(
        nodes=nodes, dependency_edges=dep_edges,
        production_edges=[], external_kinds=ext_set,
    )


class TestCatalogWriterManifests:
    def test_manifest_updated_with_sort_tier(self, tmp_path):
        """Manifest gets integer sort_tier field added."""
        m = _make_manifest("Certificate", "cert-manager.io", "cert-manager")
        _setup_catalog(tmp_path, [m])
        tiers = [SortTier(tier=0, kinds=["cert-manager.io/Certificate"])]
        graph = _simple_graph([("Certificate", "cert-manager.io", "cert-manager")])
        count = update_manifests_with_tiers(tiers, tmp_path)
        assert count == 1
        written = json.loads(
            (tmp_path / "cert-manager" / "cert-manager.io" / "cert-manager" / "Certificate" / "manifest.json").read_text()
        )
        assert written["sort_tier"] == 0
        assert isinstance(written["sort_tier"], int)

    def test_manifest_preserves_existing_fields(self, tmp_path):
        """Existing fields must not change when sort_tier is added."""
        m = _make_manifest("Issuer", "cert-manager.io", "cert-manager")
        original = dict(m)
        _setup_catalog(tmp_path, [m])
        tiers = [SortTier(tier=1, kinds=["cert-manager.io/Issuer"])]
        update_manifests_with_tiers(tiers, tmp_path)
        written = json.loads(
            (tmp_path / "cert-manager" / "cert-manager.io" / "cert-manager" / "Issuer" / "manifest.json").read_text()
        )
        for key in original:
            assert written[key] == original[key], f"Field {key!r} changed"

    def test_missing_manifest_logged_not_crash(self, tmp_path):
        """Kinds in tiers without manifest files are skipped with warning."""
        tiers = [SortTier(tier=0, kinds=["cert-manager.io/Certificate"])]
        graph = _simple_graph([("Certificate", "cert-manager.io", "cert-manager")])
        count = update_manifests_with_tiers(tiers, tmp_path)
        assert count == 0  # no manifests found


class TestCatalogWriterCanonicalJson:
    def test_json_canonical_serialization(self, tmp_path):
        """Output files must use sorted keys, 2-space indent, trailing newline."""
        data = {"z_key": 1, "a_key": 2}
        path = tmp_path / "test.json"
        _write_json(path, data)
        raw = path.read_text()
        expected = json.dumps(data, indent=2, sort_keys=True) + "\n"
        assert raw == expected


class TestServiceOrdering:
    def test_ordering_json_schema(self, tmp_path):
        """ordering.json must contain required keys."""
        tiers = [
            SortTier(tier=0, kinds=["cert-manager.io/ClusterIssuer", "cert-manager.io/Issuer"]),
            SortTier(tier=1, kinds=["cert-manager.io/Certificate"]),
        ]
        graph = _simple_graph([
            ("ClusterIssuer", "cert-manager.io", "cert-manager"),
            ("Issuer", "cert-manager.io", "cert-manager"),
            ("Certificate", "cert-manager.io", "cert-manager"),
        ])
        path = write_service_ordering("cert-manager", tiers, graph, tmp_path)
        data = json.loads(path.read_text())
        assert data["schema_version"] == "1.0"
        assert data["service"] == "cert-manager"
        assert "tiers" in data
        assert "sort_metadata" in data
        assert data["sort_metadata"]["total_kinds"] == 3
        assert data["sort_metadata"]["total_tiers"] == 2

    def test_ordering_json_tiers_sorted(self, tmp_path):
        """Tiers in ordering.json are sorted ascending by tier number."""
        tiers = [
            SortTier(tier=2, kinds=["x.io/C"]),
            SortTier(tier=0, kinds=["x.io/A"]),
            SortTier(tier=1, kinds=["x.io/B"]),
        ]
        graph = _simple_graph([
            ("A", "x.io", "x"), ("B", "x.io", "x"), ("C", "x.io", "x"),
        ])
        path = write_service_ordering("x", tiers, graph, tmp_path)
        data = json.loads(path.read_text())
        tier_nums = [t["tier"] for t in data["tiers"]]
        assert tier_nums == [0, 1, 2]

    def test_ordering_json_cycle_warnings(self, tmp_path):
        """sort_metadata.cycle_warnings is a list."""
        tiers = [SortTier(tier=0, kinds=["x.io/A"])]
        graph = _simple_graph([("A", "x.io", "x")])
        # No cycles
        path = write_service_ordering("x", tiers, graph, tmp_path)
        data = json.loads(path.read_text())
        assert data["sort_metadata"]["cycle_warnings"] == []
        # With cycle warning
        path2 = write_service_ordering(
            "x", tiers, graph, tmp_path,
            cycle_warnings=["Circular dep: A <-> B"],
        )
        data2 = json.loads(path2.read_text())
        assert data2["sort_metadata"]["cycle_warnings"] == ["Circular dep: A <-> B"]

    def test_ordering_json_unknown_external_kinds(self, tmp_path):
        """unknown_external_kinds lists externals found by set-difference, scoped to service."""
        tiers = [SortTier(tier=0, kinds=["x.io/A"])]
        graph = _simple_graph(
            kinds=[("A", "x.io", "x")],
            hard_edges=[
                ("x.io/A", "/Secret"),
                ("x.io/A", "custom.io/Widget"),
            ],
            externals=[
                ("Secret", "", "core"),
                ("Widget", "custom.io", "custom"),
            ],
        )
        path = write_service_ordering("x", tiers, graph, tmp_path)
        data = json.loads(path.read_text())
        assert "/Secret" in data["sort_metadata"]["external_kinds"]
        assert "custom.io/Widget" in data["sort_metadata"]["unknown_external_kinds"]
        assert "/Secret" not in data["sort_metadata"]["unknown_external_kinds"]

    def test_scc_group_in_ordering(self, tmp_path):
        """Tiers with SCC groups include scc_group in output."""
        tiers = [
            SortTier(tier=0, kinds=["x.io/A", "x.io/B"], scc_group=["x.io/A", "x.io/B"]),
        ]
        graph = _simple_graph([("A", "x.io", "x"), ("B", "x.io", "x")])
        path = write_service_ordering("x", tiers, graph, tmp_path)
        data = json.loads(path.read_text())
        assert data["tiers"][0]["scc_group"] == ["x.io/A", "x.io/B"]


class TestGlobalOrdering:
    def test_global_ordering_group_qualified(self, tmp_path):
        """Global ordering kinds use group/Kind format."""
        tiers = [
            SortTier(tier=0, kinds=["cert-manager.io/Issuer", "/Secret"]),
        ]
        graph = _simple_graph(
            kinds=[("Issuer", "cert-manager.io", "cert-manager")],
            externals=[("Secret", "", "core")],
        )
        path = write_global_ordering(tiers, graph, tmp_path)
        data = json.loads(path.read_text())
        all_kinds = [k for t in data["tiers"] for k in t["kinds"]]
        for k in all_kinds:
            assert "/" in k, f"Kind {k!r} not group-qualified"

    def test_global_ordering_cross_service_edges(self, tmp_path):
        """Global ordering includes cross_service_edges."""
        tiers = [
            SortTier(tier=0, kinds=["cm.io/Issuer"]),
            SortTier(tier=1, kinds=["es.io/ExtSecret"]),
        ]
        graph = _simple_graph(
            kinds=[
                ("Issuer", "cm.io", "cm"),
                ("ExtSecret", "es.io", "es"),
            ],
            hard_edges=[("es.io/ExtSecret", "cm.io/Issuer")],
        )
        path = write_global_ordering(tiers, graph, tmp_path)
        data = json.loads(path.read_text())
        assert "cross_service_edges" in data["sort_metadata"]
        assert len(data["sort_metadata"]["cross_service_edges"]) == 1
        edge = data["sort_metadata"]["cross_service_edges"][0]
        assert edge["source"] == "es.io/ExtSecret"
        assert edge["target"] == "cm.io/Issuer"

    def test_global_ordering_services_list(self, tmp_path):
        """Global ordering includes sorted services list."""
        tiers = [
            SortTier(tier=0, kinds=["cm.io/Issuer", "es.io/ExtSecret"]),
        ]
        graph = _simple_graph(
            kinds=[
                ("Issuer", "cm.io", "cm"),
                ("ExtSecret", "es.io", "es"),
            ],
        )
        path = write_global_ordering(tiers, graph, tmp_path)
        data = json.loads(path.read_text())
        assert data["sort_metadata"]["services"] == ["cm", "es"]


class TestPathSanitization:
    def test_safe_filename_dots_hyphens(self):
        """Dots and hyphens are allowed in path segments."""
        assert _sanitize_path_segment("cert-manager.io") == "cert-manager.io"

    def test_slash_replaced(self):
        """Slashes are replaced with underscore."""
        assert _sanitize_path_segment("foo/bar") == "foo_bar"

    def test_path_traversal_guard(self, tmp_path):
        """Sanitization prevents traversal — ../evil becomes .._evil (still under root)."""
        tiers = [SortTier(tier=0, kinds=["x.io/A"])]
        graph = _simple_graph([("A", "x.io", "x")])
        # After sanitization, "../evil" -> ".._evil" which is safe.
        # Verify the file is written under catalog root.
        path = write_service_ordering("../evil", tiers, graph, tmp_path)
        assert path.resolve().is_relative_to(tmp_path.resolve())


class TestWriteSortResults:
    def test_orchestrates_all_outputs(self, tmp_path):
        """write_sort_results writes manifests, service ordering, and global ordering."""
        m = _make_manifest("Certificate", "cert-manager.io", "cert-manager")
        _setup_catalog(tmp_path, [m])
        tiers = [SortTier(tier=0, kinds=["cert-manager.io/Certificate"])]
        graph = _simple_graph([("Certificate", "cert-manager.io", "cert-manager")])
        paths = write_sort_results(graph, tiers, tmp_path)
        assert "global" in paths
        assert (tmp_path / "cert-manager" / "ordering.json").exists()
        assert (tmp_path / "global-ordering.json").exists()
        # Per-service ordering uses plain Kind names
        svc_data = json.loads((tmp_path / "cert-manager" / "ordering.json").read_text())
        assert svc_data["tiers"][0]["kinds"] == ["Certificate"]
        # Global ordering uses group-qualified names
        global_data = json.loads((tmp_path / "global-ordering.json").read_text())
        assert "cert-manager.io/Certificate" in global_data["tiers"][0]["kinds"]
        # Manifest gets sort_tier
        m_path = tmp_path / "cert-manager" / "cert-manager.io" / "cert-manager" / "Certificate" / "manifest.json"
        assert json.loads(m_path.read_text())["sort_tier"] == 0


# ---------------------------------------------------------------------------
# CLI — Section 07
# ---------------------------------------------------------------------------


def _write_ref_file(kind_dir, name, target_kind, target_group, required=False,
                    confidence=0.9, detection_source="test", field_path=None):
    """Helper: write a ref JSON file into a Kind's refs/ directory."""
    refs_dir = kind_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    ref_data = {
        "name": name,
        "field_path": field_path or f"spec.{name}",
        "target_kind": target_kind,
        "target_group": target_group,
        "role": "input_ref",
        "required": required,
        "cross_namespace": False,
        "fact_ref": f"crdfacts://{target_group or 'core'}/{target_kind}#name",
        "fact_shape": "identity",
        "satisfaction": "required_value" if required else "optional",
        "detection_source": detection_source,
        "confidence": confidence,
    }
    (refs_dir / f"{name}.json").write_text(
        json.dumps(ref_data, indent=2, sort_keys=True) + "\n"
    )


def _setup_cli_catalog(tmp_path, services):
    """Set up a minimal catalog layout for CLI tests.

    services: list of dicts with keys: service, kinds.
    Each kind: dict with kind, group, and optional refs (list of ref dicts).
    Returns the catalog root path.
    """
    catalog = tmp_path / "catalog"
    for svc_info in services:
        svc_name = svc_info["service"]
        for kind_info in svc_info["kinds"]:
            kind = kind_info["kind"]
            group = kind_info["group"]
            kind_dir = catalog / group / svc_name / kind
            kind_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "schema_version": "2.0",
                "kind": kind,
                "group": group,
                "version": "v1",
                "plural": kind.lower() + "s",
                "scope": "Namespaced",
                "service": svc_name,
                "description": f"A {kind} resource",
                "operations": ["apply"],
                "refs": [],
                "outputs": [],
                "fields": [],
                "status_conditions": ["Ready"],
                "content_hash": "test",
            }
            # Write refs
            for ref in kind_info.get("refs", []):
                manifest["refs"].append(ref["name"])
                _write_ref_file(
                    kind_dir, ref["name"],
                    target_kind=ref["target_kind"],
                    target_group=ref.get("target_group", ""),
                    required=ref.get("required", False),
                    confidence=ref.get("confidence", 0.9),
                    detection_source=ref.get("detection_source", "test"),
                )
            (kind_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            )
    return catalog


class TestLoadCatalogForSort:
    """Tests for _load_catalog_for_sort helper."""

    def test_loads_manifests_and_refs(self, tmp_path):
        """Loads manifest and ref files, returns ClassifiedField data."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Certificate", "group": "cert-manager.io", "refs": [
                    {"name": "issuerRef", "target_kind": "Issuer",
                     "target_group": "cert-manager.io", "required": True},
                ]},
                {"kind": "Issuer", "group": "cert-manager.io", "refs": []},
            ]},
        ])
        result = _load_catalog_for_sort(catalog)
        assert ("cert-manager.io", "Certificate") in result["classified_fields"]
        assert ("cert-manager.io", "Issuer") in result["classified_fields"]
        cert_fields = result["classified_fields"][("cert-manager.io", "Certificate")]
        assert len(cert_fields) == 1
        assert cert_fields[0].target_kind == "Issuer"
        assert cert_fields[0].required is True

    def test_service_filter_excludes_other_services(self, tmp_path):
        """service_filter skips manifests from other services."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Issuer", "group": "cert-manager.io"},
            ]},
            {"service": "traefik", "kinds": [
                {"kind": "IngressRoute", "group": "traefik.io"},
            ]},
        ])
        result = _load_catalog_for_sort(catalog, service_filter="cert-manager")
        assert ("cert-manager.io", "Issuer") in result["classified_fields"]
        assert ("traefik.io", "IngressRoute") not in result["classified_fields"]

    def test_empty_catalog_returns_empty(self, tmp_path):
        """Empty catalog dir returns empty classified_fields."""
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        result = _load_catalog_for_sort(catalog)
        assert result["classified_fields"] == {}

    def test_reads_role_from_ref_file(self, tmp_path):
        """Role field is read from ref JSON, not hardcoded."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "test", "kinds": [
                {"kind": "Widget", "group": "test.io", "refs": [
                    {"name": "parentRef", "target_kind": "Parent",
                     "target_group": "test.io", "required": False},
                ]},
            ]},
        ])
        result = _load_catalog_for_sort(catalog)
        field = result["classified_fields"][("test.io", "Widget")][0]
        assert field.role == "input_ref"  # from the ref file's "role" key


class TestLoadOlmOwned:
    """Tests for _load_olm_owned OLM cache loader."""

    def test_loads_owned_gvks_from_cache(self, tmp_path):
        """Reads csv.yaml cache files and extracts owned GVKs."""
        import yaml
        olm_dir = tmp_path / "olm"
        svc_dir = olm_dir / "cert-manager"
        svc_dir.mkdir(parents=True)
        csv_data = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"kind": "Certificate", "name": "certificates.cert-manager.io", "version": "v1"},
                        {"kind": "Issuer", "name": "issuers.cert-manager.io", "version": "v1"},
                    ],
                    "required": [],
                },
            },
        }
        (svc_dir / "csv.yaml").write_text(yaml.dump(csv_data))
        result = _load_olm_owned(olm_dir)
        assert "cert-manager" in result
        kinds = {g.kind for g in result["cert-manager"]}
        assert kinds == {"Certificate", "Issuer"}

    def test_service_filter(self, tmp_path):
        """service_filter restricts which services are loaded."""
        import yaml
        olm_dir = tmp_path / "olm"
        for svc_name in ("cert-manager", "traefik"):
            svc_dir = olm_dir / svc_name
            svc_dir.mkdir(parents=True)
            csv_data = {
                "spec": {
                    "customresourcedefinitions": {
                        "owned": [{"kind": "Widget", "name": f"widgets.{svc_name}.io", "version": "v1"}],
                    },
                },
            }
            (svc_dir / "csv.yaml").write_text(yaml.dump(csv_data))
        result = _load_olm_owned(olm_dir, service_filter="cert-manager")
        assert "cert-manager" in result
        assert "traefik" not in result

    def test_missing_dir_returns_empty(self, tmp_path):
        """Non-existent OLM cache dir returns empty dict."""
        result = _load_olm_owned(tmp_path / "nonexistent")
        assert result == {}

    def test_malformed_yaml_skipped(self, tmp_path):
        """Malformed csv.yaml files are skipped with a warning."""
        olm_dir = tmp_path / "olm" / "bad"
        olm_dir.mkdir(parents=True)
        (olm_dir / "csv.yaml").write_text("{{{{not yaml")
        result = _load_olm_owned(tmp_path / "olm")
        assert result == {}


class TestCLI:
    """Tests for CLI entry point (_cli_main)."""

    def test_cli_no_args_outputs_json(self, tmp_path):
        """Running with catalog-dir outputs valid JSON with services key."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Issuer", "group": "cert-manager.io", "refs": []},
                {"kind": "Certificate", "group": "cert-manager.io", "refs": [
                    {"name": "issuerRef", "target_kind": "Issuer",
                     "target_group": "cert-manager.io", "required": True},
                ]},
            ]},
        ])
        out = io.StringIO()
        code = _cli_main(["--catalog-dir", str(catalog)], stdout=out)
        assert code == 0
        data = json.loads(out.getvalue())
        assert "services" in data

    def test_cli_service_flag_filters_output(self, tmp_path):
        """--service cert-manager produces output containing only cert-manager."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Issuer", "group": "cert-manager.io"},
            ]},
            {"service": "traefik", "kinds": [
                {"kind": "IngressRoute", "group": "traefik.io"},
            ]},
        ])
        out = io.StringIO()
        code = _cli_main(["--catalog-dir", str(catalog), "--service", "cert-manager"], stdout=out)
        assert code == 0
        data = json.loads(out.getvalue())
        assert list(data["services"].keys()) == ["cert-manager"]

    def test_cli_global_flag_includes_global_sort(self, tmp_path):
        """--global adds a 'global' key with tiers and cross_service_edges."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Issuer", "group": "cert-manager.io"},
            ]},
            {"service": "traefik", "kinds": [
                {"kind": "IngressRoute", "group": "traefik.io"},
            ]},
        ])
        out = io.StringIO()
        code = _cli_main(["--catalog-dir", str(catalog), "--global"], stdout=out)
        assert code == 0
        data = json.loads(out.getvalue())
        assert "global" in data
        assert "tiers" in data["global"]
        assert "cross_service_edges" in data["global"]

    def test_cli_write_flag_creates_files(self, tmp_path):
        """--write causes ordering.json and manifest updates in the catalog dir."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Issuer", "group": "cert-manager.io"},
            ]},
        ])
        out = io.StringIO()
        code = _cli_main(["--catalog-dir", str(catalog), "--write"], stdout=out)
        assert code == 0
        # Check ordering.json was written
        assert (catalog / "cert-manager" / "ordering.json").exists()
        # Check manifest.json was updated with sort_tier
        manifest = json.loads(
            (catalog / "cert-manager.io" / "cert-manager" / "Issuer" / "manifest.json").read_text()
        )
        assert "sort_tier" in manifest

    def test_cli_write_global_creates_global_ordering(self, tmp_path):
        """--write --global creates global-ordering.json."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Issuer", "group": "cert-manager.io"},
            ]},
        ])
        out = io.StringIO()
        code = _cli_main(["--catalog-dir", str(catalog), "--write", "--global"], stdout=out)
        assert code == 0
        assert (catalog / "global-ordering.json").exists()

    def test_cli_verbose_includes_edges(self, tmp_path):
        """--verbose adds edge provenance to tier entries."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Issuer", "group": "cert-manager.io"},
                {"kind": "Certificate", "group": "cert-manager.io", "refs": [
                    {"name": "issuerRef", "target_kind": "Issuer",
                     "target_group": "cert-manager.io", "required": True},
                ]},
            ]},
        ])
        out = io.StringIO()
        code = _cli_main(["--catalog-dir", str(catalog), "--verbose"], stdout=out)
        assert code == 0
        data = json.loads(out.getvalue())
        svc = data["services"]["cert-manager"]
        # Certificate tier should have edges since it depends on Issuer
        cert_tier = [t for t in svc["tiers"] if "Certificate" in t["kinds"]]
        assert len(cert_tier) == 1
        assert "edges" in cert_tier[0]
        edge = cert_tier[0]["edges"][0]
        assert "source" in edge
        assert "target" in edge
        assert "detection_source" in edge
        assert "confidence" in edge

    def test_cli_json_output_schema(self, tmp_path):
        """Output JSON has the documented structure."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Issuer", "group": "cert-manager.io"},
                {"kind": "Certificate", "group": "cert-manager.io", "refs": [
                    {"name": "issuerRef", "target_kind": "Issuer",
                     "target_group": "cert-manager.io", "required": True},
                ]},
            ]},
        ])
        out = io.StringIO()
        _cli_main(["--catalog-dir", str(catalog)], stdout=out)
        data = json.loads(out.getvalue())
        assert "services" in data
        svc = data["services"]["cert-manager"]
        assert "tiers" in svc
        assert "cycles" in svc
        assert "external_kinds" in svc
        for tier in svc["tiers"]:
            assert "tier" in tier
            assert "kinds" in tier
            assert isinstance(tier["tier"], int)
            assert isinstance(tier["kinds"], list)

    def test_cli_exit_code_zero(self, tmp_path):
        """CLI returns exit code 0 on successful execution."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "test", "kinds": [
                {"kind": "Widget", "group": "test.io"},
            ]},
        ])
        out = io.StringIO()
        code = _cli_main(["--catalog-dir", str(catalog)], stdout=out)
        assert code == 0

    def test_cli_missing_catalog_dir_returns_1(self, tmp_path):
        """Non-existent catalog dir returns exit code 1."""
        out = io.StringIO()
        err = io.StringIO()
        code = _cli_main(["--catalog-dir", str(tmp_path / "nonexistent")], stdout=out, stderr=err)
        assert code == 1

    def test_cli_unknown_service_returns_1(self, tmp_path):
        """--service with unknown name returns exit code 1."""
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Issuer", "group": "cert-manager.io"},
            ]},
        ])
        out = io.StringIO()
        err = io.StringIO()
        code = _cli_main(
            ["--catalog-dir", str(catalog), "--service", "nonexistent"],
            stdout=out, stderr=err,
        )
        assert code == 1

    def test_cli_olm_cache_flag(self, tmp_path):
        """--olm-cache passes OLM data to the graph builder."""
        import yaml
        catalog = _setup_cli_catalog(tmp_path, [
            {"service": "cert-manager", "kinds": [
                {"kind": "Certificate", "group": "cert-manager.io"},
            ]},
        ])
        olm_dir = tmp_path / "olm"
        svc_dir = olm_dir / "cert-manager"
        svc_dir.mkdir(parents=True)
        csv_data = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"kind": "Certificate", "name": "certificates.cert-manager.io", "version": "v1"},
                    ],
                },
            },
        }
        (svc_dir / "csv.yaml").write_text(yaml.dump(csv_data))
        out = io.StringIO()
        code = _cli_main([
            "--catalog-dir", str(catalog),
            "--olm-cache", str(olm_dir),
        ], stdout=out)
        assert code == 0


# ---------------------------------------------------------------------------
# Integration Tests — Section 08
# ---------------------------------------------------------------------------


@pytest.fixture
def classified_fields_all_services(all_fixtures, populated_registry):
    """Classify all CRD fixture fields using the real detection pipeline.

    Returns:
        dict mapping (group, kind) -> list[ClassifiedField]
    """
    result: dict[tuple[str, str], list[ClassifiedField]] = {}
    for fix in all_fixtures:
        fields = classify_fields(
            spec_properties=fix["spec_properties"],
            spec_required=fix.get("spec_required", []),
            group=fix["group"],
            kind=fix["kind"],
            registry=populated_registry,
        )
        result[(fix["group"], fix["kind"])] = fields
    return result


@pytest.fixture
def integration_graph(classified_fields_all_services, populated_registry):
    """Build a DependencyGraph from real classified fields."""
    return build_dependency_graph(
        classified_fields=classified_fields_all_services,
        rbac_outputs={},
        olm_owned={},
        side_effect_dict=dict(OPERATOR_SIDE_EFFECTS),
        registry=populated_registry,
    )


@pytest.fixture
def integration_tiers(integration_graph):
    """Sort the integration graph and return tier assignments."""
    return topological_sort(integration_graph)


def _gk_to_tier(tiers: list[SortTier]) -> dict[str, int]:
    """Build gk -> tier number lookup."""
    result = {}
    for st in tiers:
        for gk in st.kinds:
            result[gk] = st.tier
    return result


class TestIntegration:
    """End-to-end integration tests using real CRD fixtures."""

    def test_full_pipeline_produces_valid_tiers(self, integration_tiers):
        """Full pipeline produces non-empty, valid tier assignments."""
        assert len(integration_tiers) >= 2
        # All 21 Kinds appear exactly once.
        all_gks = []
        for st in integration_tiers:
            all_gks.extend(st.kinds)
        assert len(all_gks) == 21, f"Expected 21 Kinds, got {len(all_gks)}"
        assert len(all_gks) == len(set(all_gks)), "Duplicate Kind in tiers"
        # No external Kinds in output.
        core_gks = {f"/{k}" for _, k in CORE_EXTERNAL_KINDS} | {f"{g}/{k}" for g, k in CORE_EXTERNAL_KINDS}
        for gk in all_gks:
            assert gk not in core_gks, f"External Kind {gk} found in tier output"
        # Tier numbers are contiguous from 0.
        tier_nums = sorted(st.tier for st in integration_tiers)
        assert tier_nums == list(range(len(tier_nums)))

    def test_cert_manager_issuer_before_certificate(self, integration_tiers):
        """cert-manager: Issuer/ClusterIssuer must be in a lower tier than Certificate."""
        lookup = _gk_to_tier(integration_tiers)
        assert "cert-manager.io/Issuer" in lookup
        assert "cert-manager.io/Certificate" in lookup
        assert lookup["cert-manager.io/Issuer"] < lookup["cert-manager.io/Certificate"]
        assert lookup["cert-manager.io/ClusterIssuer"] < lookup["cert-manager.io/Certificate"]

    def test_external_secrets_secretstore_before_externalsecret(self, integration_tiers):
        """external-secrets: SecretStore in same or lower tier than ExternalSecret.

        Note: secretStoreRef may be classified as optional/soft depending on
        the detection pipeline, which places them in the same tier.
        """
        lookup = _gk_to_tier(integration_tiers)
        assert "external-secrets.io/SecretStore" in lookup
        assert "external-secrets.io/ExternalSecret" in lookup
        assert lookup["external-secrets.io/SecretStore"] <= lookup["external-secrets.io/ExternalSecret"]
        assert lookup["external-secrets.io/ClusterSecretStore"] <= lookup["external-secrets.io/ExternalSecret"]

    def test_traefik_middleware_before_ingressroute(self, integration_tiers):
        """traefik: Middleware/TraefikService in lower or equal tier to IngressRoute."""
        lookup = _gk_to_tier(integration_tiers)
        assert "traefik.io/Middleware" in lookup
        assert "traefik.io/IngressRoute" in lookup
        assert lookup["traefik.io/Middleware"] <= lookup["traefik.io/IngressRoute"]
        assert lookup["traefik.io/TraefikService"] <= lookup["traefik.io/IngressRoute"]

    def test_global_sort_respects_hard_edges(self, integration_tiers, integration_graph):
        """Every hard dep edge has target in same or earlier tier than source."""
        lookup = _gk_to_tier(integration_tiers)
        for edge in integration_graph.dependency_edges:
            if edge.edge_type != "hard":
                continue
            if edge.source_gk not in lookup or edge.target_gk not in lookup:
                continue  # one end is external
            assert lookup[edge.target_gk] < lookup[edge.source_gk], (
                f"Hard edge {edge.source_gk} -> {edge.target_gk}: "
                f"target tier {lookup[edge.target_gk]} >= source tier {lookup[edge.source_gk]}"
            )

    def test_secret_deadlock_regression(self, integration_graph, integration_tiers):
        """Secret is always external with in-degree 0 — no deadlock.

        The detection pipeline produces target_group='core' for core types,
        so external_kinds contains 'core/Secret'.
        """
        assert "core/Secret" in integration_graph.external_kinds
        all_gks = {gk for st in integration_tiers for gk in st.kinds}
        assert "core/Secret" not in all_gks
        assert "cert-manager.io/ClusterIssuer" in all_gks
        assert "cert-manager.io/Certificate" in all_gks
        assert len(integration_tiers) > 0

    def test_all_kinds_placed_in_tiers(self, integration_tiers, classified_fields_all_services):
        """Every CRD Kind from the input appears in exactly one tier."""
        expected = {f"{g}/{k}" for g, k in classified_fields_all_services}
        actual = {gk for st in integration_tiers for gk in st.kinds}
        assert expected == actual

    def test_integration_determinism(self, classified_fields_all_services, populated_registry):
        """Running the pipeline 5 times produces identical tier assignments."""
        results = []
        for _ in range(5):
            graph = build_dependency_graph(
                classified_fields=classified_fields_all_services,
                rbac_outputs={},
                olm_owned={},
                side_effect_dict=dict(OPERATOR_SIDE_EFFECTS),
                registry=populated_registry,
            )
            tiers = topological_sort(graph)
            canonical = [(st.tier, sorted(st.kinds)) for st in sorted(tiers, key=lambda t: t.tier)]
            results.append(canonical)
        for i in range(1, 5):
            assert results[i] == results[0], f"Run {i} differs from run 0"

    def test_self_loops_stripped_in_integration(self, integration_tiers):
        """Traefik self-loops are stripped; Kinds appear without scc_group."""
        all_gks = {gk for st in integration_tiers for gk in st.kinds}
        assert "traefik.io/Middleware" in all_gks
        assert "traefik.io/TraefikService" in all_gks
        # Trivial SCCs (self-loops) should not produce scc_group.
        for st in integration_tiers:
            if "traefik.io/Middleware" in st.kinds:
                assert st.scc_group is None, "Middleware should not have scc_group (trivial SCC)"
                break

    def test_write_sort_results_end_to_end(self, integration_graph, integration_tiers, tmp_path):
        """write_sort_results writes all expected output files."""
        # Set up minimal manifests so update_manifests_with_tiers has files to update.
        for gk, node in integration_graph.nodes.items():
            if node.is_external:
                continue
            kind_dir = tmp_path / node.service / node.group / node.service / node.kind
            kind_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "schema_version": "2.0",
                "kind": node.kind,
                "group": node.group,
                "service": node.service,
            }
            (kind_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            )

        write_sort_results(integration_graph, integration_tiers, tmp_path)

        # Per-service ordering files.
        for svc in ("cert-manager", "external-secrets", "traefik"):
            ordering = tmp_path / svc / "ordering.json"
            assert ordering.exists(), f"Missing {ordering}"
            data = json.loads(ordering.read_text())
            assert data["schema_version"] == "1.0"
            assert data["service"] == svc
            assert "tiers" in data
            assert data["sort_metadata"]["total_kinds"] > 0

        # Global ordering.
        global_path = tmp_path / "global-ordering.json"
        assert global_path.exists()
        global_data = json.loads(global_path.read_text())
        assert global_data["schema_version"] == "1.0"
        assert global_data["sort_metadata"]["total_kinds"] > 0

        # Verify canonical JSON format (sorted keys, 2-space indent, trailing newline).
        raw = global_path.read_text()
        expected = json.dumps(global_data, indent=2, sort_keys=True) + "\n"
        assert raw == expected, "global-ordering.json is not canonical JSON"
