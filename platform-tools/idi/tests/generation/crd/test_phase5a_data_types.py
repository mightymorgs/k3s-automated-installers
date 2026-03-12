"""Tests for Phase 5A data types, constants, and helper functions."""
from __future__ import annotations

import json
import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from idi.generation.crd.ref_detector import (
    CatalogEntry,
    K8S_FORMAT_ALLOWLIST,
    K8S_NAME_PATTERNS,
    ShapeCatalog,
    WORKLOAD_SHAPES,
    WorkloadFingerprint,
    compute_schema_fingerprint,
)


# ---------------------------------------------------------------------------
# WorkloadFingerprint
# ---------------------------------------------------------------------------


class TestWorkloadFingerprint:
    def test_frozen_immutable(self):
        fp = WorkloadFingerprint(
            required_properties=frozenset({"containers"}),
            container_shape=frozenset({"image", "name"}),
            optional_properties=frozenset({"volumes"}),
            min_match_count=2,
            produces_kind="Pod",
        )
        with pytest.raises(FrozenInstanceError):
            fp.produces_kind = "Job"

    def test_stores_all_fields(self):
        fp = WorkloadFingerprint(
            required_properties=frozenset({"containers"}),
            container_shape=frozenset({"image", "name"}),
            optional_properties=frozenset({"volumes"}),
            min_match_count=2,
            produces_kind="Pod",
        )
        assert fp.required_properties == frozenset({"containers"})
        assert fp.container_shape == frozenset({"image", "name"})
        assert fp.optional_properties == frozenset({"volumes"})
        assert fp.min_match_count == 2
        assert fp.produces_kind == "Pod"


# ---------------------------------------------------------------------------
# WORKLOAD_SHAPES
# ---------------------------------------------------------------------------


class TestWorkloadShapes:
    def test_has_exactly_three_entries(self):
        assert len(WORKLOAD_SHAPES) == 3

    def test_contains_expected_keys(self):
        assert set(WORKLOAD_SHAPES.keys()) == {
            "PodTemplateSpec", "JobSpec", "ServiceSpec",
        }

    def test_pod_template_spec(self):
        fp = WORKLOAD_SHAPES["PodTemplateSpec"]
        assert fp.produces_kind == "Pod"
        assert "containers" in fp.required_properties
        assert "image" in fp.container_shape
        assert "name" in fp.container_shape

    def test_job_spec(self):
        fp = WORKLOAD_SHAPES["JobSpec"]
        assert fp.produces_kind == "Job"
        assert "template" in fp.required_properties
        assert len(fp.container_shape) == 0

    def test_service_spec(self):
        fp = WORKLOAD_SHAPES["ServiceSpec"]
        assert fp.produces_kind == "Service"
        assert "ports" in fp.required_properties
        assert len(fp.container_shape) == 0


# ---------------------------------------------------------------------------
# K8S_NAME_PATTERNS
# ---------------------------------------------------------------------------


class TestK8sNamePatterns:
    def test_has_four_patterns(self):
        assert len(K8S_NAME_PATTERNS) == 4

    def test_all_compile(self):
        for pat in K8S_NAME_PATTERNS:
            compiled = re.compile(pat)
            assert compiled is not None

    def test_rfc1123_matches_valid(self):
        pattern = re.compile(K8S_NAME_PATTERNS[0])
        assert pattern.match("my-resource-123")

    def test_rfc1123_rejects_invalid(self):
        pattern = re.compile(K8S_NAME_PATTERNS[0])
        assert pattern.match("My Resource!!") is None

    def test_rfc1123_rejects_empty(self):
        pattern = re.compile(K8S_NAME_PATTERNS[0])
        assert pattern.match("") is None

    def test_fqdn_matches_dotted(self):
        pattern = re.compile(K8S_NAME_PATTERNS[3])
        assert pattern.match("my.host.example.com")


# ---------------------------------------------------------------------------
# K8S_FORMAT_ALLOWLIST
# ---------------------------------------------------------------------------


class TestK8sFormatAllowlist:
    def test_exact_contents(self):
        assert K8S_FORMAT_ALLOWLIST == frozenset({
            "dns1123-label",
            "dns1123-subdomain",
            "hostname",
            "qualified-name",
        })


# ---------------------------------------------------------------------------
# CatalogEntry
# ---------------------------------------------------------------------------


class TestCatalogEntry:
    def test_frozen_immutable(self):
        entry = CatalogEntry(
            fingerprint="name:string",
            target_kind="Secret",
            confirmed_in=("SecretStore",),
            confidence=0.85,
            required_properties=frozenset({"name"}),
        )
        with pytest.raises(FrozenInstanceError):
            entry.target_kind = "ConfigMap"


# ---------------------------------------------------------------------------
# ShapeCatalog
# ---------------------------------------------------------------------------


class TestShapeCatalog:
    def test_load_missing_file(self, tmp_path):
        catalog = ShapeCatalog.load(str(tmp_path / "nonexistent.json"))
        assert catalog.shapes == {}

    def test_load_valid_file(self, tmp_path):
        data = {
            "version": "1.0",
            "generated": "2026-01-01T00:00:00Z",
            "shapes": [
                {
                    "fingerprint": "name:string",
                    "target_kind": "Secret",
                    "confirmed_in": ["SecretStore", "ExternalSecret"],
                    "confidence": 0.85,
                    "required_properties": ["name"],
                },
            ],
        }
        catalog_file = tmp_path / "shape_catalog.json"
        catalog_file.write_text(json.dumps(data), encoding="utf-8")
        catalog = ShapeCatalog.load(str(catalog_file))
        assert len(catalog.shapes) == 1
        assert "name:string" in catalog.shapes
        entry = catalog.shapes["name:string"]
        assert entry.target_kind == "Secret"
        assert entry.confidence == 0.85
        assert entry.confirmed_in == ("SecretStore", "ExternalSecret")
        assert entry.required_properties == frozenset({"name"})

    def test_lookup_found(self, tmp_path):
        data = {
            "version": "1.0",
            "shapes": [
                {
                    "fingerprint": "name:string",
                    "target_kind": "Secret",
                    "confirmed_in": ["SecretStore"],
                    "confidence": 0.8,
                    "required_properties": ["name"],
                },
            ],
        }
        catalog_file = tmp_path / "shape_catalog.json"
        catalog_file.write_text(json.dumps(data), encoding="utf-8")
        catalog = ShapeCatalog.load(str(catalog_file))
        entry = catalog.lookup("name:string")
        assert entry is not None
        assert entry.target_kind == "Secret"

    def test_lookup_not_found(self):
        catalog = ShapeCatalog(shapes={})
        assert catalog.lookup("nonexistent") is None


# ---------------------------------------------------------------------------
# compute_schema_fingerprint
# ---------------------------------------------------------------------------


class TestComputeSchemaFingerprint:
    def test_sorted_name_type_pairs(self):
        props = {
            "b_field": {"type": "integer"},
            "a_field": {"type": "string"},
        }
        result = compute_schema_fingerprint(props, required=["a_field", "b_field"])
        assert result == "a_field:string,b_field:integer"

    def test_optional_suffix(self):
        props = {
            "name": {"type": "string"},
            "namespace": {"type": "string"},
        }
        result = compute_schema_fingerprint(props, required=["name"])
        assert result == "name:string,namespace:string?"

    def test_deterministic(self):
        props = {
            "z": {"type": "string"},
            "a": {"type": "integer"},
            "m": {"type": "boolean"},
        }
        r1 = compute_schema_fingerprint(props, required=["a"])
        r2 = compute_schema_fingerprint(props, required=["a"])
        assert r1 == r2

    def test_canonical_example(self):
        props = {
            "name": {"type": "string"},
            "namespace": {"type": "string"},
            "key": {"type": "string"},
        }
        result = compute_schema_fingerprint(props, required=["name"])
        assert result == "key:string?,name:string,namespace:string?"

    def test_empty_properties(self):
        assert compute_schema_fingerprint({}) == ""

    def test_no_required(self):
        props = {"x": {"type": "string"}}
        result = compute_schema_fingerprint(props)
        assert result == "x:string?"

    def test_missing_type_defaults_to_string(self):
        props = {"field": {}}
        result = compute_schema_fingerprint(props, required=["field"])
        assert result == "field:string"
