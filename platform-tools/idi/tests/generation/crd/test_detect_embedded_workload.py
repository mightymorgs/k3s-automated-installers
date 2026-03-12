"""Tests for detect_embedded_workload (C22) in ref_detector.py."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import (
    _match_workload_fingerprint,
    WORKLOAD_SHAPES,
    detect_embedded_workload,
)
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    return KindRegistry()


def _make_field(
    name: str,
    schema: dict | None = None,
    path: str | None = None,
    parent_path: str = "spec",
) -> WalkedField:
    if schema is None:
        schema = {"type": "object"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path,
        name=name,
        schema=schema,
        depth=1,
        is_array_item=False,
        required=False,
        parent_path=parent_path,
    )


def _pod_template_nested_schema(extra_props: dict | None = None) -> dict:
    """Build a nested PodTemplateSpec-like schema (spec.containers)."""
    spec_props = {
        "containers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image": {"type": "string"},
                    "name": {"type": "string"},
                    "ports": {"type": "array"},
                },
            },
        },
    }
    if extra_props:
        spec_props.update(extra_props)
    return {
        "type": "object",
        "properties": {
            "metadata": {"type": "object"},
            "spec": {
                "type": "object",
                "properties": spec_props,
            },
        },
    }


def _pod_template_flattened_schema(extra_props: dict | None = None) -> dict:
    """Build a flattened PodTemplateSpec-like schema (containers at top level)."""
    props = {
        "containers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
        },
    }
    if extra_props:
        props.update(extra_props)
    return {
        "type": "object",
        "properties": props,
    }


# ---------------------------------------------------------------------------
# Tests: detect_embedded_workload
# ---------------------------------------------------------------------------


class TestDetectEmbeddedWorkload:
    def test_nested_pod_template_with_volumes(self, registry):
        """Nested PodTemplateSpec: spec.containers + volumes -> Pod."""
        schema = _pod_template_nested_schema({
            "volumes": {"type": "array"},
            "serviceAccountName": {"type": "string"},
        })
        field = _make_field("template", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is not None
        assert result.role == "output_declaration"
        assert result.target_kind == "Pod"
        assert result.confidence == 0.8

    def test_nested_pod_template_minimal(self, registry):
        """Nested PodTemplateSpec: spec.containers + 1 optional -> Pod (min_match_count=2)."""
        schema = _pod_template_nested_schema({
            "volumes": {"type": "array"},
        })
        field = _make_field("template", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is not None
        assert result.target_kind == "Pod"

    def test_only_containers_no_match(self, registry):
        """Only containers, no optional properties -> None (below min_match_count)."""
        schema = _pod_template_nested_schema()
        field = _make_field("template", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is None

    def test_flattened_requires_higher_threshold(self, registry):
        """Flattened PodTemplateSpec with 2 matches (containers + volumes) -> None."""
        schema = _pod_template_flattened_schema({
            "volumes": {"type": "array"},
        })
        field = _make_field("podSpec", schema=schema)
        result = detect_embedded_workload(field, registry)
        # Flattened requires min_match_count + 1 = 3; only 2 matches.
        assert result is None

    def test_flattened_with_three_matches(self, registry):
        """Flattened PodTemplateSpec with 3 matches -> Pod."""
        schema = _pod_template_flattened_schema({
            "volumes": {"type": "array"},
            "serviceAccountName": {"type": "string"},
        })
        field = _make_field("podSpec", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is not None
        assert result.target_kind == "Pod"

    def test_containers_not_array(self, registry):
        """containers is not an array -> no match."""
        schema = {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {
                        "containers": {"type": "object"},
                        "volumes": {"type": "array"},
                        "serviceAccountName": {"type": "string"},
                    },
                },
            },
        }
        field = _make_field("template", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is None

    def test_container_items_missing_shape(self, registry):
        """containers[] items lack {image, name} -> no match."""
        schema = {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "properties": {
                        "containers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "command": {"type": "string"},
                                },
                            },
                        },
                        "volumes": {"type": "array"},
                        "serviceAccountName": {"type": "string"},
                    },
                },
            },
        }
        field = _make_field("template", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is None

    def test_job_spec_shape(self, registry):
        """JobSpec: template + backoffLimit -> Job."""
        schema = {
            "type": "object",
            "properties": {
                "template": {"type": "object"},
                "backoffLimit": {"type": "integer"},
                "completions": {"type": "integer"},
            },
        }
        field = _make_field("jobTemplate", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is not None
        assert result.target_kind == "Job"
        assert result.confidence == 0.8

    def test_job_spec_only_template(self, registry):
        """JobSpec with only template -> None (below min_match_count)."""
        schema = {
            "type": "object",
            "properties": {
                "template": {"type": "object"},
            },
        }
        field = _make_field("jobTemplate", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is None

    def test_service_spec_shape(self, registry):
        """ServiceSpec: ports + selector + type -> Service."""
        schema = {
            "type": "object",
            "properties": {
                "ports": {"type": "array"},
                "selector": {"type": "object"},
                "type": {"type": "string"},
            },
        }
        field = _make_field("serviceSpec", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is not None
        assert result.target_kind == "Service"

    def test_service_spec_only_ports(self, registry):
        """ServiceSpec with only ports -> None."""
        schema = {
            "type": "object",
            "properties": {
                "ports": {"type": "array"},
            },
        }
        field = _make_field("svc", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is None

    def test_no_properties(self, registry):
        """Field with no properties -> None."""
        field = _make_field("empty", schema={"type": "string"})
        result = detect_embedded_workload(field, registry)
        assert result is None

    def test_empty_properties(self, registry):
        """Field with empty properties -> None."""
        schema = {"type": "object", "properties": {}}
        field = _make_field("empty", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is None

    def test_detection_source(self, registry):
        """detection_source is correct."""
        schema = _pod_template_nested_schema({
            "volumes": {"type": "array"},
        })
        field = _make_field("template", schema=schema)
        result = detect_embedded_workload(field, registry)
        assert result is not None
        assert result.detection_source == "ref_detector:embedded_workload"


# ---------------------------------------------------------------------------
# Tests: _match_workload_fingerprint helper
# ---------------------------------------------------------------------------


class TestMatchWorkloadFingerprint:
    def test_pod_template_match(self):
        props = {
            "containers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
            },
            "volumes": {"type": "array"},
        }
        fp = WORKLOAD_SHAPES["PodTemplateSpec"]
        assert _match_workload_fingerprint(props, fp) is True

    def test_partial_match_below_threshold(self):
        props = {
            "containers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
            },
        }
        fp = WORKLOAD_SHAPES["PodTemplateSpec"]
        # Only 1 match (containers), min is 2.
        assert _match_workload_fingerprint(props, fp) is False

    def test_flattened_higher_threshold(self):
        props = {
            "containers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
            },
            "volumes": {"type": "array"},
        }
        fp = WORKLOAD_SHAPES["PodTemplateSpec"]
        # Flattened: min_match_count + 1 = 3; only 2 matches.
        assert _match_workload_fingerprint(props, fp, is_flattened=True) is False
