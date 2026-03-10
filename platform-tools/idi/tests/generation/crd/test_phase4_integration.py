"""Integration tests for CRD Phase 4 — OLM + RBAC adapters.

Validates cross-adapter merge behavior, auto-discovery, KindRegistry
population, and graceful degradation.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.dep_adapters.base import Dependency, OperationInfo, Output
from idi.generation.dep_adapters.merge import filter_self_refs, merge_deps, merge_outputs
from idi.generation.dep_adapters.olm_deps import OlmDepAdapter
from idi.generation.dep_adapters.rbac_deps import RbacDepAdapter, extract_rbac_edges

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase4"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_operation(
    service: str = "cert-manager",
    resource: str = "certificates",
) -> OperationInfo:
    return OperationInfo(
        service=service,
        resource=resource,
        operation="create",
        method="POST",
        path=f"/apis/test.io/v1/namespaces/{{ns}}/{resource}",
        body_schema={},
        response_schema={},
    )


# ---------------------------------------------------------------------------
# Test 1: OLM Confidence Wins Over RBAC in Merge
# ---------------------------------------------------------------------------


class TestMergeBehavior:
    def test_olm_wins_over_rbac_same_key(self):
        """OLM Dependency (0.95) wins over RBAC Dependency (0.7) for same key."""
        olm_dep = Dependency(
            field="olm:required:cert-manager.io/Issuer",
            target_resource="issuers",
            confidence=0.95,
            source="olm_deps:required",
        )
        rbac_dep = Dependency(
            field="olm:required:cert-manager.io/Issuer",
            target_resource="issuers",
            confidence=0.7,
            source="rbac_deps:read_only",
        )
        merged = merge_deps([olm_dep, rbac_dep])
        assert len(merged) == 1
        assert merged[0].confidence == 0.95
        assert merged[0].source == "olm_deps:required"

    def test_different_field_keys_both_survive(self):
        """OLM and RBAC with different field keys both survive merge."""
        olm_dep = Dependency(
            field="olm:required:cert-manager.io/Issuer",
            target_resource="issuers",
            confidence=0.95,
            source="olm_deps:required",
        )
        rbac_dep = Dependency(
            field="rbac:read:issuers",
            target_resource="issuers",
            confidence=0.7,
            source="rbac_deps:read_only",
        )
        merged = merge_deps([olm_dep, rbac_dep])
        assert len(merged) == 2

    def test_rbac_output_uncontested(self):
        """RBAC Output edges pass through merge_outputs uncontested."""
        rbac_output = Output(
            field="rbac:create:secrets",
            fact_ref="crdfacts://core/Secret#name",
            source="rbac_deps:create_watch",
            priority=3,
        )
        merged = merge_outputs([rbac_output])
        assert len(merged) == 1
        assert merged[0].priority == 3

    def test_self_reference_filtered(self):
        """Self-referencing dependencies filtered out."""
        dep = Dependency(
            field="rbac:read:certificates",
            target_resource="certificates",
            confidence=0.7,
            source="rbac_deps:read_only",
        )
        filtered = filter_self_refs([dep], "certificates")
        assert filtered == []

    def test_non_self_reference_kept(self):
        """Non-self-referencing dependency kept."""
        dep = Dependency(
            field="rbac:read:secrets",
            target_resource="secrets",
            confidence=0.7,
        )
        filtered = filter_self_refs([dep], "certificates")
        assert len(filtered) == 1


# ---------------------------------------------------------------------------
# Test 2: Cross-Adapter Complementarity
# ---------------------------------------------------------------------------


class TestCrossAdapterComplementarity:
    def test_rbac_produces_outputs_olm_does_not(self):
        """RBAC produces Output edges that OLM cannot."""
        reg = KindRegistry()
        reg.register("Certificate", "certificates", "cert-manager.io")

        olm_adapter = OlmDepAdapter(registry=reg)
        rbac_adapter = RbacDepAdapter(registry=reg)

        op = _make_operation()

        # OLM never produces outputs.
        olm_outputs = olm_adapter.detect_outputs(op, {})
        assert olm_outputs == []

        # RBAC can produce outputs (when chart is available).
        # Here we test with inline YAML via extract_rbac_edges.
        import yaml
        yaml_content = yaml.dump({
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "test"},
            "rules": [
                {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
                 "verbs": ["get", "list", "watch"]},
                {"apiGroups": [""], "resources": ["secrets"],
                 "verbs": ["create", "get", "list", "watch"]},
            ],
        })
        _, rbac_outputs = extract_rbac_edges(yaml_content, reg)
        assert len(rbac_outputs) >= 1

    def test_olm_produces_high_confidence_deps(self):
        """OLM produces higher confidence Dependency (0.95) than RBAC (0.7)."""
        reg = KindRegistry()
        reg.register("Certificate", "certificates", "cert-manager.io")

        olm_csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [],
                    "required": [
                        {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
                    ],
                },
            },
        }

        adapter = OlmDepAdapter(registry=reg)

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=olm_csv):
            deps = adapter.detect_dependencies(_make_operation(service="test-svc"), {}, set())

        assert len(deps) == 1
        assert deps[0].confidence == 0.95


# ---------------------------------------------------------------------------
# Test 3: KindRegistry Population from OLM
# ---------------------------------------------------------------------------


class TestKindRegistryPopulation:
    def test_olm_owned_accessible_in_registry(self):
        """OLM owned GVKs accessible in KindRegistry after adapter runs."""
        reg = KindRegistry()
        adapter = OlmDepAdapter(registry=reg)

        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"name": "externalsecrets.external-secrets.io",
                         "kind": "ExternalSecret", "version": "v1beta1"},
                        {"name": "secretstores.external-secrets.io",
                         "kind": "SecretStore", "version": "v1beta1"},
                    ],
                    "required": [],
                },
            },
        }

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            adapter.detect_dependencies(
                _make_operation(service="external-secrets"), {}, set(),
            )

        # Kinds should be registered.
        assert reg.kind_to_plural("ExternalSecret") == "externalsecrets"
        assert reg.kind_to_plural("SecretStore") == "secretstores"
        assert reg.group_for_kind("ExternalSecret") == "external-secrets.io"

    def test_rbac_can_use_olm_registered_kinds(self):
        """RBAC adapter can use Kinds registered by OLM (priority 95 > 70)."""
        reg = KindRegistry()

        # First: OLM registers ExternalSecret.
        olm_adapter = OlmDepAdapter(registry=reg)
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"name": "externalsecrets.external-secrets.io",
                         "kind": "ExternalSecret", "version": "v1beta1"},
                    ],
                    "required": [],
                },
            },
        }

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            olm_adapter.detect_dependencies(
                _make_operation(service="external-secrets"), {}, set(),
            )

        # Now RBAC can look up ExternalSecret in the shared registry.
        assert reg.plural_to_kind("externalsecrets") == "ExternalSecret"


# ---------------------------------------------------------------------------
# Test 4: Auto-Discovery
# ---------------------------------------------------------------------------


class TestAutoDiscovery:
    def test_olm_adapter_discovered(self):
        """DepAdapterRegistry discovers OlmDepAdapter."""
        from idi.generation.dep_adapters.registry import DepAdapterRegistry
        registry = DepAdapterRegistry()
        adapter_names = [a.name for a in registry._adapters]
        assert "olm_deps" in adapter_names

    def test_rbac_adapter_discovered(self):
        """DepAdapterRegistry discovers RbacDepAdapter."""
        from idi.generation.dep_adapters.registry import DepAdapterRegistry
        registry = DepAdapterRegistry()
        adapter_names = [a.name for a in registry._adapters]
        assert "rbac_deps" in adapter_names

    def test_correct_priority_order(self):
        """Both adapters in correct priority order (OLM > RBAC)."""
        from idi.generation.dep_adapters.registry import DepAdapterRegistry
        registry = DepAdapterRegistry()
        adapter_map = {a.name: a.priority for a in registry._adapters}
        assert adapter_map.get("olm_deps", 0) > adapter_map.get("rbac_deps", 0)


# ---------------------------------------------------------------------------
# Test 5: OPERATOR_SIDE_EFFECTS Validation
# ---------------------------------------------------------------------------


class TestSideEffectsValidation:
    def test_rbac_discovers_certmanager_creates_secrets(self):
        """RBAC discovers cert-manager creates Secrets (using golden fixture)."""
        reg = KindRegistry()
        reg.register("Certificate", "certificates", "cert-manager.io")
        reg.register("Issuer", "issuers", "cert-manager.io")
        reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io")
        reg.register("CertificateRequest", "certificaterequests", "cert-manager.io")
        reg.register("Ingress", "ingresses", "networking.k8s.io")

        fixture_path = _FIXTURES_DIR / "rbac_cert_manager.yaml"
        yaml_content = fixture_path.read_text(encoding="utf-8")
        _, outputs = extract_rbac_edges(yaml_content, reg)

        # Find the Secret creation output.
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert len(secret_outputs) >= 1
        assert any(o.source == "rbac_deps:create_watch" for o in secret_outputs)

    def test_rbac_matches_side_effect_registry_entry(self):
        """RBAC result matches OPERATOR_SIDE_EFFECTS entry for cert-manager."""
        from idi.generation.crd.side_effect_registry import OPERATOR_SIDE_EFFECTS

        cert_effects = OPERATOR_SIDE_EFFECTS.get(("cert-manager.io", "Certificate"), [])
        # The dictionary says cert-manager Certificate produces Secret.
        produces_secret = any(e["produces_kind"] == "Secret" for e in cert_effects)
        assert produces_secret, "OPERATOR_SIDE_EFFECTS should have cert-manager->Secret"

        # RBAC extraction should also find this.
        reg = KindRegistry()
        reg.register("Certificate", "certificates", "cert-manager.io")
        reg.register("Issuer", "issuers", "cert-manager.io")

        fixture_path = _FIXTURES_DIR / "rbac_cert_manager.yaml"
        yaml_content = fixture_path.read_text(encoding="utf-8")
        _, outputs = extract_rbac_edges(yaml_content, reg)

        rbac_finds_secret = any(
            "secrets" in o.field and o.source == "rbac_deps:create_watch"
            for o in outputs
        )
        assert rbac_finds_secret, "RBAC should also discover cert-manager creates Secrets"


# ---------------------------------------------------------------------------
# Test 6: Graceful Degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_no_helm_chart_rbac_empty(self):
        """No Helm chart -> RBAC returns empty, no error."""
        adapter = RbacDepAdapter(registry=KindRegistry())
        op = _make_operation(service="imaginary-operator")
        deps = adapter.detect_dependencies(op, {}, set())
        outputs = adapter.detect_outputs(op, {})
        assert deps == []
        assert outputs == []

    def test_no_olm_bundle_olm_empty(self):
        """No OLM bundle -> OLM returns empty, no error."""
        adapter = OlmDepAdapter(registry=KindRegistry())

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=None):
            op = _make_operation(service="imaginary-operator")
            deps = adapter.detect_dependencies(op, {}, set())
            outputs = adapter.detect_outputs(op, {})

        assert deps == []
        assert outputs == []

    def test_both_adapters_independent(self):
        """Neither adapter failure affects the other."""
        reg = KindRegistry()
        reg.register("Certificate", "certificates", "cert-manager.io")

        olm_adapter = OlmDepAdapter(registry=reg)
        rbac_adapter = RbacDepAdapter(registry=reg)

        op = _make_operation()

        # OLM fails (returns None).
        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=None):
            olm_deps = olm_adapter.detect_dependencies(op, {}, set())
        assert olm_deps == []

        # RBAC still works independently (even if it also has no chart).
        rbac_deps = rbac_adapter.detect_dependencies(op, {}, set())
        assert isinstance(rbac_deps, list)  # No exception raised.
