"""Tests for detect_ref_tuple — CRD Phase 3 Section 02 (C19)."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import detect_ref_tuple, _parse_api_version
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    """KindRegistry with core resources + some CRDs."""
    reg = KindRegistry()
    reg.register("Issuer", "issuers", "cert-manager.io")
    reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io")
    reg.register("SecretStore", "secretstores", "external-secrets.io")
    reg.register("Cluster", "clusters", "cluster.x-k8s.io")
    reg.register("Certificate", "certificates", "cert-manager.io")
    return reg


def _make_field(
    name: str,
    schema: dict | None = None,
    path: str | None = None,
    depth: int = 1,
    is_array_item: bool = False,
    required: bool = False,
    parent_path: str = "spec",
) -> WalkedField:
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path, name=name, schema=schema, depth=depth,
        is_array_item=is_array_item, required=required, parent_path=parent_path,
    )


# ---------------------------------------------------------------------------
# _parse_api_version
# ---------------------------------------------------------------------------


class TestParseApiVersion:
    def test_apps_v1(self):
        assert _parse_api_version("apps/v1") == ("apps", "v1")

    def test_cert_manager(self):
        assert _parse_api_version("cert-manager.io/v1") == ("cert-manager.io", "v1")

    def test_alpha_version(self):
        assert _parse_api_version("cert-manager.io/v1alpha2") == ("cert-manager.io", "v1alpha2")

    def test_bare_v1(self):
        assert _parse_api_version("v1") == ("", "v1")

    def test_bare_v1alpha1(self):
        assert _parse_api_version("v1alpha1") == ("", "v1alpha1")

    def test_bare_v2beta1(self):
        assert _parse_api_version("v2beta1") == ("", "v2beta1")

    def test_not_a_version(self):
        assert _parse_api_version("not-a-version") is None

    def test_empty_string(self):
        assert _parse_api_version("") is None

    def test_slash_only(self):
        assert _parse_api_version("/") is None

    def test_no_version_after_slash(self):
        assert _parse_api_version("apps/") is None

    def test_no_group_before_slash(self):
        assert _parse_api_version("/v1") is None


# ---------------------------------------------------------------------------
# detect_ref_tuple
# ---------------------------------------------------------------------------


class TestDetectRefTuple:
    def test_basic_ref_tuple_with_kind_enum(self, registry):
        """Object with {name (required), namespace, kind enum=["Cluster"]}."""
        field = _make_field("targetCluster", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "kind": {"type": "string", "enum": ["Cluster"]},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Cluster"
        assert results[0].role == "input_ref"
        assert results[0].confidence == 0.85
        assert results[0].fact_shape == "identity"
        assert results[0].detection_source == "ref_detector:ref_tuple"
        assert results[0].cross_namespace is True

    def test_multiple_kind_enum(self, registry):
        """Object with kind enum=["Issuer", "ClusterIssuer"] -> two results."""
        field = _make_field("issuerRef", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "kind": {"type": "string", "enum": ["Issuer", "ClusterIssuer"]},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert len(results) == 2
        kinds = {r.target_kind for r in results}
        assert kinds == {"Issuer", "ClusterIssuer"}

    def test_no_kind_no_apigroup_empty(self, registry):
        """Object with {name, namespace} but no kind/apiGroup -> empty."""
        field = _make_field("target", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert results == []

    def test_apigroup_single_kind_resolves(self, registry):
        """Object with apiGroup enum for single-Kind group -> resolved."""
        # cluster.x-k8s.io has only Cluster registered
        field = _make_field("sourceRef", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "apiGroup": {"type": "string", "enum": ["cluster.x-k8s.io"]},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Cluster"

    def test_apigroup_multi_kind_empty(self, registry):
        """Object with apiGroup for multi-Kind group -> empty."""
        # cert-manager.io has Issuer, ClusterIssuer, Certificate
        field = _make_field("sourceRef", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "apiGroup": {"type": "string", "enum": ["cert-manager.io"]},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert results == []

    def test_name_not_required_lower_confidence(self, registry):
        """Object with name not in required -> confidence 0.75."""
        field = _make_field("target", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "kind": {"type": "string", "enum": ["Cluster"]},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert len(results) == 1
        assert results[0].confidence == 0.75

    def test_name_only_no_indicators_empty(self, registry):
        """Object with {name} only, no namespace/kind/apiGroup -> empty."""
        field = _make_field("config", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert results == []

    def test_non_object_field_empty(self, registry):
        """Non-object field (type: string) -> empty."""
        field = _make_field("target", schema={"type": "string"})
        results = detect_ref_tuple(field, registry)
        assert results == []

    def test_object_without_name_empty(self, registry):
        """Object without name property -> empty."""
        field = _make_field("target", schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["Cluster"]},
                "namespace": {"type": "string"},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert results == []

    def test_array_item_preserves_flag(self, registry):
        """Array item with ref tuple shape -> match."""
        field = _make_field("targets", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "kind": {"type": "string", "enum": ["Cluster"]},
            },
        }, is_array_item=True)
        results = detect_ref_tuple(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Cluster"

    def test_cross_namespace_true_with_namespace(self, registry):
        """Object with namespace -> cross_namespace=True."""
        field = _make_field("target", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "kind": {"type": "string", "enum": ["Cluster"]},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert results[0].cross_namespace is True

    def test_cross_namespace_false_without_namespace(self, registry):
        """Object without namespace -> cross_namespace=False."""
        field = _make_field("target", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": ["Cluster"]},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert results[0].cross_namespace is False

    def test_apiversion_enum_resolves(self, registry):
        """Object with apiVersion enum for single-Kind group -> resolved."""
        field = _make_field("sourceRef", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "apiVersion": {"type": "string", "enum": ["cluster.x-k8s.io/v1beta1"]},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Cluster"

    def test_kind_enum_unknown_not_included(self, registry):
        """Kind enum value not in registry -> not included in results."""
        field = _make_field("target", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": ["Cluster", "NotAKind"]},
                "namespace": {"type": "string"},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Cluster"

    def test_kind_enum_all_unknown_empty(self, registry):
        """All kind enum values unknown -> empty."""
        field = _make_field("target", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": ["FooBar", "BazQux"]},
                "namespace": {"type": "string"},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert results == []

    def test_object_no_properties_empty(self, registry):
        """Object without properties dict -> empty."""
        field = _make_field("target", schema={"type": "object"})
        results = detect_ref_tuple(field, registry)
        assert results == []

    def test_name_not_string_empty(self, registry):
        """Object where name property is not string -> empty."""
        field = _make_field("target", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "integer"},
                "kind": {"type": "string", "enum": ["Cluster"]},
                "namespace": {"type": "string"},
            },
        })
        results = detect_ref_tuple(field, registry)
        assert results == []
