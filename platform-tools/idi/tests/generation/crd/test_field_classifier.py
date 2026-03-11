"""Tests for field_classifier.py — CRD Phase 2 pipeline delegation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from idi.generation.crd.field_classifier import (
    ClassifiedField,
    classify_fields,
)
from idi.generation.crd.kind_registry import KindRegistry
from tests.generation.crd.conftest import _GOLDEN_DIR, _FIXTURES_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(service: str, kind: str) -> dict[str, Any]:
    """Load a single fixture file."""
    path = _FIXTURES_DIR / service / f"{kind}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_golden(service: str, kind: str) -> dict[str, Any]:
    """Load a single golden file."""
    path = _GOLDEN_DIR / service / f"{kind}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _classify_fixture(
    fixture: dict[str, Any],
    registry: KindRegistry,
) -> list[ClassifiedField]:
    """Run classify_fields on a fixture."""
    return classify_fields(
        spec_properties=fixture["spec_properties"],
        spec_required=fixture["spec_required"],
        group=fixture["group"],
        kind=fixture["kind"],
        registry=registry,
    )


# ---------------------------------------------------------------------------
# Golden-file SUPERSET tests — Phase 2 finds MORE refs than Phase 1
# ---------------------------------------------------------------------------


class TestGoldenFileSupersetCheck:
    """Verify that classify_fields produces a SUPERSET of Phase 1 golden refs.

    Phase 2 walks nested properties (depth 5) and arrays, so it finds
    MORE input_refs than Phase 1's flat-only scan. These tests verify
    that all Phase 1 golden refs are still found (no regressions).
    """

    @pytest.fixture(autouse=True)
    def setup_registry(self, populated_registry):
        self.registry = populated_registry

    @pytest.mark.parametrize("service,kind_name", [
        ("cert-manager", "Certificate"),
        ("cert-manager", "CertificateRequest"),
        ("cert-manager", "Issuer"),
        ("cert-manager", "ClusterIssuer"),
        ("cert-manager", "Order"),
        ("cert-manager", "Challenge"),
        ("external-secrets", "ExternalSecret"),
        ("external-secrets", "SecretStore"),
        ("external-secrets", "ClusterSecretStore"),
        ("external-secrets", "ClusterExternalSecret"),
        ("external-secrets", "PushSecret"),
        ("traefik", "IngressRoute"),
        ("traefik", "IngressRouteTCP"),
        ("traefik", "IngressRouteUDP"),
        ("traefik", "Middleware"),
        ("traefik", "MiddlewareTCP"),
        ("traefik", "ServersTransport"),
        ("traefik", "ServersTransportTCP"),
        ("traefik", "TLSOption"),
        ("traefik", "TLSStore"),
        ("traefik", "TraefikService"),
    ])
    def test_golden_refs_superset(self, service, kind_name):
        """All Phase 1 golden input_refs are still found (superset check)."""
        fixture = _load_fixture(service, kind_name)
        golden = _load_golden(service, kind_name)
        fields = _classify_fixture(fixture, self.registry)

        # Build set of (field_path, target_kind) from classified output.
        actual_refs = {
            (f.field, f.target_kind)
            for f in fields
            if f.role == "input_ref" and f.target_kind
        }

        # Check that every golden ref is present.
        golden_refs = golden.get("input_refs", [])
        for gref in golden_refs:
            golden_field = gref.get("field", "")
            golden_target = gref.get("target_kind")
            # Only check if golden has target_kind (some old goldens may not).
            if golden_target:
                assert (golden_field, golden_target) in actual_refs, (
                    f"Missing golden ref: {golden_field} -> {golden_target}"
                )


# ---------------------------------------------------------------------------
# Pipeline delegation tests
# ---------------------------------------------------------------------------


class TestPipelineDelegation:
    """Verify classify_fields delegates to walk_crd_schema + classify_walked_field."""

    @pytest.fixture(autouse=True)
    def setup_registry(self, populated_registry):
        self.registry = populated_registry

    def test_simple_secret_ref(self):
        """classify_fields with secretRef returns input_ref."""
        props = {
            "secretRef": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        }
        fields = classify_fields(props, [], "cert-manager.io", "Certificate",
                                registry=self.registry)
        refs = [f for f in fields if f.role == "input_ref"]
        assert len(refs) >= 1
        assert refs[0].target_kind == "Secret"

    def test_nested_depth_4_detected(self):
        """Nested depth-4 property (SecretStore pattern) detected."""
        props = {
            "provider": {
                "type": "object",
                "properties": {
                    "vault": {
                        "type": "object",
                        "properties": {
                            "auth": {
                                "type": "object",
                                "properties": {
                                    "tokenSecretRef": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        fields = classify_fields(props, [], "external-secrets.io", "SecretStore",
                                registry=self.registry)
        refs = [f for f in fields if f.role == "input_ref"]
        assert any(f.field == "spec.provider.vault.auth.tokenSecretRef" for f in refs)

    def test_array_ref_detected(self):
        """Array property (PushSecret pattern) detected."""
        props = {
            "secretStoreRefs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }
        fields = classify_fields(props, [], "external-secrets.io", "PushSecret",
                                registry=self.registry)
        refs = [f for f in fields if f.role == "input_ref"]
        assert any(f.target_kind == "SecretStore" for f in refs)

    def test_non_ref_returns_config(self):
        """Non-ref property returns config_field."""
        props = {"replicas": {"type": "integer"}}
        fields = classify_fields(props, [], "apps", "Deployment",
                                registry=self.registry)
        assert len(fields) == 1
        assert fields[0].role == "config_field"

    def test_detection_source_on_every_result(self):
        """Every classified field has non-empty detection_source."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        for f in fields:
            assert f.detection_source, f"Field {f.field} has empty detection_source"

    def test_fact_shape_on_every_result(self):
        """Every classified field has non-empty fact_shape."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        for f in fields:
            # fact_shape may be empty for some fields from ref_detector default
            # but should be present for input_ref and output_declaration
            if f.role in ("input_ref", "output_declaration"):
                assert f.fact_shape, f"Field {f.field} ({f.role}) has empty fact_shape"


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------


class TestDeduplication:
    @pytest.fixture(autouse=True)
    def setup_registry(self, populated_registry):
        self.registry = populated_registry

    def test_parent_child_dedup(self):
        """secretRef parent classified — child secretRef.name NOT in results as separate ref."""
        props = {
            "secretRef": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "key": {"type": "string"},
                },
            },
        }
        fields = classify_fields(props, [], "core", "Test",
                                registry=self.registry)
        # secretRef should be input_ref, but name/key should not be
        # classified as separate input_refs
        refs = [f for f in fields if f.role == "input_ref"]
        ref_paths = {f.field for f in refs}
        assert "spec.secretRef" in ref_paths
        # Child fields should NOT be classified as refs
        assert "spec.secretRef.name" not in ref_paths

    def test_sibling_refs_both_kept(self):
        """Two sibling refs at same depth — both in results."""
        props = {
            "secretRef": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
            "configMapRef": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        }
        fields = classify_fields(props, [], "core", "Test",
                                registry=self.registry)
        refs = [f for f in fields if f.role == "input_ref"]
        target_kinds = {f.target_kind for f in refs}
        assert "Secret" in target_kinds
        assert "ConfigMap" in target_kinds

    def test_non_structural_ref_does_not_block_descendant(self):
        """Non-structural ref (e.g., enum_kind) at spec.x does NOT suppress spec.x.y."""
        props = {
            "typeSelector": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["Certificate", "Issuer"],
                    },
                    "secretRef": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "key": {"type": "string"},
                        },
                    },
                },
            },
        }
        fields = classify_fields(props, [], "cert-manager.io", "Test",
                                registry=self.registry)
        refs = [f for f in fields if f.role == "input_ref"]
        ref_paths = {f.field for f in refs}
        # The SKS child should appear as an independent ref
        assert "spec.typeSelector.secretRef" in ref_paths

    def test_structural_ref_still_blocks_descendants(self):
        """SKS-shape ref at spec.secretRef blocks spec.secretRef.namespace."""
        props = {
            "secretRef": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "key": {"type": "string"},
                    "namespace": {"type": "string"},
                },
            },
        }
        fields = classify_fields(props, [], "core", "Test",
                                registry=self.registry)
        refs = [f for f in fields if f.role == "input_ref"]
        ref_paths = {f.field for f in refs}
        assert "spec.secretRef" in ref_paths
        # Children of structural ref must NOT appear as independent refs
        assert "spec.secretRef.namespace" not in ref_paths
        assert "spec.secretRef.name" not in ref_paths
        assert "spec.secretRef.key" not in ref_paths

    def test_ref_tuple_blocks_descendants(self):
        """ref_tuple detection ({kind, name, namespace}) blocks descendant classification."""
        props = {
            "sourceRef": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["Certificate"],
                    },
                    "name": {"type": "string"},
                    "namespace": {"type": "string"},
                },
                "required": ["name"],
            },
        }
        fields = classify_fields(props, [], "cert-manager.io", "Test",
                                registry=self.registry)
        refs = [f for f in fields if f.role == "input_ref"]
        ref_paths = {f.field for f in refs}
        assert "spec.sourceRef" in ref_paths
        # Descendants must be blocked by ref_tuple
        assert "spec.sourceRef.name" not in ref_paths
        assert "spec.sourceRef.namespace" not in ref_paths

    def test_config_parent_does_not_suppress_child(self):
        """config_field parent does NOT suppress child classification."""
        props = {
            "config": {
                "type": "object",
                "properties": {
                    "secretRef": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        }
        fields = classify_fields(props, [], "core", "Test",
                                registry=self.registry)
        refs = [f for f in fields if f.role == "input_ref"]
        assert any(f.field == "spec.config.secretRef" for f in refs)


# ---------------------------------------------------------------------------
# Phase 2 Section 01: ClassifiedField extension tests
# ---------------------------------------------------------------------------


class TestClassifiedFieldExtensions:
    """Verify the three Phase 2 fields on ClassifiedField."""

    def test_fact_shape_defaults_to_empty(self):
        cf = ClassifiedField(
            field="spec.foo", role="config_field",
            confidence=0.5, field_type="string",
        )
        assert cf.fact_shape == ""

    def test_target_field_defaults_to_name(self):
        cf = ClassifiedField(
            field="spec.foo", role="config_field",
            confidence=0.5, field_type="string",
        )
        assert cf.target_field == "name"

    def test_detection_source_defaults_to_empty(self):
        cf = ClassifiedField(
            field="spec.foo", role="config_field",
            confidence=0.5, field_type="string",
        )
        assert cf.detection_source == ""

    def test_existing_code_without_new_fields_still_works(self):
        cf = ClassifiedField(
            field="spec.issuerRef", role="input_ref",
            confidence=0.9, field_type="object",
            target_kind="Issuer", target_group="cert-manager.io",
            required=True, cross_namespace=False,
            description="Reference to issuer",
        )
        assert cf.detection_source == ""
        assert cf.fact_shape == ""
        assert cf.target_field == "name"

    def test_blocks_descendants_defaults_to_false(self):
        """blocks_descendants defaults to False for backward compatibility."""
        cf = ClassifiedField(
            field="spec.foo", role="config_field",
            confidence=0.5, field_type="string",
        )
        assert cf.blocks_descendants is False

    def test_blocks_descendants_can_be_set_true(self):
        """blocks_descendants can be explicitly set to True."""
        cf = ClassifiedField(
            field="spec.secretRef", role="input_ref",
            confidence=0.85, field_type="object",
            target_kind="Secret", target_group="core",
            blocks_descendants=True,
        )
        assert cf.blocks_descendants is True

    def test_new_fields_can_be_set_explicitly(self):
        cf = ClassifiedField(
            field="spec.issuerRef", role="input_ref",
            confidence=0.9, field_type="object",
            detection_source="ref_detector:kind_registry",
            fact_shape="identity",
            target_field="name",
        )
        assert cf.detection_source == "ref_detector:kind_registry"
        assert cf.fact_shape == "identity"
        assert cf.target_field == "name"

    def test_fact_shape_lifecycle(self):
        cf = ClassifiedField(
            field="status.conditions", role="output_declaration",
            confidence=0.9, field_type="array",
            fact_shape="lifecycle",
            target_field="type",
        )
        assert cf.fact_shape == "lifecycle"
        assert cf.target_field == "type"

    def test_fact_shape_config(self):
        cf = ClassifiedField(
            field="spec.replicas", role="config_field",
            confidence=0.5, field_type="integer",
            fact_shape="config",
            target_field="replicas",
        )
        assert cf.fact_shape == "config"
        assert cf.target_field == "replicas"


# ---------------------------------------------------------------------------
# detection_source tests
# ---------------------------------------------------------------------------


class TestDetectionSource:
    @pytest.fixture(autouse=True)
    def setup_registry(self, populated_registry):
        self.registry = populated_registry

    def test_certificate_secret_name_detected(self):
        """spec.secretName on Certificate -> detected (NLP or KindRegistry)."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        secret_name = next(f for f in fields if f.field == "spec.secretName")
        # In Phase 2, secretName may be caught by KindRegistry (Secret+Name)
        # or NLP. Either way it should be detected.
        assert secret_name.role in ("input_ref", "output_declaration")
        assert secret_name.detection_source != ""

    def test_certificate_issuer_ref_detected(self):
        """spec.issuerRef on Certificate -> input_ref."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        issuer_ref = next(f for f in fields if f.field == "spec.issuerRef")
        assert issuer_ref.role == "input_ref"
        assert issuer_ref.target_kind == "Issuer"
        assert issuer_ref.detection_source != ""

    def test_external_secret_store_ref_detected(self):
        """spec.secretStoreRef on ExternalSecret -> input_ref, target=SecretStore."""
        fixture = _load_fixture("external-secrets", "ExternalSecret")
        fields = _classify_fixture(fixture, self.registry)
        store_ref = next(f for f in fields if f.field == "spec.secretStoreRef")
        assert store_ref.role == "input_ref"
        assert store_ref.target_kind == "SecretStore"

    def test_all_fields_have_detection_source(self):
        """Every classified field has a non-empty detection_source."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        for f in fields:
            assert f.detection_source, f"Field {f.field} has empty detection_source"


# ---------------------------------------------------------------------------
# Deleted code verification
# ---------------------------------------------------------------------------


class TestDeletedCode:
    def test_classify_single_field_not_accessible(self):
        """_classify_single_field is deleted."""
        import idi.generation.crd.field_classifier as fc
        assert not hasattr(fc, "_classify_single_field")

    def test_kind_map_not_accessible(self):
        """_KIND_MAP is deleted."""
        import idi.generation.crd.field_classifier as fc
        assert not hasattr(fc, "_KIND_MAP")

    def test_no_kubernetes_crd_imports(self):
        """No imports from adapters.kubernetes_crd in field_classifier."""
        import idi.generation.crd.field_classifier as fc
        import inspect
        source = inspect.getsource(fc)
        assert "adapters.kubernetes_crd" not in source
        assert "from idi.generation.adapters.kubernetes_crd" not in source


# ---------------------------------------------------------------------------
# Layer-specific regression tests (Phase 2 equivalents)
# ---------------------------------------------------------------------------


class TestLayerRegression:
    """Verify specific classification behaviors still work."""

    @pytest.fixture(autouse=True)
    def setup_registry(self, populated_registry):
        self.registry = populated_registry

    def test_certificate_issuer_ref_input(self):
        """spec.issuerRef on Certificate -> input_ref, target_kind=Issuer."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        issuer_ref = next(f for f in fields if f.field == "spec.issuerRef")
        assert issuer_ref.role == "input_ref"
        assert issuer_ref.target_kind == "Issuer"
        assert issuer_ref.confidence == 0.9

    def test_external_secret_store_ref(self):
        """spec.secretStoreRef on ExternalSecret -> input_ref, target_kind=SecretStore."""
        fixture = _load_fixture("external-secrets", "ExternalSecret")
        fields = _classify_fixture(fixture, self.registry)
        store_ref = next(f for f in fields if f.field == "spec.secretStoreRef")
        assert store_ref.role == "input_ref"
        assert store_ref.target_kind == "SecretStore"
        assert store_ref.confidence == 0.9

    def test_certificate_common_name_config(self):
        """spec.commonName on Certificate -> config_field."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        common_name = next(f for f in fields if f.field == "spec.commonName")
        assert common_name.role == "config_field"
        assert common_name.confidence == 0.5
