"""Tests for CRD edge promotion gates."""
from __future__ import annotations

from idi.generation.crd.edge_promotion import (
    CrdGateResult,
    gate_crd1_intra_service,
    gate_crd2_field_type,
    gate_crd3_ref_shape,
    gate_crd4_not_discriminator,
    gate_crd5_depth,
    gate_crd6_confidence,
    promote_soft_edges,
)
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


# ── G-CRD1 tests ────────────────────────────────────────────


class TestGateCrd1:
    """Tests for G-CRD1: Intra-Service Scope gate."""

    def test_same_service_passes(self):
        edge = _make_edge(source_gk="postgresql.cnpg.io/Backup", target_gk="postgresql.cnpg.io/Cluster")
        graph = _make_graph()
        r = gate_crd1_intra_service(edge, _make_cf(), graph)
        assert r.keep is True

    def test_cross_service_fails(self):
        edge = _make_edge(source_gk="postgresql.cnpg.io/Backup", target_gk="traefik.io/IngressRoute")
        graph = _make_graph()
        r = gate_crd1_intra_service(edge, _make_cf(), graph)
        assert r.keep is False
        assert "cross-service" in r.reason

    def test_external_target_fails(self):
        edge = _make_edge(source_gk="postgresql.cnpg.io/Backup", target_gk="/StorageClass")
        graph = _make_graph()
        r = gate_crd1_intra_service(edge, _make_cf(), graph)
        assert r.keep is False
        assert "external" in r.reason

    def test_source_node_not_found_fails(self):
        edge = _make_edge(source_gk="unknown.io/Missing", target_gk="postgresql.cnpg.io/Cluster")
        graph = _make_graph()
        r = gate_crd1_intra_service(edge, _make_cf(), graph)
        assert r.keep is False

    def test_target_node_not_found_fails(self):
        edge = _make_edge(source_gk="postgresql.cnpg.io/Backup", target_gk="unknown.io/Missing")
        graph = _make_graph()
        r = gate_crd1_intra_service(edge, _make_cf(), graph)
        assert r.keep is False

    def test_empty_service_fails(self):
        graph = _make_graph(extra_nodes={
            "test.io/EmptySvc": KindNode(kind="EmptySvc", group="test.io", service=""),
        })
        edge = _make_edge(source_gk="test.io/EmptySvc", target_gk="postgresql.cnpg.io/Cluster")
        r = gate_crd1_intra_service(edge, _make_cf(), graph)
        assert r.keep is False


# ── G-CRD2 tests ────────────────────────────────────────────


class TestGateCrd2:
    """Tests for G-CRD2: Field Type Validation gate."""

    def test_string_passes(self):
        r = gate_crd2_field_type(_make_edge(), _make_cf(field_type="string"), _make_graph())
        assert r.keep is True

    def test_array_passes(self):
        r = gate_crd2_field_type(_make_edge(), _make_cf(field_type="array"), _make_graph())
        assert r.keep is True

    def test_boolean_fails(self):
        r = gate_crd2_field_type(_make_edge(), _make_cf(field_type="boolean"), _make_graph())
        assert r.keep is False

    def test_integer_fails(self):
        r = gate_crd2_field_type(_make_edge(), _make_cf(field_type="integer"), _make_graph())
        assert r.keep is False

    def test_number_fails(self):
        r = gate_crd2_field_type(_make_edge(), _make_cf(field_type="number"), _make_graph())
        assert r.keep is False

    def test_object_fails(self):
        r = gate_crd2_field_type(_make_edge(), _make_cf(field_type="object"), _make_graph())
        assert r.keep is False

    def test_empty_type_fails(self):
        r = gate_crd2_field_type(_make_edge(), _make_cf(field_type=""), _make_graph())
        assert r.keep is False


# ── G-CRD3 tests ────────────────────────────────────────────


class TestGateCrd3:
    """Tests for G-CRD3: Ref-Shape Sibling Evidence (non-blocking)."""

    def test_always_passes(self):
        r = gate_crd3_ref_shape(_make_edge(), _make_cf(), _make_graph())
        assert r.keep is True

    def test_reason_indicates_non_blocking(self):
        r = gate_crd3_ref_shape(_make_edge(), _make_cf(), _make_graph())
        assert "non-blocking" in r.reason


# ── G-CRD4 tests ────────────────────────────────────────────


class TestGateCrd4:
    """Tests for G-CRD4: Discriminator / List-Map Key Exclusion."""

    def test_parent_kind_name_passes(self):
        r = gate_crd4_not_discriminator(_make_edge(), _make_cf(detection_source="parent_kind_name"), _make_graph())
        assert r.keep is True

    def test_enum_kind_passes(self):
        r = gate_crd4_not_discriminator(_make_edge(), _make_cf(detection_source="enum_kind"), _make_graph())
        assert r.keep is True

    def test_list_map_fails(self):
        r = gate_crd4_not_discriminator(_make_edge(), _make_cf(detection_source="kubernetes_ext_list_map"), _make_graph())
        assert r.keep is False

    def test_list_map_substring_fails(self):
        r = gate_crd4_not_discriminator(_make_edge(), _make_cf(detection_source="some_list_map_variant"), _make_graph())
        assert r.keep is False

    def test_structural_ref_passes(self):
        r = gate_crd4_not_discriminator(_make_edge(), _make_cf(detection_source="structural_ref"), _make_graph())
        assert r.keep is True


# ── G-CRD5 tests ────────────────────────────────────────────


class TestGateCrd5:
    """Tests for G-CRD5: Depth Sanity Check."""

    def test_shallow_path_passes(self):
        r = gate_crd5_depth(_make_edge(), _make_cf(field="spec.cluster.name"), _make_graph())
        assert r.keep is True
        assert "depth=2" in r.reason

    def test_medium_path_passes(self):
        r = gate_crd5_depth(_make_edge(), _make_cf(field="spec.routes.middlewares.name"), _make_graph())
        assert r.keep is True
        assert "depth=3" in r.reason

    def test_boundary_depth_passes(self):
        r = gate_crd5_depth(_make_edge(), _make_cf(field="spec.a.b.c.d"), _make_graph())
        assert r.keep is True
        assert "depth=4" in r.reason

    def test_one_over_boundary_fails(self):
        r = gate_crd5_depth(_make_edge(), _make_cf(field="spec.a.b.c.d.e"), _make_graph())
        assert r.keep is False
        assert "depth=5" in r.reason

    def test_deep_k8s_envelope_fails(self):
        deep_path = "spec.template.pod.affinity.podAffinity.preferredDuringSchedulingIgnoredDuringExecution.podAffinityTerm.namespaces"
        r = gate_crd5_depth(_make_edge(), _make_cf(field=deep_path), _make_graph())
        assert r.keep is False

    def test_non_spec_prefix_counts_all(self):
        r = gate_crd5_depth(_make_edge(), _make_cf(field="status.a.b.c.d.e"), _make_graph())
        assert r.keep is False


# ── G-CRD6 tests ────────────────────────────────────────────


class TestGateCrd6:
    """Tests for G-CRD6: Confidence Floor."""

    def test_above_floor_passes(self):
        r = gate_crd6_confidence(_make_edge(confidence=0.8), _make_cf(), _make_graph())
        assert r.keep is True

    def test_exactly_at_floor_passes(self):
        r = gate_crd6_confidence(_make_edge(confidence=0.75), _make_cf(), _make_graph())
        assert r.keep is True

    def test_below_floor_fails(self):
        r = gate_crd6_confidence(_make_edge(confidence=0.7), _make_cf(), _make_graph())
        assert r.keep is False

    def test_low_confidence_fails(self):
        r = gate_crd6_confidence(_make_edge(confidence=0.5), _make_cf(), _make_graph())
        assert r.keep is False


# ── promote_soft_edges() tests ───────────────────────────────


class TestPromoteSoftEdges:
    """Tests for promote_soft_edges() runner."""

    def _build_index(self, cf, edge):
        """Build a CF index entry matching an edge."""
        return {(edge.source_gk, edge.source_field, edge.target_gk): cf}

    def test_hard_edge_passthrough(self):
        edge = _make_edge(edge_type="hard")
        result = promote_soft_edges([edge], {}, _make_graph())
        assert len(result) == 1
        assert result[0].edge_type == "hard"
        assert result[0] is edge  # same object

    def test_soft_edge_promoted_all_gates_pass(self):
        edge = _make_edge(edge_type="soft")
        cf = _make_cf()
        idx = self._build_index(cf, edge)
        result = promote_soft_edges([edge], idx, _make_graph())
        assert len(result) == 1
        assert result[0].edge_type == "hard"

    def test_optional_edge_promoted_all_gates_pass(self):
        edge = _make_edge(edge_type="optional")
        cf = _make_cf()
        idx = self._build_index(cf, edge)
        result = promote_soft_edges([edge], idx, _make_graph())
        assert len(result) == 1
        assert result[0].edge_type == "hard"

    def test_soft_edge_kept_external_target(self):
        edge = _make_edge(edge_type="soft", target_gk="/StorageClass")
        cf = _make_cf()
        idx = self._build_index(cf, edge)
        result = promote_soft_edges([edge], idx, _make_graph())
        assert len(result) == 1
        assert result[0].edge_type == "soft"

    def test_soft_edge_kept_boolean_type(self):
        edge = _make_edge(edge_type="soft")
        cf = _make_cf(field_type="boolean")
        idx = self._build_index(cf, edge)
        result = promote_soft_edges([edge], idx, _make_graph())
        assert len(result) == 1
        assert result[0].edge_type == "soft"

    def test_soft_edge_kept_too_deep(self):
        edge = _make_edge(edge_type="soft", source_field="spec.a.b.c.d.e")
        cf = _make_cf(field="spec.a.b.c.d.e")
        idx = self._build_index(cf, edge)
        result = promote_soft_edges([edge], idx, _make_graph())
        assert len(result) == 1
        assert result[0].edge_type == "soft"

    def test_soft_edge_kept_low_confidence(self):
        edge = _make_edge(edge_type="soft", confidence=0.5)
        cf = _make_cf(confidence=0.5)
        idx = self._build_index(cf, edge)
        result = promote_soft_edges([edge], idx, _make_graph())
        assert len(result) == 1
        assert result[0].edge_type == "soft"

    def test_cf_not_found_preserves_edge(self):
        edge = _make_edge(edge_type="soft")
        result = promote_soft_edges([edge], {}, _make_graph())
        assert len(result) == 1
        assert result[0].edge_type == "soft"
        assert result[0] is edge

    def test_promoted_edge_preserves_fields(self):
        edge = _make_edge(
            edge_type="soft",
            source_gk="postgresql.cnpg.io/Backup",
            target_gk="postgresql.cnpg.io/Cluster",
            source_field="spec.cluster.name",
            detection_source="parent_kind_name",
            confidence=0.8,
        )
        cf = _make_cf()
        idx = self._build_index(cf, edge)
        result = promote_soft_edges([edge], idx, _make_graph())
        promoted = result[0]
        assert promoted.edge_type == "hard"
        assert promoted.source_gk == edge.source_gk
        assert promoted.target_gk == edge.target_gk
        assert promoted.source_field == edge.source_field
        assert promoted.detection_source == edge.detection_source
        assert promoted.confidence == edge.confidence

    def test_multiple_edges_mixed_outcomes(self):
        graph = _make_graph()
        hard_edge = _make_edge(edge_type="hard")
        soft_promotable = _make_edge(edge_type="soft")
        soft_external = _make_edge(edge_type="soft", target_gk="/StorageClass")
        cf = _make_cf()
        idx = {
            (soft_promotable.source_gk, soft_promotable.source_field, soft_promotable.target_gk): cf,
            (soft_external.source_gk, soft_external.source_field, soft_external.target_gk): cf,
        }
        result = promote_soft_edges([hard_edge, soft_promotable, soft_external], idx, graph)
        assert len(result) == 3
        assert result[0].edge_type == "hard"  # passthrough
        assert result[1].edge_type == "hard"  # promoted
        assert result[2].edge_type == "soft"  # kept (external)
