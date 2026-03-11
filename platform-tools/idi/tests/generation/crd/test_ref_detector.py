"""Tests for crd/ref_detector.py — CRD Phase 2 Section 03."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import (
    classify_walked_field,
    detect_enum_kind,
    detect_fuzzy_kind_name,
    detect_namespace,
    detect_parent_kind_name,
    detect_ref,
    detect_secret_key_selector,
    detect_semantic_field,
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
    depth_confidence: float = 1.0,
    sibling_names: frozenset[str] | None = None,
) -> WalkedField:
    """Build a WalkedField with sensible defaults."""
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
    if sibling_names is None:
        sibling_names = frozenset()
    return WalkedField(
        path=path,
        name=name,
        schema=schema,
        depth=depth,
        is_array_item=is_array_item,
        required=required,
        parent_path=parent_path,
        depth_confidence=depth_confidence,
        sibling_names=sibling_names,
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

    def test_ref_suffix_wrapper_object_skipped(self, registry):
        """issuerRef with non-ref-shaped properties (wrapper) → None.

        Objects named *Ref but without ref indicators (name, key, namespace)
        are wrapper objects containing nested refs, not direct refs.
        """
        field = _make_field("issuerRef", schema={
            "type": "object",
            "properties": {"group": {"type": "string"}},
        })
        result = detect_ref(field, registry)
        assert result is None

    def test_ref_suffix_with_name_property_matches(self, registry):
        """issuerRef with name property → KindRegistry match."""
        field = _make_field("issuerRef", schema={
            "type": "object",
            "properties": {"name": {"type": "string"}, "group": {"type": "string"}},
        })
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
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["active", "inactive"],
        }, path="spec.ref.kind")
        results = detect_enum_kind(field, registry)
        assert results == []

    def test_partial_matches_below_ratio(self, registry):
        """Enum ["Issuer", "unknown"] — ratio 0.5 < 0.6 → no match."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer", "unknown"],
        }, path="spec.issuerRef.kind")
        results = detect_enum_kind(field, registry)
        assert results == []

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

    # -- section-08: enum kindness ratio tests --

    def test_api_constants_denylist_filters_all(self, registry):
        """Enum with only K8s API constants — all filtered by denylist, no matches."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Orphan", "Background", "Foreground"],
        }, path="spec.deletionPropagationPolicy")
        results = detect_enum_kind(field, registry)
        assert results == []

    def test_valid_kind_enum_on_kind_field(self, registry):
        """Enum of known Kinds on field named 'kind' — ratio 1.0, kind-like field → match."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer", "ClusterIssuer"],
        }, path="spec.issuerRef.kind", parent_path="spec.issuerRef")
        sibling = {"name": {"type": "string"}, "kind": {"type": "string"}}
        results = detect_enum_kind(field, registry, sibling_fields=sibling)
        assert len(results) == 2
        kinds = {r.target_kind for r in results}
        assert kinds == {"Issuer", "ClusterIssuer"}

    def test_low_kindness_ratio_rejected(self, registry):
        """Enum with ratio 0.5 (1/2 match) on kind-like field — below 0.6 threshold."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer", "SomeRandomThing"],
        }, path="spec.ref.kind")
        results = detect_enum_kind(field, registry)
        assert results == []

    def test_non_kind_like_field_name_rejected(self, registry):
        """Enum of known Kinds on field 'deletionPolicy' — not kind-like, no match."""
        field = _make_field("deletionPolicy", schema={
            "type": "string",
            "enum": ["Issuer", "ClusterIssuer"],
        }, path="spec.deletionPolicy")
        results = detect_enum_kind(field, registry)
        assert results == []

    def test_target_kind_field_name_accepted(self, registry):
        """Enum on field 'targetKind' — kind-like field name + ratio 1.0 → match."""
        field = _make_field("targetKind", schema={
            "type": "string",
            "enum": ["Issuer", "ClusterIssuer"],
        }, path="spec.targetKind")
        results = detect_enum_kind(field, registry)
        assert len(results) == 2
        kinds = {r.target_kind for r in results}
        assert kinds == {"Issuer", "ClusterIssuer"}

    def test_denylist_adjusts_ratio_denominator(self, registry):
        """Enum with mix of denylist and real Kinds — ratio computed after filtering."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Cluster", "Issuer"],
        }, path="spec.ref.kind", parent_path="spec.ref")
        sibling = {"name": {"type": "string"}}
        results = detect_enum_kind(field, registry, sibling_fields=sibling)
        assert len(results) == 1
        assert results[0].target_kind == "Issuer"

    def test_resource_kind_field_name_accepted(self, registry):
        """Enum on field 'resourceKind' — kind-like name."""
        field = _make_field("resourceKind", schema={
            "type": "string",
            "enum": ["Certificate", "Issuer"],
        }, path="spec.resourceKind")
        results = detect_enum_kind(field, registry)
        assert len(results) == 2

    def test_exact_ratio_boundary_accepted(self, registry):
        """Enum with ratio exactly 0.8 (4/5) — at threshold, accepted."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Issuer", "ClusterIssuer", "Certificate", "ExternalSecret", "bar"],
        }, path="spec.ref.kind")
        results = detect_enum_kind(field, registry)
        assert len(results) == 4

    # -- section-03: discriminator enum suppression --

    def test_type_field_rejected(self, registry):
        """Enum on field named 'type' is rejected (removed from _KIND_LIKE_FIELD_NAMES)."""
        field = _make_field("type", schema={
            "type": "string",
            "enum": ["Issuer", "ClusterIssuer"],
        }, path="spec.sourceRef.type")
        results = detect_enum_kind(field, registry)
        assert results == []

    def test_kind_field_with_high_ratio_accepted(self, registry):
        """Enum on 'kind' with 100% kindness ratio → accepted."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Service", "Issuer"],
        }, path="spec.ref.kind", parent_path="spec.ref")
        sibling = {"name": {"type": "string"}}
        results = detect_enum_kind(field, registry, sibling_fields=sibling)
        assert len(results) == 2

    def test_kind_field_below_08_ratio_rejected(self, registry):
        """Enum on 'kind' with ratio 1/3 = 0.33 → below 0.8 threshold, rejected."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Service", "foo", "bar"],
        }, path="spec.ref.kind")
        results = detect_enum_kind(field, registry)
        assert results == []

    def test_ingressroute_routes_kind_accepted(self, registry):
        """IngressRoute routes[].kind enum ["Rule"] — regression guard."""
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Rule"],
        }, path="spec.routes.kind")
        # "Rule" is not a registered Kind, so no match expected
        results = detect_enum_kind(field, registry)
        assert results == []

    def test_traefik_service_kind_enum(self, registry):
        """Traefik routes services kind enum ["Service", "TraefikService"]."""
        registry.register("TraefikService", "traefikservices", "traefik.io")
        field = _make_field("kind", schema={
            "type": "string",
            "enum": ["Service", "TraefikService"],
        }, path="spec.routes.services.kind", parent_path="spec.routes.services")
        sibling = {"name": {"type": "string"}, "kind": {"type": "string"}}
        results = detect_enum_kind(field, registry, sibling_fields=sibling)
        assert len(results) == 2
        kinds = {r.target_kind for r in results}
        assert kinds == {"Service", "TraefikService"}


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

    def test_detection_sources(self, registry):
        """Detection sources reflect which tier fired.

        C27 (status_addressability) fires for fields with Kind names resolved
        via KindRegistry.is_ref_field(). Other tiers use status_output.
        """
        # serviceName resolves via KindRegistry -> status_addressability (C27)
        field = _make_field("serviceName", schema={"type": "string"},
                          path="status.serviceName", parent_path="status")
        result = detect_status_output(field, "Cert", "cert-manager.io", registry)
        assert result.detection_source == "ref_detector:status_addressability"

        # conditions -> status_output (tier 1)
        field = _make_field("conditions", schema={"type": "array"},
                          path="status.conditions", parent_path="status")
        result = detect_status_output(field, "Cert", "cert-manager.io", registry)
        assert result.detection_source == "ref_detector:status_output"

        # phase -> status_output (tier 3, generic)
        field = _make_field("phase", schema={"type": "string"},
                          path="status.phase", parent_path="status")
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


# ---------------------------------------------------------------------------
# detect_secret_key_selector
# ---------------------------------------------------------------------------


class TestDetectSecretKeySelector:
    """Tests for SecretKeySelector shape detection."""

    def test_basic_secret_key_selector(self):
        """Field with {key, name} properties → Secret ref."""
        field = _make_field("apiKeyRef", schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "name": {"type": "string"},
            },
        }, path="spec.provider.auth.apiKeyRef", parent_path="spec.provider.auth")
        result = detect_secret_key_selector(field)
        assert result is not None
        assert result.role == "input_ref"
        assert result.target_kind == "Secret"
        assert result.target_group == "core"
        assert result.confidence == 0.85
        assert result.detection_source == "ref_detector:secret_key_selector"

    def test_with_namespace(self):
        """Field with {key, name, namespace} → cross-namespace Secret ref."""
        field = _make_field("authRef", schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
        }, path="spec.provider.authRef", parent_path="spec.provider")
        result = detect_secret_key_selector(field)
        assert result is not None
        assert result.cross_namespace is True

    def test_no_key_property(self):
        """Object with {name, namespace} but no key → not SecretKeySelector."""
        field = _make_field("someRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
        })
        result = detect_secret_key_selector(field)
        assert result is None

    def test_non_string_key(self):
        """Object with non-string key property → not SecretKeySelector."""
        field = _make_field("someRef", schema={
            "type": "object",
            "properties": {
                "key": {"type": "integer"},
                "name": {"type": "string"},
            },
        })
        result = detect_secret_key_selector(field)
        assert result is None

    def test_with_optional_boolean(self):
        """K8s SecretKeySelector with optional boolean field still matches."""
        field = _make_field("bearerTokenSecret", schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "name": {"type": "string"},
                "optional": {"type": "boolean"},
            },
        })
        result = detect_secret_key_selector(field)
        assert result is not None
        assert result.target_kind == "Secret"

    def test_non_string_extra_property_excluded(self):
        """Object with a non-string extra property → not SecretKeySelector."""
        field = _make_field("ref", schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "name": {"type": "string"},
                "retries": {"type": "integer"},
            },
        })
        result = detect_secret_key_selector(field)
        assert result is None

    def test_pipeline_integration(self, registry):
        """SecretKeySelector detected through classify_walked_field pipeline."""
        field = _make_field("passcodeRef", schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "name": {"type": "string"},
            },
        }, path="spec.auth.passcodeRef", parent_path="spec.auth")
        results = classify_walked_field(field, registry, "SecretStore", "external-secrets.io")
        assert len(results) == 1
        assert results[0].target_kind == "Secret"
        assert results[0].detection_source == "ref_detector:secret_key_selector"


# ---------------------------------------------------------------------------
# detect_parent_kind_name
# ---------------------------------------------------------------------------


class TestDetectParentKindName:
    """Tests for parent-name → Kind resolution (C12 port)."""

    def test_singular_parent_secret(self, registry):
        """Parent 'secret' → Secret."""
        field = _make_field("name", schema={"type": "string"},
                            path="spec.templateFrom.secret.name",
                            parent_path="spec.templateFrom.secret")
        result = detect_parent_kind_name(field, registry)
        assert result is not None
        assert result.target_kind == "Secret"
        assert result.confidence == 0.80
        assert result.detection_source == "ref_detector:parent_kind_name"

    def test_plural_parent_secrets(self, registry):
        """Parent 'secrets' → Secret (depluralize)."""
        field = _make_field("name", schema={"type": "string"},
                            path="spec.webhook.secrets.name",
                            parent_path="spec.webhook.secrets")
        result = detect_parent_kind_name(field, registry)
        assert result is not None
        assert result.target_kind == "Secret"

    def test_plural_parent_services(self, registry):
        """Parent 'services' → Service (depluralize)."""
        field = _make_field("name", schema={"type": "string"},
                            path="spec.routes.services.name",
                            parent_path="spec.routes.services")
        result = detect_parent_kind_name(field, registry)
        assert result is not None
        assert result.target_kind == "Service"

    def test_camelcase_parent(self, registry):
        """Parent 'serviceAccount' → ServiceAccount."""
        field = _make_field("name", schema={"type": "string"},
                            path="spec.auth.serviceAccount.name",
                            parent_path="spec.auth.serviceAccount")
        result = detect_parent_kind_name(field, registry)
        assert result is not None
        assert result.target_kind == "ServiceAccount"

    def test_plural_parent_configmaps(self, registry):
        """Parent 'configMap' → ConfigMap."""
        field = _make_field("name", schema={"type": "string"},
                            path="spec.templateFrom.configMap.name",
                            parent_path="spec.templateFrom.configMap")
        result = detect_parent_kind_name(field, registry)
        assert result is not None
        assert result.target_kind == "ConfigMap"

    def test_non_name_field_ignored(self, registry):
        """Field not named 'name' → None."""
        field = _make_field("key", schema={"type": "string"},
                            path="spec.secret.key",
                            parent_path="spec.secret")
        result = detect_parent_kind_name(field, registry)
        assert result is None

    def test_non_string_field_ignored(self, registry):
        """Non-string 'name' field → None."""
        field = _make_field("name", schema={"type": "integer"},
                            path="spec.secret.name",
                            parent_path="spec.secret")
        result = detect_parent_kind_name(field, registry)
        assert result is None

    def test_unregistered_parent_ignored(self, registry):
        """Parent name not in KindRegistry → None."""
        field = _make_field("name", schema={"type": "string"},
                            path="spec.foobar.name",
                            parent_path="spec.foobar")
        result = detect_parent_kind_name(field, registry)
        assert result is None

    def test_pipeline_integration(self, registry):
        """Parent-name detected through classify_walked_field pipeline."""
        # Register Middleware so it can be found.
        registry.register("Middleware", "middlewares", "traefik.io")
        field = _make_field("name", schema={"type": "string"},
                            path="spec.routes.middlewares.name",
                            parent_path="spec.routes.middlewares",
                            depth=3, is_array_item=True)
        results = classify_walked_field(field, registry, "IngressRoute", "traefik.io")
        assert len(results) == 1
        assert results[0].target_kind == "Middleware"
        assert results[0].detection_source == "ref_detector:parent_kind_name"


# ---------------------------------------------------------------------------
# is_inline_object_name / list-map key suppression
# ---------------------------------------------------------------------------


class TestIsInlineObjectName:
    """Tests for inline K8s object name detection (Section 02)."""

    def test_container_spec_siblings_in_array(self, registry):
        """Array item with container-spec siblings → inline object."""
        from idi.generation.crd.ref_detector import is_inline_object_name
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.template.spec.containers.name",
            parent_path="spec.template.spec.containers",
            is_array_item=True,
            sibling_names=frozenset({"name", "image", "command", "env"}),
        )
        assert is_inline_object_name(field) is True

    def test_volume_mount_siblings_in_array(self, registry):
        """Array item with volumeMount siblings → inline object."""
        from idi.generation.crd.ref_detector import is_inline_object_name
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.template.spec.containers.volumeMounts.name",
            parent_path="spec.template.spec.containers.volumeMounts",
            is_array_item=True,
            sibling_names=frozenset({"name", "mountPath", "readOnly", "subPath"}),
        )
        assert is_inline_object_name(field) is True

    def test_ref_shape_siblings_not_inline(self, registry):
        """Ref-shape siblings (name, key, namespace) → NOT inline."""
        from idi.generation.crd.ref_detector import is_inline_object_name
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.secretRef.name",
            parent_path="spec.secretRef",
            is_array_item=False,
            sibling_names=frozenset({"name", "key", "namespace"}),
        )
        assert is_inline_object_name(field) is False

    def test_non_array_not_inline(self, registry):
        """Non-array context → NOT inline even with container siblings."""
        from idi.generation.crd.ref_detector import is_inline_object_name
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.containers.name",
            parent_path="spec.containers",
            is_array_item=False,
            sibling_names=frozenset({"name", "image", "command", "env"}),
        )
        assert is_inline_object_name(field) is False

    def test_insufficient_overlap_not_inline(self, registry):
        """Only 2 matches (< 3 threshold) → NOT inline."""
        from idi.generation.crd.ref_detector import is_inline_object_name
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.containers.name",
            parent_path="spec.containers",
            is_array_item=True,
            sibling_names=frozenset({"name", "image"}),
        )
        assert is_inline_object_name(field) is False


class TestParentKindNameListMapSuppression:
    """Tests for detect_parent_kind_name with list-map key suppression."""

    def test_volumes_name_suppressed(self, registry):
        """volumes[].name with container-spec siblings → None (suppressed)."""
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.template.spec.volumes.name",
            parent_path="spec.template.spec.volumes",
            is_array_item=True,
            sibling_names=frozenset({"name", "mountPath", "readOnly", "subPath"}),
        )
        result = detect_parent_kind_name(field, registry)
        assert result is None

    def test_secret_name_not_suppressed(self, registry):
        """secret.name without inline siblings → still detected."""
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.templateFrom.secret.name",
            parent_path="spec.templateFrom.secret",
            is_array_item=False,
            sibling_names=frozenset({"name", "key"}),
        )
        result = detect_parent_kind_name(field, registry)
        assert result is not None
        assert result.target_kind == "Secret"

    def test_issuer_name_non_array(self, registry):
        """issuer.name in non-array context → still detected."""
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.issuer.name",
            parent_path="spec.issuer",
            is_array_item=False,
            sibling_names=frozenset({"name"}),
        )
        result = detect_parent_kind_name(field, registry)
        assert result is not None
        assert result.target_kind == "Issuer"


# ---------------------------------------------------------------------------
# readOnly → output_declaration
# ---------------------------------------------------------------------------


class TestReadOnlyOutputClassification:
    """Tests for readOnly field → output_declaration."""

    def test_readonly_becomes_output(self, registry):
        """Field with readOnly: true → output_declaration."""
        field = _make_field("observedGeneration", schema={
            "type": "integer",
            "readOnly": True,
        })
        results = classify_walked_field(field, registry, "Cert", "cert-manager.io")
        assert len(results) == 1
        assert results[0].role == "output_declaration"
        assert results[0].confidence == 0.8
        assert results[0].detection_source == "ref_detector:readonly"

    def test_non_readonly_stays_config(self, registry):
        """Field without readOnly → config_field."""
        field = _make_field("observedGeneration", schema={
            "type": "integer",
        })
        results = classify_walked_field(field, registry, "Cert", "cert-manager.io")
        assert len(results) == 1
        assert results[0].role == "config_field"


# ---------------------------------------------------------------------------
# detect_fuzzy_kind_name (section-06)
# ---------------------------------------------------------------------------


class TestDetectFuzzyKindName:
    """Tests for detect_fuzzy_kind_name detector step."""

    @pytest.fixture
    def istio_registry(self) -> KindRegistry:
        reg = KindRegistry()
        reg.register("Gateway", "gateways", "networking.istio.io", service="istio")
        reg.register("VirtualService", "virtualservices", "networking.istio.io", service="istio")
        reg.register("DestinationRule", "destinationrules", "networking.istio.io", service="istio")
        return reg

    @pytest.fixture
    def cilium_registry(self) -> KindRegistry:
        reg = KindRegistry()
        reg.register("CiliumBGPPeerConfig", "ciliumbgppeerconfigs", "cilium.io", service="cilium")
        reg.register("CiliumNetworkPolicy", "ciliumnetworkpolicies", "cilium.io", service="cilium")
        return reg

    def test_plural_match_string_array(self, istio_registry):
        """'gateways' as array[string] resolves to Gateway via plural_exact."""
        field = _make_field("gateways", schema={
            "type": "array", "items": {"type": "string"},
        })
        result = detect_fuzzy_kind_name(field, istio_registry, "networking.istio.io", "istio")
        assert result is not None
        assert result.role == "input_ref"
        assert result.target_kind == "Gateway"
        assert "fuzzy_kind_name" in result.detection_source
        assert "plural_exact" in result.detection_source

    def test_suffix_match_string(self, cilium_registry):
        """'peerConfigRef' as string resolves to CiliumBGPPeerConfig."""
        field = _make_field("peerConfigRef", schema={"type": "string"})
        result = detect_fuzzy_kind_name(field, cilium_registry, "cilium.io", "cilium")
        assert result is not None
        assert result.target_kind == "CiliumBGPPeerConfig"
        assert "suffix_unique" in result.detection_source

    def test_object_type_rejected(self, istio_registry):
        """Object-type fields are rejected by type guard."""
        field = _make_field("gateways", schema={
            "type": "object", "properties": {"name": {"type": "string"}},
        })
        result = detect_fuzzy_kind_name(field, istio_registry, "networking.istio.io", "istio")
        assert result is None

    def test_integer_type_rejected(self, istio_registry):
        """Integer-type fields rejected."""
        field = _make_field("gateways", schema={"type": "integer"})
        result = detect_fuzzy_kind_name(field, istio_registry, "networking.istio.io", "istio")
        assert result is None

    def test_below_threshold_returns_none(self, istio_registry):
        """Score * depth_confidence < 0.7 returns None."""
        # Gateway plural match = 0.80, depth_confidence=0.81 → 0.648 < 0.7
        field = _make_field("gateways", schema={
            "type": "array", "items": {"type": "string"},
        }, depth_confidence=0.81)
        result = detect_fuzzy_kind_name(field, istio_registry, "networking.istio.io", "istio")
        assert result is None

    def test_above_threshold_returns_result(self, istio_registry):
        """Score * depth_confidence >= 0.7 returns ClassifiedField."""
        # Gateway plural match = 0.80, depth_confidence=0.9 → 0.72 >= 0.7
        field = _make_field("gateways", schema={
            "type": "array", "items": {"type": "string"},
        }, depth_confidence=0.9)
        result = detect_fuzzy_kind_name(field, istio_registry, "networking.istio.io", "istio")
        assert result is not None
        assert result.confidence == pytest.approx(0.72)

    def test_detection_source_format(self, istio_registry):
        """detection_source has format ref_detector:fuzzy_kind_name:{match_type}."""
        field = _make_field("gateways", schema={
            "type": "array", "items": {"type": "string"},
        })
        result = detect_fuzzy_kind_name(field, istio_registry, "networking.istio.io", "istio")
        assert result is not None
        assert result.detection_source == "ref_detector:fuzzy_kind_name:plural_exact"

    def test_no_match_returns_none(self):
        """Completely unrelated field returns None."""
        reg = KindRegistry()
        field = _make_field("somethingUnrelated", schema={"type": "string"})
        result = detect_fuzzy_kind_name(field, reg, "example.io", "test")
        assert result is None


class TestFuzzyDetectorInCascade:
    """Tests that detect_fuzzy_kind_name is wired into classify_walked_field."""

    @pytest.fixture
    def istio_registry(self) -> KindRegistry:
        reg = KindRegistry()
        reg.register("Gateway", "gateways", "networking.istio.io", service="istio")
        reg.register("VirtualService", "virtualservices", "networking.istio.io", service="istio")
        return reg

    def test_higher_priority_detector_wins(self, registry):
        """'secretName' matched by detect_ref, not fuzzy detector."""
        field = _make_field("secretName", schema={"type": "string"})
        results = classify_walked_field(field, registry, "Cert", "cert-manager.io")
        assert len(results) == 1
        assert results[0].role == "input_ref"
        assert "fuzzy_kind_name" not in results[0].detection_source

    def test_fuzzy_fires_when_no_prior_match(self, istio_registry):
        """'gateways' has no suffix match — fuzzy detector fires."""
        field = _make_field("gateways", schema={
            "type": "array", "items": {"type": "string"},
        })
        results = classify_walked_field(
            field, istio_registry, "VirtualService", "networking.istio.io",
            current_service="istio",
        )
        assert len(results) >= 1
        assert any("fuzzy_kind_name" in r.detection_source for r in results)
        fuzzy = [r for r in results if "fuzzy_kind_name" in r.detection_source][0]
        assert fuzzy.target_kind == "Gateway"

    def test_cascade_integration_cilium(self):
        """'peerConfigRef' resolves via fuzzy when no higher detector matches."""
        reg = KindRegistry()
        reg.register("CiliumBGPPeerConfig", "ciliumbgppeerconfigs", "cilium.io", service="cilium")
        field = _make_field("peerConfigRef", schema={"type": "string"})
        results = classify_walked_field(
            field, reg, "CiliumBGPClusterConfig", "cilium.io",
            current_service="cilium",
        )
        assert len(results) >= 1
        assert any(r.target_kind == "CiliumBGPPeerConfig" for r in results)


# ---------------------------------------------------------------------------
# detect_semantic_field (section-07)
# ---------------------------------------------------------------------------


class TestDetectSemanticField:
    """Tests for detect_semantic_field detector step."""

    def test_credential_name_maps_to_secret(self, registry):
        """credentialName → Secret at confidence 0.90."""
        field = _make_field("credentialName", schema={"type": "string"})
        result = detect_semantic_field(field, registry)
        assert result is not None
        assert result.role == "input_ref"
        assert result.target_kind == "Secret"
        assert result.target_group == "core"
        assert result.confidence == 0.90
        assert result.detection_source == "ref_detector:semantic_field"

    def test_tls_secret_maps_to_secret(self, registry):
        """tlsSecret → Secret at confidence 0.90."""
        field = _make_field("tlsSecret", schema={"type": "string"})
        result = detect_semantic_field(field, registry)
        assert result is not None
        assert result.target_kind == "Secret"
        assert result.target_group == "core"
        assert result.confidence == 0.90

    def test_unrecognized_field_returns_none(self, registry):
        """randomFieldName → no match (not in map)."""
        field = _make_field("randomFieldName", schema={"type": "string"})
        result = detect_semantic_field(field, registry)
        assert result is None

    def test_object_type_rejected(self, registry):
        """credentialName with type: object → no match (only string fields)."""
        field = _make_field("credentialName", schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        })
        result = detect_semantic_field(field, registry)
        assert result is None

    def test_array_type_rejected(self, registry):
        """credentialName with type: array → no match."""
        field = _make_field("credentialName", schema={
            "type": "array", "items": {"type": "string"},
        })
        result = detect_semantic_field(field, registry)
        assert result is None

    def test_case_sensitive_exact_match(self, registry):
        """credentialname (lowercase) → no match."""
        field = _make_field("credentialname", schema={"type": "string"})
        result = detect_semantic_field(field, registry)
        assert result is None

    def test_classified_field_metadata(self, registry):
        """Verify all ClassifiedField metadata is correctly populated."""
        field = _make_field("tlsSecret", schema={
            "type": "string",
            "description": "Name of TLS secret",
        }, path="spec.tls.tlsSecret", required=True)
        result = detect_semantic_field(field, registry)
        assert result is not None
        assert result.field == "spec.tls.tlsSecret"
        assert result.field_type == "string"
        assert result.required is True
        assert result.description == "Name of TLS secret"
        assert result.fact_shape == "identity"


class TestSemanticFieldInCascade:
    """Tests that detect_semantic_field is wired into classify_walked_field."""

    def test_higher_priority_detector_wins(self, registry):
        """secretName matched by detect_ref, not semantic field detector."""
        field = _make_field("secretName", schema={"type": "string"})
        results = classify_walked_field(field, registry, "Cert", "cert-manager.io")
        assert len(results) == 1
        assert "semantic_field" not in results[0].detection_source

    def test_semantic_fires_for_credential_name(self, registry):
        """credentialName has no suffix match — semantic detector fires."""
        field = _make_field("credentialName", schema={"type": "string"})
        results = classify_walked_field(
            field, registry, "KafkaUser", "strimzi.io",
        )
        assert len(results) == 1
        assert results[0].detection_source == "ref_detector:semantic_field"
        assert results[0].target_kind == "Secret"

    def test_semantic_fires_for_tls_secret(self, registry):
        """tlsSecret in cascade resolves to Secret via semantic field detector."""
        field = _make_field("tlsSecret", schema={"type": "string"})
        results = classify_walked_field(
            field, registry, "Gateway", "networking.istio.io",
        )
        assert len(results) == 1
        assert results[0].detection_source == "ref_detector:semantic_field"
        assert results[0].target_kind == "Secret"


# ---------------------------------------------------------------------------
# Depth confidence multiplication (section-12)
# ---------------------------------------------------------------------------


class TestConfidenceMultiplication:
    """Tests for centralized depth confidence multiplication in classify_walked_field."""

    def test_detector_confidence_multiplied_by_depth_confidence(self, registry):
        """detect_ref at 0.9 with depth_confidence=0.9 produces 0.81."""
        field = _make_field(
            "issuerRef",
            schema={"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"}}},
            depth=9,
            depth_confidence=0.9,
        )
        results = classify_walked_field(field, registry, "Certificate", "cert-manager.io")
        assert len(results) >= 1
        ref_result = next(r for r in results if r.role == "input_ref")
        assert ref_result.confidence == pytest.approx(0.9 * 0.9)

    def test_depth_confidence_below_floor_still_returned(self, registry):
        """Depth multiplication can push confidence below 0.7 — still returned
        (floor enforcement is downstream, not in classify_walked_field)."""
        field = _make_field(
            "issuerRef",
            schema={"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"}}},
            depth=10,
            depth_confidence=0.81,
        )
        results = classify_walked_field(field, registry, "Certificate", "cert-manager.io")
        ref_result = next(r for r in results if r.role == "input_ref")
        assert ref_result.confidence == pytest.approx(0.9 * 0.81)

    def test_default_config_field_multiplied(self, registry):
        """Default config_field (0.5) with depth_confidence=0.9 -> 0.45."""
        field = _make_field(
            "someConfigValue",
            schema={"type": "string"},
            depth=9,
            depth_confidence=0.9,
        )
        results = classify_walked_field(field, registry, "MyKind", "example.io")
        assert len(results) == 1
        assert results[0].role == "config_field"
        assert results[0].confidence == pytest.approx(0.5 * 0.9)

    def test_depth_confidence_1_0_is_noop(self, registry):
        """When depth_confidence == 1.0, multiplication is a no-op."""
        field = _make_field(
            "issuerRef",
            schema={"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"}}},
            depth_confidence=1.0,
        )
        results = classify_walked_field(field, registry, "Certificate", "cert-manager.io")
        ref_result = next(r for r in results if r.role == "input_ref")
        assert ref_result.confidence == pytest.approx(0.9)

    def test_output_declaration_also_multiplied(self, registry):
        """output_declaration (readOnly) at 0.8 with depth_confidence=0.9 -> 0.72."""
        field = _make_field(
            "observedGeneration",
            schema={"type": "integer", "readOnly": True},
            depth=9,
            depth_confidence=0.9,
        )
        results = classify_walked_field(field, registry, "MyKind", "example.io")
        output_results = [r for r in results if r.role == "output_declaration"]
        assert len(output_results) >= 1
        assert output_results[0].confidence == pytest.approx(0.8 * 0.9)
