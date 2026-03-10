"""Tests for detect_status_output C27 enhancement — CRD Phase 3 Section 06."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import detect_status_output
from idi.generation.crd.schema_walker import WalkedField


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
    parent_path: str = "status",
) -> WalkedField:
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path, name=name, schema=schema, depth=1,
        is_array_item=False, required=False, parent_path=parent_path,
    )


class TestDetectStatusOutputC27:
    def test_service_name_via_kind_registry(self, registry):
        """status.serviceName -> Service via KindRegistry longest-match."""
        field = _make_field("serviceName", schema={"type": "string"})
        result = detect_status_output(field, "Certificate", "cert-manager.io", registry)
        assert result is not None
        assert result.role == "output_declaration"
        assert result.target_kind == "Service"
        assert result.target_group == "core"
        assert result.confidence == 0.85
        assert result.detection_source == "ref_detector:status_addressability"
        assert result.fact_shape == "identity"

    def test_ca_bundle_secret_name(self, registry):
        """status.caBundleSecretName -> Secret (longest match)."""
        field = _make_field("caBundleSecretName", schema={"type": "string"})
        result = detect_status_output(field, "ClusterIssuer", "cert-manager.io", registry)
        assert result is not None
        assert result.target_kind == "Secret"
        assert result.detection_source == "ref_detector:status_addressability"

    def test_load_balancer_service_name(self, registry):
        """status.loadBalancerServiceName -> Service."""
        field = _make_field("loadBalancerServiceName", schema={"type": "string"})
        result = detect_status_output(field, "Ingress", "networking.k8s.io", registry)
        assert result is not None
        assert result.target_kind == "Service"
        assert result.detection_source == "ref_detector:status_addressability"

    def test_conditions_falls_through(self, registry):
        """status.conditions -> falls through to conditions branch."""
        field = _make_field("conditions", schema={"type": "array"})
        result = detect_status_output(field, "Certificate", "cert-manager.io", registry)
        assert result is not None
        assert result.detection_source == "ref_detector:status_output"
        assert result.confidence == 0.9
        assert result.fact_shape == "lifecycle"

    def test_phase_falls_through_to_generic(self, registry):
        """status.phase -> no Kind match, falls through to generic."""
        field = _make_field("phase", schema={"type": "string"})
        result = detect_status_output(field, "Certificate", "cert-manager.io", registry)
        assert result is not None
        assert result.confidence == 0.6
        assert result.detection_source == "ref_detector:status_output"

    def test_observed_generation_generic(self, registry):
        """status.observedGeneration -> generic branch (no Kind match)."""
        field = _make_field("observedGeneration", schema={"type": "integer"})
        result = detect_status_output(field, "Certificate", "cert-manager.io", registry)
        assert result is not None
        assert result.confidence == 0.6
        assert result.detection_source == "ref_detector:status_output"

    def test_c27_result_has_target_kind(self, registry):
        """C27 branch sets target_kind from KindRegistry."""
        field = _make_field("secretName", schema={"type": "string"})
        result = detect_status_output(field, "Certificate", "cert-manager.io", registry)
        assert result.target_kind == "Secret"
        assert result.target_group == "core"

    def test_field_not_in_registry_falls_through(self, registry):
        """Field name without Kind match -> falls through to generic."""
        field = _make_field("readyReplicas", schema={"type": "integer"})
        result = detect_status_output(field, "Deployment", "apps", registry)
        assert result is not None
        assert result.confidence == 0.6

    def test_existing_conditions_regression(self, registry):
        """Regression: existing conditions detection still works."""
        field = _make_field("conditions", schema={"type": "array"})
        result = detect_status_output(field, "Cert", "cert-manager.io", registry)
        assert result.detection_source == "ref_detector:status_output"
        assert result.confidence == 0.9
        assert result.fact_shape == "lifecycle"

    def test_existing_generic_regression(self, registry):
        """Regression: generic status field detection still works."""
        field = _make_field("message", schema={"type": "string"})
        result = detect_status_output(field, "Cert", "cert-manager.io", registry)
        assert result.confidence == 0.6
        assert result.detection_source == "ref_detector:status_output"
