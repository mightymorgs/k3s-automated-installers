"""Tests for identifier index pre-computation in verify.py."""
from __future__ import annotations

from idi.generation.dep_adapters.verify import build_identifier_index


def _spec_with_response(resource_path: str, method: str, properties: dict) -> dict:
    """Build a minimal spec with a response schema."""
    return {
        "paths": {
            resource_path: {
                method: {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": properties,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }


class TestIdentifierIndexFromResponseSchemas:
    """Test extraction of identifiers from response schemas."""

    def test_extracts_id_field(self):
        """GET /users returns {id: integer} -> 'id' in users identifiers."""
        spec = _spec_with_response("/users", "get", {
            "id": {"type": "integer"},
            "name": {"type": "string"},
        })
        skill_paths = {
            "svc/users/list": {
                "resource": "users", "operation": "list",
                "method": "GET", "endpoint": "/users",
            },
        }
        index = build_identifier_index(spec, skill_paths)
        assert "id" in index.get("users", set())

    def test_extracts_uuid_field(self):
        """GET /items returns {uuid: string, format: uuid} -> 'uuid' in identifiers."""
        spec = _spec_with_response("/items", "get", {
            "uuid": {"type": "string", "format": "uuid"},
            "title": {"type": "string"},
        })
        skill_paths = {
            "svc/items/list": {
                "resource": "items", "operation": "list",
                "method": "GET", "endpoint": "/items",
            },
        }
        index = build_identifier_index(spec, skill_paths)
        assert "uuid" in index.get("items", set())

    def test_extracts_id_suffixed_fields(self):
        """GET /series returns {series_id: integer} -> 'series_id' in identifiers."""
        spec = _spec_with_response("/series", "get", {
            "id": {"type": "integer"},
            "series_id": {"type": "integer"},
        })
        skill_paths = {
            "svc/series/list": {
                "resource": "series", "operation": "list",
                "method": "GET", "endpoint": "/series",
            },
        }
        index = build_identifier_index(spec, skill_paths)
        ids = index.get("series", set())
        assert "id" in ids
        assert "series_id" in ids

    def test_extracts_slug_and_name_with_spec_signals(self):
        """readOnly string fields are detected as server-generated identifiers."""
        spec = _spec_with_response("/resources", "get", {
            "slug": {"type": "string", "readOnly": True},
            "name": {"type": "string", "readOnly": True},
            "description": {"type": "string"},
        })
        skill_paths = {
            "svc/resources/list": {
                "resource": "resources", "operation": "list",
                "method": "GET", "endpoint": "/resources",
            },
        }
        index = build_identifier_index(spec, skill_paths)
        ids = index.get("resources", set())
        assert "slug" in ids
        assert "name" in ids
        # description is NOT an identifier (not readOnly, not integer, no format)
        assert "description" not in ids

    def test_missing_response_schema_empty_set(self):
        """Resource with only POST (no GET/LIST) -> empty identifiers."""
        spec = {"paths": {"/actions": {"post": {"responses": {"201": {}}}}}}
        skill_paths = {
            "svc/actions/create": {
                "resource": "actions", "operation": "create",
                "method": "POST", "endpoint": "/actions",
            },
        }
        index = build_identifier_index(spec, skill_paths)
        assert index.get("actions", set()) == set()


class TestIdentifierIndexFromPathParams:
    """Test extraction of identifiers from path parameters."""

    def test_extracts_adjacent_path_param(self):
        """Path /users/{user_id} -> user_id and user in users identifiers."""
        spec = _spec_with_response("/users/{user_id}", "get", {
            "id": {"type": "integer"},
        })
        skill_paths = {
            "svc/users/retrieve": {
                "resource": "users", "operation": "retrieve",
                "method": "GET", "endpoint": "/users/{user_id}",
            },
        }
        index = build_identifier_index(spec, skill_paths)
        ids = index.get("users", set())
        assert "user_id" in ids
        assert "user" in ids  # Normalized stripped form

    def test_nested_path_params_correct_association(self):
        """Nested path params go to their adjacent resource only."""
        spec = {"paths": {
            "/orgs/{org_id}/teams/{team_id}": {
                "get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "integer"}}}}}}}}
            },
        }}
        skill_paths = {
            "svc/teams/retrieve": {
                "resource": "teams", "operation": "retrieve",
                "method": "GET", "endpoint": "/orgs/{org_id}/teams/{team_id}",
            },
        }
        index = build_identifier_index(spec, skill_paths)
        team_ids = index.get("teams", set())
        assert "team_id" in team_ids
        # org_id should NOT be in teams' identifiers
        assert "org_id" not in team_ids


class TestIdentifierIndexEdgeCases:
    """Edge cases for identifier index."""

    def test_empty_spec_empty_index(self):
        """Empty spec and skill_paths -> empty index."""
        assert build_identifier_index({}, {}) == {}

    def test_swagger2_format(self):
        """Swagger 2.0 response schema format is handled."""
        spec = {
            "swagger": "2.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "integer"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        skill_paths = {
            "svc/users/list": {
                "resource": "users", "operation": "list",
                "method": "GET", "endpoint": "/users",
            },
        }
        index = build_identifier_index(spec, skill_paths)
        assert "id" in index.get("users", set())

    def test_multiple_operations_merged(self):
        """Identifiers from list and retrieve are merged."""
        spec = {
            "paths": {
                "/items": {
                    "get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "integer"}}}}}}}},
                },
                "/items/{item_id}": {
                    "get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "integer"}, "slug": {"type": "string", "readOnly": True}}}}}}}},
                },
            },
        }
        skill_paths = {
            "svc/items/list": {"resource": "items", "operation": "list", "method": "GET", "endpoint": "/items"},
            "svc/items/retrieve": {"resource": "items", "operation": "retrieve", "method": "GET", "endpoint": "/items/{item_id}"},
        }
        index = build_identifier_index(spec, skill_paths)
        ids = index.get("items", set())
        assert "id" in ids
        assert "slug" in ids
        assert "item_id" in ids  # From path param
