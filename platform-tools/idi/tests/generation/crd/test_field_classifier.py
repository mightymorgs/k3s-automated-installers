"""Tests for field_classifier.py — CRD Phase 1a refactor."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from idi.generation.crd.field_classifier import (
    ClassifiedField,
    classify_fields,
    _resource_to_kind,
    _resource_to_group,
)
from idi.generation.crd.kind_registry import KindRegistry
from tests.generation.crd.conftest import assert_json_equivalent, _GOLDEN_DIR, _FIXTURES_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fields_to_dicts(fields: list[ClassifiedField]) -> list[dict[str, Any]]:
    """Convert ClassifiedField list to dicts for comparison."""
    return [
        {
            "field": f.field,
            "role": f.role,
            "confidence": f.confidence,
            "field_type": f.field_type,
            "target_kind": f.target_kind,
            "target_group": f.target_group,
            "required": f.required,
            "cross_namespace": f.cross_namespace,
        }
        for f in fields
    ]


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


def _compare_classified_to_golden(
    fields: list[ClassifiedField],
    golden: dict[str, Any],
    fixture: dict[str, Any],
) -> None:
    """Compare classified fields to golden file output.

    Checks that input_refs, output_declarations, and config_fields match.
    """
    # Build actual ref/output/config sets.
    actual_refs = []
    actual_outputs = []
    actual_config = []
    for f in fields:
        if f.role == "input_ref" and f.target_kind:
            actual_refs.append({
                "field": f.field,
                "target_kind": f.target_kind,
                "target_group": f.target_group or fixture["group"],
                "role": "input_ref",
                "required": f.required,
                "cross_namespace": f.cross_namespace,
            })
        elif f.role == "output_declaration":
            actual_outputs.append({
                "field": f.field,
                "produces_kind": f.target_kind or "Unknown",
                "produces_group": f.target_group or "core",
                "role": "output_declaration",
            })
        elif f.role == "config_field":
            entry: dict[str, Any] = {
                "field": f.field,
                "type": f.field_type,
            }
            if f.description:
                entry["description"] = f.description
            actual_config.append(entry)

    # Strip fact_ref from golden data (fact_ref is added by output_writer, not classifier).
    golden_refs = [
        {k: v for k, v in r.items() if k != "fact_ref"}
        for r in golden.get("input_refs", [])
    ]
    golden_outputs = [
        {k: v for k, v in o.items() if k != "fact_ref"}
        for o in golden.get("output_declarations", [])
    ]

    # Compare. We use assert_json_equivalent for array-order-independent comparison.
    assert_json_equivalent(
        {"input_refs": actual_refs},
        {"input_refs": golden_refs},
    )
    assert_json_equivalent(
        {"output_declarations": actual_outputs},
        {"output_declarations": golden_outputs},
    )
    assert_json_equivalent(
        {"config_fields": actual_config},
        {"config_fields": golden.get("config_fields", [])},
    )


# ---------------------------------------------------------------------------
# Golden-file equivalence tests
# ---------------------------------------------------------------------------


class TestGoldenFileEquivalence:
    """Verify that classify_fields produces identical output to golden files."""

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
    def test_golden_equivalence(self, service, kind_name):
        """classify_fields output matches golden file for {service}/{kind_name}."""
        fixture = _load_fixture(service, kind_name)
        golden = _load_golden(service, kind_name)
        fields = _classify_fixture(fixture, self.registry)
        _compare_classified_to_golden(fields, golden, fixture)


# ---------------------------------------------------------------------------
# Layer-specific regression tests
# ---------------------------------------------------------------------------


class TestLayerRegression:
    """Verify specific classification layers work correctly."""

    @pytest.fixture(autouse=True)
    def setup_registry(self, populated_registry):
        self.registry = populated_registry

    def test_certificate_secret_name_output(self):
        """spec.secretName on Certificate -> output_declaration via side-effect registry."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        secret_name = next(f for f in fields if f.field == "spec.secretName")
        assert secret_name.role == "output_declaration"
        assert secret_name.confidence == 0.95

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


# ---------------------------------------------------------------------------
# _resource_to_kind without fallback
# ---------------------------------------------------------------------------


class TestResourceToKind:
    @pytest.fixture(autouse=True)
    def setup_registry(self, populated_registry):
        self.registry = populated_registry

    def test_secrets(self):
        assert _resource_to_kind("secrets", self.registry) == "Secret"

    def test_configmaps(self):
        assert _resource_to_kind("configmaps", self.registry) == "ConfigMap"

    def test_ingressclasses(self):
        assert _resource_to_kind("ingressclasses", self.registry) == "IngressClass"

    def test_unknown_plural(self):
        assert _resource_to_kind("unknown_plural", self.registry) is None

    def test_endpoints(self):
        assert _resource_to_kind("endpoints", self.registry) == "Endpoint"


# ---------------------------------------------------------------------------
# _resource_to_group with registry
# ---------------------------------------------------------------------------


class TestResourceToGroup:
    @pytest.fixture(autouse=True)
    def setup_registry(self, populated_registry):
        self.registry = populated_registry

    def test_secrets(self):
        assert _resource_to_group("secrets", self.registry) == "core"

    def test_deployments(self):
        assert _resource_to_group("deployments", self.registry) == "apps"

    def test_unknown(self):
        assert _resource_to_group("unknown", self.registry) == ""


# ---------------------------------------------------------------------------
# detection_source tests
# ---------------------------------------------------------------------------


class TestDetectionSource:
    @pytest.fixture(autouse=True)
    def setup_registry(self, populated_registry):
        self.registry = populated_registry

    def test_certificate_secret_name_side_effect(self):
        """spec.secretName on Certificate -> layer1_side_effect."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        secret_name = next(f for f in fields if f.field == "spec.secretName")
        assert secret_name.detection_source == "field_classifier:layer1_side_effect"

    def test_certificate_issuer_ref_layer3(self):
        """spec.issuerRef on Certificate -> layer3_object_name_ref."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        issuer_ref = next(f for f in fields if f.field == "spec.issuerRef")
        assert issuer_ref.detection_source == "field_classifier:layer3_object_name_ref"

    def test_external_secret_store_ref_layer3(self):
        """spec.secretStoreRef on ExternalSecret -> layer3 (object+name+Ref structural heuristic)."""
        fixture = _load_fixture("external-secrets", "ExternalSecret")
        fields = _classify_fixture(fixture, self.registry)
        store_ref = next(f for f in fields if f.field == "spec.secretStoreRef")
        # secretStoreRef is an object with name property, so structural heuristic (layer 3)
        # takes priority over registry matching (layer 2).
        assert store_ref.detection_source == "field_classifier:layer3_object_name_ref"

    def test_certificate_common_name_default(self):
        """spec.commonName on Certificate -> layer5_default."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        common_name = next(f for f in fields if f.field == "spec.commonName")
        assert common_name.detection_source == "field_classifier:layer5_default"

    def test_all_fields_have_detection_source(self):
        """Every classified field has a non-empty detection_source."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, self.registry)
        for f in fields:
            assert f.detection_source, f"Field {f.field} has empty detection_source"


# ---------------------------------------------------------------------------
# Phase 2 Section 01: ClassifiedField extension tests
# ---------------------------------------------------------------------------


class TestClassifiedFieldExtensions:
    """Verify the three new Phase 2 fields on ClassifiedField."""

    def test_fact_shape_defaults_to_empty(self):
        """fact_shape defaults to empty string."""
        cf = ClassifiedField(
            field="spec.foo", role="config_field",
            confidence=0.5, field_type="string",
        )
        assert cf.fact_shape == ""

    def test_target_field_defaults_to_name(self):
        """target_field defaults to 'name'."""
        cf = ClassifiedField(
            field="spec.foo", role="config_field",
            confidence=0.5, field_type="string",
        )
        assert cf.target_field == "name"

    def test_detection_source_defaults_to_empty(self):
        """detection_source defaults to empty string (pre-existing)."""
        cf = ClassifiedField(
            field="spec.foo", role="config_field",
            confidence=0.5, field_type="string",
        )
        assert cf.detection_source == ""

    def test_existing_code_without_new_fields_still_works(self):
        """Constructing ClassifiedField with only original fields succeeds."""
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

    def test_new_fields_can_be_set_explicitly(self):
        """New fields can be explicitly set on construction."""
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
        """fact_shape can be set to 'lifecycle'."""
        cf = ClassifiedField(
            field="status.conditions", role="output_declaration",
            confidence=0.9, field_type="array",
            fact_shape="lifecycle",
            target_field="type",
        )
        assert cf.fact_shape == "lifecycle"
        assert cf.target_field == "type"

    def test_fact_shape_config(self):
        """fact_shape can be set to 'config'."""
        cf = ClassifiedField(
            field="spec.replicas", role="config_field",
            confidence=0.5, field_type="integer",
            fact_shape="config",
            target_field="replicas",
        )
        assert cf.fact_shape == "config"
        assert cf.target_field == "replicas"
