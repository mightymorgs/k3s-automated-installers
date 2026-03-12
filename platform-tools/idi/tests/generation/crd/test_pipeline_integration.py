"""Tests for Phase 5A pipeline integration — merge policy, ordering, superset."""
from __future__ import annotations

from typing import Any

import pytest

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import (
    _merge_additive_results,
    classify_walked_field,
    K8S_NAME_PATTERNS,
    ManifestFlags,
)
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
    reg.register("Certificate", "certificates", "cert-manager.io")
    reg.register("ExternalSecret", "externalsecrets", "external-secrets.io")
    return reg


def _make_field(
    name: str,
    schema: dict | None = None,
    path: str | None = None,
    parent_path: str = "spec",
    depth: int = 1,
    required: bool = False,
) -> WalkedField:
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path,
        name=name,
        schema=schema,
        depth=depth,
        is_array_item=False,
        required=required,
        parent_path=parent_path,
    )


# ---------------------------------------------------------------------------
# Tests: _merge_additive_results
# ---------------------------------------------------------------------------


class TestMergeAdditiveResults:
    def test_same_key_higher_confidence_wins(self):
        """Two entries with same (field, role, target_kind): higher confidence wins."""
        c1 = ClassifiedField(
            field="spec.ref", role="input_ref", confidence=0.75,
            field_type="string", target_kind="Secret",
            detection_source="ref_detector:constraint_fk",
        )
        c2 = ClassifiedField(
            field="spec.ref", role="input_ref", confidence=0.85,
            field_type="string", target_kind="Secret",
            detection_source="ref_detector:cataloged_shape",
        )
        merged = _merge_additive_results([c1, c2])
        assert len(merged) == 1
        assert merged[0].confidence == 0.85

    def test_same_key_equal_confidence_earlier_wins(self):
        """Equal confidence: earlier pipeline step (lower index) wins."""
        c1 = ClassifiedField(
            field="spec.ref", role="input_ref", confidence=0.8,
            field_type="string", target_kind="Pod",
            detection_source="ref_detector:embedded_workload",
        )
        c2 = ClassifiedField(
            field="spec.ref", role="input_ref", confidence=0.8,
            field_type="string", target_kind="Pod",
            detection_source="ref_detector:cataloged_shape",
        )
        merged = _merge_additive_results([c1, c2])
        assert len(merged) == 1
        assert merged[0].detection_source == "ref_detector:embedded_workload"

    def test_different_roles_both_kept(self):
        """Different roles -> both kept."""
        c1 = ClassifiedField(
            field="spec.template", role="input_ref", confidence=0.75,
            field_type="object", target_kind="Secret",
            detection_source="ref_detector:constraint_fk",
        )
        c2 = ClassifiedField(
            field="spec.template", role="output_declaration", confidence=0.8,
            field_type="object", target_kind="Pod",
            detection_source="ref_detector:embedded_workload",
        )
        merged = _merge_additive_results([c1, c2])
        assert len(merged) == 2

    def test_same_role_different_target_kind(self):
        """Same role but different target_kind -> both kept."""
        c1 = ClassifiedField(
            field="spec.ref", role="input_ref", confidence=0.8,
            field_type="string", target_kind="Secret",
            detection_source="ref_detector:cataloged_shape",
        )
        c2 = ClassifiedField(
            field="spec.ref", role="input_ref", confidence=0.8,
            field_type="string", target_kind="ConfigMap",
            detection_source="ref_detector:cataloged_shape",
        )
        merged = _merge_additive_results([c1, c2])
        assert len(merged) == 2

    def test_empty_list(self):
        assert _merge_additive_results([]) == []

    def test_single_entry(self):
        c = ClassifiedField(
            field="spec.x", role="input_ref", confidence=0.8,
            field_type="string", target_kind="Secret",
        )
        merged = _merge_additive_results([c])
        assert len(merged) == 1
        assert merged[0] is c


# ---------------------------------------------------------------------------
# Tests: Pipeline ordering
# ---------------------------------------------------------------------------


class TestPipelineOrdering:
    def test_embedded_resource_exclusive_return(self, registry):
        """x-kubernetes-embedded-resource: true without target Kind -> config_field at 0.95."""
        field = _make_field("rawResource", schema={
            "type": "object",
            "x-kubernetes-embedded-resource": True,
        })
        results = classify_walked_field(field, registry, "MyApp", "example.com")
        assert len(results) == 1
        assert results[0].role == "config_field"
        assert results[0].confidence == 0.95
        assert results[0].detection_source == "ref_detector:kubernetes_ext_embedded"

    def test_detect_ref_exclusive(self, registry):
        """detect_ref match -> exclusive return, no Phase 5A detectors called."""
        field = _make_field("secretRef", schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        })
        results = classify_walked_field(field, registry, "MyApp", "example.com")
        assert len(results) == 1
        assert results[0].detection_source == "ref_detector:kind_registry"

    def test_detect_ref_tuple_exclusive(self, registry):
        """detect_ref_tuple match -> exclusive return."""
        field = _make_field("targetRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["Secret"],
                },
            },
            "required": ["name"],
        })
        results = classify_walked_field(field, registry, "MyApp", "example.com")
        assert len(results) >= 1
        assert results[0].detection_source == "ref_detector:ref_tuple"

    def test_constraint_fk_additive(self, registry):
        """Constraint FK is additive — does not prevent other detectors."""
        field = _make_field("server", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        sibling_fields = {
            "server": {"type": "string"},
            "namespace": {"type": "string"},
        }
        results = classify_walked_field(
            field, registry, "MyApp", "example.com",
            sibling_fields=sibling_fields,
        )
        # Should get constraint_fk result (additive).
        sources = {r.detection_source for r in results}
        assert "ref_detector:constraint_fk" in sources or any(
            "constraint_fk" in r.detection_source for r in results
        )

    def test_embedded_workload_additive(self, registry):
        """Embedded workload detection runs as additive step."""
        schema = {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {
                        "containers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "image": {"type": "string"},
                                    "name": {"type": "string"},
                                },
                            },
                        },
                        "volumes": {"type": "array"},
                    },
                },
            },
        }
        field = _make_field("template", schema=schema)
        results = classify_walked_field(field, registry, "MyApp", "example.com")
        # Should contain embedded_workload detection.
        sources = {r.detection_source for r in results}
        has_workload = any("embedded_workload" in s for s in sources)
        assert has_workload

    def test_list_map_additive_does_not_block(self, registry):
        """List-map (0.8, additive) does not prevent other detectors."""
        schema = {
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
        }
        field = _make_field("services", schema=schema)
        results = classify_walked_field(field, registry, "MyApp", "example.com")
        sources = {r.detection_source for r in results}
        # Should have kubernetes_ext_list_map.
        assert any("kubernetes_ext_list_map" in s for s in sources)


# ---------------------------------------------------------------------------
# Tests: Behavioral superset (Phase 1-4 preserved)
# ---------------------------------------------------------------------------


class TestBehavioralSuperset:
    def test_phase2_ref_still_works(self, registry):
        """Phase 2 detect_ref is still functional."""
        field = _make_field("issuerRef", schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        })
        results = classify_walked_field(field, registry, "Certificate", "cert-manager.io")
        assert len(results) >= 1
        assert results[0].target_kind == "Issuer"

    def test_phase3_passthrough_still_works(self, registry):
        """Phase 3 passthrough detection is still functional."""
        field = _make_field("resource", schema={
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
            "x-kubernetes-embedded-resource": True,
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["Secret"],
                },
                "metadata": {"type": "object"},
            },
            "required": ["apiVersion", "kind"],
        })
        flags = ManifestFlags()
        results = classify_walked_field(
            field, registry, "MyApp", "example.com",
            manifest_flags=flags,
        )
        # Should fire the x-kubernetes-embedded-resource exclusive path.
        # With single Kind enum, it emits input_ref; with multi-kind, config_field.
        assert len(results) >= 1
        assert any(
            r.detection_source == "ref_detector:kubernetes_ext_embedded"
            for r in results
        )

    def test_config_field_default(self, registry):
        """Unrecognized field -> config_field as default."""
        field = _make_field("debugLevel", schema={"type": "integer"})
        results = classify_walked_field(field, registry, "MyApp", "example.com")
        assert len(results) == 1
        assert results[0].role == "config_field"
        assert results[0].detection_source == "default:config_field"
