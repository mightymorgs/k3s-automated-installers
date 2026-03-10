"""Tests for CrdDepAdapter — CRD Phase 2 Section 04."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.dep_adapters.base import OperationInfo
from idi.generation.dep_adapters.crd_dep import CrdDepAdapter


@pytest.fixture
def registry():
    """Registry with core + test CRDs."""
    reg = KindRegistry()
    reg.register("SecretStore", "secretstores", "external-secrets.io")
    reg.register("ClusterSecretStore", "clustersecretstores", "external-secrets.io")
    reg.register("Certificate", "certificates", "cert-manager.io")
    reg.register("Issuer", "issuers", "cert-manager.io")
    reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io")
    return reg


@pytest.fixture
def adapter(registry):
    return CrdDepAdapter(registry=registry)


def _make_operation(service="test", body_schema=None, response_schema=None):
    return OperationInfo(
        service=service,
        resource="testresource",
        operation="create",
        method="POST",
        path="/apis/test.io/v1/namespaces/{namespace}/testresources",
        body_schema=body_schema or {},
        response_schema=response_schema or {},
    )


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
# ESO CRDs not cross-service
# ---------------------------------------------------------------------------


class TestEsoBehaviorChange:
    def test_secretstores_not_in_core_plurals(self, registry):
        assert "secretstores" not in registry.core_plurals()

    def test_clustersecretstores_not_in_core_plurals(self, registry):
        assert "clustersecretstores" not in registry.core_plurals()

    def test_resolve_secretstores_empty_known(self, adapter):
        """secretstores without known_resources -> None."""
        result = adapter._resolve_target("secretstores", set())
        assert result == (None, False)

    def test_resolve_secretstores_in_known(self, adapter):
        """secretstores in known_resources -> works."""
        result = adapter._resolve_target("secretstores", {"secretstores"})
        assert result == ("secretstores", False)


# ---------------------------------------------------------------------------
# detect_dependencies
# ---------------------------------------------------------------------------


class TestDetectDependencies:
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
        op = _make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secrets"})
        assert len(deps) >= 1
        assert deps[0].target_resource == "secrets"

    def test_crdfacts_uri_format(self, adapter):
        """URI format is crdfacts://{target_group}/{target_kind}#{target_field}."""
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
        op = _make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secrets"})
        assert len(deps) >= 1
        assert deps[0].fact_ref == "crdfacts://core/Secret#name"

    def test_no_facts_uri_in_output(self, adapter):
        """No facts:// URIs in output (regression check)."""
        body = {
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {
                        "secretRef": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                        "configMapRef": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                    },
                },
            },
        }
        op = _make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secrets", "configmaps"})
        for dep in deps:
            assert not dep.fact_ref.startswith("facts://")
            assert dep.fact_ref.startswith("crdfacts://")

    def test_required_field_satisfaction(self, adapter):
        """Required field -> satisfaction='required_value'."""
        body = {
            "properties": {
                "spec": {
                    "type": "object",
                    "required": ["secretRef"],
                    "properties": {
                        "secretRef": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                    },
                },
            },
        }
        op = _make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secrets"})
        assert len(deps) >= 1
        assert deps[0].satisfaction == "required_value"

    def test_optional_field_satisfaction(self, adapter):
        """Optional field -> satisfaction='optional_with_default'."""
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
        op = _make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secrets"})
        assert len(deps) >= 1
        assert deps[0].satisfaction == "optional_with_default"

    def test_nested_ref_depth_4(self, adapter):
        """Nested ref at depth 4 (SecretStore pattern) detected."""
        body = {
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {
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
                                                    "properties": {
                                                        "name": {"type": "string"},
                                                    },
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        op = _make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secrets"})
        secret_deps = [d for d in deps if d.target_resource == "secrets"]
        assert len(secret_deps) >= 1
        assert "tokenSecretRef" in secret_deps[0].field

    def test_array_ref_detected(self, adapter):
        """Array ref (PushSecret pattern) detected."""
        body = {
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {
                        "secretStoreRefs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        }
        op = _make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secretstores"})
        store_deps = [d for d in deps if d.target_resource == "secretstores"]
        assert len(store_deps) >= 1

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
        op = _make_operation(service="cert-manager", body_schema=body)
        deps = adapter.detect_dependencies(op, {}, set())
        secret_deps = [d for d in deps if d.target_resource == "secrets"]
        assert len(secret_deps) >= 1
        assert secret_deps[0].target_service == "k8s"

    def test_empty_body_returns_empty(self, adapter):
        """Operation with no body returns empty list."""
        op = _make_operation(body_schema=None)
        deps = adapter.detect_dependencies(op, {}, set())
        assert deps == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_parent_child_dedup(self, adapter):
        """secretRef (parent) and secretRef.name (child) — only parent produces Dependency."""
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
        op = _make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secrets"})
        # Should have exactly 1 dep for secretRef, not 2
        # (the child spec.secretRef.name is deduplicated)
        secret_deps = [d for d in deps if d.target_resource == "secrets"]
        assert len(secret_deps) == 1
        assert "secretRef" in secret_deps[0].field

    def test_sibling_refs_both_kept(self, adapter):
        """Two sibling refs both produce Dependencies."""
        body = {
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {
                        "secretRef": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                        "configMapRef": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                    },
                },
            },
        }
        op = _make_operation(body_schema=body)
        deps = adapter.detect_dependencies(op, {}, {"secrets", "configmaps"})
        targets = {d.target_resource for d in deps}
        assert "secrets" in targets
        assert "configmaps" in targets


# ---------------------------------------------------------------------------
# detect_outputs
# ---------------------------------------------------------------------------


class TestDetectOutputs:
    def test_status_field_with_kind_name(self, adapter):
        """Status field with Kind name -> Output emitted."""
        body = {
            "properties": {
                "status": {
                    "type": "object",
                    "properties": {
                        "serviceName": {"type": "string"},
                    },
                },
            },
        }
        op = _make_operation(body_schema=body)
        outputs = adapter.detect_outputs(op, {})
        assert len(outputs) >= 1
        assert any("serviceName" in o.field for o in outputs)

    def test_status_conditions_output(self, adapter):
        """Status conditions -> Output emitted."""
        body = {
            "properties": {
                "status": {
                    "type": "object",
                    "properties": {
                        "conditions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        }
        op = _make_operation(body_schema=body)
        outputs = adapter.detect_outputs(op, {})
        assert len(outputs) >= 1

    def test_generic_status_not_emitted(self, adapter):
        """Generic status field (confidence 0.6) -> NOT emitted."""
        body = {
            "properties": {
                "status": {
                    "type": "object",
                    "properties": {
                        "observedGeneration": {"type": "integer"},
                        "phase": {"type": "string"},
                    },
                },
            },
        }
        op = _make_operation(body_schema=body)
        outputs = adapter.detect_outputs(op, {})
        # Generic status fields are below 0.7 threshold
        fields = [o.field for o in outputs]
        assert "status.observedGeneration" not in fields
        assert "status.phase" not in fields

    def test_no_status_returns_empty(self, adapter):
        """Body with no status schema returns empty outputs."""
        body = {
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {"foo": {"type": "string"}},
                },
            },
        }
        op = _make_operation(body_schema=body)
        outputs = adapter.detect_outputs(op, {})
        assert outputs == []

    def test_output_uses_crdfacts_uri(self, adapter):
        """Output fact_ref uses crdfacts:// scheme."""
        body = {
            "properties": {
                "status": {
                    "type": "object",
                    "properties": {
                        "conditions": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                    },
                },
            },
        }
        op = _make_operation(body_schema=body)
        outputs = adapter.detect_outputs(op, {})
        for out in outputs:
            assert out.fact_ref.startswith("crdfacts://")


# ---------------------------------------------------------------------------
# matches()
# ---------------------------------------------------------------------------


class TestMatches:
    def test_matches_apis_path(self, adapter):
        """matches() returns True for /apis/ paths."""
        spec = {"paths": {"/apis/test.io/v1/namespaces/{ns}/things": {}}}
        assert adapter.matches(spec, "test") is True

    def test_matches_api_v1_namespaces(self, adapter):
        """matches() returns True for /api/v1/namespaces paths."""
        spec = {"paths": {"/api/v1/namespaces/{ns}/configmaps": {}}}
        assert adapter.matches(spec, "test") is True

    def test_no_match(self, adapter):
        """matches() returns False for non-K8s paths."""
        spec = {"paths": {"/v1/users": {}}}
        assert adapter.matches(spec, "test") is False


# ---------------------------------------------------------------------------
# Default no-arg construction
# ---------------------------------------------------------------------------


class TestDefaultConstruction:
    def test_no_arg_instantiation(self):
        """CrdDepAdapter can be instantiated without args (for discovery)."""
        adapter = CrdDepAdapter()
        assert adapter.registry is not None
        assert "secrets" in adapter.registry.core_plurals()
