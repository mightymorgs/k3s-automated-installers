"""Tests for OLM dependency adapter — CRD Phase 4 Section 02."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.olm_loader import GVKRef
from idi.generation.dep_adapters.base import OperationInfo
from idi.generation.dep_adapters.olm_deps import OlmDepAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry() -> KindRegistry:
    """Registry with core K8s + cert-manager CRDs pre-registered."""
    reg = KindRegistry()
    reg.register("Certificate", "certificates", "cert-manager.io")
    reg.register("Issuer", "issuers", "cert-manager.io")
    reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io")
    return reg


def _make_operation(service: str = "external-secrets") -> OperationInfo:
    return OperationInfo(
        service=service,
        resource="externalsecrets",
        operation="create",
        method="POST",
        path="/apis/external-secrets.io/v1beta1/namespaces/{ns}/externalsecrets",
        body_schema={},
        response_schema={},
    )


def _make_csv_with_required(required: list[dict], owned: list[dict] | None = None) -> dict:
    """Build a minimal OLM CSV dict."""
    return {
        "spec": {
            "customresourcedefinitions": {
                "owned": owned or [],
                "required": required,
            },
        },
    }


def _make_csv_with_owned(owned: list[dict]) -> dict:
    return _make_csv_with_required([], owned=owned)


# ---------------------------------------------------------------------------
# Class attributes
# ---------------------------------------------------------------------------


class TestClassAttributes:
    def test_name(self):
        adapter = OlmDepAdapter()
        assert adapter.name == "olm_deps"

    def test_priority(self):
        adapter = OlmDepAdapter()
        assert adapter.priority == 95


# ---------------------------------------------------------------------------
# matches()
# ---------------------------------------------------------------------------


class TestMatches:
    def test_apis_path(self):
        adapter = OlmDepAdapter()
        spec = {"paths": {"/apis/external-secrets.io/v1beta1/namespaces/{ns}/externalsecrets": {}}}
        assert adapter.matches(spec, "external-secrets") is True

    def test_api_v1_namespaces(self):
        adapter = OlmDepAdapter()
        spec = {"paths": {"/api/v1/namespaces/{ns}/configmaps": {}}}
        assert adapter.matches(spec, "test") is True

    def test_rest_path_no_match(self):
        adapter = OlmDepAdapter()
        spec = {"paths": {"/v1/users": {}}}
        assert adapter.matches(spec, "test") is False

    def test_empty_spec(self):
        adapter = OlmDepAdapter()
        assert adapter.matches({}, "test") is False


# ---------------------------------------------------------------------------
# detect_dependencies() — required GVKs
# ---------------------------------------------------------------------------


class TestRequiredGvks:
    def test_required_produces_dependency(self):
        """CSV with required GVK produces Dependency at confidence 0.95."""
        reg = _make_registry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_required([
            {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert len(deps) == 1
        assert deps[0].confidence == 0.95

    def test_field_includes_group(self):
        """Dependency field is 'olm:required:{group}/{Kind}'."""
        reg = _make_registry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_required([
            {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert deps[0].field == "olm:required:cert-manager.io/Certificate"

    def test_target_resource_is_plural(self):
        """Dependency target_resource is KindRegistry plural."""
        reg = _make_registry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_required([
            {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert deps[0].target_resource == "certificates"

    def test_fact_ref_crdfacts_uri(self):
        """Dependency fact_ref uses crdfacts:// URI with #name fragment."""
        reg = _make_registry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_required([
            {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert deps[0].fact_ref == "crdfacts://cert-manager.io/Certificate#name"

    def test_source_olm_required(self):
        """Dependency source is 'olm_deps:required'."""
        reg = _make_registry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_required([
            {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert deps[0].source == "olm_deps:required"

    def test_lineage_type_reference(self):
        """Dependency lineage_type is 'reference'."""
        reg = _make_registry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_required([
            {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert deps[0].lineage_type == "reference"

    def test_unknown_kind_skipped(self):
        """Required GVK with Kind not in KindRegistry is skipped."""
        reg = KindRegistry()  # No CRDs registered
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_required([
            {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert deps == []

    def test_no_csv_returns_empty(self):
        """No CSV available returns empty list."""
        adapter = OlmDepAdapter(registry=_make_registry())

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=None):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert deps == []

    def test_malformed_csv_returns_empty(self):
        """Malformed CSV (missing spec) returns empty list."""
        adapter = OlmDepAdapter(registry=_make_registry())
        csv = {"not_spec": {}}

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert deps == []

    def test_results_cached_per_service(self):
        """Second call for same service does not re-fetch."""
        reg = _make_registry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_required([
            {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv) as mock_fetch:
            adapter.detect_dependencies(_make_operation(), {}, set())
            adapter.detect_dependencies(_make_operation(), {}, set())

        mock_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# detect_dependencies() — owned GVK registration
# ---------------------------------------------------------------------------


class TestOwnedGvks:
    def test_owned_registers_in_kindregistry(self):
        """Owned GVK registers Kind in KindRegistry with correct plural."""
        reg = KindRegistry()  # Empty (no CRDs)
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_owned([
            {"name": "externalsecrets.external-secrets.io", "kind": "ExternalSecret", "version": "v1beta1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            adapter.detect_dependencies(_make_operation(), {}, set())

        assert reg.kind_to_plural("ExternalSecret") == "externalsecrets"

    def test_owned_registers_correct_group(self):
        """Owned GVK registers correct group."""
        reg = KindRegistry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_owned([
            {"name": "externalsecrets.external-secrets.io", "kind": "ExternalSecret", "version": "v1beta1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            adapter.detect_dependencies(_make_operation(), {}, set())

        assert reg.group_for_kind("ExternalSecret") == "external-secrets.io"

    def test_idempotent_registration(self):
        """Running adapter twice does not corrupt registry."""
        reg = KindRegistry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_owned([
            {"name": "externalsecrets.external-secrets.io", "kind": "ExternalSecret", "version": "v1beta1"},
        ])

        # Run twice (different service names to bypass per-service cache).
        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            adapter.detect_dependencies(
                _make_operation(service="svc-a"), {}, set(),
            )
            adapter.detect_dependencies(
                _make_operation(service="svc-b"), {}, set(),
            )

        # Still only one entry.
        assert reg.kind_to_plural("ExternalSecret") == "externalsecrets"
        assert reg.group_for_kind("ExternalSecret") == "external-secrets.io"

    def test_owned_produces_no_dependency_edges(self):
        """Owned GVKs produce no Dependency edges."""
        reg = KindRegistry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_owned([
            {"name": "externalsecrets.external-secrets.io", "kind": "ExternalSecret", "version": "v1beta1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            deps = adapter.detect_dependencies(_make_operation(), {}, set())

        assert deps == []


# ---------------------------------------------------------------------------
# detect_outputs()
# ---------------------------------------------------------------------------


class TestDetectOutputs:
    def test_always_returns_empty(self):
        """detect_outputs always returns empty list."""
        reg = _make_registry()
        adapter = OlmDepAdapter(registry=reg)
        csv = _make_csv_with_required([
            {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
        ])

        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            outputs = adapter.detect_outputs(_make_operation(), {})

        assert outputs == []


# ---------------------------------------------------------------------------
# Default no-arg construction
# ---------------------------------------------------------------------------


class TestDefaultConstruction:
    def test_no_arg_instantiation(self):
        """OlmDepAdapter can be instantiated without args (for discovery)."""
        adapter = OlmDepAdapter()
        assert adapter.registry is not None
        assert adapter.name == "olm_deps"
