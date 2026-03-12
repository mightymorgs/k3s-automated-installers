"""Tests for KindRegistry.fuzzy_resolve -- 4 lexical heuristics with precision guards."""
from __future__ import annotations

import pytest
from idi.generation.crd.kind_registry import KindRegistry, KindCandidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def istio_registry():
    """Registry with Istio kinds registered under service='istio'."""
    reg = KindRegistry()
    for kind, plural, group in [
        ("Gateway", "gateways", "networking.istio.io"),
        ("VirtualService", "virtualservices", "networking.istio.io"),
        ("DestinationRule", "destinationrules", "networking.istio.io"),
        ("ServiceEntry", "serviceentries", "networking.istio.io"),
    ]:
        reg.register(kind, plural, group, service="istio")
    return reg


@pytest.fixture
def cilium_registry():
    """Registry with Cilium kinds registered under service='cilium'."""
    reg = KindRegistry()
    for kind, plural, group in [
        ("CiliumBGPPeerConfig", "ciliumbgppeerconfigs", "cilium.io"),
        ("CiliumNetworkPolicy", "ciliumnetworkpolicies", "cilium.io"),
        ("CiliumClusterwideNetworkPolicy", "ciliumclusterwidenetworkpolicies", "cilium.io"),
    ]:
        reg.register(kind, plural, group, service="cilium")
    return reg


@pytest.fixture
def flux_registry():
    """Registry with Flux kinds registered under service='flux'."""
    reg = KindRegistry()
    for kind, plural, group in [
        ("HelmRepository", "helmrepositories", "source.toolkit.fluxcd.io"),
        ("HelmRelease", "helmreleases", "helm.toolkit.fluxcd.io"),
        ("GitRepository", "gitrepositories", "source.toolkit.fluxcd.io"),
        ("Bucket", "buckets", "source.toolkit.fluxcd.io"),
        ("Kustomization", "kustomizations", "kustomize.toolkit.fluxcd.io"),
    ]:
        reg.register(kind, plural, group, service="flux")
    return reg


# ---------------------------------------------------------------------------
# Exact plural match (confidence 0.80)
# ---------------------------------------------------------------------------


class TestExactPluralMatch:
    def test_gateways_resolves_to_gateway(self, istio_registry):
        """'gateways' exact-matches the registered plural for Gateway."""
        result = istio_registry.fuzzy_resolve("gateways", scope_service="istio")
        assert len(result) == 1
        assert result[0].kind == "Gateway"
        assert result[0].score == pytest.approx(0.80)
        assert result[0].match_type == "plural_exact"

    def test_gateways_multiple_services_not_unique(self):
        """When multiple services register 'gateways', returns empty (ambiguous)."""
        reg = KindRegistry()
        reg.register("Gateway", "gateways", "networking.istio.io", service="istio")
        reg.register("Gateway", "gateways", "gateway.networking.k8s.io", service="k8s-gateway")
        result = reg.fuzzy_resolve("gateways", require_unique=True)
        assert result == []

    def test_secrets_resolves_to_secret(self):
        """'secrets' matches core Secret (always available)."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("secrets")
        assert len(result) == 1
        assert result[0].kind == "Secret"
        assert result[0].score == pytest.approx(0.80)

    def test_configmaps_resolves_to_configmap(self):
        """'configmaps' matches core ConfigMap."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("configmaps")
        assert len(result) == 1
        assert result[0].kind == "ConfigMap"

    def test_array_suffix_stripped(self, istio_registry):
        """Field name with [] suffix: 'gateways[]' still resolves."""
        result = istio_registry.fuzzy_resolve("gateways[]", scope_service="istio")
        assert len(result) == 1
        assert result[0].kind == "Gateway"
        assert result[0].score == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# Suffix match (confidence 0.75)
# ---------------------------------------------------------------------------


class TestSuffixMatch:
    def test_peer_config_ref_matches_cilium_bgp_peer_config(self, cilium_registry):
        """'peerConfigRef' -> strip 'Ref' -> 'peerConfig' -> ends-with CiliumBGPPeerConfig."""
        result = cilium_registry.fuzzy_resolve("peerConfigRef", scope_service="cilium")
        assert len(result) == 1
        assert result[0].kind == "CiliumBGPPeerConfig"
        assert result[0].score == pytest.approx(0.75)
        assert result[0].match_type == "suffix_unique"

    def test_db_ref_too_short(self):
        """'dbRef' stripped to 'db' (2 chars < 4 minimum) -> returns empty."""
        reg = KindRegistry()
        reg.register("Database", "databases", "example.io", service="test")
        result = reg.fuzzy_resolve("dbRef", scope_service="test")
        assert result == []

    def test_suffix_match_not_unique(self):
        """Multiple kinds ending with same suffix -> returns empty (ambiguous)."""
        reg = KindRegistry()
        reg.register("FooPolicy", "foopolicies", "a.io", service="svc")
        reg.register("BarPolicy", "barpolicies", "b.io", service="svc")
        # "policyRef" -> strip "Ref" -> "policy" -> both end with "Policy" -> ambiguous
        result = reg.fuzzy_resolve("policyRef", scope_service="svc")
        assert result == []

    def test_suffix_match_raw_name(self, cilium_registry):
        """Raw field name (no Ref/Name suffix) can also do suffix match."""
        # "peerConfig" without Ref suffix should still match CiliumBGPPeerConfig
        result = cilium_registry.fuzzy_resolve("peerConfig", scope_service="cilium")
        assert len(result) == 1
        assert result[0].kind == "CiliumBGPPeerConfig"
        assert result[0].score == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# CamelCase tail segment (confidence 0.65 with infra prefix, 0.50 without)
# ---------------------------------------------------------------------------


class TestCamelCaseTail:
    def test_backend_services_infra_prefix(self):
        """'backendServices' -> tail 'Services' -> plural of Service -> 0.65."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("backendServices")
        assert len(result) == 1
        assert result[0].kind == "Service"
        assert result[0].score == pytest.approx(0.65)
        assert result[0].match_type == "camel_tail"

    def test_metrics_server_no_kind(self):
        """'metricsServer' -> tail 'Server' -> not a registered Kind -> empty."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("metricsServer")
        assert result == []

    def test_target_gateway_infra_prefix(self, istio_registry):
        """'targetGateway' -> prefix 'target' in allowlist, tail 'Gateway' -> 0.65."""
        result = istio_registry.fuzzy_resolve("targetGateway", scope_service="istio")
        assert len(result) == 1
        assert result[0].kind == "Gateway"
        assert result[0].score == pytest.approx(0.65)

    def test_enabled_services_non_infra_prefix(self):
        """'enabledServices' -> compound name, non-infra prefix -> 0.50.

        Compound names are exempt from Kind-level denylist. At 0.50 this is
        below the 0.7 emission threshold, so the caller filters it out.
        """
        reg = KindRegistry()
        result = reg.fuzzy_resolve("enabledServices")
        assert len(result) == 1
        assert result[0].kind == "Service"
        assert result[0].score == pytest.approx(0.50)

    def test_target_gateway_ref_with_suffix(self, istio_registry):
        """'targetGatewayRef' -> skip 'Ref' tail, use 'Gateway', prefix 'target' -> 0.65."""
        result = istio_registry.fuzzy_resolve("targetGatewayRef", scope_service="istio")
        assert len(result) == 1
        assert result[0].kind == "Gateway"
        assert result[0].score == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# Exact lowercase Kind match (confidence 0.55, requires corroboration)
# ---------------------------------------------------------------------------


class TestExactLowercaseKindMatch:
    def test_policy_without_corroboration(self):
        """'policy' is in _FUZZY_DENYLIST -> returns empty without corroboration."""
        reg = KindRegistry()
        reg.register("Policy", "policies", "example.io", service="test")
        result = reg.fuzzy_resolve("policy", scope_service="test")
        assert result == []

    def test_policy_with_corroboration(self):
        """'policy' with sibling corroboration -> score 0.55."""
        reg = KindRegistry()
        reg.register("Policy", "policies", "example.io", service="test")
        result = reg.fuzzy_resolve(
            "policy", scope_service="test",
            sibling_names=frozenset({"namespace", "name"}),
        )
        assert len(result) == 1
        assert result[0].score == pytest.approx(0.55)
        assert result[0].match_type == "bare_kind"

    def test_bucket_not_denylisted(self, flux_registry):
        """'bucket' is NOT in denylist -> matches Bucket at 0.55 without corroboration."""
        result = flux_registry.fuzzy_resolve("bucket", scope_service="flux")
        assert len(result) == 1
        assert result[0].kind == "Bucket"
        assert result[0].score == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# Cross-service penalty
# ---------------------------------------------------------------------------


class TestCrossServicePenalty:
    def test_cross_service_penalty_applied(self, istio_registry):
        """Istio Gateway matched from flux scope -> confidence * 0.7."""
        result = istio_registry.fuzzy_resolve("gateways", scope_service="flux")
        assert len(result) == 1
        # 0.80 * 0.7 = 0.56
        assert result[0].score == pytest.approx(0.80 * 0.7)

    def test_core_kind_no_penalty(self):
        """Core Secret matched from any service -> NO penalty."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("secrets", scope_service="flux")
        assert len(result) == 1
        assert result[0].score == pytest.approx(0.80)  # No penalty

    def test_same_service_no_penalty(self, istio_registry):
        """Same-service match -> no penalty."""
        result = istio_registry.fuzzy_resolve("gateways", scope_service="istio")
        assert len(result) == 1
        assert result[0].score == pytest.approx(0.80)

    def test_no_scope_no_penalty(self, istio_registry):
        """No scope_service -> no penalty applied."""
        result = istio_registry.fuzzy_resolve("gateways")
        assert len(result) == 1
        assert result[0].score == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# High-risk noun denylist
# ---------------------------------------------------------------------------


class TestDenylist:
    def test_service_in_denylist(self):
        """'service' is in _FUZZY_DENYLIST -> returns empty without corroboration."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("service")
        assert result == []

    def test_role_in_denylist(self):
        """'role' is in _FUZZY_DENYLIST -> returns empty."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("role")
        assert result == []

    def test_type_in_denylist(self):
        """'type' is in _FUZZY_DENYLIST -> returns empty."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("type")
        assert result == []

    def test_service_with_corroborating_siblings(self):
        """'service' WITH sibling 'namespace' -> allowed (corroborated)."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve(
            "service",
            sibling_names=frozenset({"namespace", "port"}),
        )
        assert len(result) == 1
        assert result[0].kind == "Service"

    def test_denylist_with_ref_suffix_stripped(self):
        """'serviceRef' -> strip 'Ref' -> 'service' in denylist -> blocked."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("serviceRef")
        assert result == []

    def test_denylist_ref_with_corroboration(self):
        """'serviceRef' with corroboration -> allowed."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve(
            "serviceRef",
            sibling_names=frozenset({"namespace"}),
        )
        assert len(result) == 1
        assert result[0].kind == "Service"

    def test_services_plural_blocked_by_kind_denylist(self):
        """'services' (plural of denylisted 'service') blocked without corroboration."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("services")
        assert result == []

    def test_services_plural_allowed_with_corroboration(self):
        """'services' with corroboration -> allowed."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve(
            "services",
            sibling_names=frozenset({"namespace"}),
        )
        assert len(result) == 1
        assert result[0].kind == "Service"

    def test_compound_name_not_blocked_by_kind_denylist(self):
        """'backendServices' is compound -> Kind-level denylist does NOT apply."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("backendServices")
        assert len(result) == 1
        assert result[0].kind == "Service"
        assert result[0].score == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string(self):
        """Empty field name -> empty result."""
        reg = KindRegistry()
        assert reg.fuzzy_resolve("") == []

    def test_single_character(self):
        """Single character field name -> empty result."""
        reg = KindRegistry()
        assert reg.fuzzy_resolve("x") == []

    def test_no_match_at_all(self):
        """Completely unrelated name -> empty result."""
        reg = KindRegistry()
        assert reg.fuzzy_resolve("somethingCompletelyUnrelated") == []

    def test_kind_candidate_dataclass(self):
        """KindCandidate is frozen and has expected fields."""
        c = KindCandidate(kind="Secret", api_group="core", score=0.80, match_type="plural_exact")
        assert c.kind == "Secret"
        assert c.api_group == "core"
        assert c.score == 0.80
        assert c.match_type == "plural_exact"

    def test_digits_preserved_in_camelcase(self):
        """Digits in field names are preserved by _decompose_camel_case."""
        from idi.generation.crd.kind_registry import KindRegistry
        segments = KindRegistry._decompose_camel_case("bgpV2Peers")
        assert "2" in segments
        assert "Peers" in segments

    def test_suffix_raw_name_as_proper_suffix(self):
        """Raw field name (no Ref/Name) can match as proper suffix of Kind."""
        reg = KindRegistry()
        reg.register("CiliumNetworkPolicy", "ciliumnetworkpolicies", "cilium.io", service="cilium")
        # "networkPolicy" is a proper suffix of "CiliumNetworkPolicy"
        result = reg.fuzzy_resolve("networkPolicy", scope_service="cilium")
        assert len(result) == 1
        assert result[0].kind == "CiliumNetworkPolicy"
        assert result[0].score == pytest.approx(0.75)
        assert result[0].match_type == "suffix_unique"

    def test_bare_kind_below_threshold(self):
        """Bare Kind match at 0.55 is below 0.7 emission threshold by design."""
        reg = KindRegistry()
        reg.register("Sidecar", "sidecars", "networking.istio.io", service="istio")
        result = reg.fuzzy_resolve("sidecar", scope_service="istio")
        assert len(result) == 1
        assert result[0].score == pytest.approx(0.55)
        assert result[0].score < 0.7  # Below emission threshold
