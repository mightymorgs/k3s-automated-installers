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


# ── Gate constants ───────────────────────────────────────────────────────

NON_ID_FORMATS = frozenset({
    "date", "date-time", "email", "uri", "ipv4", "ipv6",
    "byte", "binary", "password",
})

ID_FIELD_NAMES = frozenset({
    "id", "uuid", "slug", "key", "name", "pk", "uid", "identifier",
})

# Types that are interchangeable for ID compatibility (G5).
_ID_COMPATIBLE_TYPES = frozenset({"string", "integer"})


# ── Gate implementations ────────────────────────────────────────────────


def gate_g1_non_id_format(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    ctx: GateContext,
) -> GateResult:
    """G1: Reject fields with non-identifier formats (safety net)."""
    if field_schema is None:
        return GateResult(keep=True, gate="G1", reason="no schema")
    fmt = field_schema.get("format", "")
    if isinstance(fmt, str) and fmt.lower() in NON_ID_FORMATS:
        return GateResult(keep=False, gate="G1", reason=f"non-id format: {fmt}")
    return GateResult(keep=True, gate="G1", reason="format ok")


def gate_g2_enum(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    ctx: GateContext,
) -> GateResult:
    """G2: Reject fields with enum constraints (safety net)."""
    if field_schema is None:
        return GateResult(keep=True, gate="G2", reason="no schema")
    if "enum" in field_schema:
        return GateResult(keep=False, gate="G2", reason="enum present")
    return GateResult(keep=True, gate="G2", reason="no enum")


def gate_g3_bounded_value(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    ctx: GateContext,
) -> GateResult:
    """G3: Reject integer/number fields with tight bounds or defaults."""
    if field_schema is None:
        return GateResult(keep=True, gate="G3", reason="no schema")

    field_type = _normalize_type(field_schema.get("type", ""))
    if field_type not in ("integer", "number"):
        return GateResult(keep=True, gate="G3", reason=f"type={field_type}")

    # Check for tight maximum (< 10000).
    has_tight_max = False
    maximum = field_schema.get("maximum")
    if maximum is not None:
        try:
            max_val = float(maximum)
            if max_val < 10000:
                has_tight_max = True
        except (ValueError, TypeError):
            pass  # Unparseable maximum — skip this check

    # Check for non-null default.
    has_default = (
        "default" in field_schema
        and field_schema["default"] is not None
    )

    bounds: list[str] = []
    if has_tight_max:
        bounds.append(f"max={maximum}")
    if has_default:
        bounds.append(f"default={field_schema['default']}")

    if bounds:
        return GateResult(keep=False, gate="G3", reason=f"bounded: {', '.join(bounds)}")
    return GateResult(keep=True, gate="G3", reason="numeric but unbounded")


def gate_g4_non_scalar(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    ctx: GateContext,
) -> GateResult:
    """G4: Reject boolean, object, and plain-string-array fields."""
    if field_schema is None:
        return GateResult(keep=True, gate="G4", reason="no schema")

    field_type = _normalize_type(field_schema.get("type", ""))
    if field_type == "boolean":
        return GateResult(keep=False, gate="G4", reason="type=boolean")
    if field_type == "object":
        return GateResult(keep=False, gate="G4", reason="type=object")
    if field_type == "array":
        items = field_schema.get("items", {})
        if not isinstance(items, dict):
            return GateResult(keep=False, gate="G4", reason="array with unknown items")
        items_type = _normalize_type(items.get("type", ""))
        items_format = items.get("format", "")
        # UUID-formatted string arrays pass (multi-FK).
        if items_type == "string" and items_format not in ("uuid",):
            return GateResult(keep=False, gate="G4", reason="array of plain strings")
        if items_type not in ("string", "integer"):
            return GateResult(keep=False, gate="G4", reason=f"array of {items_type or 'unknown'}")
    return GateResult(keep=True, gate="G4", reason=f"type={field_type}")


def gate_g6_query_filter(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    ctx: GateContext,
) -> GateResult:
    """G6: Reject optional query parameters on GET endpoints."""
    if ctx.operation is None:
        return GateResult(keep=True, gate="G6", reason="no operation context")
    if ctx.operation.method.upper() != "GET":
        return GateResult(keep=True, gate="G6", reason=f"method={ctx.operation.method}")

    # Check if field is a query param.
    for param in ctx.operation.query_params:
        if not isinstance(param, dict):
            continue
        if param.get("name") == dep.field:
            required = param.get("required", False)
            if not required:
                return GateResult(
                    keep=False, gate="G6",
                    reason="optional query filter on GET",
                )
            return GateResult(keep=True, gate="G6", reason="required query param")

    # Fallback: check dep.source for query-tagged edges.
    if dep.source == "generic_odg:query":
        return GateResult(
            keep=False, gate="G6",
            reason="query-sourced dep on GET",
        )
    return GateResult(keep=True, gate="G6", reason="not a query param")


def gate_g5_producer_consumer(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    ctx: GateContext,
) -> GateResult:
    """G5: Reject edges where consumer type is incompatible with all producer types."""
    if field_schema is None:
        return GateResult(keep=True, gate="G5", reason="no schema")

    consumer_type = _normalize_type(field_schema.get("type", ""))
    # Unwrap array types to items.type.
    if consumer_type == "array":
        items = field_schema.get("items", {})
        if isinstance(items, dict):
            consumer_type = _normalize_type(items.get("type", ""))

    if not consumer_type:
        return GateResult(keep=True, gate="G5", reason="consumer type unknown")

    produced_types = _get_producer_types(dep.target_resource, ctx)
    if not produced_types:
        return GateResult(keep=True, gate="G5", reason="target has no response identifiers")

    # Check type compatibility.
    if consumer_type in produced_types:
        return GateResult(
            keep=True, gate="G5",
            reason=f"type compatible: {consumer_type} in {produced_types}",
        )
    if consumer_type in _ID_COMPATIBLE_TYPES and produced_types & _ID_COMPATIBLE_TYPES:
        return GateResult(
            keep=True, gate="G5",
            reason=f"type coercible: {consumer_type} vs {produced_types}",
        )

    return GateResult(
        keep=False, gate="G5",
        reason=f"type mismatch: consumer={consumer_type}, producers={produced_types}",
    )


def gate_g7_crud_signature(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    ctx: GateContext,
) -> GateResult:
    """G7: Reject edges targeting POST-only endpoints with no outputs."""
    target_resource = dep.target_resource
    if target_resource not in ctx.resource_operations:
        return GateResult(keep=True, gate="G7", reason="target resource not found")

    operations = ctx.resource_operations[target_resource]
    if "list" in operations or "retrieve" in operations:
        return GateResult(
            keep=True, gate="G7",
            reason=f"has {'list' if 'list' in operations else 'retrieve'}",
        )

    methods = ctx.resource_methods.get(target_resource, set())
    if "GET" in methods:
        return GateResult(keep=True, gate="G7", reason="has GET endpoint")

    # POST-only: check for outputs.
    outputs = ctx.outputs_by_resource.get(target_resource, {})
    if outputs:
        return GateResult(
            keep=True, gate="G7",
            reason="POST-only but produces outputs",
        )

    return GateResult(
        keep=False, gate="G7",
        reason=f"POST-only target with no outputs: {target_resource}",
    )


# ── G5 helpers ───────────────────────────────────────────────────────────


def _extract_response_identifiers(
    spec: dict[str, Any],
    response_schema: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Extract identifier fields from a response schema."""
    identifiers: dict[str, dict[str, Any]] = {}
    props = response_schema.get("properties", {})
    for fname, fschema in props.items():
        if not isinstance(fschema, dict):
            continue
        resolved = _resolve_schema(spec, fschema)
        fname_lower = fname.lower()
        is_id_name = fname_lower in ID_FIELD_NAMES or fname_lower.endswith("_id")
        has_id_format = resolved.get("format") in ("uuid", "int64", "int32")
        if is_id_name or has_id_format:
            identifiers[fname] = resolved
    return identifiers


def _get_response_schema_for_operation(
    spec: dict[str, Any],
    endpoint: str,
    method: str,
) -> dict[str, Any] | None:
    """Extract the primary response schema from the spec for an endpoint."""
    paths = spec.get("paths", {})
    path_item = paths.get(endpoint)
    if path_item is None:
        # Try with/without trailing slash.
        alt = endpoint.rstrip("/") + "/" if not endpoint.endswith("/") else endpoint.rstrip("/")
        path_item = paths.get(alt)
    if path_item is None:
        return None

    operation = path_item.get(method.lower())
    if operation is None:
        return None

    responses = operation.get("responses", {})
    for code in ("200", "201", "202", 200, 201, 202):
        resp = responses.get(code)
        if not resp:
            continue
        # OpenAPI 3.x
        for _ct, ct_val in resp.get("content", {}).items():
            schema = ct_val.get("schema", {})
            if schema:
                resolved = _resolve_schema(spec, schema)
                # Handle array responses.
                if resolved.get("type") == "array" and "items" in resolved:
                    return _resolve_schema(spec, resolved["items"])
                return resolved
        # Swagger 2.0
        schema = resp.get("schema", {})
        if schema:
            resolved = _resolve_schema(spec, schema)
            if resolved.get("type") == "array" and "items" in resolved:
                return _resolve_schema(spec, resolved["items"])
            return resolved
    return None


def _get_producer_types(
    target_resource: str,
    ctx: GateContext,
) -> set[str]:
    """Get the set of identifier types produced by a target resource.

    Memoized in ``ctx._producer_cache``.
    """
    if target_resource in ctx._producer_cache:
        return ctx._producer_cache[target_resource]

    produced_types: set[str] = set()

    # Find target operations from generated_skill_paths.
    for skill_path, meta in ctx.generated_skill_paths.items():
        parts = skill_path.split("/")
        if len(parts) < 3:
            continue
        if parts[1] != target_resource:
            continue
        op_type = meta.get("operation", parts[2])
        if op_type not in ("create", "list", "retrieve"):
            continue

        # Find endpoint info.
        endpoint = None
        method = meta.get("method", "")
        # Look up the endpoint from the spec paths.
        for spec_path, path_item in ctx.spec.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue
            op = path_item.get(method.lower())
            if op is None:
                continue
            # Match by checking if this path corresponds to the target resource.
            # Simple heuristic: resource name appears in the path segments.
            path_segs = [s for s in spec_path.split("/") if s and not s.startswith("{")]
            resource_matches = any(
                target_resource.replace("-", "").replace("_", "")
                in seg.replace("-", "").replace("_", "")
                for seg in path_segs
            )
            if resource_matches:
                endpoint = spec_path
                break

        if endpoint:
            resp_schema = _get_response_schema_for_operation(
                ctx.spec, endpoint, method,
            )
            if resp_schema:
                ids = _extract_response_identifiers(ctx.spec, resp_schema)
                for id_schema in ids.values():
                    id_type = _normalize_type(id_schema.get("type", ""))
                    if id_type:
                        produced_types.add(id_type)

    ctx._producer_cache[target_resource] = produced_types
    return produced_types


# ── Gate registry ────────────────────────────────────────────────────────

# Each entry is (gate_id, gate_function).
_GATES: list[tuple[str, Any]] = [
    ("G1", gate_g1_non_id_format),
    ("G2", gate_g2_enum),
    ("G3", gate_g3_bounded_value),
    ("G4", gate_g4_non_scalar),
    ("G5", gate_g5_producer_consumer),
    ("G6", gate_g6_query_filter),
    ("G7", gate_g7_crud_signature),
]


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

    # Track create endpoints for output extraction.
    create_endpoints: dict[str, tuple[str, str]] = {}  # resource -> (endpoint_pattern, method)

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

        # Track create endpoints for G7's outputs check.
        if op_type == "create" and method:
            create_endpoints[resource] = (resource, method)

    # Build outputs_by_resource for G7: check create operations' response schemas.
    for resource, (_, method) in create_endpoints.items():
        # Search spec paths for this resource's create endpoint.
        for spec_path, path_item in spec.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue
            op = path_item.get(method.lower())
            if op is None:
                continue
            # Simple heuristic: resource name appears in path segments.
            path_segs = [s for s in spec_path.split("/") if s and not s.startswith("{")]
            resource_clean = resource.replace("-", "").replace("_", "")
            resource_matches = any(
                resource_clean in seg.replace("-", "").replace("_", "")
                for seg in path_segs
            )
            if not resource_matches:
                continue

            resp_schema = _get_response_schema_for_operation(spec, spec_path, method)
            if resp_schema:
                ids = _extract_response_identifiers(spec, resp_schema)
                if ids:
                    outputs_by_resource[resource] = {
                        f"facts://{parts[0]}/{resource}#{fname}": fname
                        for fname in ids
                    }
            break  # Use first matching path

    return GateContext(
        operation=None,  # set per-call in registry.detect()
        spec=spec,
        generated_skill_paths=generated_skill_paths,
        known_resources=known_resources,
        resource_operations=dict(resource_operations),
        resource_methods=dict(resource_methods),
        outputs_by_resource=outputs_by_resource,
    )
