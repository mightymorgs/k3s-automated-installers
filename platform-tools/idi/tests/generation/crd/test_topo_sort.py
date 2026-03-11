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
    topological_sort,
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
