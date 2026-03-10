"""Tests for detect_scale_subresource (C20) in ref_detector.py."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import detect_scale_subresource


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    """KindRegistry with core resources + some CRDs."""
    reg = KindRegistry()
    reg.register("Certificate", "certificates", "cert-manager.io")
    return reg


def _make_crd_spec(
    *,
    has_scale: bool = True,
    spec_replicas_path: str = ".spec.replicas",
    status_replicas_path: str = ".status.replicas",
    spec_properties: dict | None = None,
    versions: list | None = None,
) -> dict:
    """Build a CRD spec dict with optional scale subresource."""
    if versions is not None:
        return {"versions": versions}

    version: dict = {
        "name": "v1",
        "served": True,
        "storage": True,
        "schema": {
            "openAPIV3Schema": {
                "type": "object",
                "properties": {
                    "spec": {
                        "type": "object",
                        "properties": spec_properties or {},
                    },
                },
            },
        },
    }
    if has_scale:
        version["subresources"] = {
            "scale": {
                "specReplicasPath": spec_replicas_path,
                "statusReplicasPath": status_replicas_path,
            },
            "status": {},
        }

    return {"versions": [version]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDetectScaleSubresource:
    def test_with_scale_and_deployment_ref(self, registry):
        """CRD with scale + deploymentRef field -> output_declaration."""
        crd_spec = _make_crd_spec(
            spec_properties={
                "deploymentName": {"type": "string"},
                "replicas": {"type": "integer"},
            },
        )
        results = detect_scale_subresource(crd_spec, "MyScaler", "", registry)
        assert len(results) == 1
        r = results[0]
        assert r.role == "output_declaration"
        assert r.confidence == 0.9
        assert r.target_kind == "Deployment"
        assert r.detection_source == "ref_detector:scale_subresource"

    def test_with_statefulset_ref(self, registry):
        """CRD with scale + statefulSetRef -> target_kind=StatefulSet."""
        crd_spec = _make_crd_spec(
            spec_properties={
                "statefulSetRef": {"type": "object"},
                "replicas": {"type": "integer"},
            },
        )
        results = detect_scale_subresource(crd_spec, "MyScaler", "", registry)
        assert len(results) == 1
        assert results[0].target_kind == "StatefulSet"

    def test_without_scale_subresource(self, registry):
        """CRD without subresources.scale -> empty list."""
        crd_spec = _make_crd_spec(has_scale=False)
        results = detect_scale_subresource(crd_spec, "MyApp", "", registry)
        assert results == []

    def test_missing_spec_replicas_path(self, registry):
        """Scale subresource missing specReplicasPath -> empty list."""
        crd_spec = {
            "versions": [{
                "name": "v1",
                "subresources": {
                    "scale": {
                        "statusReplicasPath": ".status.replicas",
                    },
                },
                "schema": {"openAPIV3Schema": {"type": "object", "properties": {
                    "spec": {"type": "object", "properties": {}},
                }}},
            }],
        }
        results = detect_scale_subresource(crd_spec, "MyApp", "", registry)
        assert results == []

    def test_empty_spec_replicas_path(self, registry):
        """specReplicasPath is empty string -> empty list."""
        crd_spec = _make_crd_spec(spec_replicas_path="")
        results = detect_scale_subresource(crd_spec, "MyApp", "", registry)
        assert results == []

    def test_no_workload_kind_fields(self, registry):
        """Scale subresource but no fields reference workload Kinds -> empty list."""
        crd_spec = _make_crd_spec(
            spec_properties={
                "config": {"type": "string"},
                "replicas": {"type": "integer"},
            },
        )
        results = detect_scale_subresource(crd_spec, "MyApp", "", registry)
        assert results == []

    def test_spec_replicas_path_wrong_prefix(self, registry):
        """specReplicasPath not starting with .spec. -> skip."""
        crd_spec = _make_crd_spec(spec_replicas_path=".replicas")
        results = detect_scale_subresource(crd_spec, "MyApp", "", registry)
        assert results == []

    def test_status_replicas_path_wrong_prefix(self, registry):
        """statusReplicasPath not starting with .status. -> skip."""
        crd_spec = _make_crd_spec(status_replicas_path=".replicas")
        results = detect_scale_subresource(crd_spec, "MyApp", "", registry)
        assert results == []

    def test_multi_version_one_has_scale(self, registry):
        """Multiple versions, only one has scale -> still detects."""
        versions = [
            {
                "name": "v1alpha1",
                "schema": {"openAPIV3Schema": {"type": "object", "properties": {
                    "spec": {"type": "object", "properties": {
                        "deploymentRef": {"type": "object"},
                    }},
                }}},
            },
            {
                "name": "v1",
                "subresources": {
                    "scale": {
                        "specReplicasPath": ".spec.replicas",
                        "statusReplicasPath": ".status.replicas",
                    },
                },
                "schema": {"openAPIV3Schema": {"type": "object", "properties": {
                    "spec": {"type": "object", "properties": {
                        "deploymentRef": {"type": "object"},
                    }},
                }}},
            },
        ]
        crd_spec = _make_crd_spec(versions=versions)
        results = detect_scale_subresource(crd_spec, "MyScaler", "", registry)
        assert len(results) == 1
        assert results[0].target_kind == "Deployment"

    def test_detection_source(self, registry):
        """detection_source is set correctly."""
        crd_spec = _make_crd_spec(
            spec_properties={
                "deploymentName": {"type": "string"},
            },
        )
        results = detect_scale_subresource(crd_spec, "MyScaler", "", registry)
        assert len(results) == 1
        assert results[0].detection_source == "ref_detector:scale_subresource"

    def test_field_is_scale_subresource(self, registry):
        """Emitted ClassifiedField.field is 'scale_subresource'."""
        crd_spec = _make_crd_spec(
            spec_properties={
                "deploymentName": {"type": "string"},
            },
        )
        results = detect_scale_subresource(crd_spec, "MyScaler", "", registry)
        assert len(results) == 1
        assert results[0].field == "scale_subresource"

    def test_empty_versions_list(self, registry):
        """No versions at all -> empty list."""
        crd_spec = {"versions": []}
        results = detect_scale_subresource(crd_spec, "MyApp", "", registry)
        assert results == []
