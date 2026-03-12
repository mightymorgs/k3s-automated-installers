"""Programmatic gates for filtering false positive dependency edges.

Gates operate on spec-derived signals only — no hand-crafted field name
lists or curated verb sets.  Each gate receives a ``Dependency``, the
field's OpenAPI schema, the full spec, and a ``GateContext`` carrying
pre-built indexes.  Gates return ``GateResult(keep, gate, reason)`` so
that filtering decisions are traceable.

The ``apply_gates()`` orchestrator runs all registered gates against
each dependency candidate and returns only surviving edges plus
structured statistics.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from idi.generation.dep_adapters.base import Dependency, OperationInfo

logger = logging.getLogger(__name__)

# ── Gate result and context types ────────────────────────────────────────


@dataclass
class GateResult:
    """Outcome of a single gate evaluation."""

    keep: bool
    gate: str
    reason: str


@dataclass
class GateStats:
    """Aggregated statistics from one ``apply_gates()`` call."""

    total_evaluated: int = 0
    schema_resolved: int = 0
    schema_missing: int = 0
    kills_by_gate: dict[str, int] = field(
        default_factory=lambda: defaultdict(int),
    )
    passes_by_gate: dict[str, int] = field(
        default_factory=lambda: defaultdict(int),
    )
    no_data_by_gate: dict[str, int] = field(
        default_factory=lambda: defaultdict(int),
    )


@dataclass
class GateContext:
    """Shared context for gate evaluation.

    Pre-built indexes avoid forward-reference problems and disk I/O
    by computing resource metadata before the per-operation loop.
    """

    operation: OperationInfo | None
    spec: dict[str, Any]
    generated_skill_paths: dict[str, dict[str, Any]]
    known_resources: set[str]
    resource_operations: dict[str, list[str]]
    resource_methods: dict[str, set[str]]
    outputs_by_resource: dict[str, dict[str, str]]
    _producer_cache: dict[str, dict[str, Any]] = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────


def _normalize_type(type_value: Any) -> str:
    """Normalize an OpenAPI ``type`` value to a simple string.

    Handles OpenAPI 3.1 arrays like ``["string", "null"]`` by filtering
    out ``"null"`` and returning the remaining type.
    """
    if isinstance(type_value, list):
        non_null = [t for t in type_value if t != "null"]
        return non_null[0] if non_null else ""
    if isinstance(type_value, str):
        return type_value
    return ""


def _resolve_ref(spec: dict[str, Any], ref: str, depth: int = 0,
                 visited: set[str] | None = None) -> dict[str, Any]:
    """Follow a ``$ref`` string to its target schema."""
    if depth > 10 or not ref.startswith("#/"):
        return {}
    if visited is None:
        visited = set()
    if ref in visited:
        return {}
    visited = visited | {ref}

    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part, {})
        else:
            return {}
    if not isinstance(node, dict):
        return {}
    # Recursively resolve nested $ref
    if "$ref" in node:
        return _resolve_ref(spec, node["$ref"], depth + 1, visited)
    return node


def _resolve_schema(spec: dict[str, Any], schema: dict[str, Any],
                    depth: int = 0) -> dict[str, Any]:
    """Recursively resolve ``$ref`` and ``allOf`` in a schema."""
    if depth > 10 or not isinstance(schema, dict):
        return schema if isinstance(schema, dict) else {}
    if "$ref" in schema:
        resolved = _resolve_ref(spec, schema["$ref"], depth)
        return _resolve_schema(spec, resolved, depth + 1)
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for sub in schema["allOf"]:
            resolved = _resolve_schema(spec, sub, depth + 1)
            for k, v in resolved.items():
                if k == "properties" and "properties" in merged:
                    merged["properties"].update(v)
                elif k == "required" and "required" in merged:
                    merged["required"] = list(set(merged["required"]) | set(v))
                else:
                    merged[k] = v
        return merged
    return schema


def _resolve_field_schema(
    dep: Dependency,
    operation: OperationInfo,
    spec: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve the OpenAPI schema for a dependency's field.

    Searches body properties, path param schemas, and query params
    in order, returning the first match.
    """
    # Body properties (top-level only).
    body_props = operation.body_schema.get("properties", {})
    if dep.field in body_props:
        raw = body_props[dep.field]
        if isinstance(raw, dict):
            return _resolve_schema(spec, raw)

    # Path parameter schemas.
    if dep.field in operation.path_param_schemas:
        raw = operation.path_param_schemas[dep.field]
        if isinstance(raw, dict):
            # Handle both {"type": ...} and {"schema": {"type": ...}} forms
            if "schema" in raw and "type" not in raw:
                return _resolve_schema(spec, raw["schema"])
            return _resolve_schema(spec, raw)

    # Query parameters.
    for param in operation.query_params:
        if not isinstance(param, dict):
            continue
        if param.get("name") == dep.field:
            if "schema" in param:
                return _resolve_schema(spec, param["schema"])
            # Swagger 2.0: type directly on param
            if "type" in param:
                return param

    return None


# ── Gate registry ────────────────────────────────────────────────────────

# Each entry is (gate_id, gate_function).
# Gate functions are appended by subsequent sections.
_GATES: list[tuple[str, Any]] = []


# ── Orchestrator ─────────────────────────────────────────────────────────


def apply_gates(
    deps: list[Dependency],
    operation: OperationInfo,
    spec: dict[str, Any],
    ctx: GateContext,
) -> tuple[list[Dependency], GateStats]:
    """Run all registered gates against *deps*, returning survivors + stats."""
    stats = GateStats()
    surviving: list[Dependency] = []

    for dep in deps:
        stats.total_evaluated += 1

        # Resolve field schema for this dependency.
        field_schema = _resolve_field_schema(dep, operation, spec)
        if field_schema is not None:
            stats.schema_resolved += 1
        else:
            stats.schema_missing += 1

        # Run each gate.
        killed = False
        for gate_id, gate_fn in _GATES:
            result: GateResult = gate_fn(dep, field_schema, spec, ctx)
            if not result.keep:
                stats.kills_by_gate[gate_id] += 1
                killed = True
                logger.debug(
                    "Gate %s killed %s:%s->%s: %s",
                    gate_id, operation.resource, dep.field,
                    dep.target_resource, result.reason,
                )
                break  # First kill is sufficient
            else:
                stats.passes_by_gate[gate_id] += 1

        if not killed:
            surviving.append(dep)

    return surviving, stats


# ── Context factory ──────────────────────────────────────────────────────


def build_gate_context(
    spec: dict[str, Any],
    generated_skill_paths: dict[str, dict[str, Any]],
    known_resources: set[str],
) -> GateContext:
    """Build a ``GateContext`` from pipeline data.

    Pre-computes resource-level indexes from ``generated_skill_paths``
    so that gates can inspect any target resource in O(1).
    """
    resource_operations: dict[str, list[str]] = defaultdict(list)
    resource_methods: dict[str, set[str]] = defaultdict(set)
    outputs_by_resource: dict[str, dict[str, str]] = {}

    for skill_path, meta in generated_skill_paths.items():
        parts = skill_path.split("/")
        if len(parts) < 3:
            continue
        resource = parts[1]
        op_type = meta.get("operation", parts[2])
        method = meta.get("method", "").upper()

        resource_operations[resource].append(op_type)
        if method:
            resource_methods[resource].add(method)

    return GateContext(
        operation=None,  # set per-call in registry.detect()
        spec=spec,
        generated_skill_paths=generated_skill_paths,
        known_resources=known_resources,
        resource_operations=dict(resource_operations),
        resource_methods=dict(resource_methods),
        outputs_by_resource=outputs_by_resource,
    )
