"""Tests for detect_example_kinds and _scan_for_kind_values — CRD Phase 3 Section 03 (C24)."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import detect_example_kinds, _scan_for_kind_values
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    reg = KindRegistry()
    reg.register("Issuer", "issuers", "cert-manager.io")
    reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io")
    reg.register("SecretStore", "secretstores", "external-secrets.io")
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
# _scan_for_kind_values
# ---------------------------------------------------------------------------


class TestScanForKindValues:
    def test_dict_with_kind_key(self):
        assert _scan_for_kind_values({"kind": "Issuer"}) == ["Issuer"]

    def test_nested_kind(self):
        assert _scan_for_kind_values({"template": {"kind": "Deployment"}}) == ["Deployment"]

    def test_depth_exceeded(self):
        """Nesting beyond max_depth=3 stops scanning."""
        val = {"a": {"b": {"c": {"d": {"kind": "Deep"}}}}}
        assert _scan_for_kind_values(val) == []

    def test_list_of_dicts(self):
        val = [{"kind": "A"}, {"kind": "B"}]
        result = _scan_for_kind_values(val)
        assert sorted(result) == ["A", "B"]

    def test_string_value(self):
        assert _scan_for_kind_values("just a string") == []

    def test_none(self):
        assert _scan_for_kind_values(None) == []

    def test_integer(self):
        assert _scan_for_kind_values(42) == []

    def test_kind_value_not_string(self):
        """kind key with integer value -> not included."""
        assert _scan_for_kind_values({"kind": 42}) == []

    def test_max_visited_limit(self):
        """Large structure stops at visit limit."""
        val = {f"key{i}": {"kind": f"Kind{i}"} for i in range(100)}
        result = _scan_for_kind_values(val, max_visited=10)
        assert len(result) <= 10

    def test_empty_dict(self):
        assert _scan_for_kind_values({}) == []

    def test_empty_list(self):
        assert _scan_for_kind_values([]) == []


# ---------------------------------------------------------------------------
# detect_example_kinds
# ---------------------------------------------------------------------------


class TestDetectExampleKinds:
    def test_example_with_kind_key(self, registry):
        """Field with example={kind: "ClusterIssuer"} -> match."""
        field = _make_field("backupTarget", schema={
            "type": "object",
            "example": {"kind": "ClusterIssuer", "name": "my-issuer"},
        })
        results = detect_example_kinds(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "ClusterIssuer"
        assert results[0].confidence == 0.8
        assert results[0].detection_source == "ref_detector:example_kind"
        assert results[0].fact_shape == "identity"
        assert results[0].role == "input_ref"

    def test_default_with_kind_key(self, registry):
        """Field with default={kind: "Issuer"} -> match."""
        field = _make_field("ref", schema={
            "type": "object",
            "default": {"kind": "Issuer"},
        })
        results = detect_example_kinds(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Issuer"

    def test_string_example_matching_kind(self, registry):
        """Field with example="SecretStore" -> match."""
        field = _make_field("kind", schema={
            "type": "string",
            "example": "SecretStore",
        })
        results = detect_example_kinds(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "SecretStore"

    def test_example_kind_not_in_registry(self, registry):
        """Field with example={kind: "NotAKind"} -> empty."""
        field = _make_field("ref", schema={
            "type": "object",
            "example": {"kind": "NotAKind"},
        })
        results = detect_example_kinds(field, registry)
        assert results == []

    def test_no_example_or_default(self, registry):
        """Field with no example/default -> empty."""
        field = _make_field("foo", schema={"type": "string"})
        results = detect_example_kinds(field, registry)
        assert results == []

    def test_x_kubernetes_examples_list(self, registry):
        """x-kubernetes-examples as list of dicts with kind."""
        field = _make_field("ref", schema={
            "type": "object",
            "x-kubernetes-examples": [
                {"kind": "Issuer", "name": "my-issuer"},
                {"something": "else"},
            ],
        })
        results = detect_example_kinds(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Issuer"

    def test_nested_example(self, registry):
        """Example with nested kind at depth 2."""
        field = _make_field("template", schema={
            "type": "object",
            "example": {"template": {"kind": "Issuer"}},
        })
        results = detect_example_kinds(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Issuer"

    def test_deeply_nested_stops(self, registry):
        """Example nested beyond max depth -> not found."""
        field = _make_field("deep", schema={
            "type": "object",
            "example": {"a": {"b": {"c": {"d": {"kind": "Issuer"}}}}},
        })
        results = detect_example_kinds(field, registry)
        assert results == []

    def test_status_block_role(self, registry):
        """Field in status block -> role=output_declaration."""
        field = _make_field("ref", schema={
            "type": "object",
            "example": {"kind": "Issuer"},
        }, parent_path="status")
        results = detect_example_kinds(field, registry)
        assert len(results) == 1
        assert results[0].role == "output_declaration"

    def test_spec_block_role(self, registry):
        """Field in spec block -> role=input_ref."""
        field = _make_field("ref", schema={
            "type": "object",
            "example": {"kind": "Issuer"},
        }, parent_path="spec")
        results = detect_example_kinds(field, registry)
        assert len(results) == 1
        assert results[0].role == "input_ref"

    def test_multiple_kinds_in_different_fields(self, registry):
        """Multiple Kind names in example and default."""
        field = _make_field("ref", schema={
            "type": "object",
            "example": {"kind": "Issuer"},
            "default": {"kind": "ClusterIssuer"},
        })
        results = detect_example_kinds(field, registry)
        assert len(results) == 2
        kinds = {r.target_kind for r in results}
        assert kinds == {"Issuer", "ClusterIssuer"}

    def test_kind_value_integer_ignored(self, registry):
        """Example with kind value as integer -> ignored."""
        field = _make_field("ref", schema={
            "type": "object",
            "example": {"kind": 42},
        })
        results = detect_example_kinds(field, registry)
        assert results == []

    def test_x_kubernetes_examples_empty_list(self, registry):
        """x-kubernetes-examples with empty list -> empty."""
        field = _make_field("ref", schema={
            "type": "object",
            "x-kubernetes-examples": [],
        })
        results = detect_example_kinds(field, registry)
        assert results == []

    def test_large_example_no_crash(self, registry):
        """Example with many nodes -> scanning stops at limit (no crash)."""
        big_val = {f"key{i}": {"nested": {"kind": f"Kind{i}"}} for i in range(100)}
        field = _make_field("big", schema={
            "type": "object",
            "example": big_val,
        })
        # Should not crash.
        results = detect_example_kinds(field, registry)
        # Most of these Kinds won't be in registry, so result may be empty.
        assert isinstance(results, list)

    def test_same_kind_deduplicated(self, registry):
        """Same Kind in both example and default -> one result."""
        field = _make_field("ref", schema={
            "type": "object",
            "example": {"kind": "Issuer"},
            "default": {"kind": "Issuer"},
        })
        results = detect_example_kinds(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Issuer"
