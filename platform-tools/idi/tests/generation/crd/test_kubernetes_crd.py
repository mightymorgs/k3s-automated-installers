"""Tests for KubernetesCrdAdapter refactor — CRD Phase 1a."""
from __future__ import annotations

import pytest

from idi.generation.adapters.kubernetes_crd import KubernetesCrdAdapter
from idi.generation.crd.kind_registry import KindRegistry


@pytest.fixture
def registry():
    """Registry with core + external-secrets CRDs."""
    reg = KindRegistry()
    reg.register("SecretStore", "secretstores", "external-secrets.io")
    reg.register("ClusterSecretStore", "clustersecretstores", "external-secrets.io")
    reg.register("ExternalSecret", "externalsecrets", "external-secrets.io")
    reg.register("Issuer", "issuers", "cert-manager.io")
    return reg


@pytest.fixture
def adapter(registry):
    """KubernetesCrdAdapter with registry."""
    return KubernetesCrdAdapter(
        service="external-secrets",
        registry=registry,
        known_resources={"externalsecrets", "secretstores", "clustersecretstores"},
    )


# ---------------------------------------------------------------------------
# extract_field_refs
# ---------------------------------------------------------------------------


class TestExtractFieldRefs:
    def test_secret_ref(self, adapter):
        """Schema with secretRef returns secrets target."""
        schema = {
            "properties": {
                "secretRef": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        assert len(refs) >= 1
        secret_refs = [r for r in refs if r["field"] == "secretRef"]
        assert len(secret_refs) >= 1
        assert secret_refs[0]["target_resource"] == "secrets"

    def test_configmap_key_ref(self, adapter):
        """Schema with configMapKeyRef returns configmaps."""
        schema = {
            "properties": {
                "configMapKeyRef": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "key": {"type": "string"}},
                },
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        matched = [r for r in refs if r["field"] == "configMapKeyRef"]
        assert len(matched) >= 1
        assert matched[0]["target_resource"] == "configmaps"

    def test_secret_store_ref(self, adapter):
        """Schema with secretStoreRef returns secretstores."""
        schema = {
            "properties": {
                "secretStoreRef": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        matched = [r for r in refs if r["field"] == "secretStoreRef"]
        assert len(matched) >= 1
        assert matched[0]["target_resource"] == "secretstores"

    def test_unknown_field_empty(self, adapter):
        """Schema with unknown field returns no refs."""
        schema = {
            "properties": {
                "fooBar": {"type": "string"},
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        assert refs == []

    def test_excluded_fields_skipped(self, adapter):
        """EXCLUDED_FIELDS (status, namespace, etc.) are skipped."""
        schema = {
            "properties": {
                "status": {"type": "object"},
                "namespace": {"type": "string"},
                "apiVersion": {"type": "string"},
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        assert refs == []

    def test_cross_namespace_detection(self, adapter):
        """Schema with namespace property -> cross_namespace: True."""
        schema = {
            "properties": {
                "secretRef": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "namespace": {"type": "string"},
                    },
                },
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        secret_refs = [r for r in refs if r["field"] == "secretRef"]
        assert len(secret_refs) >= 1
        assert secret_refs[0]["cross_namespace"] is True

    def test_object_reference(self, adapter):
        """Schema with $ref to ObjectReference returns type k8s_ref with target 'any'."""
        schema = {
            "properties": {
                "sourceRef": {
                    "$ref": "io.k8s.api.core.v1.ObjectReference",
                },
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        assert len(refs) == 1
        assert refs[0]["target_resource"] == "any"
        assert refs[0]["source"] == "objectref"

    def test_label_selector_skipped(self, adapter):
        """Schema with $ref to LabelSelector is skipped."""
        schema = {
            "properties": {
                "selector": {
                    "$ref": "io.k8s.apimachinery.pkg.apis.meta.v1.LabelSelector",
                },
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        assert refs == []

    def test_none_schema(self, adapter):
        """None schema returns empty list."""
        assert adapter.extract_field_refs(None, "x") == []

    def test_empty_schema(self, adapter):
        """Empty dict schema returns empty list."""
        assert adapter.extract_field_refs({}, "x") == []


# ---------------------------------------------------------------------------
# _match_ref_pattern
# ---------------------------------------------------------------------------


class TestMatchRefPattern:
    def test_secret_ref(self, adapter):
        assert adapter._match_ref_pattern("secretRef") == "secrets"

    def test_configmap_ref(self, adapter):
        assert adapter._match_ref_pattern("configMapRef") == "configmaps"

    def test_secret_store_ref(self, adapter):
        assert adapter._match_ref_pattern("secretStoreRef") == "secretstores"

    def test_unknown_ref(self, adapter):
        assert adapter._match_ref_pattern("unknownRef") is None

    def test_secret_key_ref(self, adapter):
        """Well-known compound: secretKeyRef -> secrets."""
        assert adapter._match_ref_pattern("secretKeyRef") == "secrets"


# ---------------------------------------------------------------------------
# _infer_target_from_field_name
# ---------------------------------------------------------------------------


class TestInferTarget:
    def test_secret_store_ref_via_registry(self, adapter):
        assert adapter._infer_target_from_field_name("secretStoreRef") == "secretstores"

    def test_issuer_ref_via_registry(self, adapter):
        assert adapter._infer_target_from_field_name("issuerRef") == "issuers"

    def test_unknown_thing_ref_fallback(self, adapter):
        """Unknown ref falls back to naive pluralization."""
        result = adapter._infer_target_from_field_name("unknownThingRef")
        assert result == "unknownthings"


# ---------------------------------------------------------------------------
# *Name field detection
# ---------------------------------------------------------------------------


class TestNameFieldDetection:
    def test_secret_name(self, adapter):
        """secretName (type: string) -> secrets."""
        schema = {
            "properties": {
                "secretName": {"type": "string"},
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        matched = [r for r in refs if r["field"] == "secretName"]
        assert len(matched) == 1
        assert matched[0]["target_resource"] == "secrets"
        assert matched[0]["source"] in ("k8s_ref_pattern", "k8s_name_pattern")

    def test_configmap_name(self, adapter):
        """configMapName -> configmaps."""
        schema = {
            "properties": {
                "configMapName": {"type": "string"},
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        matched = [r for r in refs if r["field"] == "configMapName"]
        assert len(matched) == 1
        assert matched[0]["target_resource"] == "configmaps"
        assert matched[0]["source"] in ("k8s_ref_pattern", "k8s_name_pattern")

    def test_unknown_name_no_match(self, adapter):
        """unknownName (not in registry) -> no match."""
        schema = {
            "properties": {
                "unknownName": {"type": "string"},
            },
        }
        refs = adapter.extract_field_refs(schema, "externalsecret")
        assert refs == []


# ---------------------------------------------------------------------------
# Regression: secretStoreRef longest match
# ---------------------------------------------------------------------------


class TestLongestMatchRegression:
    def test_secret_store_ref_not_secret(self, adapter):
        """secretStoreRef matches SecretStore, NOT Secret."""
        result = adapter._match_ref_pattern("secretStoreRef")
        assert result == "secretstores"

    def test_cluster_secret_store_ref(self, adapter):
        """clusterSecretStoreRef matches ClusterSecretStore."""
        result = adapter._match_ref_pattern("clusterSecretStoreRef")
        assert result == "clustersecretstores"
