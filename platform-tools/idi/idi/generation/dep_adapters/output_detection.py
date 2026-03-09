"""Response ID field output detection for write operations.

Extracted from ``field_extractor.build_heuristic_outputs()``.
Enhanced with RESTler-style CreateOrUpdate PUT detection and
method priority ranking.
"""
from __future__ import annotations

from idi.generation.dep_adapters.base import OperationInfo, Output
from idi.generation.fact_model import canonicalize_field

_ID_FIELD_PRECEDENCE: list[str] = [
    "id", "pk", "uuid", "guid", "uid", "_id",
    "key", "token", "slug", "name",
    "request_id",
]

_METHOD_PRIORITY: dict[str, int] = {
    "POST": 3,
    "PUT": 2,
    "PATCH": 1,
}


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
    if operation.method in ("PUT", "PATCH") and _has_resource_id_in_path(operation):
        return []

    props = operation.response_schema.get("properties", {})
    if not props:
        return []

    results: list[Output] = []
    seen: set[str] = set()

    for field_name in _ID_FIELD_PRECEDENCE:
        if field_name not in props:
            continue
        canonical = canonicalize_field(field_name)
        fact_ref = f"facts://{operation.service}/{operation.resource}#{canonical}"
        if fact_ref not in seen:
            results.append(Output(
                field=field_name,
                fact_ref=fact_ref,
                source="generic_odg",
                priority=priority,
            ))
            seen.add(fact_ref)

    return results


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
