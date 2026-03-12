"""Programmatic gates for filtering false positive dependency edges.

Each gate evaluates a single spec-derived signal and returns a GateResult
indicating whether the edge should be kept or killed. Gates run after
adapter merge/dedup/threshold filtering but before final output.

All signals are derived from the OpenAPI spec — no hand-crafted field
name lists or curated verb sets.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from idi.generation.dep_adapters.base import Dependency, OperationInfo

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Result of applying a gate to a dependency edge."""

    gate: str
    keep: bool
    reason: str


_NON_ID_FORMATS: frozenset[str] = frozenset({
    "date", "date-time", "email", "uri", "ipv4", "ipv6",
    "byte", "binary", "password",
})

_ID_FIELD_NAMES: frozenset[str] = frozenset({
    "id", "uuid", "slug", "key", "name", "pk", "uid", "identifier",
})


# ── Field schema resolution ─────────────────────────────────────────


def _resolve_field_schema(
    dep: Dependency,
    operation: OperationInfo,
    spec: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve the consumer field's schema from the operation or spec."""
    source = dep.source

    # Try source-specific lookup first
    if "body" in source:
        schema = _lookup_body_field(dep.field, operation.body_schema)
        if schema is not None:
            return schema
    elif "query" in source:
        schema = _lookup_query_param(dep.field, operation.query_params)
        if schema is not None:
            return schema
    elif "path" in source:
        schema = operation.path_param_schemas.get(dep.field)
        if schema is not None:
            return schema

    # Fallback: try all sources
    schema = _lookup_body_field(dep.field, operation.body_schema)
    if schema is not None:
        return schema
    schema = _lookup_query_param(dep.field, operation.query_params)
    if schema is not None:
        return schema
    schema = operation.path_param_schemas.get(dep.field)
    if schema is not None:
        return schema

    return None


def _lookup_body_field(
    field_name: str, body_schema: dict[str, Any],
) -> dict[str, Any] | None:
    """Look up a field in the body schema properties."""
    props = body_schema.get("properties", {})
    return props.get(field_name)


def _lookup_query_param(
    field_name: str, query_params: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Look up a field in the query parameters."""
    for param in query_params:
        if param.get("name") == field_name:
            # OAS3: schema is nested; Swagger 2.0: type on param directly
            return param.get("schema", param)
    return None


# ── Gate G1: Non-ID Format Block ─────────────────────────────────────


def gate_g1_non_id_format(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G1: Non-ID Format Block — kill fields with non-identifier formats."""
    if field_schema is None:
        return GateResult("G1", True, "no schema")

    fmt = field_schema.get("format", "")
    if fmt and fmt.lower() in _NON_ID_FORMATS:
        return GateResult("G1", False, f"format={fmt}")
    return GateResult("G1", True, "format ok")


# ── Gate G2: Enum Block ──────────────────────────────────────────────


def gate_g2_enum(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G2: Enum Block — kill fields with enum constraints."""
    if field_schema is None:
        return GateResult("G2", True, "no schema")

    if field_schema.get("enum"):
        return GateResult("G2", False, f"enum present")
    return GateResult("G2", True, "no enum")


# ── Gate G4: Non-Scalar Block ────────────────────────────────────────


def gate_g4_non_scalar(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G4: Non-Scalar Block — kill boolean, object, and plain-string arrays."""
    if field_schema is None:
        return GateResult("G4", True, "no schema")

    field_type = field_schema.get("type", "")

    if field_type == "boolean":
        return GateResult("G4", False, "type=boolean")
    if field_type == "object":
        return GateResult("G4", False, "type=object")
    if field_type == "array":
        items = field_schema.get("items", {})
        items_type = items.get("type", "")
        items_format = items.get("format", "")
        # Integer arrays are common FK ID lists — always pass
        if items_type == "integer":
            return GateResult("G4", True, "array of integers")
        # UUID string arrays are FK refs — pass
        if items_type == "string" and items_format == "uuid":
            return GateResult("G4", True, "array of uuid strings")
        # Plain string arrays (CIDR lists, header lists) — kill
        if items_type == "string":
            return GateResult("G4", False, "array of plain strings")
        # Arrays of unknown/complex types — kill
        return GateResult("G4", False, f"array of {items_type or 'unknown'}")

    return GateResult("G4", True, f"type={field_type}")


# ── Gate registry ────────────────────────────────────────────────────

# Gates added in implementation order. G3, G5, G6, G7 will be added
# in subsequent sections.
_GATES = [
    gate_g4_non_scalar,
    gate_g1_non_id_format,
    gate_g2_enum,
]


# ── Orchestrator ─────────────────────────────────────────────────────


def apply_gates(
    deps: list[Dependency],
    operation: OperationInfo,
    spec: dict[str, Any],
    skill_paths: dict[str, dict] | None = None,
) -> list[Dependency]:
    """Apply all gates to a list of dependencies, returning survivors."""
    if not deps:
        return []

    survivors: list[Dependency] = []
    for dep in deps:
        field_schema = _resolve_field_schema(dep, operation, spec)
        killed = False
        for gate_fn in _GATES:
            result = gate_fn(dep, field_schema, spec, operation, skill_paths)
            if not result.keep:
                logger.debug(
                    "Gate %s killed edge %s:%s->%s: %s",
                    result.gate, operation.resource, dep.field,
                    dep.target_resource, result.reason,
                )
                killed = True
                break
        if not killed:
            survivors.append(dep)

    return survivors
