"""Recursive CRD schema traversal.

Yields every field in a CRD spec (or status) schema as a WalkedField
dataclass. Handles nested objects to configurable depth and descends
into array item schemas. This is a pure traversal module — it knows
nothing about what constitutes a "reference".

C6: depth traversal (SecretStore tokenSecretRef at depth 4)
C7: array handling (PushSecret secretStoreRefs[], IngressRoute routes[])
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


# Fields to exclude from traversal at every level.
# Moved from adapters/kubernetes_crd.py.
EXCLUDED_FIELDS = frozenset({
    "status",
    "namespace",
    "apiVersion",
    "kind",
    "resourceVersion",
    "selfLink",
    "creationTimestamp",
    "deletionTimestamp",
    "deletionGracePeriodSeconds",
    "generation",
    "finalizers",
    "ownerReferences",
    "managedFields",
    "annotations",
    "labels",
    "selector",
})

# Top-level K8s envelope fields — skipped at root level only by walk_crd_schema.
# Moved from dep_adapters/crd_dep.py.
_K8S_ENVELOPE = frozenset({"apiVersion", "kind", "metadata", "status"})


@dataclass(frozen=True)
class WalkedField:
    """A single field yielded by the schema walker."""

    path: str           # "spec.provider.vault.auth.tokenSecretRef"
    name: str           # "tokenSecretRef"
    schema: dict        # the field's JSON schema dict
    depth: int          # 4
    is_array_item: bool  # True if inside an array's items schema
    required: bool      # True if field name is in parent's 'required' list
    parent_path: str    # "spec.provider.vault.auth"


def walk_crd_schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
    prefix: str = "spec",
    max_depth: int = 5,
) -> Iterator[WalkedField]:
    """Recursively yield every field in a CRD spec schema.

    Args:
        properties: The properties dict from the spec schema.
        required: Required field names at this level.
        prefix: Dot-path prefix (default: "spec").
        max_depth: Maximum traversal depth (default: 5).

    Yields:
        WalkedField for each property at every level.
    """
    yield from _walk_recursive(
        properties=properties,
        required=required or [],
        prefix=prefix,
        max_depth=max_depth,
        current_depth=1,
        is_array_item=False,
        skip_envelope=True,
        skip_status_in_excluded=True,
    )


def walk_crd_status(
    status_properties: dict[str, Any],
    prefix: str = "status",
    max_depth: int = 3,
) -> Iterator[WalkedField]:
    """Walk status subresource fields for output_declaration detection.

    Uses a lower max_depth (3 vs 5) because operator status fields
    are typically shallow. Does NOT apply _K8S_ENVELOPE filtering.
    Does NOT skip "status" from EXCLUDED_FIELDS (since we ARE walking status).

    Args:
        status_properties: The properties dict from the status schema.
        prefix: Dot-path prefix (default: "status").
        max_depth: Maximum traversal depth (default: 3).

    Yields:
        WalkedField for each status property.
    """
    yield from _walk_recursive(
        properties=status_properties,
        required=[],
        prefix=prefix,
        max_depth=max_depth,
        current_depth=1,
        is_array_item=False,
        skip_envelope=False,
        skip_status_in_excluded=False,
    )


def _walk_recursive(
    properties: dict[str, Any],
    required: list[str],
    prefix: str,
    max_depth: int,
    current_depth: int,
    is_array_item: bool,
    skip_envelope: bool,
    skip_status_in_excluded: bool,
) -> Iterator[WalkedField]:
    """Internal recursive walker.

    Args:
        properties: Properties dict to walk.
        required: Required field names at this level.
        prefix: Current path prefix.
        max_depth: Maximum depth limit.
        current_depth: Current recursion depth.
        is_array_item: Whether we are inside an array's items schema.
        skip_envelope: Whether to skip _K8S_ENVELOPE at root level.
        skip_status_in_excluded: Whether to skip "status" from EXCLUDED_FIELDS.
    """
    if current_depth > max_depth:
        return

    is_root = (current_depth == 1)

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue

        # Skip envelope fields at root level only.
        if skip_envelope and is_root and prop_name in _K8S_ENVELOPE:
            continue

        # Skip excluded fields at every level.
        if prop_name in EXCLUDED_FIELDS:
            # Exception: don't skip "status" when walking status subresource
            if prop_name == "status" and not skip_status_in_excluded:
                pass  # allow through
            else:
                continue

        field_path = f"{prefix}.{prop_name}"
        field_required = prop_name in required

        # Yield this field.
        yield WalkedField(
            path=field_path,
            name=prop_name,
            schema=prop_schema,
            depth=current_depth,
            is_array_item=is_array_item,
            required=field_required,
            parent_path=prefix,
        )

        # Recurse into nested objects.
        if prop_schema.get("type") == "object" and "properties" in prop_schema:
            yield from _walk_recursive(
                properties=prop_schema["properties"],
                required=prop_schema.get("required", []),
                prefix=field_path,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                is_array_item=is_array_item,
                skip_envelope=False,
                skip_status_in_excluded=skip_status_in_excluded,
            )

        # Recurse into array items.
        if prop_schema.get("type") == "array":
            items = prop_schema.get("items")
            if isinstance(items, dict) and "properties" in items:
                yield from _walk_recursive(
                    properties=items["properties"],
                    required=items.get("required", []),
                    prefix=field_path,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                    is_array_item=True,
                    skip_envelope=False,
                    skip_status_in_excluded=skip_status_in_excluded,
                )
