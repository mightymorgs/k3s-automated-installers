"""Query parameter FK detection adapter.

Runs the same RESTler-style target inference on query parameters
that body_fk runs on body schema fields. Covers GET/list operations
whose filter params reference other resources (e.g., provider, user,
stage_uuid, source__slug).

Wired into generic_odg alongside body_fk and path_deps.
"""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency, OperationInfo
from idi.generation.dep_adapters.target_inference import infer_target

# Pagination / sorting / search params — never FK references.
_SKIP_QUERY_PARAMS: frozenset[str] = frozenset({
    "page", "page_size", "per_page", "limit", "offset", "cursor",
    "ordering", "order", "order_by", "sort", "sort_by", "sort_dir",
    "search", "q", "query", "format", "fields", "expand",
    "status", "state", "version", "level", "start", "end",
})

# Suffixes on query param names that indicate config/filter values, not FKs.
_NON_FK_SUFFIXES: tuple[str, ...] = (
    "_timeout", "_path", "_version", "_namespace", "_name",
    "_level", "_type", "_format", "_family", "_action", "_mode",
    "_status", "_state", "_flags", "_includes", "_excludes",
    "_policy",  # propagation_policy, deletion_policy — enums
    "_token",   # access_token, bearer_token — auth strings
    "_mount_path",
)

# Exact field names that are never FKs in query context.
_SKIP_QUERY_EXACT: frozenset[str] = frozenset({
    "domain", "tailnet", "namespace", "name",
})

# Well-known resource-type suffixes in field names.
# When a field ends with one of these, the suffix is the primary FK signal
# (e.g., enrollment_flow -> flows, web_certificate -> certificates).
_RESOURCE_TYPE_SUFFIXES: dict[str, str] = {
    "_flow": "flow",
    "_certificate": "certificate",
    "_group": "group",
    "_user": "user",
    "_source": "source",
    "_stage": "stage",
    "_policy": "policy",
    "_provider": "provider",
    "_role": "role",
    "_token": "token",
}


def detect_query_deps(
    operation: OperationInfo,
    known_resources: set[str],
) -> list[Dependency]:
    """Detect FK dependencies from query parameters."""
    if not operation.query_params:
        return []

    results: list[Dependency] = []
    for param in operation.query_params:
        name = param.get("name", "")
        name_lower = name.lower()
        if not name or name_lower in _SKIP_QUERY_PARAMS:
            continue
        if name_lower in _SKIP_QUERY_EXACT:
            continue
        if any(name_lower.endswith(sfx) for sfx in _NON_FK_SUFFIXES):
            continue

        # Build field_info dict matching what infer_target expects.
        field_info: dict = {"type": param.get("type", "string")}
        fmt = param.get("format")
        if fmt:
            field_info["format"] = fmt

        # Django-style double-underscore filters (e.g., provider__id,
        # source__slug) — strip the suffix for target inference but
        # keep the full name as the dependency field.
        inference_name = name
        if "__" in name:
            base, _, suffix = name.rpartition("__")
            if suffix in ("id", "pk", "uuid", "slug", "name"):
                inference_name = base

        # Try suffix-based inference first (e.g., enrollment_flow -> "flow").
        # This prevents the prefix word from matching a wrong resource.
        target = None
        confidence = 0.0
        name_lower = inference_name.lower()
        for suffix, resource_hint in _RESOURCE_TYPE_SUFFIXES.items():
            if name_lower.endswith(suffix):
                hint_target, hint_conf = infer_target(
                    resource_hint, field_info, known_resources,
                )
                if hint_target is not None and hint_conf > confidence:
                    target = hint_target
                    confidence = hint_conf

        # Fall back to standard inference on the full name.
        std_target, std_conf = infer_target(
            inference_name, field_info, known_resources,
        )
        if std_target is not None and std_conf > confidence:
            target = std_target
            confidence = std_conf

        if target is not None:
            results.append(Dependency(
                field=name,
                target_resource=target,
                target_operation="create",
                fact_ref=f"facts://{operation.service}/{target}#id",
                confidence=confidence,
                source="generic_odg:query",
                lineage_type="copy",
            ))

    return results
