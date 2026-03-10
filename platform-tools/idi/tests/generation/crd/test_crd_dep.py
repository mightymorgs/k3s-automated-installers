"""Tests for CrdDepAdapter refactor — CRD Phase 1a."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.dep_adapters.crd_dep import CrdDepAdapter


@pytest.fixture
def registry():
    """Registry with core + test CRDs."""
    reg = KindRegistry()
    reg.register("SecretStore", "secretstores", "external-secrets.io")
    reg.register("ClusterSecretStore", "clustersecretstores", "external-secrets.io")
    reg.register("Certificate", "certificates", "cert-manager.io")
    return reg


@pytest.fixture
def adapter(registry):
    return CrdDepAdapter(registry=registry)


# ---------------------------------------------------------------------------
# _resolve_target
# ---------------------------------------------------------------------------


class TestResolveTarget:
    def test_target_in_known_resources(self, adapter):
        """Target in known_resources -> (target, False)."""
        result = adapter._resolve_target("secrets", {"secrets", "configmaps"})
        assert result == ("secrets", False)

    def test_target_lowercase_match(self, adapter):
        """Lowercase matching in known_resources."""
        result = adapter._resolve_target("Secrets", {"secrets"})
        assert result == ("secrets", False)

    def test_core_plural_cross_service(self, adapter):
        """Core plural not in known_resources -> cross-service."""
        result = adapter._resolve_target("secrets", set())
        assert result == ("secrets", True)

    def test_deployments_cross_service(self, adapter):
        """Deployments is core -> cross-service."""
        result = adapter._resolve_target("deployments", set())
        assert result == ("deployments", True)

    def test_crd_plural_not_cross_service(self, adapter):
        """CRD plural 'secretstores' not in known_resources -> NOT cross-service."""
        result = adapter._resolve_target("secretstores", set())
        assert result == (None, False)

    def test_completely_unknown(self, adapter):
        """Unknown target -> (None, False)."""
        result = adapter._resolve_target("unknownresource", set())
        assert result == (None, False)


# ---------------------------------------------------------------------------
# ESO CRDs not cross-service (behavior change)
# ---------------------------------------------------------------------------


class TestEsoBehaviorChange:
    def test_secretstores_not_in_core_plurals(self, registry):
        assert "secretstores" not in registry.core_plurals()

    def test_clustersecretstores_not_in_core_plurals(self, registry):
        assert "clustersecretstores" not in registry.core_plurals()

    def test_resolve_secretstores_empty_known(self, adapter):
        """secretstores without known_resources -> None (no longer cross-service)."""
        result = adapter._resolve_target("secretstores", set())
        assert result == (None, False)

    def test_resolve_secretstores_in_known(self, adapter):
        """secretstores in known_resources -> works."""
        result = adapter._resolve_target("secretstores", {"secretstores"})
        assert result == ("secretstores", False)


# ---------------------------------------------------------------------------
# _walk_and_detect skip logic
# ---------------------------------------------------------------------------


class TestWalkAndDetectSkip:
    def test_ref_fields_skipped_during_recursion(self, adapter, registry):
        """Fields matching registry.is_ref_field are not recursed into."""
        from idi.generation.adapters.kubernetes_crd import KubernetesCrdAdapter
        k8s_adapter = KubernetesCrdAdapter(service="test", registry=registry)

        schema = {
            "properties": {
                "secretRef": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "nested": {
                            "type": "object",
                            "properties": {
                                "deepSecretRef": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                },
                            },
                        },
                    },
                },
            },
        }
        results = []
        adapter._walk_and_detect(
            k8s_adapter, schema, "test",
            {"secrets"}, results, depth=0,
        )
        # secretRef should be detected, but not recursed into for deeper refs.
        fields = [r.field for r in results]
        assert "secretRef" in fields
        # deepSecretRef should NOT be found since we skip recursion into secretRef.
        assert "deepSecretRef" not in fields

    def test_k8s_envelope_skipped(self, adapter, registry):
        """_K8S_ENVELOPE fields are skipped."""
        from idi.generation.adapters.kubernetes_crd import KubernetesCrdAdapter
        k8s_adapter = KubernetesCrdAdapter(service="test", registry=registry)

        schema = {
            "properties": {
                "metadata": {
                    "type": "object",
                    "properties": {
                        "secretRef": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                    },
                },
            },
        }
        results = []
        adapter._walk_and_detect(
            k8s_adapter, schema, "test", {"secrets"}, results, depth=0,
        )
        # Metadata is in _K8S_ENVELOPE, so nothing should be found inside it.
        assert len(results) == 0

    def test_nested_objects_recursed(self, adapter, registry):
        """Nested objects ARE recursed into."""
        from idi.generation.adapters.kubernetes_crd import KubernetesCrdAdapter
        k8s_adapter = KubernetesCrdAdapter(service="test", registry=registry)

        schema = {
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "secretRef": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                    },
                },
            },
        }
        results = []
        adapter._walk_and_detect(
            k8s_adapter, schema, "test", {"secrets"}, results, depth=0,
        )
        assert any(r.field == "secretRef" for r in results)


# ---------------------------------------------------------------------------
# detect_dependencies integration
# ---------------------------------------------------------------------------


class TestDetectDependencies:
    def _make_operation(self, service="test", body_schema=None):
        from idi.generation.dep_adapters.base import OperationInfo
        return OperationInfo(
            service=service,
            resource="testresource",
            operation="create",
            method="POST",
            path="/apis/test.io/v1/namespaces/{namespace}/testresources",
            body_schema=body_schema,
            response_schema=None,
        )

    def test_secret_ref_produces_dependency(self, adapter):
        """CRD body with secretRef produces a Dependency."""
        body = {
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {
                        "secretRef": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                    },
                },
            },
        }
        op = self._make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secrets"})
        assert len(deps) >= 1
        assert deps[0].target_resource == "secrets"

    def test_cross_service_has_k8s_service(self, adapter):
        """Cross-service dependency has target_service='k8s'."""
        body = {
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {
                        "secretRef": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                    },
                },
            },
        }
        op = self._make_operation(service="cert-manager", body_schema=body)
        # secrets not in known_resources -> cross-service
        deps = adapter.detect_dependencies(op, {}, set())
        secret_deps = [d for d in deps if d.target_resource == "secrets"]
        assert len(secret_deps) >= 1
        assert secret_deps[0].target_service == "k8s"

    def test_empty_body_returns_empty(self, adapter):
        """Operation with no body returns empty list."""
        op = self._make_operation(body_schema=None)
        deps = adapter.detect_dependencies(op, {}, set())
        assert deps == []


# ---------------------------------------------------------------------------
# Default no-arg construction
# ---------------------------------------------------------------------------


class TestDefaultConstruction:
    def test_no_arg_instantiation(self):
        """CrdDepAdapter can be instantiated without args (for discovery)."""
        adapter = CrdDepAdapter()
        assert adapter.registry is not None
        assert "secrets" in adapter.registry.core_plurals()
