"""Integration tests for Phase 3 pipeline — CRD Phase 3 Section 07.

Verifies that Phase 2 golden edges survive the full Phase 3 pipeline
(including suppression) and that new Phase 3 detectors produce correct
edges end-to-end.
"""
from __future__ import annotations

import pytest

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import ManifestFlags, classify_walked_field
from idi.generation.crd.schema_walker import WalkedField


@pytest.fixture
def registry() -> KindRegistry:
    reg = KindRegistry()
    reg.register("Issuer", "issuers", "cert-manager.io")
    reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io")
    reg.register("SecretStore", "secretstores", "external-secrets.io")
    reg.register("ClusterSecretStore", "clustersecretstores", "external-secrets.io")
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
        path=path, name=name, schema=schema, depth=depth,
        is_array_item=False, required=required, parent_path=parent_path,
    )


class TestPhase2GoldenEdges:
    """Phase 2 edges must survive Phase 3 suppression."""

    def test_certificate_issuer_ref_preserved(self, registry):
        """Certificate issuerRef -> Issuer still detected."""
        field = _make_field("issuerRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": ["Issuer", "ClusterIssuer"]},
            },
        })
        results = classify_walked_field(
            field, registry, "Certificate", "cert-manager.io",
        )
        # detect_ref catches it first (KindRegistry match on issuerRef)
        assert len(results) == 1
        assert results[0].role == "input_ref"
        assert results[0].target_kind == "Issuer"
        assert results[0].detection_source == "ref_detector:kind_registry"

    def test_secret_store_token_secret_ref_preserved(self, registry):
        """SecretStore tokenSecretRef -> Secret still detected."""
        field = _make_field("tokenSecretRef", schema={
            "type": "object",
            "properties": {"key": {"type": "string"}},
        }, path="spec.provider.vault.auth.tokenSecretRef",
            parent_path="spec.provider.vault.auth")
        results = classify_walked_field(
            field, registry, "SecretStore", "external-secrets.io",
        )
        assert len(results) == 1
        assert results[0].role == "input_ref"
        assert results[0].target_kind == "Secret"

    def test_enum_kind_issuer_preserved(self, registry):
        """Enum kind=["Issuer", "ClusterIssuer"] still detected when no name-based match."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer", "ClusterIssuer"],
        }, path="spec.ref.kind", parent_path="spec.ref")
        sibling = {"name": {"type": "string"}, "kind": {"type": "string"}}
        results = classify_walked_field(
            field, registry, "Certificate", "cert-manager.io",
            sibling_fields=sibling,
        )
        assert len(results) == 2
        kinds = {r.target_kind for r in results}
        assert kinds == {"Issuer", "ClusterIssuer"}

    def test_config_field_preserved(self, registry):
        """Unmatched fields still produce config_field."""
        field = _make_field("replicas", schema={"type": "integer"})
        results = classify_walked_field(
            field, registry, "Deployment", "apps",
        )
        assert len(results) == 1
        assert results[0].role == "config_field"


class TestPhase3RefTupleEndToEnd:
    """End-to-end tests for detect_ref_tuple through the full pipeline."""

    def test_ref_tuple_with_kind_enum_survives(self, registry):
        """Reference tuple with kind enum -> correct edges that survive suppression."""
        field = _make_field("targetCluster", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "kind": {"type": "string", "enum": ["Secret"]},
            },
        })
        results = classify_walked_field(
            field, registry, "MyResource", "example.io",
        )
        refs = [r for r in results if r.role == "input_ref"]
        assert len(refs) == 1
        assert refs[0].target_kind == "Secret"
        assert refs[0].detection_source == "ref_detector:ref_tuple"

    def test_ref_tuple_without_kind_returns_nothing(self, registry):
        """Reference tuple without resolvable Kind -> no edges."""
        field = _make_field("target", schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
        })
        results = classify_walked_field(
            field, registry, "MyResource", "example.io",
        )
        # Falls through to config_field
        assert all(r.role == "config_field" for r in results)


class TestPhase3PassthroughEndToEnd:
    """End-to-end tests for passthrough manifest detection."""

    def test_passthrough_with_constrained_kinds(self, registry):
        """Passthrough with kind enum -> flag + edges."""
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
        results = classify_walked_field(
            field, registry, "Application", "argoproj.io",
            manifest_flags=flags,
        )
        refs = [r for r in results if r.role == "input_ref"]
        assert len(refs) == 2
        kinds = {r.target_kind for r in refs}
        assert kinds == {"Deployment", "Service"}
        assert flags.accepts_arbitrary_resources is True


class TestPhase3Deduplication:
    """Verify deduplication runs before suppression."""

    def test_dedup_before_suppression(self, registry):
        """When enum_kind and example_kind both find same Kind, only one edge emitted."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer"],
            "example": "Issuer",
        }, path="spec.ref.kind", parent_path="spec.ref")
        sibling = {"name": {"type": "string"}, "kind": {"type": "string"}}
        results = classify_walked_field(
            field, registry, "Certificate", "cert-manager.io",
            sibling_fields=sibling,
        )
        # Should have one Issuer edge (deduplicated), not two
        issuer_refs = [r for r in results if r.target_kind == "Issuer" and r.role == "input_ref"]
        assert len(issuer_refs) == 1


class TestPhase3ManifestFlagsNone:
    """Verify pipeline works end-to-end with manifest_flags=None."""

    def test_none_flags_no_crash(self, registry):
        """classify_walked_field with manifest_flags=None works end-to-end."""
        field = _make_field("secretRef", schema={"type": "object"})
        results = classify_walked_field(
            field, registry, "Certificate", "cert-manager.io",
            manifest_flags=None,
        )
        assert len(results) == 1
        assert results[0].target_kind == "Secret"


class TestPhase3SuppressionPreservesLegitimate:
    """Verify suppression does not harm legitimate detections."""

    def test_secret_name_not_suppressed(self, registry):
        """secretName detected by KindRegistry -> not suppressed."""
        field = _make_field("secretName", schema={"type": "string"})
        results = classify_walked_field(
            field, registry, "Certificate", "cert-manager.io",
        )
        # This goes through side_effect:operator_dict for Certificate
        assert len(results) == 1
        # Should not be suppressed regardless of path
        assert "suppressed" not in results[0].detection_source

    def test_config_map_ref_not_suppressed(self, registry):
        """configMapRef -> not suppressed."""
        field = _make_field("configMapRef", schema={"type": "object"})
        results = classify_walked_field(
            field, registry, "MyResource", "example.io",
        )
        refs = [r for r in results if r.role == "input_ref"]
        assert len(refs) == 1
        assert refs[0].target_kind == "ConfigMap"
        assert "suppressed" not in refs[0].detection_source
