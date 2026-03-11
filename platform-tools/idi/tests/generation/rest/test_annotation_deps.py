"""Tests for dep_adapters/annotation_deps.py — annotation parsing adapter."""
import logging

import pytest

from idi.generation.dep_adapters.annotation_deps import AnnotationDepsAdapter
from idi.generation.dep_adapters.base import (
    Dependency,
    DetectionSource,
    OperationInfo,
)


@pytest.fixture
def adapter():
    return AnnotationDepsAdapter()


@pytest.fixture
def base_spec():
    """Minimal OAS 3.0 spec with /users and /users/{userId}/posts paths."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {"operationId": "listUsers", "responses": {"200": {}}},
                "post": {"operationId": "createUser", "responses": {"201": {}}},
            },
            "/users/{userId}/posts": {
                "get": {"operationId": "listPosts", "responses": {"200": {}}},
                "post": {"operationId": "createPost", "responses": {"201": {}}},
            },
        },
    }


@pytest.fixture
def dummy_operation():
    return OperationInfo(
        service="test-api",
        resource="posts",
        operation="createPost",
        path="/users/{userId}/posts",
        method="POST",
        body_schema={},
        response_schema={},
    )


class TestMatches:
    """matches() returns True when annotation keys are present."""

    def test_matches_idi_annotations(self, adapter, base_spec):
        base_spec["x-idi-annotations"] = []
        assert adapter.matches(base_spec, "test") is True

    def test_matches_restler_annotations(self, adapter, base_spec):
        base_spec["x-restler-annotations"] = []
        assert adapter.matches(base_spec, "test") is True

    def test_matches_both_annotations(self, adapter, base_spec):
        base_spec["x-idi-annotations"] = []
        base_spec["x-restler-annotations"] = []
        assert adapter.matches(base_spec, "test") is True

    def test_no_annotations_returns_false(self, adapter, base_spec):
        assert adapter.matches(base_spec, "test") is False


class TestIdiAnnotations:
    """x-idi-annotations parsing for producer/consumer dependencies."""

    def test_dependency_emitted_at_099_explicit(self, adapter, base_spec, dummy_operation):
        """Producer/consumer annotation emits Dependency at confidence 0.99."""
        base_spec["x-idi-annotations"] = [
            {
                "producer_endpoint": "/users",
                "producer_method": "POST",
                "producer_field": "id",
                "consumer_field": "user_id",
            }
        ]
        deps = adapter.detect_dependencies(dummy_operation, base_spec, {"users", "posts"})
        assert len(deps) == 1
        dep = deps[0]
        assert dep.field == "user_id"
        assert dep.target_resource == "users"
        assert dep.confidence == 0.99
        assert dep.lineage_type == "explicit"
        assert dep.detection_source == DetectionSource.ANNOTATION
        assert "x-idi-annotations" in dep.source

    def test_classification_external_no_dependency(self, adapter, base_spec, dummy_operation):
        """Classification 'external' does not emit a Dependency."""
        base_spec["x-idi-annotations"] = [
            {"field": "external_ref", "classification": "external"}
        ]
        deps = adapter.detect_dependencies(dummy_operation, base_spec, {"users"})
        assert deps == []

    def test_empty_annotation_list(self, adapter, base_spec, dummy_operation):
        """Empty annotation list returns empty dependencies."""
        base_spec["x-idi-annotations"] = []
        deps = adapter.detect_dependencies(dummy_operation, base_spec, set())
        assert deps == []


class TestRestlerAnnotations:
    """x-restler-annotations parsing for RESTler compatibility."""

    def test_restler_format_emits_dependency(self, adapter, base_spec, dummy_operation):
        """RESTler annotation emits Dependency at confidence 0.99."""
        base_spec["x-restler-annotations"] = [
            {
                "producer_resource_name": "users",
                "producer_method": "POST",
                "consumer_resource_name": "posts",
                "consumer_method": "POST",
            }
        ]
        deps = adapter.detect_dependencies(dummy_operation, base_spec, {"users", "posts"})
        assert len(deps) == 1
        dep = deps[0]
        assert dep.target_resource == "users"
        assert dep.confidence == 0.99
        assert dep.lineage_type == "explicit"
        assert "x-restler-annotations" in dep.source

    def test_restler_with_explicit_field_names(self, adapter, base_spec, dummy_operation):
        """RESTler annotation with explicit parameter names uses them."""
        base_spec["x-restler-annotations"] = [
            {
                "producer_resource_name": "users",
                "producer_method": "POST",
                "consumer_resource_name": "posts",
                "consumer_method": "POST",
                "producer_parameter_name": "id",
                "consumer_parameter_name": "author_id",
            }
        ]
        deps = adapter.detect_dependencies(dummy_operation, base_spec, {"users", "posts"})
        assert len(deps) == 1
        assert deps[0].field == "author_id"


class TestValidation:
    """Invalid annotations are rejected with warnings."""

    def test_invalid_endpoint_skipped(self, adapter, base_spec, dummy_operation, caplog):
        """Annotation referencing non-existent endpoint is skipped."""
        base_spec["x-idi-annotations"] = [
            {
                "producer_endpoint": "/nonexistent",
                "producer_method": "POST",
                "producer_field": "id",
                "consumer_field": "ref_id",
            }
        ]
        with caplog.at_level(logging.WARNING):
            deps = adapter.detect_dependencies(dummy_operation, base_spec, {"users"})
        assert deps == []
        assert any("non-existent" in r.message.lower() or "skipping" in r.message.lower()
                    for r in caplog.records)

    def test_invalid_method_skipped(self, adapter, base_spec, dummy_operation, caplog):
        """Annotation referencing non-existent method is skipped."""
        base_spec["x-idi-annotations"] = [
            {
                "producer_endpoint": "/users",
                "producer_method": "DELETE",
                "producer_field": "id",
                "consumer_field": "ref_id",
            }
        ]
        with caplog.at_level(logging.WARNING):
            deps = adapter.detect_dependencies(dummy_operation, base_spec, {"users"})
        assert deps == []

    def test_malformed_entry_skipped(self, adapter, base_spec, dummy_operation, caplog):
        """Entry missing required keys is skipped with warning."""
        base_spec["x-idi-annotations"] = [
            {"producer_endpoint": "/users"}  # missing other keys
        ]
        with caplog.at_level(logging.WARNING):
            deps = adapter.detect_dependencies(dummy_operation, base_spec, {"users"})
        assert deps == []

    def test_both_formats_parsed(self, adapter, base_spec, dummy_operation):
        """Both x-idi-annotations and x-restler-annotations are parsed together."""
        base_spec["x-idi-annotations"] = [
            {
                "producer_endpoint": "/users",
                "producer_method": "POST",
                "producer_field": "id",
                "consumer_field": "user_id",
            }
        ]
        base_spec["x-restler-annotations"] = [
            {
                "producer_resource_name": "users",
                "producer_method": "POST",
                "consumer_resource_name": "posts",
                "consumer_method": "POST",
            }
        ]
        deps = adapter.detect_dependencies(dummy_operation, base_spec, {"users", "posts"})
        assert len(deps) == 2
        assert all(d.lineage_type == "explicit" for d in deps)


class TestDetectOutputs:
    """detect_outputs always returns empty list."""

    def test_returns_empty(self, adapter, base_spec, dummy_operation):
        outputs = adapter.detect_outputs(dummy_operation, base_spec)
        assert outputs == []
