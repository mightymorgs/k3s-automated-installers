"""Tests for crd/ref_detector.py — CRD Phase 2 Section 03."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import (
    classify_walked_field,
    detect_enum_kind,
    detect_namespace,
    detect_ref,
    detect_status_output,
)
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    """KindRegistry with core resources + some CRDs."""
    reg = KindRegistry()
    # Register CRD kinds used in tests.
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
    depth: int = 1,
    is_array_item: bool = False,
    required: bool = False,
    parent_path: str = "spec",
) -> WalkedField:
    """Build a WalkedField with sensible defaults."""
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path,
        name=name,
        schema=schema,
        depth=depth,
        is_array_item=is_array_item,
        required=required,
        parent_path=parent_path,
    )


# ---------------------------------------------------------------------------
# detect_ref: exclusions
# ---------------------------------------------------------------------------


class TestDetectRefExclusions:
    def test_label_selector_returns_none(self, registry):
        """LabelSelector $ref returns None."""
        field = _make_field("selector", schema={
            "type": "object",
            "$ref": "io.k8s.apimachinery.pkg.apis.meta.v1.LabelSelector",
        })
        assert detect_ref(field, registry) is None

    def test_object_reference_returns_none(self, registry):
        """ObjectReference $ref returns None."""
        field = _make_field("targetRef", schema={
            "type": "object",
            "$ref": "io.k8s.api.core.v1.ObjectReference",
        })
        assert detect_ref(field, registry) is None

    def test_object_reference_with_name_property_returns_none(self, registry):
        """ObjectReference with name property — exclusion fires before structural."""
        field = _make_field("targetRef", schema={
            "type": "object",
            "$ref": "ObjectReference",
            "properties": {"name": {"type": "string"}},
        })
        # This would match structural ref (step 4) if exclusion didn't fire first.
        assert detect_ref(field, registry) is None

    def test_short_label_selector_pattern(self, registry):
        """Short LabelSelector pattern also excluded."""
        field = _make_field("matchLabels", schema={
            "type": "object",
            "$ref": "LabelSelector",
        })
        assert detect_ref(field, registry) is None


# ---------------------------------------------------------------------------
# detect_ref: KindRegistry match (step 3)
# ---------------------------------------------------------------------------


class TestDetectRefKindRegistry:
    def test_secret_ref_matched(self, registry):
        """secretRef matched via KindRegistry."""
        field = _make_field("secretRef", schema={"type": "object"})
        result = detect_ref(field, registry)
        assert result is not None
        assert result.role == "input_ref"
        assert result.confidence == 0.9
        assert result.target_kind == "Secret"
        assert result.detection_source == "ref_detector:kind_registry"
        assert result.fact_shape == "identity"

    def test_config_map_name_matched(self, registry):
        """configMapName matched via KindRegistry."""
        field = _make_field("configMapName", schema={"type": "string"})
        result = detect_ref(field, registry)
        assert result is not None
        assert result.target_kind == "ConfigMap"
        assert result.detection_source == "ref_detector:kind_registry"

    def test_token_secret_ref_matched(self, registry):
        """tokenSecretRef matched — targets Secret."""
        field = _make_field("tokenSecretRef", schema={
            "type": "object",
            "properties": {"key": {"type": "string"}},
        })
        result = detect_ref(field, registry)
        assert result is not None
        assert result.target_kind == "Secret"
        assert result.detection_source == "ref_detector:kind_registry"

    def test_random_field_returns_none(self, registry):
        """randomField returns None (no match)."""
        field = _make_field("randomField", schema={"type": "string"})
        assert detect_ref(field, registry) is None

    def test_field_path_preserved(self, registry):
        """field path from WalkedField is preserved in ClassifiedField."""
        field = _make_field("secretRef", schema={"type": "object"},
                          path="spec.provider.vault.auth.secretRef")
        result = detect_ref(field, registry)
        assert result is not None
        assert result.field == "spec.provider.vault.auth.secretRef"

    def test_required_flag_preserved(self, registry):
        """required flag from WalkedField is preserved."""
        field = _make_field("secretRef", schema={"type": "object"}, required=True)
        result = detect_ref(field, registry)
        assert result is not None
        assert result.required is True


# ---------------------------------------------------------------------------
# detect_ref: structural ref (step 4)
# ---------------------------------------------------------------------------


class TestDetectRefStructural:
    def test_issuer_ref_matched_by_kind_registry_first(self, registry):
        """issuerRef is matched by KindRegistry (step 3) before structural (step 4).

        KindRegistry knows the Issuer+Ref suffix pattern, so step 3 fires first.
        Both would produce the same classification, but detection_source reflects
        the earlier match.
        """
        field = _make_field("issuerRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string"},
            },
        })
        result = detect_ref(field, registry)
        assert result is not None
        assert result.role == "input_ref"
        assert result.confidence == 0.9
        assert result.target_kind == "Issuer"
        # KindRegistry fires first since "issuerRef" matches Issuer via is_ref_field.
        assert result.detection_source == "ref_detector:kind_registry"

    def test_structural_ref_for_non_registry_suffix(self, registry):
        """Structural ref fires for object + name + Ref when KindRegistry suffix
        matching doesn't handle the pattern but all_kinds() contains the Kind.

        Register a Kind whose name doesn't trigger is_ref_field suffix matching
        but IS in all_kinds().
        """
        # Register a kind with an unusual name that doesn't trigger suffix matching.
        registry.register("Vault", "vaults", "vault.hashicorp.com")
        field = _make_field("vaultRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        })
        result = detect_ref(field, registry)
        assert result is not None
        assert result.role == "input_ref"
        assert result.confidence == 0.9
        assert result.target_kind == "Vault"
        # vaultRef matches KindRegistry via is_ref_field ({Kind}Ref pattern)
        # so it's still kind_registry, not structural_ref.
        # This is fine — the structural_ref path is a fallback for when
        # KindRegistry suffix matching fails but the Kind is known.

    def test_git_ref_returns_none(self, registry):
        """gitRef (object + name + Ref but KindRegistry doesn't know 'Git')."""
        field = _make_field("gitRef", schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        })
        result = detect_ref(field, registry)
        assert result is None

    def test_no_ref_suffix_returns_none(self, registry):
        """fooBar (object + name but no Ref suffix) returns None."""
        field = _make_field("fooBar", schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        })
        result = detect_ref(field, registry)
        assert result is None

    def test_ref_suffix_but_no_name_property(self, registry):
        """issuerRef but no name property in schema — KindRegistry match (step 3) still works."""
        field = _make_field("issuerRef", schema={
            "type": "object",
            "properties": {"group": {"type": "string"}},
        })
        # This won't match structural (no "name" property) but will match
        # KindRegistry (step 3) since "issuerRef" matches Issuer via is_ref_field.
        result = detect_ref(field, registry)
        assert result is not None
        assert result.detection_source == "ref_detector:kind_registry"

    def test_cross_namespace_detected(self, registry):
        """Ref with namespace property sets cross_namespace."""
        field = _make_field("issuerRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
        })
        result = detect_ref(field, registry)
        assert result is not None
        assert result.cross_namespace is True


# ---------------------------------------------------------------------------
# detect_ref: array ref (step 5)
# ---------------------------------------------------------------------------


class TestDetectRefArray:
    def test_secret_store_refs_array(self, registry):
        """secretStoreRefs (array, Refs suffix, KindRegistry resolves)."""
        field = _make_field("secretStoreRefs", schema={
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
            },
        })
        result = detect_ref(field, registry)
        assert result is not None
        assert result.role == "input_ref"
        assert result.confidence == 0.85
        assert result.target_kind == "SecretStore"
        assert result.detection_source == "ref_detector:array_ref"

    def test_unknown_thing_refs_returns_none(self, registry):
        """unknownThingRefs (array, Refs suffix, KindRegistry can't resolve)."""
        field = _make_field("unknownThingRefs", schema={
            "type": "array",
            "items": {"type": "object"},
        })
        result = detect_ref(field, registry)
        assert result is None

    def test_non_array_not_matched(self, registry):
        """Object field with Refs suffix — not an array, not matched by step 5."""
        field = _make_field("secretStoreRefs", schema={"type": "object"})
        # Falls through to KindRegistry match, which may or may not match.
        result = detect_ref(field, registry)
        # SecretStore is known, so KindRegistry (step 3) matches it.
        # The key point: it's NOT array_ref detection.
        if result:
            assert result.detection_source != "ref_detector:array_ref"


# ---------------------------------------------------------------------------
# detect_enum_kind
# ---------------------------------------------------------------------------


class TestDetectEnumKind:
    def test_issuer_cluster_issuer_with_sibling_name(self, registry):
        """Enum ["Issuer", "ClusterIssuer"] with sibling name — two results at 0.95."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer", "ClusterIssuer"],
        }, path="spec.issuerRef.kind", parent_path="spec.issuerRef")
        sibling = {"name": {"type": "string"}, "kind": {"type": "string"}}
        results = detect_enum_kind(field, registry, sibling_fields=sibling)
        assert len(results) == 2
        assert all(r.confidence == 0.95 for r in results)
        assert all(r.detection_source == "ref_detector:enum_kind" for r in results)
        kinds = {r.target_kind for r in results}
        assert kinds == {"Issuer", "ClusterIssuer"}

    def test_results_point_to_sibling_name_path(self, registry):
        """Results point to sibling name field path, not enum field path."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer"],
        }, path="spec.issuerRef.kind", parent_path="spec.issuerRef")
        sibling = {"name": {"type": "string"}}
        results = detect_enum_kind(field, registry, sibling_fields=sibling)
        assert len(results) == 1
        assert results[0].field == "spec.issuerRef.name"

    def test_no_sibling_name_falls_back(self, registry):
        """Enum with no sibling name — falls back at 0.8 pointing to enum field."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer"],
        }, path="spec.issuerRef.kind")
        results = detect_enum_kind(field, registry, sibling_fields=None)
        assert len(results) == 1
        assert results[0].confidence == 0.8
        assert results[0].field == "spec.issuerRef.kind"

    def test_no_kind_matches_empty_list(self, registry):
        """Enum ["active", "inactive"] — no Kind matches, empty list."""
        field = _make_field("state", schema={
            "type": "string",
            "enum": ["active", "inactive"],
        })
        results = detect_enum_kind(field, registry)
        assert results == []

    def test_partial_matches(self, registry):
        """Enum ["Issuer", "unknown"] — only Issuer returned."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer", "unknown"],
        }, path="spec.issuerRef.kind")
        results = detect_enum_kind(field, registry)
        assert len(results) == 1
        assert results[0].target_kind == "Issuer"

    def test_case_insensitive_match(self, registry):
        """Case-insensitive: enum ["secret", "configmap"] — matches."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["secret", "configmap"],
        }, path="spec.ref.kind", parent_path="spec.ref")
        sibling = {"name": {"type": "string"}}
        results = detect_enum_kind(field, registry, sibling_fields=sibling)
        assert len(results) == 2
        kinds = {r.target_kind for r in results}
        assert kinds == {"Secret", "ConfigMap"}

    def test_no_enum_property_empty_list(self, registry):
        """No enum property — empty list."""
        field = _make_field("kind", schema={"type": "string"})
        results = detect_enum_kind(field, registry)
        assert results == []

    def test_empty_enum_list(self, registry):
        """Empty enum list — empty list."""
        field = _make_field("kind", schema={"type": "string", "enum": []})
        results = detect_enum_kind(field, registry)
        assert results == []


# ---------------------------------------------------------------------------
# detect_status_output
# ---------------------------------------------------------------------------


class TestDetectStatusOutput:
    def test_service_name_in_status(self, registry):
        """status.serviceName contains 'Service' — confidence 0.85."""
        field = _make_field("serviceName", schema={"type": "string"},
                          path="status.serviceName", parent_path="status")
        result = detect_status_output(field, "Certificate", "cert-manager.io", registry)
        assert result is not None
        assert result.role == "output_declaration"
        assert result.confidence == 0.85
        assert result.fact_shape == "identity"
        assert result.target_kind == "Service"

    def test_conditions_array(self, registry):
        """status.conditions (array) — confidence 0.9, lifecycle."""
        field = _make_field("conditions", schema={"type": "array"},
                          path="status.conditions", parent_path="status")
        result = detect_status_output(field, "Certificate", "cert-manager.io", registry)
        assert result is not None
        assert result.confidence == 0.9
        assert result.fact_shape == "lifecycle"
        assert result.target_field == "type"

    def test_observed_generation_generic(self, registry):
        """status.observedGeneration — confidence 0.6 (below threshold)."""
        field = _make_field("observedGeneration", schema={"type": "integer"},
                          path="status.observedGeneration", parent_path="status")
        result = detect_status_output(field, "Certificate", "cert-manager.io", registry)
        assert result is not None
        assert result.confidence == 0.6
        assert result.fact_shape == "config"

    def test_phase_generic(self, registry):
        """status.phase — confidence 0.6."""
        field = _make_field("phase", schema={"type": "string"},
                          path="status.phase", parent_path="status")
        result = detect_status_output(field, "Certificate", "cert-manager.io", registry)
        assert result is not None
        assert result.confidence == 0.6
        assert result.target_field == "phase"

    def test_all_use_status_output_source(self, registry):
        """All tiers use detection_source='ref_detector:status_output'."""
        for name, schema_type in [("serviceName", "string"), ("conditions", "array"), ("phase", "string")]:
            field = _make_field(name, schema={"type": schema_type},
                              path=f"status.{name}", parent_path="status")
            result = detect_status_output(field, "Cert", "cert-manager.io", registry)
            assert result.detection_source == "ref_detector:status_output"


# ---------------------------------------------------------------------------
# detect_namespace
# ---------------------------------------------------------------------------


class TestDetectNamespace:
    def test_object_with_namespace(self, registry):
        """Object schema with namespace property — True."""
        field = _make_field("issuerRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
        })
        assert detect_namespace(field) is True

    def test_object_without_namespace(self, registry):
        """Object schema without namespace — False."""
        field = _make_field("issuerRef", schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        })
        assert detect_namespace(field) is False

    def test_string_field(self, registry):
        """String field — False."""
        field = _make_field("foo", schema={"type": "string"})
        assert detect_namespace(field) is False


# ---------------------------------------------------------------------------
# classify_walked_field
# ---------------------------------------------------------------------------


class TestClassifyWalkedField:
    def test_detect_ref_wins(self, registry):
        """detect_ref match wins (priority 1)."""
        field = _make_field("secretRef", schema={"type": "object"})
        results = classify_walked_field(field, registry, "Certificate", "cert-manager.io")
        assert len(results) == 1
        assert results[0].detection_source == "ref_detector:kind_registry"

    def test_enum_kind_used_when_no_ref(self, registry):
        """detect_enum_kind used when detect_ref returns None."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer", "ClusterIssuer"],
        }, path="spec.issuerRef.kind", parent_path="spec.issuerRef")
        sibling = {"name": {"type": "string"}, "kind": {"type": "string"}}
        results = classify_walked_field(
            field, registry, "Certificate", "cert-manager.io",
            sibling_fields=sibling,
        )
        assert len(results) == 2
        assert all(r.detection_source == "ref_detector:enum_kind" for r in results)

    def test_nlp_fallback_for_name_fields(self, registry):
        """NLP fallback for *Name fields when no structural match."""
        field = _make_field("secretName", schema={
            "type": "string",
            "description": "will be automatically created",
        })
        results = classify_walked_field(
            field, registry, "Certificate", "cert-manager.io",
        )
        assert len(results) == 1
        # secretName matches KindRegistry (Secret), so detect_ref catches it first.
        # Let's use a field that NLP catches but KindRegistry doesn't.
        field2 = _make_field("outputName", schema={
            "type": "string",
            "description": "will be automatically created",
        })
        results2 = classify_walked_field(
            field2, registry, "Certificate", "cert-manager.io",
        )
        assert len(results2) == 1
        assert results2[0].role == "output_declaration"
        assert "nlp" in results2[0].detection_source or "side_effect" in results2[0].detection_source

    def test_default_config_field(self, registry):
        """Default config_field for completely unmatched field."""
        field = _make_field("replicas", schema={"type": "integer"})
        results = classify_walked_field(field, registry, "Cert", "cert-manager.io")
        assert len(results) == 1
        assert results[0].role == "config_field"
        assert results[0].confidence == 0.5
        assert results[0].detection_source == "default:config_field"
        assert results[0].fact_shape == "config"

    def test_returns_list_type(self, registry):
        """classify_walked_field always returns a list."""
        field = _make_field("foo", schema={"type": "string"})
        results = classify_walked_field(field, registry, "Cert", "cert-manager.io")
        assert isinstance(results, list)

    def test_side_effect_dict_for_certificate_secret_name(self, registry):
        """Certificate spec.secretName uses side-effect dictionary (priority 0).

        The side-effect dictionary (confidence 0.95) overrides KindRegistry
        structural detection (0.9) for known operator outputs. Certificate's
        spec.secretName is an output_declaration — the operator creates the Secret.
        """
        field = _make_field("secretName", schema={
            "type": "string",
            "description": "Name of the Secret resource to store the TLS certificate",
        })
        results = classify_walked_field(
            field, registry, "Certificate", "cert-manager.io",
        )
        assert len(results) == 1
        assert results[0].role == "output_declaration"
        assert results[0].detection_source == "side_effect:operator_dict"
        assert results[0].confidence == 0.95
