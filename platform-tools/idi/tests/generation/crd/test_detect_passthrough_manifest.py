"""Tests for detect_passthrough_manifest — CRD Phase 3 Section 05 (C26)."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import ManifestFlags, detect_passthrough_manifest
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    reg = KindRegistry()
    reg.register("Issuer", "issuers", "cert-manager.io")
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


class TestDetectPassthroughManifest:
    def test_preserve_unknown_fields_no_enum(self, registry):
        """Object with preserve-unknown-fields + required apiVersion/kind, no kind enum.

        -> empty ClassifiedField list, ManifestFlags.accepts_arbitrary_resources=True
        """
        flags = ManifestFlags()
        field = _make_field("resources", schema={
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
            "required": ["apiVersion", "kind"],
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {"type": "string"},
                "metadata": {"type": "object"},
            },
        })
        results = detect_passthrough_manifest(field, registry, flags)
        assert results == []
        assert flags.accepts_arbitrary_resources is True
        assert flags.passthrough_detection_source == "ref_detector:passthrough_manifest"
        assert flags.passthrough_field_path == "spec.resources"

    def test_embedded_resource_marker(self, registry):
        """x-kubernetes-embedded-resource=true -> same behavior as preserve-unknown-fields."""
        flags = ManifestFlags()
        field = _make_field("template", schema={
            "type": "object",
            "x-kubernetes-embedded-resource": True,
            "required": ["apiVersion", "kind"],
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {"type": "string"},
            },
        })
        results = detect_passthrough_manifest(field, registry, flags)
        assert results == []
        assert flags.accepts_arbitrary_resources is True

    def test_constrained_kind_enum(self, registry):
        """Preserve-unknown-fields + kind enum -> flag + edges."""
        flags = ManifestFlags()
        field = _make_field("resources", schema={
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
            "required": ["apiVersion", "kind"],
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {"type": "string", "enum": ["Deployment", "Service"]},
                "metadata": {"type": "object"},
            },
        })
        results = detect_passthrough_manifest(field, registry, flags)
        assert flags.accepts_arbitrary_resources is True
        # Deployment and Service are in the core registry
        assert len(results) == 2
        kinds = {r.target_kind for r in results}
        assert kinds == {"Deployment", "Service"}
        assert all(r.confidence == 0.95 for r in results)
        assert all(r.detection_source == "ref_detector:passthrough_manifest" for r in results)

    def test_no_marker_returns_empty(self, registry):
        """Object without preserve-unknown-fields or embedded-resource -> empty, no flag."""
        flags = ManifestFlags()
        field = _make_field("config", schema={
            "type": "object",
            "required": ["apiVersion", "kind"],
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {"type": "string"},
            },
        })
        results = detect_passthrough_manifest(field, registry, flags)
        assert results == []
        assert flags.accepts_arbitrary_resources is False

    def test_preserve_unknown_without_av_kind(self, registry):
        """Preserve-unknown-fields but missing apiVersion/kind properties -> empty."""
        flags = ManifestFlags()
        field = _make_field("data", schema={
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
            "properties": {
                "config": {"type": "string"},
            },
        })
        results = detect_passthrough_manifest(field, registry, flags)
        assert results == []
        assert flags.accepts_arbitrary_resources is False

    def test_kind_enum_unknown_skipped(self, registry):
        """Kind enum value not in registry -> not in results."""
        flags = ManifestFlags()
        field = _make_field("resources", schema={
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
            "required": ["apiVersion", "kind"],
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {"type": "string", "enum": ["NotAKind"]},
            },
        })
        results = detect_passthrough_manifest(field, registry, flags)
        assert results == []
        assert flags.accepts_arbitrary_resources is True  # Flag still set

    def test_manifest_flags_none_no_crash(self, registry):
        """manifest_flags=None -> function returns correct results, no crash."""
        field = _make_field("resources", schema={
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
            "required": ["apiVersion", "kind"],
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {"type": "string", "enum": ["Deployment"]},
            },
        })
        results = detect_passthrough_manifest(field, registry, manifest_flags=None)
        assert len(results) == 1
        assert results[0].target_kind == "Deployment"

    def test_passthrough_field_path_recorded(self, registry):
        """passthrough_field_path records the triggering field path."""
        flags = ManifestFlags()
        field = _make_field("spec.template.resources", schema={
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
            "required": ["apiVersion", "kind"],
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {"type": "string"},
            },
        }, path="spec.template.resources")
        detect_passthrough_manifest(field, registry, flags)
        assert flags.passthrough_field_path == "spec.template.resources"

    def test_both_markers_single_mutation(self, registry):
        """Both markers present -> still single flag mutation."""
        flags = ManifestFlags()
        field = _make_field("resources", schema={
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
            "x-kubernetes-embedded-resource": True,
            "required": ["apiVersion", "kind"],
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {"type": "string"},
            },
        })
        detect_passthrough_manifest(field, registry, flags)
        assert flags.accepts_arbitrary_resources is True

    def test_apiversion_kind_in_required_but_not_properties(self, registry):
        """apiVersion/kind in required array but not in properties -> still detects."""
        flags = ManifestFlags()
        field = _make_field("resources", schema={
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
            "required": ["apiVersion", "kind"],
        })
        detect_passthrough_manifest(field, registry, flags)
        assert flags.accepts_arbitrary_resources is True
