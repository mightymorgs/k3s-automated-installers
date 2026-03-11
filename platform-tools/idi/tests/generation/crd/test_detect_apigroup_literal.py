"""Tests for detect_apigroup_literal — CRD Phase 3 Section 04 (C25)."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import detect_apigroup_literal
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    """Registry with core + CRDs. cert-manager.io has multiple Kinds."""
    reg = KindRegistry()
    reg.register("Issuer", "issuers", "cert-manager.io")
    reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io")
    reg.register("Certificate", "certificates", "cert-manager.io")
    reg.register("Cluster", "clusters", "cluster.x-k8s.io")
    return reg


@pytest.fixture
def single_kind_registry() -> KindRegistry:
    """Registry where a custom group has exactly one Kind."""
    reg = KindRegistry()
    reg.register("MyResource", "myresources", "example.io")
    return reg


def _make_field(
    name: str,
    schema: dict | None = None,
    path: str | None = None,
    parent_path: str = "spec",
    required: bool = False,
) -> WalkedField:
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path, name=name, schema=schema, depth=1,
        is_array_item=False, required=required, parent_path=parent_path,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDetectApigroupLiteral:
    def test_single_kind_group_emits(self, single_kind_registry):
        """Enum with single-Kind group -> one ClassifiedField."""
        field = _make_field("apiVersion", schema={
            "type": "string",
            "enum": ["example.io/v1"],
        })
        results = detect_apigroup_literal(field, single_kind_registry)
        assert len(results) == 1
        assert results[0].target_kind == "MyResource"
        assert results[0].target_group == "example.io"
        assert results[0].confidence == 0.85
        assert results[0].detection_source == "ref_detector:apigroup_literal"
        assert results[0].fact_shape == "identity"

    def test_multi_kind_group_no_edge(self, registry):
        """Enum with multi-Kind group -> empty list."""
        field = _make_field("apiGroup", schema={
            "type": "string",
            "enum": ["cert-manager.io/v1"],
        })
        results = detect_apigroup_literal(field, registry)
        assert results == []

    def test_core_group_v1_multi_kind(self, registry):
        """Core API group (v1) has many Kinds -> empty."""
        field = _make_field("apiVersion", schema={
            "type": "string",
            "enum": ["v1"],
        })
        results = detect_apigroup_literal(field, registry)
        assert results == []

    def test_core_group_v1_single_kind(self):
        """Test registry with single core Kind -> emits."""
        reg = KindRegistry.__new__(KindRegistry)
        reg._kind_to_entries = {}
        reg._plural_to_entries = {}
        reg._sorted_entries = []
        # Manually register only one core kind
        reg.register("Pod", "pods", "")
        field = _make_field("apiVersion", schema={
            "type": "string",
            "enum": ["v1"],
        })
        results = detect_apigroup_literal(field, reg)
        assert len(results) == 1
        assert results[0].target_kind == "Pod"

    def test_v1alpha1_recognized(self, registry):
        """v1alpha1 -> recognized as core group."""
        field = _make_field("apiVersion", schema={
            "type": "string",
            "enum": ["v1alpha1"],
        })
        # Core group has many kinds -> empty
        results = detect_apigroup_literal(field, registry)
        assert results == []

    def test_v2beta1_recognized(self, single_kind_registry):
        """example.io/v2beta1 -> correct group extraction."""
        field = _make_field("apiVersion", schema={
            "type": "string",
            "enum": ["example.io/v2beta1"],
        })
        results = detect_apigroup_literal(field, single_kind_registry)
        assert len(results) == 1
        assert results[0].target_kind == "MyResource"

    def test_not_a_version_string(self, single_kind_registry):
        """Enum value that's not an apiVersion -> no match."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["not-a-version-string"],
        })
        results = detect_apigroup_literal(field, single_kind_registry)
        assert results == []

    def test_multiple_enum_values(self, registry):
        """Multiple enum values processed independently."""
        # cluster.x-k8s.io has only Cluster (single-Kind), cert-manager.io has multiple
        field = _make_field("apiVersion", schema={
            "type": "string",
            "enum": ["cert-manager.io/v1", "cluster.x-k8s.io/v1beta1"],
        })
        results = detect_apigroup_literal(field, registry)
        # cert-manager.io -> multi-Kind, skipped; cluster.x-k8s.io -> single Kind
        assert len(results) == 1
        assert results[0].target_kind == "Cluster"

    def test_no_enum_empty(self, registry):
        """Field with no enum -> empty."""
        field = _make_field("apiVersion", schema={"type": "string"})
        results = detect_apigroup_literal(field, registry)
        assert results == []

    def test_group_not_in_registry(self, registry):
        """Group not in registry -> empty."""
        field = _make_field("apiVersion", schema={
            "type": "string",
            "enum": ["unknown.io/v1"],
        })
        results = detect_apigroup_literal(field, registry)
        assert results == []

    def test_integer_enum_value_skipped(self, registry):
        """Non-string enum value -> skipped gracefully."""
        field = _make_field("apiVersion", schema={
            "type": "string",
            "enum": [42, "cluster.x-k8s.io/v1"],
        })
        results = detect_apigroup_literal(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Cluster"

    def test_empty_enum_list(self, registry):
        """Empty enum list -> empty."""
        field = _make_field("apiVersion", schema={
            "type": "string",
            "enum": [],
        })
        results = detect_apigroup_literal(field, registry)
        assert results == []
