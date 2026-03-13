"""Tests for CRD false negative detectors — label_selector_ref, suffix_ref_tuple, polymorphic_ref."""
from __future__ import annotations

import pytest

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.kind_registry import KindEntry, KindRegistry
from idi.generation.crd.ref_detector import (
    _augment_polymorphic_refs,
    _singularize,
    detect_label_selector_ref,
    detect_suffix_ref_tuple,
)
from idi.generation.crd.topo_sort import (
    DependencyEdge,
    KindNode,
    _filter_cross_service_cross_group_edges,
)
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


# ---------------------------------------------------------------------------
# _singularize tests
# ---------------------------------------------------------------------------


class TestSingularize:
    def test_options(self):
        assert _singularize("options") == "option"

    def test_stores(self):
        assert _singularize("stores") == "store"

    def test_policies(self):
        assert _singularize("policies") == "policy"

    def test_addresses(self):
        assert _singularize("addresses") == "address"

    def test_ingress_preserved(self):
        """ingress does not end in a standard plural suffix."""
        assert _singularize("ingress") == "ingress"

    def test_tls_preserved(self):
        assert _singularize("tls") == "tls"

    def test_status_preserved(self):
        """status ends in 'us' — should not be mangled."""
        assert _singularize("status") == "status"

    def test_classes(self):
        assert _singularize("classes") == "class"

    def test_proxy_preserved(self):
        """proxy doesn't end in 's'."""
        assert _singularize("proxy") == "proxy"

    def test_bus_preserved(self):
        """bus is too short after removing 's'."""
        assert _singularize("bus") == "bus"


# ---------------------------------------------------------------------------
# detect_suffix_ref_tuple tests
# ---------------------------------------------------------------------------


def _ref_tuple_schema(
    *, has_name: bool = True, has_namespace: bool = True,
    has_kind: bool = False, has_api_group: bool = False,
    has_api_version: bool = False, name_required: bool = True,
) -> dict:
    """Build a reference tuple object schema."""
    props = {}
    required = []
    if has_name:
        props["name"] = {"type": "string"}
        if name_required:
            required.append("name")
    if has_namespace:
        props["namespace"] = {"type": "string"}
    if has_kind:
        props["kind"] = {"type": "string"}
    if has_api_group:
        props["apiGroup"] = {"type": "string"}
    if has_api_version:
        props["apiVersion"] = {"type": "string"}
    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


@pytest.fixture
def traefik_ref_registry() -> KindRegistry:
    """KindRegistry with traefik Kinds + a core Secret."""
    reg = KindRegistry()
    reg.register("TLSOption", "tlsoptions", "traefik.io", service="traefik")
    reg.register("TLSStore", "tlsstores", "traefik.io", service="traefik")
    reg.register("IngressRoute", "ingressroutes", "traefik.io", service="traefik")
    return reg


class TestDetectSuffixRefTuple:
    def test_options_matches_tls_option(self, traefik_ref_registry: KindRegistry):
        """'options' with {name, namespace} -> TLSOption at 0.80."""
        field = _make_field("options", schema=_ref_tuple_schema())
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert len(results) == 1
        assert results[0].target_kind == "TLSOption"
        assert results[0].confidence == 0.80
        assert results[0].detection_source == "ref_detector:suffix_ref_tuple"

    def test_store_matches_tls_store(self, traefik_ref_registry: KindRegistry):
        """'store' with {name, namespace} -> TLSStore at 0.80."""
        field = _make_field("store", schema=_ref_tuple_schema())
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert len(results) == 1
        assert results[0].target_kind == "TLSStore"
        assert results[0].confidence == 0.80

    def test_option_singular_matches(self, traefik_ref_registry: KindRegistry):
        """'option' (already singular) -> TLSOption at 0.80."""
        field = _make_field("option", schema=_ref_tuple_schema())
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert len(results) == 1
        assert results[0].target_kind == "TLSOption"

    def test_missing_name_property(self, traefik_ref_registry: KindRegistry):
        """Schema missing 'name' property -> []."""
        field = _make_field("options", schema=_ref_tuple_schema(has_name=False))
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert results == []

    def test_name_not_required(self, traefik_ref_registry: KindRegistry):
        """'name' not in required list -> []."""
        field = _make_field("options", schema=_ref_tuple_schema(name_required=False))
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert results == []

    def test_has_kind_defers(self, traefik_ref_registry: KindRegistry):
        """Schema has 'kind' property -> [] (defer to detect_ref_tuple)."""
        field = _make_field("options", schema=_ref_tuple_schema(has_kind=True))
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert results == []

    def test_has_api_group_defers(self, traefik_ref_registry: KindRegistry):
        """Schema has 'apiGroup' property -> [] (defer to detect_ref_tuple)."""
        field = _make_field("options", schema=_ref_tuple_schema(has_api_group=True))
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert results == []

    def test_has_api_version_defers(self, traefik_ref_registry: KindRegistry):
        """Schema has 'apiVersion' property -> [] (defer to detect_ref_tuple)."""
        field = _make_field("options", schema=_ref_tuple_schema(has_api_version=True))
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert results == []

    def test_short_candidate_rejected(self, traefik_ref_registry: KindRegistry):
        """Field name candidate < 4 chars (e.g., 'ref') -> []."""
        field = _make_field("ref", schema=_ref_tuple_schema())
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert results == []

    def test_core_kind_filtered(self):
        """Resolved Kind is core (is_core=True) -> filtered out."""
        reg = KindRegistry()
        reg.register("TLSOption", "tlsoptions", "traefik.io", service="traefik")
        # Secret is core
        field = _make_field("secrets", schema=_ref_tuple_schema())
        results = detect_suffix_ref_tuple(field, reg, "traefik")
        assert results == []

    def test_wrong_service_filtered(self, traefik_ref_registry: KindRegistry):
        """Resolved Kind in different service -> filtered out."""
        field = _make_field("options", schema=_ref_tuple_schema())
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "other-service")
        assert results == []

    def test_multiple_matches_lower_confidence(self):
        """Multiple Kind matches -> all emitted at confidence 0.65."""
        reg = KindRegistry()
        reg.register("TLSStore", "tlsstores", "traefik.io", service="traefik")
        reg.register("SecretStore", "secretstores", "traefik.io", service="traefik")
        field = _make_field("stores", schema=_ref_tuple_schema())
        results = detect_suffix_ref_tuple(field, reg, "traefik")
        assert len(results) == 2
        kinds = {r.target_kind for r in results}
        assert "TLSStore" in kinds
        assert "SecretStore" in kinds
        assert all(r.confidence == 0.65 for r in results)

    def test_blocks_descendants(self, traefik_ref_registry: KindRegistry):
        """blocks_descendants is True (children are ref components)."""
        field = _make_field("options", schema=_ref_tuple_schema())
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert len(results) == 1
        assert results[0].blocks_descendants is True

    def test_field_type_is_object(self, traefik_ref_registry: KindRegistry):
        """field_type is 'object'."""
        field = _make_field("options", schema=_ref_tuple_schema())
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert results[0].field_type == "object"

    def test_cross_namespace_when_namespace_present(self, traefik_ref_registry: KindRegistry):
        """cross_namespace is True when namespace property exists."""
        field = _make_field("options", schema=_ref_tuple_schema(has_namespace=True))
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert results[0].cross_namespace is True

    def test_cross_namespace_false_without_namespace(self, traefik_ref_registry: KindRegistry):
        """cross_namespace is False when namespace property absent."""
        field = _make_field("options", schema=_ref_tuple_schema(has_namespace=False))
        results = detect_suffix_ref_tuple(field, traefik_ref_registry, "traefik")
        assert len(results) == 1
        assert results[0].cross_namespace is False


# ---------------------------------------------------------------------------
# _augment_polymorphic_refs tests
# ---------------------------------------------------------------------------


@pytest.fixture
def certmanager_registry() -> KindRegistry:
    """KindRegistry with cert-manager Kinds."""
    reg = KindRegistry()
    reg.register("Issuer", "issuers", "cert-manager.io", service="cert-manager")
    reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io", service="cert-manager")
    reg.register("Certificate", "certificates", "cert-manager.io", service="cert-manager")
    reg.register("CertificateRequest", "certificaterequests", "cert-manager.io", service="cert-manager")
    return reg


def _issuer_ref_schema(*, has_kind: bool = True, kind_enum: list[str] | None = None) -> dict:
    """Build issuerRef-like schema."""
    props: dict = {
        "name": {"type": "string"},
        "group": {"type": "string"},
    }
    if has_kind:
        kind_prop: dict = {"type": "string"}
        if kind_enum is not None:
            kind_prop["enum"] = kind_enum
        props["kind"] = kind_prop
    return {"type": "object", "properties": props, "required": ["name"]}


def _make_primary_result(
    field_path: str = "spec.issuerRef",
    target_kind: str = "Issuer",
    target_group: str = "cert-manager.io",
    confidence: float = 0.85,
    detection_source: str = "ref_detector:ref_tuple",
) -> ClassifiedField:
    """Create a primary ClassifiedField as if from detect_ref_tuple."""
    return ClassifiedField(
        field=field_path,
        role="input_ref",
        confidence=confidence,
        field_type="object",
        target_kind=target_kind,
        target_group=target_group,
        required=True,
        cross_namespace=False,
        description="",
        detection_source=detection_source,
        fact_shape="identity",
        blocks_descendants=True,
    )


class TestAugmentPolymorphicRefs:
    def test_adds_cluster_issuer(self, certmanager_registry: KindRegistry):
        """Primary Issuer -> adds ClusterIssuer (substring match)."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        kinds = {r.target_kind for r in results}
        assert "Issuer" in kinds
        assert "ClusterIssuer" in kinds

    def test_does_not_add_certificate(self, certmanager_registry: KindRegistry):
        """'Issuer' not in 'Certificate' -> Certificate not added."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        kinds = {r.target_kind for r in results}
        assert "Certificate" not in kinds
        assert "CertificateRequest" not in kinds

    def test_inherits_primary_confidence(self, certmanager_registry: KindRegistry):
        """Augmented result inherits primary's confidence."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result(confidence=0.85)
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        augmented = [r for r in results if r.target_kind == "ClusterIssuer"]
        assert len(augmented) == 1
        assert augmented[0].confidence == 0.85

    def test_detection_source(self, certmanager_registry: KindRegistry):
        """Augmented result has detection_source='ref_detector:polymorphic_ref'."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        augmented = [r for r in results if r.target_kind == "ClusterIssuer"]
        assert augmented[0].detection_source == "ref_detector:polymorphic_ref"

    def test_same_field_path(self, certmanager_registry: KindRegistry):
        """Augmented result has same field path as primary."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result(field_path="spec.issuerRef")
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        augmented = [r for r in results if r.target_kind == "ClusterIssuer"]
        assert augmented[0].field == "spec.issuerRef"

    def test_target_group_from_registry(self, certmanager_registry: KindRegistry):
        """Augmented result has target_group from KindRegistry."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        augmented = [r for r in results if r.target_kind == "ClusterIssuer"]
        assert augmented[0].target_group == "cert-manager.io"

    def test_kind_with_enum_no_augmentation(self, certmanager_registry: KindRegistry):
        """kind field has enum -> no augmentation (already constrained)."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema(kind_enum=["Issuer"]))
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        assert len(results) == 1  # Only original
        assert results[0].target_kind == "Issuer"

    def test_kind_with_multi_enum_no_augmentation(self, certmanager_registry: KindRegistry):
        """kind field with multi-value enum -> no augmentation."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema(
            kind_enum=["Issuer", "ClusterIssuer"],
        ))
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        assert len(results) == 1

    def test_no_kind_property_no_augmentation(self, certmanager_registry: KindRegistry):
        """Schema has no kind property -> no augmentation."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema(has_kind=False))
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        assert len(results) == 1

    def test_no_same_group_siblings(self):
        """Primary target has no same-group siblings -> empty additions."""
        reg = KindRegistry()
        reg.register("Issuer", "issuers", "cert-manager.io", service="cert-manager")
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, reg, "cert-manager", "Certificate",
        )
        assert len(results) == 1  # Only original

    def test_safety_valve_too_many_siblings(self):
        """More than 5 surviving siblings -> no augmentation."""
        reg = KindRegistry()
        reg.register("Issuer", "issuers", "cert-manager.io", service="cert-manager")
        for i in range(7):
            reg.register(f"ClusterIssuer{i}", f"clusterissuer{i}s", "cert-manager.io", service="cert-manager")
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, reg, "cert-manager", "Certificate",
        )
        assert len(results) == 1  # Only original

    def test_sibling_different_service_filtered(self):
        """Sibling in different service -> filtered out."""
        reg = KindRegistry()
        reg.register("Issuer", "issuers", "cert-manager.io", service="cert-manager")
        reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io", service="other-service")
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result()
        results = _augment_polymorphic_refs(
            [primary], field, reg, "cert-manager", "Certificate",
        )
        assert len(results) == 1

    def test_source_kind_excluded(self, certmanager_registry: KindRegistry):
        """Source Kind excluded from siblings."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result()
        # Source is "Certificate" — shouldn't appear in augmented results
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        kinds = {r.target_kind for r in results}
        assert "Certificate" not in kinds

    def test_wrong_detection_source_no_augmentation(self, certmanager_registry: KindRegistry):
        """detection_source not containing 'ref_tuple' or 'kind_registry' -> no augmentation."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result(detection_source="ref_detector:label_selector_ref")
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        assert len(results) == 1

    def test_depth_decayed_confidence_inherited(self, certmanager_registry: KindRegistry):
        """Depth-decayed primary (confidence 0.6) -> augmented also has 0.6."""
        field = _make_field("issuerRef", schema=_issuer_ref_schema())
        primary = _make_primary_result(confidence=0.6)
        results = _augment_polymorphic_refs(
            [primary], field, certmanager_registry, "cert-manager", "Certificate",
        )
        augmented = [r for r in results if r.target_kind == "ClusterIssuer"]
        assert len(augmented) == 1
        assert augmented[0].confidence == 0.6


# ---------------------------------------------------------------------------
# _filter_cross_service_cross_group_edges tests
# ---------------------------------------------------------------------------


def _make_edge(
    source_gk: str, target_gk: str,
    edge_type: str = "hard",
    source_field: str = "spec.ref",
    detection_source: str = "ref_detector:ref_tuple",
    confidence: float = 0.85,
) -> DependencyEdge:
    return DependencyEdge(
        source_gk=source_gk, target_gk=target_gk,
        edge_type=edge_type, source_field=source_field,
        detection_source=detection_source, confidence=confidence,
    )


@pytest.fixture
def cross_service_nodes() -> dict[str, KindNode]:
    return {
        "networking.istio.io/EnvoyFilter": KindNode(kind="EnvoyFilter", group="networking.istio.io", service="istio"),
        "postgresql.cnpg.io/Cluster": KindNode(kind="Cluster", group="postgresql.cnpg.io", service="cnpg"),
        "monitoring.coreos.com/AlertmanagerConfig": KindNode(kind="AlertmanagerConfig", group="monitoring.coreos.com", service="kube-prometheus"),
        "notification.toolkit.fluxcd.io/Receiver": KindNode(kind="Receiver", group="notification.toolkit.fluxcd.io", service="flux"),
        "helm.toolkit.fluxcd.io/HelmRelease": KindNode(kind="HelmRelease", group="helm.toolkit.fluxcd.io", service="flux"),
        "source.toolkit.fluxcd.io/GitRepository": KindNode(kind="GitRepository", group="source.toolkit.fluxcd.io", service="flux"),
        "cert-manager.io/Certificate": KindNode(kind="Certificate", group="cert-manager.io", service="cert-manager"),
        "cert-manager.io/Issuer": KindNode(kind="Issuer", group="cert-manager.io", service="cert-manager"),
    }


class TestFilterCrossServiceCrossGroupEdges:
    def test_same_group_unchanged(self, cross_service_nodes: dict[str, KindNode]):
        """Same group edge (cert-manager -> cert-manager) -> unchanged."""
        edge = _make_edge("cert-manager.io/Certificate", "cert-manager.io/Issuer")
        result = _filter_cross_service_cross_group_edges([edge], cross_service_nodes)
        assert len(result) == 1
        assert result[0].edge_type == "hard"

    def test_different_group_same_service_unchanged(self, cross_service_nodes: dict[str, KindNode]):
        """Different group, same service (flux helm -> flux source) -> unchanged."""
        edge = _make_edge("helm.toolkit.fluxcd.io/HelmRelease", "source.toolkit.fluxcd.io/GitRepository")
        result = _filter_cross_service_cross_group_edges([edge], cross_service_nodes)
        assert len(result) == 1
        assert result[0].edge_type == "hard"

    def test_different_group_different_service_heuristic_demoted(self, cross_service_nodes: dict[str, KindNode]):
        """Different group and service with new FN detector source -> demoted."""
        edge = _make_edge(
            "networking.istio.io/EnvoyFilter", "postgresql.cnpg.io/Cluster",
            edge_type="hard", detection_source="ref_detector:suffix_ref_tuple",
        )
        result = _filter_cross_service_cross_group_edges([edge], cross_service_nodes)
        assert len(result) == 1
        assert result[0].edge_type == "optional"

    def test_different_group_different_service_soft_heuristic_demoted(self, cross_service_nodes: dict[str, KindNode]):
        """Different group and service (prom -> flux) with soft heuristic -> demoted."""
        edge = _make_edge(
            "monitoring.coreos.com/AlertmanagerConfig",
            "notification.toolkit.fluxcd.io/Receiver",
            edge_type="soft",
            detection_source="ref_detector:suffix_ref_tuple",
        )
        result = _filter_cross_service_cross_group_edges([edge], cross_service_nodes)
        assert len(result) == 1
        assert result[0].edge_type == "optional"

    def test_different_group_different_service_strong_source_unchanged(self, cross_service_nodes: dict[str, KindNode]):
        """Different group and service with strong source (ref_tuple) -> unchanged."""
        edge = _make_edge(
            "networking.istio.io/EnvoyFilter", "postgresql.cnpg.io/Cluster",
            edge_type="hard", detection_source="ref_detector:ref_tuple",
        )
        result = _filter_cross_service_cross_group_edges([edge], cross_service_nodes)
        assert len(result) == 1
        assert result[0].edge_type == "hard"

    def test_already_optional_stays_optional(self, cross_service_nodes: dict[str, KindNode]):
        """Already optional cross-group cross-service edge -> stays optional."""
        edge = _make_edge(
            "networking.istio.io/EnvoyFilter",
            "postgresql.cnpg.io/Cluster",
            edge_type="optional",
            detection_source="ref_detector:suffix_ref_tuple",
        )
        result = _filter_cross_service_cross_group_edges([edge], cross_service_nodes)
        assert len(result) == 1
        assert result[0].edge_type == "optional"

    def test_missing_node_unchanged(self, cross_service_nodes: dict[str, KindNode]):
        """Edge with node not in nodes dict -> unchanged (safety)."""
        edge = _make_edge("unknown.io/Foo", "postgresql.cnpg.io/Cluster", edge_type="hard")
        result = _filter_cross_service_cross_group_edges([edge], cross_service_nodes)
        assert len(result) == 1
        assert result[0].edge_type == "hard"

    def test_external_node_unchanged(self, cross_service_nodes: dict[str, KindNode]):
        """Edge to external node -> unchanged (don't demote core K8s refs)."""
        nodes = dict(cross_service_nodes)
        nodes["/Secret"] = KindNode(kind="Secret", group="", service="core", is_external=True)
        edge = _make_edge(
            "cert-manager.io/Certificate", "/Secret",
            edge_type="soft", detection_source="ref_detector:suffix_ref_tuple",
        )
        nodes["cert-manager.io/Certificate"] = KindNode(
            kind="Certificate", group="cert-manager.io", service="cert-manager",
        )
        result = _filter_cross_service_cross_group_edges([edge], nodes)
        assert len(result) == 1
        assert result[0].edge_type == "soft"
