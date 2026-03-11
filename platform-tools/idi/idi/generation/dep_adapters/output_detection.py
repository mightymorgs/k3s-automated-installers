"""Response ID field output detection for write operations.

Extracted from ``field_extractor.build_heuristic_outputs()``.
Enhanced with RESTler-style CreateOrUpdate PUT detection and
method priority ranking.

Extended in section 10 with:
- Full response schema tree walk to depth 5
- Read-only field detection via PUT vs GET set difference
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from idi.generation.dep_adapters.base import OperationInfo, Output
from idi.generation.fact_model import canonicalize_field

try:
    from idi.generation.adapters.envelope_detector import detect_envelope
except ImportError:
    detect_envelope = None

_ID_FIELD_PRECEDENCE: list[str] = [
    "id", "pk", "uuid", "guid", "uid", "_id",
    "key", "token", "slug", "name",
    "request_id",
]

_METHOD_PRIORITY: dict[str, int] = {
    "POST": 4,
    "PUT": 3,
    "PATCH": 2,
    "GET": 1,
}

_LEAF_TYPES: frozenset[str] = frozenset({"string", "integer", "number", "boolean"})

_WALK_MAX_DEPTH = 5


# ---------------------------------------------------------------------------
# Full response schema tree walk (#13)
# ---------------------------------------------------------------------------

def walk_response_schema(
    schema: dict[str, Any],
    service: str,
    resource: str,
    *,
    max_depth: int = _WALK_MAX_DEPTH,
    resolve_ref: Callable[[str], dict[str, Any]] | None = None,
) -> list[Output]:
    """Walk response schema tree to depth ``max_depth``, registering leaf fields as producers.

    Leaf fields (string, integer, number, boolean) are registered with their
    full JSON-path (e.g. "metadata.uid"). readOnly fields get source='readonly_field',
    non-readOnly fields get source='response_walk'.

    Cycle detection: maintains a visited set of schema object ids.
    Array items are walked by appending "[]" to the path component.
    """
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties")
    if not props:
        return []

    # Envelope unwrapping if detector is available.
    if detect_envelope is not None:
        envelope = detect_envelope(schema)
        if envelope is not None and envelope.confidence >= 0.8:
            # Navigate to the unwrapped schema.
            unwrapped = _navigate_path(schema, envelope.unwrap_path)
            if unwrapped and isinstance(unwrapped, dict) and "properties" in unwrapped:
                schema = unwrapped

    results: list[Output] = []
    seen: set[str] = set()
    _walk_recursive(
        schema=schema,
        service=service,
        resource=resource,
        path_prefix="",
        depth=0,
        max_depth=max_depth,
        visited=set(),
        results=results,
        seen=seen,
    )
    return results


def _walk_recursive(
    schema: dict[str, Any],
    service: str,
    resource: str,
    path_prefix: str,
    depth: int,
    max_depth: int,
    visited: set[int],
    results: list[Output],
    seen: set[str],
) -> None:
    """Internal recursive helper for response schema walking."""
    if depth >= max_depth or not isinstance(schema, dict):
        return

    # Cycle detection via object identity.
    schema_id = id(schema)
    if schema_id in visited:
        return
    visited = visited | {schema_id}

    for field_name, field_schema in schema.get("properties", {}).items():
        if not isinstance(field_schema, dict):
            continue

        field_path = f"{path_prefix}.{field_name}" if path_prefix else field_name
        field_type = field_schema.get("type", "")

        # Leaf field — register as output.
        if field_type in _LEAF_TYPES:
            is_readonly = field_schema.get("readOnly", False)
            source = "readonly_field" if is_readonly else "response_walk"
            canonical = canonicalize_field(field_name)
            fact_ref = f"facts://{service}/{resource}#{canonical}"

            # Dedup by field path: different physical fields may share a
            # canonical name (e.g., id and metadata.uid both → #id).
            if field_path not in seen:
                results.append(Output(
                    field=field_path,
                    fact_ref=fact_ref,
                    source=source,
                    priority=1,
                ))
                seen.add(field_path)

        # Nested object — recurse. Also handle schemas with properties but no type.
        if (field_type == "object" or (not field_type and "properties" in field_schema)) and "properties" in field_schema:
            _walk_recursive(
                field_schema, service, resource, field_path,
                depth + 1, max_depth, visited, results, seen,
            )

        # Array items — recurse into item schema.
        if field_type == "array":
            items = field_schema.get("items")
            if isinstance(items, dict) and items.get("type") == "object" and "properties" in items:
                _walk_recursive(
                    items, service, resource, f"{field_path}[]",
                    depth + 1, max_depth, visited, results, seen,
                )


def _navigate_path(schema: dict[str, Any], dot_path: str) -> dict[str, Any] | None:
    """Navigate a dot-separated path into a schema's properties."""
    current = schema
    for segment in dot_path.split("."):
        props = current.get("properties", {})
        if segment not in props:
            return None
        current = props[segment]
        if not isinstance(current, dict):
            return None
    return current


# ---------------------------------------------------------------------------
# Read-only set difference (#14)
# ---------------------------------------------------------------------------

def infer_readonly_by_diff(
    operations: list[OperationInfo],
) -> dict[str, set[str]]:
    """Infer read-only fields by comparing PUT request vs GET response schemas.

    Groups operations by resource path template. For each group that has both
    a PUT and a GET, computes GET_response_fields - PUT_request_fields.
    Fields in the difference set are inferred as server-generated (read-only).

    Only PUT vs GET is used. POST and PATCH are explicitly excluded.

    Returns a dict mapping resource path template to set of inferred read-only
    field names.
    """
    groups: dict[str, dict[str, OperationInfo]] = defaultdict(dict)
    for op in operations:
        if op.method in ("PUT", "GET"):
            groups[op.path][op.method] = op

    result: dict[str, set[str]] = {}
    for path_template, method_ops in groups.items():
        put_op = method_ops.get("PUT")
        get_op = method_ops.get("GET")
        if put_op is None or get_op is None:
            continue

        put_fields = set(put_op.body_schema.get("properties", {}).keys())
        get_fields = set(get_op.response_schema.get("properties", {}).keys())

        inferred = get_fields - put_fields
        if inferred:
            result[path_template] = inferred

    return result


# ---------------------------------------------------------------------------
# Main output detection
# ---------------------------------------------------------------------------

def detect_outputs(operation: OperationInfo) -> list[Output]:
    """Detect output facts from response schema for write operations.

    POST always produces outputs. PUT produces outputs only if it's a
    create-or-update (no resource ID in path). PATCH on a specific
    resource (ID in path) is treated as an update and produces nothing.
    """
    priority = _METHOD_PRIORITY.get(operation.method, 0)
    if priority == 0:
        return []

    # PUT/PATCH with resource-specific path param = update, not create.
    # GET always reads (produces) data regardless of path structure.
    if operation.method in ("PUT", "PATCH") and _has_resource_id_in_path(operation):
        return []

    props = operation.response_schema.get("properties", {})
    if not props:
        return []

    results: list[Output] = []
    seen: set[str] = set()

    # Classify readOnly/writeOnly fields from response schema.
    readonly_fields, writeonly_fields = classify_readonly_writeonly(props)
    writeonly_set = set(writeonly_fields)

    for field_name in _ID_FIELD_PRECEDENCE:
        if field_name not in props:
            continue
        if field_name in writeonly_set:
            continue
        canonical = canonicalize_field(field_name)
        fact_ref = f"facts://{operation.service}/{operation.resource}#{canonical}"
        if fact_ref not in seen:
            results.append(Output(
                field=field_name,
                fact_ref=fact_ref,
                source="readonly_field" if field_name in readonly_fields else "generic_odg",
                priority=priority,
            ))
            seen.add(fact_ref)

    # Also register readOnly fields not in _ID_FIELD_PRECEDENCE as outputs.
    for field_name in readonly_fields:
        if field_name in writeonly_set:
            continue
        canonical = canonicalize_field(field_name)
        fact_ref = f"facts://{operation.service}/{operation.resource}#{canonical}"
        if fact_ref not in seen:
            results.append(Output(
                field=field_name,
                fact_ref=fact_ref,
                source="readonly_field",
                priority=priority,
            ))
            seen.add(fact_ref)

    return results


def classify_readonly_writeonly(
    props: dict,
) -> tuple[list[str], list[str]]:
    """Classify fields by readOnly/writeOnly attributes.

    Returns (readonly_fields, writeonly_fields) where each is a list
    of field names.
    """
    readonly: list[str] = []
    writeonly: list[str] = []
    for name, schema in props.items():
        if not isinstance(schema, dict):
            continue
        if schema.get("readOnly"):
            readonly.append(name)
        if schema.get("writeOnly"):
            writeonly.append(name)
    return readonly, writeonly


def _has_resource_id_in_path(operation: OperationInfo) -> bool:
    """Check if the path ends with a parameter for this resource's own ID.

    E.g., /api/things/{thing_id} -> True (update)
          /api/things -> False (create)
          /v1/secret/data/{path} -> False ('path' is not an ID param)
    """
    segments = operation.path.rstrip("/").split("/")
    if not segments or not segments[-1].startswith("{"):
        return False

    param = segments[-1].strip("{}")
    param_lower = param.lower()

    # Check if param looks like this resource's ID.
    resource_stem = operation.resource.split("-")[-1].rstrip("s")
    id_patterns = [
        f"{resource_stem}_id", f"{resource_stem}_pk",
        f"{resource_stem}_uuid", "id", "pk",
    ]
    return param_lower in id_patterns
