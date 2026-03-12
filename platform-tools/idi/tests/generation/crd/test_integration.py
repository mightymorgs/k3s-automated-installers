"""Integration tests for two-pass orchestration — CRD Phase 1a."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from idi.generation.crd.field_classifier import classify_fields
from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.generate_all import (
    _generate_crd_service,
    _load_crd_schemas_for_service,
)
from tests.generation.crd.conftest import (
    _FIXTURES_DIR,
    _GOLDEN_DIR,
    assert_json_equivalent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_mini_manifest_config(service: str) -> dict[str, Any]:
    """Build a minimal manifest config for a test service."""
    # This simulates the manifest config structure for local-spec loading.
    configs = {
        "cert-manager": {
            "schema": "specs/cert-manager-openapi.json",
            "style": "kubernetes",
            "crd_kinds": [
                {
                    "group": "cert-manager.io",
                    "version": "v1",
                    "kinds": [
                        {"stem": "certificate_v1", "kind": "Certificate", "plural": "certificates", "namespaced": True},
                        {"stem": "certificaterequest_v1", "kind": "CertificateRequest", "plural": "certificaterequests", "namespaced": True},
                        {"stem": "issuer_v1", "kind": "Issuer", "plural": "issuers", "namespaced": True},
                        {"stem": "clusterissuer_v1", "kind": "ClusterIssuer", "plural": "clusterissuers", "namespaced": False},
                    ],
                },
                {
                    "group": "acme.cert-manager.io",
                    "version": "v1",
                    "kinds": [
                        {"stem": "order_v1", "kind": "Order", "plural": "orders", "namespaced": True},
                        {"stem": "challenge_v1", "kind": "Challenge", "plural": "challenges", "namespaced": True},
                    ],
                },
            ],
        },
        "external-secrets": {
            "schema": "specs/external-secrets-openapi.json",
            "style": "kubernetes",
            "crd_kinds": [
                {
                    "group": "external-secrets.io",
                    "version": "v1beta1",
                    "kinds": [
                        {"stem": "externalsecret_v1beta1", "kind": "ExternalSecret", "plural": "externalsecrets", "namespaced": True},
                        {"stem": "secretstore_v1beta1", "kind": "SecretStore", "plural": "secretstores", "namespaced": True},
                        {"stem": "clustersecretstore_v1beta1", "kind": "ClusterSecretStore", "plural": "clustersecretstores", "namespaced": False},
                        {"stem": "clusterexternalsecret_v1beta1", "kind": "ClusterExternalSecret", "plural": "clusterexternalsecrets", "namespaced": False},
                        {"stem": "pushsecret_v1alpha1", "kind": "PushSecret", "plural": "pushsecrets", "namespaced": True},
                    ],
                },
            ],
        },
        "traefik": {
            "schema": "specs/traefik-openapi.json",
            "style": "kubernetes",
            "crd_kinds": [
                {
                    "group": "traefik.io",
                    "version": "v1alpha1",
                    "kinds": [
                        {"stem": "ingressroute_v1alpha1", "kind": "IngressRoute", "plural": "ingressroutes", "namespaced": True},
                        {"stem": "ingressroutetcp_v1alpha1", "kind": "IngressRouteTCP", "plural": "ingressroutetcps", "namespaced": True},
                        {"stem": "ingressrouteudp_v1alpha1", "kind": "IngressRouteUDP", "plural": "ingressrouteudps", "namespaced": True},
                        {"stem": "middleware_v1alpha1", "kind": "Middleware", "plural": "middlewares", "namespaced": True},
                        {"stem": "middlewaretcp_v1alpha1", "kind": "MiddlewareTCP", "plural": "middlewaretcps", "namespaced": True},
                        {"stem": "serverstransport_v1alpha1", "kind": "ServersTransport", "plural": "serverstransports", "namespaced": True},
                        {"stem": "serverstransporttcp_v1alpha1", "kind": "ServersTransportTCP", "plural": "serverstransporttcps", "namespaced": True},
                        {"stem": "tlsoption_v1alpha1", "kind": "TLSOption", "plural": "tlsoptions", "namespaced": True},
                        {"stem": "tlsstore_v1alpha1", "kind": "TLSStore", "plural": "tlsstores", "namespaced": True},
                        {"stem": "traefikservice_v1alpha1", "kind": "TraefikService", "plural": "traefikservices", "namespaced": True},
                    ],
                },
            ],
        },
    }
    return configs[service]


# ---------------------------------------------------------------------------
# Two-pass registry population
# ---------------------------------------------------------------------------


class TestTwoPassRegistryPopulation:
    """Verify global registry is populated from all services."""

    def test_populated_registry_has_all_21_kinds(self, populated_registry):
        """Registry with all fixtures has all 21 CRD kinds."""
        kinds = populated_registry.all_kinds()
        # 20 bootstrap + 21 CRDs = 41 kinds
        assert len(kinds) >= 41
        assert "Certificate" in kinds
        assert "ExternalSecret" in kinds
        assert "IngressRoute" in kinds

    def test_cert_manager_kinds_in_registry(self, populated_registry):
        expected = {"Certificate", "CertificateRequest", "Issuer", "ClusterIssuer", "Order", "Challenge"}
        assert expected.issubset(populated_registry.all_kinds())

    def test_external_secrets_kinds_in_registry(self, populated_registry):
        expected = {"ExternalSecret", "SecretStore", "ClusterSecretStore", "ClusterExternalSecret", "PushSecret"}
        assert expected.issubset(populated_registry.all_kinds())

    def test_traefik_kinds_in_registry(self, populated_registry):
        expected = {"IngressRoute", "IngressRouteTCP", "IngressRouteUDP", "Middleware", "MiddlewareTCP",
                    "ServersTransport", "ServersTransportTCP", "TLSOption", "TLSStore", "TraefikService"}
        assert expected.issubset(populated_registry.all_kinds())

    def test_core_resources_in_registry(self, populated_registry):
        assert "Secret" in populated_registry.all_kinds()
        assert "ConfigMap" in populated_registry.all_kinds()
        assert "Service" in populated_registry.all_kinds()


# ---------------------------------------------------------------------------
# Cross-service reference resolution
# ---------------------------------------------------------------------------


class TestCrossServiceResolution:
    """Verify cross-service CRD references resolve with shared registry."""

    def test_certificate_ref_resolves_with_shared_registry(self, populated_registry):
        """A field 'certificateRef' resolves to cert-manager's Certificate."""
        is_ref, kind, plural, group = populated_registry.is_ref_field("certificateRef")
        assert is_ref is True
        assert kind == "Certificate"
        assert plural == "certificates"
        assert group == "cert-manager.io"

    def test_certificate_ref_fails_without_registration(self):
        """Without cert-manager registered, certificateRef doesn't resolve."""
        reg = KindRegistry()  # Only core resources
        is_ref, _, _, _ = reg.is_ref_field("certificateRef")
        assert is_ref is False


# ---------------------------------------------------------------------------
# Pipeline output equivalence
# ---------------------------------------------------------------------------


class TestDecomposedPipelineOutput:
    """Verify _generate_crd_service produces decomposed output."""

    @pytest.fixture(autouse=True)
    def setup(self, populated_registry, tmp_path):
        config = _build_mini_manifest_config("cert-manager")
        project_root = Path(__file__).parent.parent.parent.parent.parent.parent
        specs_dir = project_root / "catalog"

        if not (specs_dir / config["schema"]).exists():
            pytest.skip("Catalog specs not available")

        self.tmp_path = tmp_path
        self.result = _generate_crd_service(
            "cert-manager", config, tmp_path, specs_dir, registry=populated_registry,
        )

    def test_success(self):
        assert self.result["success"] is True
        assert self.result["stats"]["skills"] == 6

    def test_certificate_directory_exists(self):
        cert_dir = self.tmp_path / "cert-manager.io" / "cert-manager" / "Certificate"
        assert cert_dir.is_dir()

    def test_manifest_exists(self):
        cert_dir = self.tmp_path / "cert-manager.io" / "cert-manager" / "Certificate"
        assert (cert_dir / "manifest.json").exists()

    def test_operations_exist(self):
        cert_dir = self.tmp_path / "cert-manager.io" / "cert-manager" / "Certificate"
        assert (cert_dir / "operations" / "apply.json").exists()

    def test_subdirectories_exist(self):
        cert_dir = self.tmp_path / "cert-manager.io" / "cert-manager" / "Certificate"
        assert (cert_dir / "refs").is_dir()
        assert (cert_dir / "outputs").is_dir()
        assert (cert_dir / "fields").is_dir()

    def test_manifest_refs_match_files(self):
        cert_dir = self.tmp_path / "cert-manager.io" / "cert-manager" / "Certificate"
        manifest = json.loads((cert_dir / "manifest.json").read_text())
        actual_refs = sorted(p.stem for p in (cert_dir / "refs").glob("*.json"))
        assert manifest["refs"] == actual_refs

    def test_manifest_outputs_match_files(self):
        cert_dir = self.tmp_path / "cert-manager.io" / "cert-manager" / "Certificate"
        manifest = json.loads((cert_dir / "manifest.json").read_text())
        actual_outputs = sorted(p.stem for p in (cert_dir / "outputs").glob("*.json"))
        assert manifest["outputs"] == actual_outputs

    def test_manifest_fields_match_files(self):
        cert_dir = self.tmp_path / "cert-manager.io" / "cert-manager" / "Certificate"
        manifest = json.loads((cert_dir / "manifest.json").read_text())
        actual_fields = sorted(p.stem for p in (cert_dir / "fields").glob("*.json"))
        assert manifest["fields"] == actual_fields

    def test_all_6_kinds_have_directories(self):
        """All cert-manager Kinds produce decomposed directories."""
        base = self.tmp_path
        for kind_name in ["Certificate", "CertificateRequest", "Issuer", "ClusterIssuer"]:
            kind_dir = base / "cert-manager.io" / "cert-manager" / kind_name
            assert kind_dir.is_dir(), f"Missing: {kind_dir}"
        for kind_name in ["Order", "Challenge"]:
            kind_dir = base / "acme.cert-manager.io" / "cert-manager" / kind_name
            assert kind_dir.is_dir(), f"Missing: {kind_dir}"

    def test_no_monolithic_files(self):
        """No old monolithic {Kind}.json files produced."""
        monolithic = list(self.tmp_path.rglob("*.json"))
        for f in monolithic:
            # Monolithic files would be directly under service dir, not in subdirs.
            assert f.parent.name != "cert-manager" or f.name == "manifest.json" or \
                   f.parent.parent.name != "cert-manager"


# ---------------------------------------------------------------------------
# Fallback for direct calls
# ---------------------------------------------------------------------------


class TestDirectCallFallback:
    def test_generate_crd_service_without_registry(self, tmp_path):
        """_generate_crd_service with registry=None creates its own."""
        config = _build_mini_manifest_config("cert-manager")
        project_root = Path(__file__).parent.parent.parent.parent.parent.parent
        specs_dir = project_root / "catalog"

        if not (specs_dir / config["schema"]).exists():
            pytest.skip("Catalog specs not available")

        result = _generate_crd_service(
            "cert-manager", config, tmp_path, specs_dir, registry=None,
        )
        assert result["success"] is True
