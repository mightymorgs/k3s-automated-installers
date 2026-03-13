"""Tests for CRD false negative detectors — label_selector_ref, suffix_ref_tuple, polymorphic_ref."""
from __future__ import annotations

import pytest

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.kind_registry import KindEntry, KindRegistry
from idi.generation.crd.ref_detector import detect_label_selector_ref
from idi.generation.crd.schema_walker import WalkedField


def _make_field(
    name: str,
    schema: dict | None = None,
    path: str | None = None,
    depth: int = 2,
    is_array_item: bool = False,
    required: bool = False,
    parent_path: str = "spec",
) -> WalkedField:
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path, name=name, schema=schema, depth=depth,
        is_array_item=is_array_item, required=required, parent_path=parent_path,
    )


def _label_selector_schema() -> dict:
    """Standard metav1.LabelSelector schema shape."""
    return {
        "type": "object",
        "properties": {
            "matchLabels": {"type": "object", "additionalProperties": {"type": "string"}},
            "matchExpressions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "operator": {"type": "string"},
                        "values": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def prom_registry() -> KindRegistry:
    """KindRegistry with kube-prometheus Kinds."""
    reg = KindRegistry()
    reg.register("PodMonitor", "podmonitors", "monitoring.coreos.com", service="kube-prometheus")
    reg.register("ServiceMonitor", "servicemonitors", "monitoring.coreos.com", service="kube-prometheus")
    reg.register("Probe", "probes", "monitoring.coreos.com", service="kube-prometheus")
    reg.register("PrometheusRule", "prometheusrules", "monitoring.coreos.com", service="kube-prometheus")
    reg.register("ScrapeConfig", "scrapeconfigs", "monitoring.coreos.com", service="kube-prometheus")
    reg.register("AlertmanagerConfig", "alertmanagerconfigs", "monitoring.coreos.com", service="kube-prometheus")
    return reg


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


# ---------------------------------------------------------------------------
# detect_label_selector_ref tests
# ---------------------------------------------------------------------------


class TestDetectLabelSelectorRef:
    def test_pod_monitor_selector(self, prom_registry: KindRegistry):
        """podMonitorSelector + LabelSelector schema -> PodMonitor."""
        field = _make_field("podMonitorSelector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is not None
        assert result.target_kind == "PodMonitor"
        assert result.confidence == 0.85
        assert result.detection_source == "ref_detector:label_selector_ref"

    def test_service_monitor_selector(self, prom_registry: KindRegistry):
        """serviceMonitorSelector -> ServiceMonitor."""
        field = _make_field("serviceMonitorSelector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is not None
        assert result.target_kind == "ServiceMonitor"

    def test_rule_selector(self, prom_registry: KindRegistry):
        """ruleSelector -> PrometheusRule."""
        field = _make_field("ruleSelector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is not None
        assert result.target_kind == "PrometheusRule"

    def test_alertmanager_config_selector(self, prom_registry: KindRegistry):
        """alertmanagerConfigSelector -> AlertmanagerConfig."""
        field = _make_field("alertmanagerConfigSelector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is not None
        assert result.target_kind == "AlertmanagerConfig"

    def test_scrape_config_selector(self, prom_registry: KindRegistry):
        """scrapeConfigSelector -> ScrapeConfig."""
        field = _make_field("scrapeConfigSelector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is not None
        assert result.target_kind == "ScrapeConfig"

    def test_not_ending_in_selector(self, prom_registry: KindRegistry):
        """Field not ending in Selector -> None."""
        field = _make_field("podMonitorRef", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is None

    def test_bare_selector(self, prom_registry: KindRegistry):
        """Bare 'selector' -> None (empty base guard)."""
        field = _make_field("selector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is None

    def test_bare_selector_capitalized(self, prom_registry: KindRegistry):
        """Bare 'Selector' -> None (empty base guard)."""
        field = _make_field("Selector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is None

    def test_schema_not_object(self, prom_registry: KindRegistry):
        """Schema type not object -> None."""
        field = _make_field("podMonitorSelector", schema={"type": "string"})
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is None

    def test_schema_no_label_selector_shape(self, prom_registry: KindRegistry):
        """Object schema but no matchLabels/matchExpressions -> None."""
        field = _make_field("podMonitorSelector", schema={
            "type": "object",
            "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
        })
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is None

    def test_no_kind_registry_match(self, prom_registry: KindRegistry):
        """Stripped name has no KindRegistry match -> None."""
        field = _make_field("fooBarSelector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is None

    def test_different_service(self, prom_registry: KindRegistry):
        """Stripped name matches Kind in different service -> None."""
        field = _make_field("podMonitorSelector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "other-service")
        assert result is None

    def test_core_kind_rejected(self, prom_registry: KindRegistry):
        """nodeSelector -> Node is_core=True -> None."""
        # Node is already in core registry
        field = _make_field("nodeSelector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is None

    def test_result_attributes(self, prom_registry: KindRegistry):
        """Verify all ClassifiedField attributes."""
        field = _make_field("podMonitorSelector", schema=_label_selector_schema())
        result = detect_label_selector_ref(field, prom_registry, "kube-prometheus")
        assert result is not None
        assert result.role == "input_ref"
        assert result.field_type == "object"
        assert result.fact_shape == "identity"
        assert result.blocks_descendants is False
        assert result.target_group == "monitoring.coreos.com"
