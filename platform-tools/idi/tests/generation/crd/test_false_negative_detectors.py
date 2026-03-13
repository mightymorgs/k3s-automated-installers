"""Tests for CRD false negative detectors — label_selector_ref, suffix_ref_tuple, polymorphic_ref."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindEntry, KindRegistry
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def traefik_registry() -> KindRegistry:
    """KindRegistry with traefik + external-secrets Kinds."""
    reg = KindRegistry()
    reg.register("TLSOption", "tlsoptions", "traefik.io", service="traefik")
    reg.register("TLSStore", "tlsstores", "traefik.io", service="traefik")
    reg.register("IngressRoute", "ingressroutes", "traefik.io", service="traefik")
    reg.register("Middleware", "middlewares", "traefik.io", service="traefik")
    reg.register("SecretStore", "secretstores", "external-secrets.io", service="external-secrets")
    return reg


# ---------------------------------------------------------------------------
# KindRegistry.suffix_match tests
# ---------------------------------------------------------------------------


class TestSuffixMatch:
    def test_option_scoped_traefik(self, traefik_registry: KindRegistry):
        """suffix_match("Option", scope_service="traefik") -> TLSOption."""
        results = traefik_registry.suffix_match("Option", scope_service="traefik")
        kinds = [e.kind for e in results]
        assert kinds == ["TLSOption"]

    def test_store_scoped_traefik(self, traefik_registry: KindRegistry):
        """suffix_match("Store", scope_service="traefik") -> TLSStore only (not SecretStore)."""
        results = traefik_registry.suffix_match("Store", scope_service="traefik")
        kinds = [e.kind for e in results]
        assert "TLSStore" in kinds
        assert "SecretStore" not in kinds

    def test_route_scoped_traefik(self, traefik_registry: KindRegistry):
        """suffix_match("Route", scope_service="traefik") -> IngressRoute."""
        results = traefik_registry.suffix_match("Route", scope_service="traefik")
        kinds = [e.kind for e in results]
        assert kinds == ["IngressRoute"]

    def test_nonexistent_suffix(self, traefik_registry: KindRegistry):
        """suffix_match("Nonexistent") -> []."""
        results = traefik_registry.suffix_match("Nonexistent", scope_service="traefik")
        assert results == []

    def test_wrong_service(self, traefik_registry: KindRegistry):
        """suffix_match("Option", scope_service="other-service") -> []."""
        results = traefik_registry.suffix_match("Option", scope_service="other-service")
        assert results == []

    def test_no_service_scope(self, traefik_registry: KindRegistry):
        """suffix_match("Option", scope_service=None) -> TLSOption (from traefik)."""
        results = traefik_registry.suffix_match("Option", scope_service=None)
        kinds = [e.kind for e in results]
        assert "TLSOption" in kinds

    def test_case_insensitive(self, traefik_registry: KindRegistry):
        """suffix_match("option") matches TLSOption (case-insensitive)."""
        results = traefik_registry.suffix_match("option", scope_service="traefik")
        kinds = [e.kind for e in results]
        assert "TLSOption" in kinds

    def test_store_unscoped_returns_both(self, traefik_registry: KindRegistry):
        """suffix_match("Store", scope_service=None) -> both TLSStore and SecretStore."""
        results = traefik_registry.suffix_match("Store", scope_service=None)
        kinds = {e.kind for e in results}
        assert "TLSStore" in kinds
        assert "SecretStore" in kinds

    def test_short_suffix_matches(self, traefik_registry: KindRegistry):
        """Short suffix like 'e' will match many things — no minimum enforced here."""
        results = traefik_registry.suffix_match("e", scope_service="traefik")
        # IngressRoute ends with 'e', Middleware ends with 'e'
        kinds = {e.kind for e in results}
        assert len(kinds) >= 1  # At least some matches

    def test_deduplicates_by_kind_name(self):
        """Same Kind registered with multiple groups -> one result per Kind name."""
        reg = KindRegistry()
        reg.register("Gateway", "gateways", "networking.k8s.io", service="gateway-api")
        reg.register("Gateway", "gateways", "gateway.networking.k8s.io", service="gateway-api")
        results = reg.suffix_match("Gateway", scope_service="gateway-api")
        kinds = [e.kind for e in results]
        assert kinds == ["Gateway"]
