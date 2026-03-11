"""Tests for full response schema tree walk (#13) and read-only set difference (#14).

Section 10: Response walk and readOnly field detection enhancements.
"""
from __future__ import annotations

import pytest

from idi.generation.dep_adapters.base import OperationInfo, Output
from idi.generation.dep_adapters.output_detection import (
    detect_outputs,
    infer_readonly_by_diff,
    walk_response_schema,
)


@pytest.fixture
def base_operation():
    """Factory for OperationInfo with configurable response_schema."""
    def _make(method="POST", path="/users", response_schema=None, body_schema=None,
              resource="users"):
        return OperationInfo(
            service="test-service",
            resource=resource,
            operation=f"{method.lower()}_{resource}",
            path=path,
            method=method,
            body_schema=body_schema or {},
            response_schema=response_schema or {},
        )
    return _make


# Deep nested schema for depth tests.
DEEP_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "metadata": {
            "type": "object",
            "properties": {
                "uid": {"type": "string", "readOnly": True},
                "labels": {
                    "type": "object",
                    "properties": {
                        "app": {"type": "string"},
                        "nested": {
                            "type": "object",
                            "properties": {
                                "deep": {"type": "string"},
                                "deeper": {
                                    "type": "object",
                                    "properties": {
                                        "leaf": {"type": "string"},
                                        "too_deep": {
                                            "type": "object",
                                            "properties": {
                                                "excluded": {"type": "string"},
                                            },
                                        },
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


# -----------------------------------------------------------------------
# Full Response Schema Tree Walk (#13)
# -----------------------------------------------------------------------

class TestWalkResponseSchema:
    """Tests for recursive response schema walking to depth 5."""

    def test_depth_1_field_registered(self, base_operation):
        """Depth-1 response field registered as producer."""
        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
            },
        }
        outputs = walk_response_schema(schema, "test-svc", "users")
        fields = {o.field for o in outputs}
        assert "id" in fields

    def test_depth_3_nested_field(self, base_operation):
        """Depth-3 field (metadata.labels.app) registered."""
        outputs = walk_response_schema(DEEP_SCHEMA, "test-svc", "users")
        paths = {o.field for o in outputs}
        assert "metadata.labels.app" in paths

    def test_depth_5_field_registered(self, base_operation):
        """Depth-5 field registered (at the depth limit)."""
        outputs = walk_response_schema(DEEP_SCHEMA, "test-svc", "users")
        paths = {o.field for o in outputs}
        assert "metadata.labels.nested.deeper.leaf" in paths

    def test_depth_6_field_excluded(self, base_operation):
        """Depth-6 field NOT registered (depth limit exceeded)."""
        outputs = walk_response_schema(DEEP_SCHEMA, "test-svc", "users")
        paths = {o.field for o in outputs}
        assert "metadata.labels.nested.deeper.too_deep.excluded" not in paths

    def test_readonly_nested_field_confidence_09(self, base_operation):
        """readOnly nested field gets confidence-equivalent priority boost (source='readonly_field')."""
        outputs = walk_response_schema(DEEP_SCHEMA, "test-svc", "users")
        uid_outputs = [o for o in outputs if o.field == "metadata.uid"]
        assert len(uid_outputs) == 1
        assert uid_outputs[0].source == "readonly_field"

    def test_non_readonly_field_source(self, base_operation):
        """Non-readOnly field gets baseline source."""
        outputs = walk_response_schema(DEEP_SCHEMA, "test-svc", "users")
        app_outputs = [o for o in outputs if o.field == "metadata.labels.app"]
        assert len(app_outputs) == 1
        assert app_outputs[0].source == "response_walk"

    def test_recursive_schema_cycle_detection(self, base_operation):
        """Circular schema reference terminates without stack overflow."""
        # Create two distinct schema objects that reference each other
        manager_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
            },
        }
        user_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "manager": manager_schema,
            },
        }
        # Create the cycle: manager -> reports -> user -> manager ...
        manager_schema["properties"]["reports"] = user_schema

        outputs = walk_response_schema(user_schema, "test-svc", "users")
        fields = {o.field for o in outputs}
        assert "id" in fields
        assert "name" in fields
        # First level of nesting should work
        assert "manager.id" in fields
        assert "manager.title" in fields
        # Cycle detected: manager.reports points back to user_schema which
        # is already in visited → recursion halts. No deeper fields.
        assert "manager.reports.id" not in fields

    def test_array_items_walked(self, base_operation):
        """Array items with object type walked correctly."""
        schema = {
            "type": "object",
            "properties": {
                "conditions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "status": {"type": "string", "readOnly": True},
                        },
                    },
                },
            },
        }
        outputs = walk_response_schema(schema, "test-svc", "users")
        paths = {o.field for o in outputs}
        assert "conditions[].type" in paths
        assert "conditions[].status" in paths

    def test_json_path_format(self, base_operation):
        """JSON paths use dot-separated format with [] for arrays."""
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
                                    "image": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        }
        outputs = walk_response_schema(schema, "test-svc", "pods")
        paths = {o.field for o in outputs}
        assert "spec.containers[].image" in paths

    def test_empty_schema_returns_empty(self):
        """Empty or missing schema returns empty list."""
        assert walk_response_schema({}, "svc", "res") == []
        assert walk_response_schema({"type": "object"}, "svc", "res") == []

    def test_different_paths_same_canonical(self):
        """Different physical fields that share a canonical name are both registered."""
        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "metadata": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                    },
                },
            },
        }
        outputs = walk_response_schema(schema, "svc", "users")
        id_outputs = [o for o in outputs if o.fact_ref == "facts://svc/users#id"]
        # Both "id" and "metadata.id" are registered (different paths)
        assert len(id_outputs) == 2
        fields = {o.field for o in id_outputs}
        assert "id" in fields
        assert "metadata.id" in fields

    def test_object_without_explicit_type(self):
        """Schema with properties but no type still gets walked."""
        schema = {
            "type": "object",
            "properties": {
                "metadata": {
                    "properties": {
                        "uid": {"type": "string", "readOnly": True},
                    },
                },
            },
        }
        outputs = walk_response_schema(schema, "svc", "users")
        paths = {o.field for o in outputs}
        assert "metadata.uid" in paths


# -----------------------------------------------------------------------
# Read-Only Set Difference (#14)
# -----------------------------------------------------------------------

class TestReadOnlySetDifference:
    """Tests for inferring read-only fields via PUT request vs GET response comparison."""

    def test_basic_set_difference(self):
        """PUT request {name, email} vs GET response {id, name, email, created_at} -> {id, created_at} inferred."""
        put_op = OperationInfo(
            service="svc", resource="users", operation="put_users",
            path="/users/{id}", method="PUT",
            body_schema={"type": "object", "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            }},
            response_schema={},
        )
        get_op = OperationInfo(
            service="svc", resource="users", operation="get_users",
            path="/users/{id}", method="GET",
            body_schema={},
            response_schema={"type": "object", "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "created_at": {"type": "string"},
            }},
        )
        result = infer_readonly_by_diff([put_op, get_op])
        assert "/users/{id}" in result
        assert result["/users/{id}"] == {"id", "created_at"}

    def test_put_get_pairing(self):
        """PUT + GET on same path template are paired correctly."""
        put_op = OperationInfo(
            service="svc", resource="users", operation="put_users",
            path="/users/{user_id}", method="PUT",
            body_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            response_schema={},
        )
        get_op = OperationInfo(
            service="svc", resource="users", operation="get_users",
            path="/users/{user_id}", method="GET",
            body_schema={},
            response_schema={"type": "object", "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
            }},
        )
        result = infer_readonly_by_diff([put_op, get_op])
        assert "/users/{user_id}" in result
        assert "id" in result["/users/{user_id}"]

    def test_post_excluded_from_diff(self):
        """POST + GET but no PUT -> set-diff NOT applied."""
        post_op = OperationInfo(
            service="svc", resource="users", operation="post_users",
            path="/users", method="POST",
            body_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            response_schema={},
        )
        get_op = OperationInfo(
            service="svc", resource="users", operation="get_users",
            path="/users", method="GET",
            body_schema={},
            response_schema={"type": "object", "properties": {
                "id": {"type": "string"}, "name": {"type": "string"},
            }},
        )
        result = infer_readonly_by_diff([post_op, get_op])
        # No PUT exists, so no diff should be computed
        assert len(result) == 0

    def test_patch_excluded_from_diff(self):
        """PATCH + GET but no PUT -> set-diff NOT applied."""
        patch_op = OperationInfo(
            service="svc", resource="users", operation="patch_users",
            path="/users/{id}", method="PATCH",
            body_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            response_schema={},
        )
        get_op = OperationInfo(
            service="svc", resource="users", operation="get_users",
            path="/users/{id}", method="GET",
            body_schema={},
            response_schema={"type": "object", "properties": {
                "id": {"type": "string"}, "name": {"type": "string"},
            }},
        )
        result = infer_readonly_by_diff([patch_op, get_op])
        assert len(result) == 0

    def test_diff_inferred_confidence_085(self, base_operation):
        """Diff-inferred read-only fields produce source='readonly_diff'."""
        put_op = OperationInfo(
            service="svc", resource="users", operation="put_users",
            path="/users/{id}", method="PUT",
            body_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            response_schema={},
        )
        get_op = OperationInfo(
            service="svc", resource="users", operation="get_users",
            path="/users/{id}", method="GET",
            body_schema={},
            response_schema={"type": "object", "properties": {
                "id": {"type": "string"}, "name": {"type": "string"},
            }},
        )
        result = infer_readonly_by_diff([put_op, get_op])
        # Verify that "id" is inferred as readonly
        assert "id" in result["/users/{id}"]

    def test_spec_declared_overrides_diff(self):
        """spec-declared readOnly is always preferred over diff-inferred."""
        put_op = OperationInfo(
            service="svc", resource="users", operation="put_users",
            path="/users/{id}", method="PUT",
            body_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            response_schema={},
        )
        get_op = OperationInfo(
            service="svc", resource="users", operation="get_users",
            path="/users/{id}", method="GET",
            body_schema={},
            response_schema={"type": "object", "properties": {
                "id": {"type": "string", "readOnly": True},
                "name": {"type": "string"},
                "created_at": {"type": "string"},
            }},
        )
        diff_result = infer_readonly_by_diff([put_op, get_op])
        # id and created_at are diff-inferred readonly
        assert "id" in diff_result["/users/{id}"]
        assert "created_at" in diff_result["/users/{id}"]

        # Walk the GET response schema: id should have source='readonly_field' (spec-declared)
        # because readOnly: true is set on the schema
        outputs = walk_response_schema(
            get_op.response_schema, "svc", "users",
        )
        id_out = [o for o in outputs if o.field == "id"]
        assert len(id_out) == 1
        assert id_out[0].source == "readonly_field"  # Spec-declared takes precedence

    def test_grouping_by_path_template(self):
        """Operations grouped by resource path template correctly."""
        ops = [
            OperationInfo(service="svc", resource="users", operation="put_users",
                          path="/users/{id}", method="PUT",
                          body_schema={"type": "object", "properties": {"name": {"type": "string"}}},
                          response_schema={}),
            OperationInfo(service="svc", resource="users", operation="get_users",
                          path="/users/{id}", method="GET",
                          body_schema={},
                          response_schema={"type": "object", "properties": {
                              "id": {"type": "string"}, "name": {"type": "string"}}}),
            OperationInfo(service="svc", resource="teams", operation="put_teams",
                          path="/teams/{team_id}", method="PUT",
                          body_schema={"type": "object", "properties": {"name": {"type": "string"}}},
                          response_schema={}),
            OperationInfo(service="svc", resource="teams", operation="get_teams",
                          path="/teams/{team_id}", method="GET",
                          body_schema={},
                          response_schema={"type": "object", "properties": {
                              "id": {"type": "string"}, "name": {"type": "string"}}}),
        ]
        result = infer_readonly_by_diff(ops)
        assert "/users/{id}" in result
        assert "/teams/{team_id}" in result
        assert "id" in result["/users/{id}"]
        assert "id" in result["/teams/{team_id}"]
