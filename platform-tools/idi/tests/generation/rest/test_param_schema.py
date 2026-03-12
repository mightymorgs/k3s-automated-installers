"""Tests for path parameter schema passthrough (section-06)."""
from __future__ import annotations

from idi.generation.dep_adapters.base import OperationInfo
from idi.generation.dep_adapters.path_deps import detect_path_deps


def _op(path: str, path_param_schemas: dict | None = None) -> OperationInfo:
    return OperationInfo(
        service="test-svc", resource="test", operation="get_test",
        path=path, method="GET", body_schema={}, response_schema={},
        path_param_schemas=path_param_schemas or {},
    )


class TestOperationInfoParamSchemas:
    """OperationInfo accepts and defaults path_param_schemas."""

    def test_accepts_path_param_schemas(self):
        op = _op("/users/{id}", path_param_schemas={"id": {"type": "string"}})
        assert op.path_param_schemas == {"id": {"type": "string"}}

    def test_defaults_to_empty_dict(self):
        op = OperationInfo(
            service="s", resource="r", operation="o",
            path="/x", method="GET", body_schema={}, response_schema={},
        )
        assert op.path_param_schemas == {}


class TestEnumParamSkipped:
    """Params with enum constraints are routing selectors, not FKs."""

    def test_enum_param_skipped(self):
        """Param with enum is not treated as FK."""
        deps = detect_path_deps(
            _op(
                "/secrets/{type}/config",
                path_param_schemas={"type": {"type": "string", "enum": ["aws-kms", "pkcs11"]}},
            ),
            known_resources={"secrets"},
        )
        # {type} should be skipped — it's a routing selector
        type_deps = [d for d in deps if d.field == "type"]
        assert len(type_deps) == 0

    def test_non_enum_param_processed(self):
        """Param without enum is processed normally."""
        deps = detect_path_deps(
            _op(
                "/users/{userId}",
                path_param_schemas={"userId": {"type": "string"}},
            ),
            known_resources={"users"},
        )
        assert len(deps) == 1
        assert deps[0].target_resource == "users"

    def test_uuid_format_param_processed(self):
        """Param with format: uuid is FK-like, should be processed."""
        deps = detect_path_deps(
            _op(
                "/users/{userId}",
                path_param_schemas={"userId": {"type": "string", "format": "uuid"}},
            ),
            known_resources={"users"},
        )
        assert len(deps) == 1
        assert deps[0].target_resource == "users"

    def test_missing_schema_default_behavior(self):
        """Param not in path_param_schemas → treated as no schema."""
        deps = detect_path_deps(
            _op("/users/{userId}", path_param_schemas={}),
            known_resources={"users"},
        )
        assert len(deps) == 1
        assert deps[0].target_resource == "users"

    def test_enum_param_among_normal_params(self):
        """Only the enum param is skipped; others are processed."""
        deps = detect_path_deps(
            _op(
                "/secrets/{type}/{name}",
                path_param_schemas={
                    "type": {"type": "string", "enum": ["kv", "pki"]},
                    "name": {"type": "string"},
                },
            ),
            known_resources={"secrets"},
        )
        type_deps = [d for d in deps if d.field == "type"]
        name_deps = [d for d in deps if d.field == "name"]
        assert len(type_deps) == 0
        assert len(name_deps) == 1


class TestParamSchemaExtraction:
    """Verify the cli.py extraction pattern for OAS3 and Swagger2 params."""

    @staticmethod
    def _extract(all_params: list[dict]) -> dict[str, dict]:
        """Replicate the cli.py extraction logic for testability."""
        schemas: dict[str, dict] = {}
        for p in all_params:
            if p.get("in") == "path" and "name" in p:
                schemas[p["name"]] = p.get("schema", p)
        return schemas

    def test_oas3_param_extracts_nested_schema(self):
        params = [{"in": "path", "name": "userId", "schema": {"type": "string", "format": "uuid"}}]
        schemas = self._extract(params)
        assert schemas["userId"] == {"type": "string", "format": "uuid"}

    def test_swagger2_param_falls_back_to_param_object(self):
        params = [{"in": "path", "name": "type", "type": "string", "enum": ["kv", "pki"]}]
        schemas = self._extract(params)
        assert schemas["type"]["enum"] == ["kv", "pki"]

    def test_operation_level_overrides_path_level(self):
        path_params = [{"in": "path", "name": "id", "schema": {"type": "integer"}}]
        op_params = [{"in": "path", "name": "id", "schema": {"type": "string", "format": "uuid"}}]
        schemas = self._extract(path_params + op_params)
        assert schemas["id"] == {"type": "string", "format": "uuid"}

    def test_query_params_ignored(self):
        params = [
            {"in": "path", "name": "id", "schema": {"type": "string"}},
            {"in": "query", "name": "limit", "schema": {"type": "integer"}},
        ]
        schemas = self._extract(params)
        assert "limit" not in schemas
        assert "id" in schemas
