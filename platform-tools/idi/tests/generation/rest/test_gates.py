"""Tests for the programmatic gate system in gates.py."""
from __future__ import annotations

from collections import defaultdict

from idi.generation.dep_adapters.base import Dependency, DetectionSource, OperationInfo
from idi.generation.dep_adapters.gates import (
    GateContext,
    GateResult,
    GateStats,
    _normalize_type,
    _resolve_field_schema,
    apply_gates,
    build_gate_context,
)


def _dep(field: str = "f", target: str = "t", source: str = "generic_odg:body",
         confidence: float = 0.5) -> Dependency:
    return Dependency(field=field, target_resource=target, confidence=confidence, source=source)


def _op(body_schema: dict | None = None,
        path_param_schemas: dict | None = None,
        query_params: list | None = None,
        method: str = "POST") -> OperationInfo:
    return OperationInfo(
        service="test-svc",
        resource="test-res",
        operation="create",
        path="/test",
        method=method,
        body_schema=body_schema or {},
        response_schema={},
        path_param_schemas=path_param_schemas or {},
        query_params=query_params or [],
    )


def _gate_ctx(spec: dict | None = None,
              generated_skill_paths: dict | None = None,
              known_resources: set | None = None,
              resource_operations: dict | None = None,
              resource_methods: dict | None = None,
              outputs_by_resource: dict | None = None,
              operation: OperationInfo | None = None) -> GateContext:
    return GateContext(
        operation=operation or _op(),
        spec=spec or {},
        generated_skill_paths=generated_skill_paths or {},
        known_resources=known_resources or set(),
        resource_operations=resource_operations or {},
        resource_methods=resource_methods or {},
        outputs_by_resource=outputs_by_resource or {},
    )


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------

class TestGateResult:
    def test_keep_true(self):
        r = GateResult(keep=True, gate="G1", reason="ok")
        assert r.keep is True
        assert r.gate == "G1"
        assert r.reason == "ok"

    def test_keep_false(self):
        r = GateResult(keep=False, gate="G4", reason="type=boolean")
        assert r.keep is False
        assert r.gate == "G4"


# ---------------------------------------------------------------------------
# GateContext
# ---------------------------------------------------------------------------

class TestGateContext:
    def test_construction(self):
        ctx = _gate_ctx(
            resource_operations={"roles": ["create", "list"]},
            resource_methods={"roles": {"POST", "GET"}},
            outputs_by_resource={"roles": {"facts://svc/roles#id": "id"}},
        )
        assert ctx.resource_operations["roles"] == ["create", "list"]
        assert "POST" in ctx.resource_methods["roles"]
        assert ctx.outputs_by_resource["roles"] == {"facts://svc/roles#id": "id"}

    def test_producer_cache_defaults_to_empty(self):
        ctx = _gate_ctx()
        assert ctx._producer_cache == {}


# ---------------------------------------------------------------------------
# GateStats
# ---------------------------------------------------------------------------

class TestGateStats:
    def test_defaults(self):
        s = GateStats()
        assert s.total_evaluated == 0
        assert s.schema_resolved == 0
        assert s.schema_missing == 0

    def test_kills_by_gate_is_defaultdict(self):
        s = GateStats()
        s.kills_by_gate["G1"] += 1
        assert s.kills_by_gate["G1"] == 1


# ---------------------------------------------------------------------------
# _normalize_type
# ---------------------------------------------------------------------------

class TestNormalizeType:
    def test_plain_string(self):
        assert _normalize_type("string") == "string"

    def test_list_with_null(self):
        assert _normalize_type(["string", "null"]) == "string"

    def test_list_null_first(self):
        assert _normalize_type(["null", "integer"]) == "integer"

    def test_none_returns_empty(self):
        assert _normalize_type(None) == ""

    def test_missing_returns_empty(self):
        assert _normalize_type("") == ""

    def test_integer(self):
        assert _normalize_type("integer") == "integer"

    def test_list_with_only_null(self):
        # Edge case: ["null"] -> ""
        assert _normalize_type(["null"]) == ""


# ---------------------------------------------------------------------------
# _resolve_field_schema
# ---------------------------------------------------------------------------

class TestResolveFieldSchema:
    def test_finds_body_field(self):
        op = _op(body_schema={"properties": {"user_id": {"type": "string", "format": "uuid"}}})
        dep = _dep(field="user_id")
        schema = _resolve_field_schema(dep, op, {})
        assert schema is not None
        assert schema["type"] == "string"
        assert schema["format"] == "uuid"

    def test_finds_path_param(self):
        op = _op(path_param_schemas={"project_id": {"type": "integer"}})
        dep = _dep(field="project_id")
        schema = _resolve_field_schema(dep, op, {})
        assert schema is not None
        assert schema["type"] == "integer"

    def test_finds_query_param(self):
        op = _op(query_params=[
            {"name": "user_id", "in": "query", "required": False,
             "schema": {"type": "string"}},
        ])
        dep = _dep(field="user_id")
        schema = _resolve_field_schema(dep, op, {})
        assert schema is not None
        assert schema["type"] == "string"

    def test_returns_none_when_not_found(self):
        op = _op()
        dep = _dep(field="nonexistent")
        assert _resolve_field_schema(dep, op, {}) is None

    def test_body_has_priority_over_query(self):
        op = _op(
            body_schema={"properties": {"field": {"type": "integer"}}},
            query_params=[{"name": "field", "in": "query", "schema": {"type": "string"}}],
        )
        dep = _dep(field="field")
        schema = _resolve_field_schema(dep, op, {})
        assert schema["type"] == "integer"  # body wins

    def test_path_param_with_nested_schema(self):
        op = _op(path_param_schemas={"id": {"schema": {"type": "string"}, "in": "path"}})
        dep = _dep(field="id")
        schema = _resolve_field_schema(dep, op, {})
        # Should handle the case where path_param_schemas has the schema nested
        assert schema is not None


# ---------------------------------------------------------------------------
# apply_gates
# ---------------------------------------------------------------------------

class TestApplyGates:
    def test_no_gates_returns_all_deps(self):
        deps = [_dep(field="a"), _dep(field="b")]
        op = _op()
        ctx = _gate_ctx(operation=op)
        result, stats = apply_gates(deps, op, {}, ctx)
        assert len(result) == 2
        assert stats.total_evaluated == 2

    def test_returns_gate_stats(self):
        deps = [_dep(field="x")]
        op = _op()
        ctx = _gate_ctx(operation=op)
        result, stats = apply_gates(deps, op, {}, ctx)
        assert isinstance(stats, GateStats)
        assert stats.total_evaluated == 1


# ---------------------------------------------------------------------------
# build_gate_context
# ---------------------------------------------------------------------------

class TestBuildGateContext:
    def test_resource_operations_from_skill_paths(self):
        paths = {
            "svc/res/create": {"operation": "create", "method": "POST"},
            "svc/res/list": {"operation": "list", "method": "GET"},
        }
        ctx = build_gate_context({}, paths, set())
        assert sorted(ctx.resource_operations["res"]) == ["create", "list"]

    def test_resource_methods_from_skill_paths(self):
        paths = {
            "svc/res/create": {"operation": "create", "method": "POST"},
            "svc/res/list": {"operation": "list", "method": "GET"},
            "svc/res/retrieve": {"operation": "retrieve", "method": "GET"},
        }
        ctx = build_gate_context({}, paths, set())
        assert ctx.resource_methods["res"] == {"POST", "GET"}

    def test_multiple_resources(self):
        paths = {
            "svc/users/create": {"operation": "create", "method": "POST"},
            "svc/roles/create": {"operation": "create", "method": "POST"},
            "svc/roles/list": {"operation": "list", "method": "GET"},
        }
        ctx = build_gate_context({}, paths, set())
        assert "users" in ctx.resource_operations
        assert "roles" in ctx.resource_operations
        assert sorted(ctx.resource_operations["roles"]) == ["create", "list"]

    def test_empty_skill_paths(self):
        ctx = build_gate_context({}, {}, set())
        assert ctx.resource_operations == {}
        assert ctx.resource_methods == {}
