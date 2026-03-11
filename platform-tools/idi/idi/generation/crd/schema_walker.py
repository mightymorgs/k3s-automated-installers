"""Recursive CRD schema traversal.

Yields every field in a CRD spec (or status) schema as a WalkedField
dataclass. Handles nested objects to configurable depth and descends
into array item schemas. This is a pure traversal module — it knows
nothing about what constitutes a "reference".

C6: depth traversal (SecretStore tokenSecretRef at depth 4)
C7: array handling (PushSecret secretStoreRefs[], IngressRoute routes[])
"""
from __future__ import annotations

import json
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
    # Note: "selector" was removed from this set. The original reason was to
    # exclude K8s label selectors (matchLabels/matchExpressions), but those
    # patterns don't trigger ref detection anyway. Removing it unblocks
    # PushSecret.spec.selector.secret.name and similar valid ref paths.
})

# Top-level K8s envelope fields — skipped at root level only by walk_crd_schema.
# Moved from dep_adapters/crd_dep.py.
_K8S_ENVELOPE = frozenset({"apiVersion", "kind", "metadata", "status"})


def _flatten_composed(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten allOf/oneOf/anyOf compositions into a single schema.

    - allOf: merge all sub-schemas' properties and required lists.
    - oneOf/anyOf with exactly 1 item: unwrap the single sub-schema.
    - oneOf/anyOf with multiple items: skip (ambiguous).

    Returns the original schema if no composition is present, or a merged
    copy with composed properties folded in. Does NOT modify the input.
    """
    has_allof = isinstance(schema.get("allOf"), list)
    has_oneof = isinstance(schema.get("oneOf"), list)
    has_anyof = isinstance(schema.get("anyOf"), list)

    if not (has_allof or has_oneof or has_anyof):
        return schema

    # Start with a shallow copy so we don't mutate the input.
    merged: dict[str, Any] = {}
    merged_props: dict[str, Any] = dict(schema.get("properties", {}))
    merged_required: list[str] = list(schema.get("required", []))

    # allOf: merge all sub-schemas.
    if has_allof:
        for sub in schema["allOf"]:
            if isinstance(sub, dict):
                merged_props.update(sub.get("properties", {}))
                merged_required.extend(sub.get("required", []))

    # oneOf/anyOf: unwrap if exactly one item.
    for key in ("oneOf", "anyOf"):
        items = schema.get(key)
        if isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict):
            sub = items[0]
            merged_props.update(sub.get("properties", {}))
            merged_required.extend(sub.get("required", []))

    if not merged_props:
        return schema

    # Copy all non-composition keys from original.
    for k, v in schema.items():
        if k not in ("allOf", "oneOf", "anyOf", "properties", "required"):
            merged[k] = v

    merged["properties"] = merged_props
    if merged_required:
        merged["required"] = list(dict.fromkeys(merged_required))  # deduplicate, preserve order

    # Infer type if not set.
    if "type" not in merged and merged_props:
        merged["type"] = "object"

    return merged


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
    depth_confidence: float = 1.0           # Always 1.0 in Phase 0; populated in Phase 2
    sibling_names: frozenset[str] = frozenset()  # Parent object's property names


def _compute_deep_fingerprint(
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> str:
    """Compute a deep structural fingerprint from schema properties.

    Uses json.dumps with sort_keys to produce a canonical string that
    captures the full nested structure, not just top-level names/types.
    Returns "" for empty properties (signals: do not cache).
    """
    if not properties:
        return ""
    # Include required list in the key so different requiredness = different cache entry
    key_obj = {"p": properties}
    if required:
        key_obj["r"] = sorted(required)
    return json.dumps(key_obj, sort_keys=True)


# Type alias for the memoization cache.
# Key: (fingerprint_string, is_array_item) tuple
# Value: list of (relative_path, depth_offset, field_schema, is_array_item, required, sibling_names) tuples
_CacheEntry = list[tuple[str, int, dict, bool, bool, frozenset]]
_CacheKey = tuple[str, bool]


def walk_crd_schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
    prefix: str = "spec",
    max_depth: int = 12,
    full_confidence_depth: int = 8,
    depth_decay: float = 0.9,
) -> Iterator[WalkedField]:
    """Recursively yield every field in a CRD spec schema.

    Uses fingerprint-based memoization to avoid re-walking identical
    sub-schema shapes. Cache is per-call (not shared across invocations).

    Args:
        properties: The properties dict from the spec schema.
        required: Required field names at this level.
        prefix: Dot-path prefix (default: "spec").
        max_depth: Maximum traversal depth (default: 12).
        full_confidence_depth: Depth up to which depth_confidence stays 1.0 (default: 8).
        depth_decay: Confidence multiplier per level beyond full_confidence_depth (default: 0.9).

    Yields:
        WalkedField for each property at every level.
    """
    cache: dict[_CacheKey, _CacheEntry] = {}
    yield from _walk_recursive(
        properties=properties,
        required=required or [],
        prefix=prefix,
        max_depth=max_depth,
        current_depth=1,
        is_array_item=False,
        skip_envelope=True,
        skip_status_in_excluded=True,
        full_confidence_depth=full_confidence_depth,
        depth_decay=depth_decay,
        cache=cache,
    )


def walk_crd_status(
    status_properties: dict[str, Any],
    prefix: str = "status",
    max_depth: int = 3,
) -> Iterator[WalkedField]:
    """Walk status subresource fields for output_declaration detection.

    Uses a lower max_depth (3 vs 12) because operator status fields
    are typically shallow. Does NOT apply _K8S_ENVELOPE filtering.
    Does NOT skip "status" from EXCLUDED_FIELDS (since we ARE walking status).

    Args:
        status_properties: The properties dict from the status schema.
        prefix: Dot-path prefix (default: "status").
        max_depth: Maximum traversal depth (default: 3).

    Yields:
        WalkedField for each status property.
    """
    cache: dict[_CacheKey, _CacheEntry] = {}
    yield from _walk_recursive(
        properties=status_properties,
        required=[],
        prefix=prefix,
        max_depth=max_depth,
        current_depth=1,
        is_array_item=False,
        skip_envelope=False,
        skip_status_in_excluded=False,
        cache=cache,
    )


def _replay_cached(
    cached: _CacheEntry,
    prefix: str,
    base_depth: int,
    max_depth: int,
    full_confidence_depth: int,
    depth_decay: float,
) -> Iterator[WalkedField]:
    """Replay cached fields with adjusted paths and recomputed depth_confidence."""
    for rel_path, depth_offset, schema, cached_is_array, cached_required, cached_siblings in cached:
        actual_depth = base_depth + depth_offset
        if actual_depth > max_depth:
            continue
        actual_path = f"{prefix}.{rel_path}" if rel_path else prefix
        # Recompute depth_confidence from actual depth at replay site
        if actual_depth <= full_confidence_depth:
            dc = 1.0
        else:
            dc = depth_decay ** (actual_depth - full_confidence_depth)
        # Derive parent_path from actual_path
        dot_idx = actual_path.rfind(".")
        parent = actual_path[:dot_idx] if dot_idx > 0 else prefix
        yield WalkedField(
            path=actual_path,
            name=actual_path.rsplit(".", 1)[-1],
            schema=schema,
            depth=actual_depth,
            is_array_item=cached_is_array,
            required=cached_required,
            parent_path=parent,
            sibling_names=cached_siblings,
            depth_confidence=dc,
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
    full_confidence_depth: int = 8,
    depth_decay: float = 0.9,
    cache: dict[_CacheKey, _CacheEntry] | None = None,
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
        full_confidence_depth: Depth up to which depth_confidence stays 1.0.
        depth_decay: Confidence multiplier per level beyond full_confidence_depth.
        cache: Per-call fingerprint memoization cache.
    """
    if current_depth > max_depth:
        return

    is_root = (current_depth == 1)
    siblings = frozenset(properties.keys())

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
            # Exception: allow "kind" at depth > 1 (inside arrays/objects).
            # At root level (depth 1), "kind" is the K8s envelope field.
            # At deeper levels, it's often a discriminator enum (e.g.,
            # services[].kind with enum ["Service", "TraefikService"]).
            elif prop_name == "kind" and current_depth > 1:
                pass  # allow through
            else:
                continue

        field_path = f"{prefix}.{prop_name}"
        field_required = prop_name in required

        # Compute depth confidence decay.
        if current_depth <= full_confidence_depth:
            depth_confidence = 1.0
        else:
            depth_confidence = depth_decay ** (current_depth - full_confidence_depth)

        # Yield this field.
        yield WalkedField(
            path=field_path,
            name=prop_name,
            schema=prop_schema,
            depth=current_depth,
            is_array_item=is_array_item,
            required=field_required,
            parent_path=prefix,
            sibling_names=siblings,
            depth_confidence=depth_confidence,
        )

        # Flatten composed schemas (allOf/oneOf/anyOf) before recursion.
        effective_schema = _flatten_composed(prop_schema)

        # Recurse into nested objects.
        if effective_schema.get("type") == "object" and "properties" in effective_schema:
            child_props = effective_schema["properties"]
            child_required = effective_schema.get("required", [])
            yield from _walk_subtree_cached(
                cache=cache,
                child_props=child_props,
                child_required=child_required,
                prefix=field_path,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                is_array_item=is_array_item,
                skip_status_in_excluded=skip_status_in_excluded,
                full_confidence_depth=full_confidence_depth,
                depth_decay=depth_decay,
            )

        # Recurse into array items.
        if effective_schema.get("type") == "array":
            items = effective_schema.get("items")
            if isinstance(items, dict):
                items = _flatten_composed(items)
            if isinstance(items, dict) and "properties" in items:
                child_props = items["properties"]
                child_required = items.get("required", [])
                yield from _walk_subtree_cached(
                    cache=cache,
                    child_props=child_props,
                    child_required=child_required,
                    prefix=field_path,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                    is_array_item=True,
                    skip_status_in_excluded=skip_status_in_excluded,
                    full_confidence_depth=full_confidence_depth,
                    depth_decay=depth_decay,
                )


def _walk_subtree_cached(
    cache: dict[_CacheKey, _CacheEntry] | None,
    child_props: dict[str, Any],
    child_required: list[str],
    prefix: str,
    max_depth: int,
    current_depth: int,
    is_array_item: bool,
    skip_status_in_excluded: bool,
    full_confidence_depth: int,
    depth_decay: float,
) -> Iterator[WalkedField]:
    """Walk a subtree with fingerprint-based memoization.

    On first encounter of a fingerprint, walks normally and caches the results
    as relative entries. On subsequent encounters, replays from cache with
    adjusted paths and recomputed depth_confidence.
    """
    if cache is None:
        yield from _walk_recursive(
            properties=child_props,
            required=child_required,
            prefix=prefix,
            max_depth=max_depth,
            current_depth=current_depth,
            is_array_item=is_array_item,
            skip_envelope=False,
            skip_status_in_excluded=skip_status_in_excluded,
            full_confidence_depth=full_confidence_depth,
            depth_decay=depth_decay,
            cache=cache,
        )
        return

    fingerprint = _compute_deep_fingerprint(child_props, child_required)

    # Don't cache empty fingerprints (no benefit, could cause spurious hits).
    if not fingerprint:
        yield from _walk_recursive(
            properties=child_props,
            required=child_required,
            prefix=prefix,
            max_depth=max_depth,
            current_depth=current_depth,
            is_array_item=is_array_item,
            skip_envelope=False,
            skip_status_in_excluded=skip_status_in_excluded,
            full_confidence_depth=full_confidence_depth,
            depth_decay=depth_decay,
            cache=cache,
        )
        return

    # Cache key includes is_array_item so object vs array contexts don't collide.
    cache_key: _CacheKey = (fingerprint, is_array_item)

    if cache_key in cache:
        yield from _replay_cached(
            cached=cache[cache_key],
            prefix=prefix,
            base_depth=current_depth,
            max_depth=max_depth,
            full_confidence_depth=full_confidence_depth,
            depth_decay=depth_decay,
        )
        return

    # First encounter — walk normally, collect results, and cache.
    results: _CacheEntry = []
    for field in _walk_recursive(
        properties=child_props,
        required=child_required,
        prefix=prefix,
        max_depth=max_depth,
        current_depth=current_depth,
        is_array_item=is_array_item,
        skip_envelope=False,
        skip_status_in_excluded=skip_status_in_excluded,
        full_confidence_depth=full_confidence_depth,
        depth_decay=depth_decay,
        cache=cache,
    ):
        yield field
        # Store relative path (strip prefix) and depth offset for replay.
        if field.path.startswith(prefix + "."):
            rel_path = field.path[len(prefix) + 1:]
        else:
            rel_path = ""
        depth_offset = field.depth - current_depth
        results.append((
            rel_path,
            depth_offset,
            field.schema,
            field.is_array_item,
            field.required,
            field.sibling_names,
        ))
    cache[cache_key] = results
