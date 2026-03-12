"""Tests for detect_kubernetes_extensions (C32) in ref_detector.py."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import detect_kubernetes_extensions
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    return KindRegistry()


def _make_field(
    name: str,
    schema: dict | None = None,
    path: str | None = None,
    parent_path: str = "spec",
) -> WalkedField:
    if schema is None:
        schema = {"type": "object"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path,
        name=name,
        schema=schema,
        depth=1,
        is_array_item=False,
        required=False,
        parent_path=parent_path,
    )


# ---------------------------------------------------------------------------
# Tests: x-kubernetes-embedded-resource
# ---------------------------------------------------------------------------


class TestEmbeddedResource:
    def test_embedded_resource_true_no_kind(self, registry):
        """x-kubernetes-embedded-resource: true without Kind -> config_field at 0.95."""
        field = _make_field("rawResource", schema={
            "type": "object",
            "x-kubernetes-embedded-resource": True,
            "x-kubernetes-preserve-unknown-fields": True,
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is not None
        assert result.role == "config_field"
        assert result.confidence == 0.95
        assert result.detection_source == "ref_detector:kubernetes_ext_embedded"

    def test_embedded_resource_with_multi_kind_enum(self, registry):
        """Embedded resource with kind enum ["ConfigMap", "Secret"] -> config_field (passthrough)."""
        field = _make_field("rawResource", schema={
            "type": "object",
            "x-kubernetes-embedded-resource": True,
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["ConfigMap", "Secret"],
                },
            },
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is not None
        assert result.target_kind is None
        assert result.role == "config_field"

    def test_embedded_resource_with_single_kind_enum(self, registry):
        """Embedded resource with kind enum ["Secret"] -> input_ref with target_kind=Secret."""
        field = _make_field("rawResource", schema={
            "type": "object",
            "x-kubernetes-embedded-resource": True,
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["Secret"],
                },
            },
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is not None
        assert result.target_kind == "Secret"
        assert result.role == "input_ref"

    def test_embedded_resource_no_kind_property(self, registry):
        """Embedded resource without kind property -> config_field at 0.95 (passthrough)."""
        field = _make_field("rawResource", schema={
            "type": "object",
            "x-kubernetes-embedded-resource": True,
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is not None
        assert result.role == "config_field"
        assert result.confidence == 0.95

    def test_embedded_resource_with_preserve_unknown(self, registry):
        """Extensions can coexist; embedded resource still triggers."""
        field = _make_field("rawResource", schema={
            "type": "object",
            "x-kubernetes-embedded-resource": True,
            "x-kubernetes-preserve-unknown-fields": True,
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is not None
        assert result.role == "config_field"

    def test_embedded_resource_false(self, registry):
        """x-kubernetes-embedded-resource: false -> None."""
        field = _make_field("field", schema={
            "type": "object",
            "x-kubernetes-embedded-resource": False,
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is None

    def test_embedded_resource_sets_manifest_flags(self):
        """Embedded resource without target Kind sets ManifestFlags via orchestrator."""
        from idi.generation.crd.ref_detector import ManifestFlags, classify_walked_field
        registry = KindRegistry()
        flags = ManifestFlags()
        field = _make_field("rawResource", schema={
            "type": "object",
            "x-kubernetes-embedded-resource": True,
        })
        results = classify_walked_field(
            field, registry, "TestKind", "test.io",
            manifest_flags=flags,
        )
        assert flags.accepts_arbitrary_resources is True
        assert len(results) == 1
        assert results[0].role == "config_field"


# ---------------------------------------------------------------------------
# Tests: x-kubernetes-list-type: map
# ---------------------------------------------------------------------------


class TestListMap:
    def test_list_map_with_service_shape(self, registry):
        """List-map with [name] keys + ServiceSpec-like items -> output_declaration."""
        field = _make_field("services", schema={
            "type": "array",
            "x-kubernetes-list-type": "map",
            "x-kubernetes-list-map-keys": ["name"],
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "ports": {"type": "array"},
                    "selector": {"type": "object"},
                    "type": {"type": "string"},
                },
            },
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is not None
        assert result.role == "output_declaration"
        assert result.target_kind == "Service"
        assert result.confidence == 0.8
        assert result.detection_source == "ref_detector:kubernetes_ext_list_map"

    def test_list_map_no_workload_shape(self, registry):
        """List-map with [name] keys but items don't match shapes -> None."""
        field = _make_field("configs", schema={
            "type": "array",
            "x-kubernetes-list-type": "map",
            "x-kubernetes-list-map-keys": ["name"],
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                },
            },
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is None

    def test_list_map_port_keys(self, registry):
        """List-map with keys=["port"] (not ["name"]) -> None."""
        field = _make_field("ports", schema={
            "type": "array",
            "x-kubernetes-list-type": "map",
            "x-kubernetes-list-map-keys": ["port"],
            "items": {
                "type": "object",
                "properties": {
                    "port": {"type": "integer"},
                    "protocol": {"type": "string"},
                },
            },
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is None

    def test_list_type_set(self, registry):
        """x-kubernetes-list-type: "set" -> None."""
        field = _make_field("items", schema={
            "type": "array",
            "x-kubernetes-list-type": "set",
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is None

    def test_list_map_job_spec_items(self, registry):
        """List-map items matching JobSpec -> target_kind=Job."""
        field = _make_field("jobs", schema={
            "type": "array",
            "x-kubernetes-list-type": "map",
            "x-kubernetes-list-map-keys": ["name"],
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "template": {"type": "object"},
                    "backoffLimit": {"type": "integer"},
                    "completions": {"type": "integer"},
                },
            },
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is not None
        assert result.target_kind == "Job"

    def test_list_map_service_spec_items(self, registry):
        """List-map items matching ServiceSpec -> target_kind=Service."""
        field = _make_field("services", schema={
            "type": "array",
            "x-kubernetes-list-type": "map",
            "x-kubernetes-list-map-keys": ["name"],
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "ports": {"type": "array"},
                    "selector": {"type": "object"},
                    "type": {"type": "string"},
                },
            },
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is not None
        assert result.target_kind == "Service"


# ---------------------------------------------------------------------------
# Tests: x-kubernetes-int-or-string
# ---------------------------------------------------------------------------


class TestIntOrString:
    def test_int_or_string_only(self, registry):
        """x-kubernetes-int-or-string: true -> None."""
        field = _make_field("port", schema={
            "x-kubernetes-int-or-string": True,
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: no extensions
# ---------------------------------------------------------------------------


class TestNoExtensions:
    def test_no_extensions(self, registry):
        """Field without any x-kubernetes extensions -> None."""
        field = _make_field("config", schema={
            "type": "string",
        })
        result = detect_kubernetes_extensions(field, registry)
        assert result is None
