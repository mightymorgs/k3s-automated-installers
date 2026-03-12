"""Tests for programmatic gates in dep_adapters/verify.py."""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency, OperationInfo
from idi.generation.dep_adapters.verify import (
    GateResult,
    _resolve_field_schema,
    apply_gates,
    gate_g1_non_id_format,
    gate_g2_enum,
    gate_g4_non_scalar,
)


def _dep(field: str = "f", target: str = "t", source: str = "generic_odg:body",
         confidence: float = 0.5) -> Dependency:
    return Dependency(field=field, target_resource=target, source=source,
                      confidence=confidence)


def _op(body_schema: dict | None = None,
        query_params: list | None = None,
        path_param_schemas: dict | None = None,
        method: str = "POST") -> OperationInfo:
    return OperationInfo(
        service="svc", resource="res", operation="create",
        path="/res", method=method,
        body_schema=body_schema or {},
        response_schema={},
        path_params=[],
        query_params=query_params or [],
        path_param_schemas=path_param_schemas or {},
        namespace_params=frozenset(),
    )


# ── Infrastructure ──────────────────────────────────────────────────

class TestApplyGates:
    def test_empty_deps_returns_empty(self):
        result = apply_gates([], _op(), {})
        assert result == []

    def test_passes_all_when_no_gate_fires(self):
        deps = [_dep(field="user_id")]
        op = _op(body_schema={"properties": {"user_id": {"type": "string"}}})
        result = apply_gates(deps, op, {})
        assert len(result) == 1

    def test_removes_deps_killed_by_gate(self):
        deps = [_dep(field="is_active")]
        op = _op(body_schema={"properties": {"is_active": {"type": "boolean"}}})
        result = apply_gates(deps, op, {})
        assert len(result) == 0


class TestGateResult:
    def test_stores_fields(self):
        gr = GateResult(gate="G1", keep=False, reason="format=email")
        assert gr.gate == "G1"
        assert gr.keep is False
        assert gr.reason == "format=email"


class TestResolveFieldSchema:
    def test_finds_body_field(self):
        dep = _dep(field="user_id", source="generic_odg:body")
        op = _op(body_schema={"properties": {"user_id": {"type": "integer"}}})
        schema = _resolve_field_schema(dep, op, {})
        assert schema is not None
        assert schema["type"] == "integer"

    def test_finds_query_param(self):
        dep = _dep(field="status", source="generic_odg:query")
        op = _op(query_params=[
            {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["active"]}}
        ])
        schema = _resolve_field_schema(dep, op, {})
        assert schema is not None
        assert schema["type"] == "string"

    def test_finds_path_param(self):
        dep = _dep(field="project_id", source="generic_odg:path")
        op = _op(path_param_schemas={"project_id": {"type": "integer", "format": "int64"}})
        schema = _resolve_field_schema(dep, op, {})
        assert schema is not None
        assert schema["type"] == "integer"

    def test_returns_none_for_unknown_field(self):
        dep = _dep(field="unknown_field", source="generic_odg:body")
        op = _op(body_schema={"properties": {"other": {"type": "string"}}})
        schema = _resolve_field_schema(dep, op, {})
        assert schema is None


# ── G4: Non-Scalar Block ────────────────────────────────────────────

class TestGateG4NonScalar:
    def test_kills_boolean(self):
        r = gate_g4_non_scalar(_dep(), {"type": "boolean"}, {}, _op(), None)
        assert r.keep is False

    def test_kills_object(self):
        r = gate_g4_non_scalar(_dep(), {"type": "object"}, {}, _op(), None)
        assert r.keep is False

    def test_kills_plain_string_array(self):
        schema = {"type": "array", "items": {"type": "string"}}
        r = gate_g4_non_scalar(_dep(), schema, {}, _op(), None)
        assert r.keep is False

    def test_passes_uuid_string_array(self):
        schema = {"type": "array", "items": {"type": "string", "format": "uuid"}}
        r = gate_g4_non_scalar(_dep(), schema, {}, _op(), None)
        assert r.keep is True

    def test_passes_integer_array(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        r = gate_g4_non_scalar(_dep(), schema, {}, _op(), None)
        assert r.keep is True

    def test_passes_string_type(self):
        r = gate_g4_non_scalar(_dep(), {"type": "string"}, {}, _op(), None)
        assert r.keep is True

    def test_passes_integer_type(self):
        r = gate_g4_non_scalar(_dep(), {"type": "integer"}, {}, _op(), None)
        assert r.keep is True

    def test_passes_no_schema(self):
        r = gate_g4_non_scalar(_dep(), None, {}, _op(), None)
        assert r.keep is True

    def test_kills_array_unknown_items_type(self):
        schema = {"type": "array", "items": {"type": "object"}}
        r = gate_g4_non_scalar(_dep(), schema, {}, _op(), None)
        assert r.keep is False


# ── G1: Non-ID Format Block ─────────────────────────────────────────

class TestGateG1NonIdFormat:
    def test_kills_datetime(self):
        r = gate_g1_non_id_format(_dep(), {"type": "string", "format": "date-time"}, {}, _op(), None)
        assert r.keep is False

    def test_kills_email(self):
        r = gate_g1_non_id_format(_dep(), {"type": "string", "format": "email"}, {}, _op(), None)
        assert r.keep is False

    def test_kills_uri(self):
        r = gate_g1_non_id_format(_dep(), {"type": "string", "format": "uri"}, {}, _op(), None)
        assert r.keep is False

    def test_kills_ipv4(self):
        r = gate_g1_non_id_format(_dep(), {"type": "string", "format": "ipv4"}, {}, _op(), None)
        assert r.keep is False

    def test_kills_binary(self):
        r = gate_g1_non_id_format(_dep(), {"type": "string", "format": "binary"}, {}, _op(), None)
        assert r.keep is False

    def test_kills_password(self):
        r = gate_g1_non_id_format(_dep(), {"type": "string", "format": "password"}, {}, _op(), None)
        assert r.keep is False

    def test_passes_uuid(self):
        r = gate_g1_non_id_format(_dep(), {"type": "string", "format": "uuid"}, {}, _op(), None)
        assert r.keep is True

    def test_passes_int64(self):
        r = gate_g1_non_id_format(_dep(), {"type": "integer", "format": "int64"}, {}, _op(), None)
        assert r.keep is True

    def test_passes_no_format(self):
        r = gate_g1_non_id_format(_dep(), {"type": "string"}, {}, _op(), None)
        assert r.keep is True

    def test_passes_no_schema(self):
        r = gate_g1_non_id_format(_dep(), None, {}, _op(), None)
        assert r.keep is True


# ── G2: Enum Block ──────────────────────────────────────────────────

class TestGateG2Enum:
    def test_kills_with_enum(self):
        r = gate_g2_enum(_dep(), {"type": "string", "enum": ["active", "disabled"]}, {}, _op(), None)
        assert r.keep is False

    def test_passes_without_enum(self):
        r = gate_g2_enum(_dep(), {"type": "string"}, {}, _op(), None)
        assert r.keep is True

    def test_passes_no_schema(self):
        r = gate_g2_enum(_dep(), None, {}, _op(), None)
        assert r.keep is True
