"""Tests for OpenAPI Links Parser — dep_adapters/link_deps.py."""
from __future__ import annotations

import logging

import pytest

from idi.generation.dep_adapters.base import (
    DetectionSource,
    Dependency,
    OperationInfo,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter():
    from idi.generation.dep_adapters.link_deps import LinkDepsAdapter
    return LinkDepsAdapter()


@pytest.fixture
def spec_with_links():
    """OAS 3.0 spec: POST /users -> links to GET /users/{userId}."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"id": {"type": "string"}},
                                    },
                                },
                            },
                            "links": {
                                "GetUser": {
                                    "operationId": "getUser",
                                    "parameters": {
                                        "userId": "$response.body#/id",
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "/users/{userId}": {
                "get": {
                    "operationId": "getUser",
                    "parameters": [
                        {"name": "userId", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def _make_op(path: str, method: str, service: str = "test") -> OperationInfo:
    return OperationInfo(
        service=service,
        resource=path.strip("/").split("/")[0],
        operation=method,
        path=path,
        method=method,
        body_schema={},
        response_schema={},
    )


# ---------------------------------------------------------------------------
# TestLinksAdapterMatching
# ---------------------------------------------------------------------------

class TestLinksAdapterMatching:
    """Tests for the matches() method."""

    def test_matches_openapi_30_spec(self, adapter):
        spec = {"openapi": "3.0.0", "paths": {}}
        assert adapter.matches(spec, "test") is True

    def test_matches_openapi_31_spec(self, adapter):
        spec = {"openapi": "3.1.0", "paths": {}}
        assert adapter.matches(spec, "test") is True

    def test_no_match_swagger_20(self, adapter):
        spec = {"swagger": "2.0", "paths": {}}
        assert adapter.matches(spec, "test") is False

    def test_no_match_no_version(self, adapter):
        spec = {"paths": {}}
        assert adapter.matches(spec, "test") is False

    def test_spec_without_links(self, adapter, minimal_openapi_spec):
        """OAS 3.0 spec with no links -> detect_dependencies returns empty."""
        op = _make_op("/users", "post")
        deps = adapter.detect_dependencies(op, minimal_openapi_spec, set())
        assert deps == []


# ---------------------------------------------------------------------------
# TestLinkResolution
# ---------------------------------------------------------------------------

class TestLinkResolution:
    """Tests for resolving link targets."""

    def test_link_with_operation_id(self, adapter, spec_with_links):
        op = _make_op("/users", "post")
        deps = adapter.detect_dependencies(op, spec_with_links, set())
        assert len(deps) == 1
        assert deps[0].target_resource == "users"
        assert deps[0].target_operation == "get"

    def test_link_with_relative_operation_ref(self, adapter):
        """operationRef '#/paths/~1users~1{userId}/get' resolves correctly."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "responses": {
                            "201": {
                                "description": "Created",
                                "links": {
                                    "GetUser": {
                                        "operationRef": "#/paths/~1users~1{userId}/get",
                                        "parameters": {
                                            "userId": "$response.body#/id",
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
                "/users/{userId}": {
                    "get": {
                        "operationId": "getUser",
                        "parameters": [
                            {"name": "userId", "in": "path", "required": True,
                             "schema": {"type": "string"}},
                        ],
                        "responses": {"200": {"description": "OK"}},
                    },
                },
            },
        }
        op = _make_op("/users", "post")
        deps = adapter.detect_dependencies(op, spec, set())
        assert len(deps) == 1
        assert deps[0].target_resource == "users"
        assert deps[0].target_operation == "get"

    def test_link_with_external_url_operation_ref(self, adapter, caplog):
        """External operationRef URL -> skipped with warning."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "responses": {
                            "201": {
                                "description": "Created",
                                "links": {
                                    "ExtLink": {
                                        "operationRef": "https://example.com/spec.json#/paths/~1foo/get",
                                        "parameters": {"id": "$response.body#/id"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        op = _make_op("/users", "post")
        with caplog.at_level(logging.WARNING):
            deps = adapter.detect_dependencies(op, spec, set())
        assert deps == []
        assert any("SSRF" in r.message or "external" in r.message.lower() for r in caplog.records)

    def test_link_referencing_nonexistent_operation_id(self, adapter, caplog):
        """operationId 'doesNotExist' -> skipped with warning."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "responses": {
                            "201": {
                                "description": "Created",
                                "links": {
                                    "Ghost": {
                                        "operationId": "doesNotExist",
                                        "parameters": {"id": "$response.body#/id"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        op = _make_op("/users", "post")
        with caplog.at_level(logging.WARNING):
            deps = adapter.detect_dependencies(op, spec, set())
        assert deps == []
        assert any("doesNotExist" in r.message for r in caplog.records)

    def test_multiple_links_from_same_response(self, adapter):
        """Two links on the same response -> two dependencies."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "responses": {
                            "201": {
                                "description": "Created",
                                "links": {
                                    "GetUser": {
                                        "operationId": "getUser",
                                        "parameters": {"userId": "$response.body#/id"},
                                    },
                                    "DeleteUser": {
                                        "operationId": "deleteUser",
                                        "parameters": {"userId": "$response.body#/id"},
                                    },
                                },
                            },
                        },
                    },
                },
                "/users/{userId}": {
                    "get": {
                        "operationId": "getUser",
                        "parameters": [
                            {"name": "userId", "in": "path", "required": True,
                             "schema": {"type": "string"}},
                        ],
                        "responses": {"200": {"description": "OK"}},
                    },
                    "delete": {
                        "operationId": "deleteUser",
                        "parameters": [
                            {"name": "userId", "in": "path", "required": True,
                             "schema": {"type": "string"}},
                        ],
                        "responses": {"204": {"description": "Deleted"}},
                    },
                },
            },
        }
        op = _make_op("/users", "post")
        deps = adapter.detect_dependencies(op, spec, set())
        assert len(deps) == 2
        methods = {d.target_operation for d in deps}
        assert methods == {"get", "delete"}


# ---------------------------------------------------------------------------
# TestRuntimeExpressionParsing
# ---------------------------------------------------------------------------

class TestRuntimeExpressionParsing:
    """Tests for the two-stage runtime expression parser."""

    def test_response_body_json_pointer(self):
        from idi.generation.dep_adapters.link_deps import parse_runtime_expression
        result = parse_runtime_expression("$response.body#/id")
        assert result is not None
        assert result.source_field == "id"

    def test_response_body_nested_pointer(self):
        from idi.generation.dep_adapters.link_deps import parse_runtime_expression
        result = parse_runtime_expression("$response.body#/data/user/id")
        assert result is not None
        assert result.source_field == "data.user.id"

    def test_request_path_param(self):
        from idi.generation.dep_adapters.link_deps import parse_runtime_expression
        result = parse_runtime_expression("$request.path.userId")
        assert result is not None
        assert result.source_field == "userId"
        assert result.source_type == "request.path"

    def test_request_query_param(self):
        from idi.generation.dep_adapters.link_deps import parse_runtime_expression
        result = parse_runtime_expression("$request.query.filter")
        assert result is not None
        assert result.source_field == "filter"
        assert result.source_type == "request.query"

    def test_response_header(self):
        from idi.generation.dep_adapters.link_deps import parse_runtime_expression
        result = parse_runtime_expression("$response.header.Location")
        assert result is not None
        assert result.source_field == "Location"
        assert result.source_type == "response.header"

    def test_json_pointer_tilde1_escape(self):
        from idi.generation.dep_adapters.link_deps import parse_runtime_expression
        result = parse_runtime_expression("$response.body#/a~1b")
        assert result is not None
        assert result.source_field == "a/b"

    def test_json_pointer_tilde0_escape(self):
        from idi.generation.dep_adapters.link_deps import parse_runtime_expression
        result = parse_runtime_expression("$response.body#/a~0b")
        assert result is not None
        assert result.source_field == "a~b"

    def test_unparseable_expression(self, caplog):
        from idi.generation.dep_adapters.link_deps import parse_runtime_expression
        with caplog.at_level(logging.WARNING):
            result = parse_runtime_expression("$$invalid.expression")
        assert result is None
        assert any("parse" in r.message.lower() or "invalid" in r.message.lower()
                    for r in caplog.records)


# ---------------------------------------------------------------------------
# TestDependencyEmission
# ---------------------------------------------------------------------------

class TestDependencyEmission:
    """Tests for the emitted Dependency objects."""

    def test_confidence_is_1_0(self, adapter, spec_with_links):
        op = _make_op("/users", "post")
        deps = adapter.detect_dependencies(op, spec_with_links, set())
        assert len(deps) == 1
        assert deps[0].confidence == 1.0

    def test_lineage_type_is_explicit(self, adapter, spec_with_links):
        op = _make_op("/users", "post")
        deps = adapter.detect_dependencies(op, spec_with_links, set())
        assert deps[0].lineage_type == "explicit"

    def test_source_identifies_adapter(self, adapter, spec_with_links):
        op = _make_op("/users", "post")
        deps = adapter.detect_dependencies(op, spec_with_links, set())
        assert deps[0].source == "link_deps"
        assert deps[0].detection_source == DetectionSource.OPENAPI_LINK

    def test_detect_outputs_returns_empty(self, adapter, spec_with_links):
        op = _make_op("/users", "post")
        outputs = adapter.detect_outputs(op, spec_with_links)
        assert outputs == []


# ---------------------------------------------------------------------------
# TestAdapterRegistration
# ---------------------------------------------------------------------------

class TestAdapterRegistration:
    """Tests for priority and registry integration."""

    def test_priority_above_generic_odg(self, adapter):
        from idi.generation.dep_adapters.generic_odg import GenericODGAdapter
        assert adapter.priority > GenericODGAdapter.priority

    def test_auto_discovered_by_registry(self):
        from idi.generation.dep_adapters.registry import DepAdapterRegistry
        registry = DepAdapterRegistry()
        adapter_names = [a.name for a in registry._adapters]
        assert "link_deps" in adapter_names
