Now I have all the context I need. Let me generate the section content.

# Section 11: Fingerprint Memoization

## Overview

This section adds fingerprint-based memoization to the schema walker so that repeated sub-schema shapes (common in recursive CRDs like ArgoCD ApplicationSet generators) are walked once and replayed from cache on subsequent encounters. This prevents exponential traversal cost when the same structural shape appears at multiple positions or depths in a CRD schema.

**Dependency:** Section 10 (Depth Decay) must be implemented first. Section 10 changes `walk_crd_schema` and `_walk_recursive` to accept `full_confidence_depth` and `depth_decay` parameters and to populate `depth_confidence` on `WalkedField`. This section builds on that modified walker.

**File modified:** `platform-tools/idi/idi/generation/crd/schema_walker.py`
**Test file modified:** `platform-tools/idi/tests/generation/crd/test_schema_walker.py`

**Critical constraint:** Precision > Recall. Memoization must produce identical field structures to a non-memoized walk. The only difference is performance: cached replay vs fresh recursion. `depth_confidence` must be recomputed from the actual depth at the replay site, not carried over from the cache.

## Background

### The Problem

CRD schemas can contain recursive or repeated sub-schema shapes. For example, ArgoCD's ApplicationSet has `generators` that contain nested `generators` (matrix/merge patterns), each with the same sub-schema shape. Without memoization, the walker re-traverses the same structural shape at every occurrence, leading to O(n^k) traversal for k nesting levels of n-property schemas.

With Section 10's `max_depth` raised from 8 to 12, this becomes more expensive: 4 additional depth levels of repeated shapes compound the cost. Memoization bounds the cost to O(n * k) by caching the first traversal and replaying it with adjusted paths and recomputed depth confidence.

### Schema Fingerprinting

The `compute_schema_fingerprint` function already exists in `ref_detector.py` (line 179). It takes a `properties` dict and optional `required` list and produces a canonical string like `"key:string?,name:string,namespace:string?"`. This string uniquely identifies the structural shape of a schema node (property names, types, requiredness) without caring about position or depth.

The plan calls for either extracting this function to a shared utility or duplicating the ~20 LOC. The simplest approach is to import it from `ref_detector` or to duplicate it in `schema_walker.py` to avoid a circular import (since `ref_detector` imports from `schema_walker`). Duplication is the safer choice given that `schema_walker` is a leaf module that should not import from `ref_detector`.

## Tests

Write these tests BEFORE implementing. Add to `tests/generation/crd/test_schema_walker.py`.

**File:** `platform-tools/idi/tests/generation/crd/test_schema_walker.py`

```python
class TestMemoization:
    """Tests for fingerprint-based schema memoization in the walker."""

    def test_same_shape_different_depths_yields_same_fields(self):
        """Same schema shape at depth 3 and depth 10 yields identical field
        structure (names and relative paths), but different depth_confidence."""
        # Build a schema where the same sub-shape {name: string, key: string}
        # appears at two different depths.
        # Depth 3: spec.alpha.beta.{name, key}
        # Depth 6: spec.alpha.beta.gamma.delta.epsilon.{name, key}
        # After walk, both sites should yield name and key fields.
        # depth_confidence should differ (depth 3 = 1.0, depth 10 with
        # full_confidence_depth=8 should be < 1.0).
        leaf_shape = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "key": {"type": "string"},
            },
        }
        # Build nested chain to depth 3
        shallow = {
            "alpha": {
                "type": "object",
                "properties": {
                    "beta": leaf_shape,
                },
            },
        }
        # Build nested chain to depth 10
        deep = leaf_shape
        for level_name in reversed(
            ["a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9"]
        ):
            deep = {
                "type": "object",
                "properties": {level_name: deep},
            }
        # Combine both paths under spec
        props = {
            "shallow": {
                "type": "object",
                "properties": {"beta": leaf_shape},
            },
            "deep_root": deep,
        }
        fields = list(walk_crd_schema(
            props, max_depth=12,
            full_confidence_depth=8, depth_decay=0.9,
        ))
        # Find shallow name field vs deep name field
        shallow_name = [
            f for f in fields
            if f.name == "name" and "shallow" in f.path
        ]
        deep_name = [
            f for f in fields
            if f.name == "name" and "deep_root" in f.path
        ]
        assert len(shallow_name) >= 1
        assert len(deep_name) >= 1
        # Both should exist but confidence should differ
        assert shallow_name[0].depth_confidence == 1.0
        assert deep_name[0].depth_confidence < 1.0

    def test_memoization_produces_correct_relative_paths(self):
        """Memoized replay adjusts prefix correctly so field paths are
        accurate at the replay site."""
        leaf_shape = {
            "type": "object",
            "properties": {
                "secretName": {"type": "string"},
                "port": {"type": "integer"},
            },
        }
        props = {
            "primary": leaf_shape,
            "secondary": leaf_shape,
        }
        fields = list(walk_crd_schema(props))
        # Both sites should have correct paths
        primary_fields = {
            f.name for f in fields if f.path.startswith("spec.primary.")
        }
        secondary_fields = {
            f.name for f in fields if f.path.startswith("spec.secondary.")
        }
        assert primary_fields == {"secretName", "port"}
        assert secondary_fields == {"secretName", "port"}

    def test_cache_is_per_call(self):
        """Cache from one walk_crd_schema call does not leak to the next."""
        leaf = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }
        # First call
        fields_1 = list(walk_crd_schema({"a": leaf}))
        # Second call with different top-level structure but same leaf shape
        fields_2 = list(walk_crd_schema({"b": leaf}))
        # Paths should reflect separate calls, not cross-contaminate
        paths_1 = {f.path for f in fields_1}
        paths_2 = {f.path for f in fields_2}
        assert "spec.a" in paths_1
        assert "spec.b" in paths_2
        assert "spec.b" not in paths_1
        assert "spec.a" not in paths_2

    def test_recursive_generators_memoized(self):
        """Recursive ApplicationSet-like generators do not cause exponential
        walk. The same generator shape encountered at multiple depths is
        replayed from cache."""
        # Simulate: spec.generators[].matrix.generators[].git.{repoURL, path}
        # The inner generators[] has the same shape as outer generators[]
        git_shape = {
            "type": "object",
            "properties": {
                "repoURL": {"type": "string"},
                "path": {"type": "string"},
            },
        }
        # Inner generators (same shape will repeat)
        generator_item = {
            "type": "object",
            "properties": {
                "git": git_shape,
            },
        }
        # Outer generators contains matrix containing inner generators
        outer_generator_item = {
            "type": "object",
            "properties": {
                "git": git_shape,
                "matrix": {
                    "type": "object",
                    "properties": {
                        "generators": {
                            "type": "array",
                            "items": generator_item,
                        },
                    },
                },
            },
        }
        props = {
            "generators": {
                "type": "array",
                "items": outer_generator_item,
            },
        }
        fields = list(walk_crd_schema(props, max_depth=12))
        # Should find repoURL at multiple depths without exponential blowup
        repo_fields = [f for f in fields if f.name == "repoURL"]
        assert len(repo_fields) >= 2  # at least outer + inner

    def test_performance_memoized_vs_depth_increase(self):
        """Walking 148 CRDs at depth 12 with memoization should be at most
        2x baseline time at depth 8 without memoization.

        This is a benchmark test — mark with pytest.mark.slow if needed.
        Placeholder: actual benchmark requires real CRD fixtures.
        """
        # Synthetic benchmark: deeply nested repeated shapes
        import time

        leaf = {
            "type": "object",
            "properties": {f"f{i}": {"type": "string"} for i in range(5)},
        }
        # Build a wide, deep schema with repeated shapes
        level = leaf
        for i in range(10):
            level = {
                "type": "object",
                "properties": {
                    f"branch_a_{i}": level,
                    f"branch_b_{i}": level,
                },
            }
        props = {"root": level}

        start = time.perf_counter()
        fields = list(walk_crd_schema(props, max_depth=12))
        elapsed = time.perf_counter() - start

        # Should complete in reasonable time (< 5 seconds) thanks to memoization
        # Without memoization, 2^10 branches * 10 depth * 5 fields = very large
        assert elapsed < 5.0
        assert len(fields) > 0
```

## Implementation Details

### Step 1: Duplicate `compute_schema_fingerprint` in schema_walker.py

Copy the fingerprinting function from `ref_detector.py` into `schema_walker.py` to avoid a circular import. The function is ~20 LOC.

**File:** `platform-tools/idi/idi/generation/crd/schema_walker.py`

```python
def _compute_schema_fingerprint(
    properties: dict[str, dict],
    required: list[str] | None = None,
) -> str:
    """Compute a structural fingerprint from schema properties.

    Returns sorted name:type pairs with ? suffix for optional properties.
    Example: "key:string?,name:string,namespace:string?"

    This is a local copy of ref_detector.compute_schema_fingerprint to
    avoid circular imports (ref_detector imports from schema_walker).
    """
```

The logic is: iterate `sorted(properties.keys())`, extract each property's `type` (defaulting to `"string"`), mark optional with `?`, and join with `,`. This produces a canonical key suitable for dict-based caching.

### Step 2: Add per-call cache to `_walk_recursive`

Add a `_cache` parameter (defaulting to `None`) to `_walk_recursive`. At the top-level `walk_crd_schema` entry point, create a fresh `dict` and pass it down through every recursive call. This ensures:

- The cache is scoped to a single `walk_crd_schema` invocation
- No stale data leaks between different CRDs
- No module-level mutable state

The cache type is `dict[str, list[tuple[str, int, dict[str, Any]]]]`, keyed by fingerprint string. Each cached entry is a list of `(relative_path, relative_depth_offset, schema_node)` tuples representing the fields found during the first walk of that shape.

### Step 3: Cache population on first encounter

When `_walk_recursive` encounters a schema node with properties, compute its fingerprint. If the fingerprint is not in the cache:

1. Walk normally (existing recursion logic)
2. Collect results as a list of `(relative_path_from_this_node, depth_offset_from_this_node, field_schema)` tuples
3. Store in cache under the fingerprint key
4. Yield the fields normally

The relative path is computed by stripping the current prefix from the yielded field's path. The depth offset is `field.depth - current_depth`.

### Step 4: Cache replay on subsequent encounters

When the fingerprint IS in the cache:

1. Iterate the cached tuples
2. For each `(relative_path, depth_offset, schema_node)`:
   - Compute `actual_path = current_prefix + "." + relative_path`
   - Compute `actual_depth = current_depth + depth_offset`
   - Skip if `actual_depth > max_depth`
   - Recompute `depth_confidence` from `actual_depth` using the decay formula from Section 10:
     - `depth <= full_confidence_depth` -> `1.0`
     - `depth > full_confidence_depth` -> `depth_decay ** (depth - full_confidence_depth)`
   - Yield a new `WalkedField` with the adjusted values
3. Do NOT recurse into child properties (the cache already contains all descendant fields)

### Step 5: Update `walk_crd_schema` entry point

Modify `walk_crd_schema` to create the cache dict and pass it (along with `full_confidence_depth` and `depth_decay` from Section 10) into `_walk_recursive`:

```python
def walk_crd_schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
    prefix: str = "spec",
    max_depth: int = 12,              # raised in section-10
    full_confidence_depth: int = 8,    # from section-10
    depth_decay: float = 0.9,          # from section-10
) -> Iterator[WalkedField]:
    """Recursively yield every field in a CRD spec schema.

    Uses fingerprint-based memoization to avoid re-walking identical
    sub-schema shapes. Cache is per-call (not shared across invocations).
    """
    cache: dict[str, list[tuple[str, int, dict[str, Any]]]] = {}
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
```

### Step 6: Update `_walk_recursive` signature

Add `full_confidence_depth`, `depth_decay`, and `cache` parameters to `_walk_recursive`. These are threaded through every recursive call.

```python
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
    cache: dict[str, list[tuple[str, int, dict[str, Any]]]] | None = None,
) -> Iterator[WalkedField]:
```

### Step 7: Memoization logic placement

The memoization check happens at the point where `_walk_recursive` is about to recurse into a sub-object's properties (the two recursion sites: object properties and array items). Before recursing, compute the fingerprint of the child properties. If cached, replay; otherwise, recurse normally and capture results for caching.

Key implementation detail: the cache captures the entire subtree of results from a given schema shape, not just one level. This means the replay completely replaces the recursion -- no further recursion is needed for a cache hit.

### Step 8: Sibling names in replayed fields

When replaying cached fields, `sibling_names` must also be correct. Since `sibling_names` is derived from the schema structure (the parent object's property names), and the schema structure is identical for a fingerprint match, the cached `sibling_names` values can be reused directly. Only the root-level siblings of the replayed subtree need adjustment (they come from the parent at the replay site), but fields deeper than the root of the cached subtree retain their original sibling relationships.

### Step 9: walk_crd_status compatibility

`walk_crd_status` should also benefit from memoization. Pass a fresh cache dict through `walk_crd_status` as well, following the same pattern as `walk_crd_schema`.

## Edge Cases

1. **Empty properties:** An empty properties dict produces an empty fingerprint `""`. Do not cache empty fingerprints (they provide no benefit and could cause spurious hits).

2. **Schema with only excluded fields:** If all properties in a sub-schema are excluded fields, the cache entry will be an empty list. This is correct -- replay yields nothing, matching the non-memoized behavior.

3. **`is_array_item` flag:** This flag should be part of the cache key OR set correctly during replay. Fields inside array items need `is_array_item=True`. The simplest approach: include `is_array_item` in the cached tuples and replay it faithfully.

4. **`required` list differences:** Two schemas with the same property names/types but different `required` lists will produce different fingerprints (the `?` suffix differs). This is correct -- requiredness affects `WalkedField.required` and should not be conflated.

5. **Composed schemas (allOf/oneOf/anyOf):** The `_flatten_composed` call happens before recursion. The fingerprint is computed on the flattened/effective schema, so composed schemas that flatten to the same structure will share a cache entry. This is the desired behavior.

## Validation Criteria

1. All existing `test_schema_walker.py` tests pass unchanged (memoization is an internal optimization; external behavior is identical)
2. New memoization tests pass
3. Fields from memoized replay have correct `path`, `depth`, `depth_confidence`, `parent_path`, `is_array_item`, `required`, and `sibling_names`
4. Cache is not shared between separate `walk_crd_schema` calls
5. Performance on deeply nested repeated schemas is bounded (no exponential blowup)
6. `walk_crd_status` also uses memoization

## Implementation Notes (Actual)

### Deviations from plan:
1. **Deep fingerprint instead of shallow:** Plan called for duplicating `compute_schema_fingerprint` from `ref_detector.py` (shallow: top-level names/types only). Code review identified this as a correctness bug — same top-level shape with different nested children would collide. Replaced with `_compute_deep_fingerprint` using `json.dumps(properties, sort_keys=True)` for a canonical deep structural key.

2. **Composite cache key:** Plan did not include `is_array_item` in the cache key. Code review identified that the same schema shape in object vs array context needs separate cache entries. Cache key changed from `str` to `tuple[str, bool]` = `(fingerprint, is_array_item)`.

3. **Test file already committed:** The 5 memoization tests were committed in a prior session. This session's commit contains only the schema_walker.py implementation + review fixes.

### Test results: 66 walker tests + 1051 total CRD tests pass.

## Files Summary

| Action | File |
|--------|------|
| Modified | `platform-tools/idi/idi/generation/crd/schema_walker.py` |
| Modified (prior session) | `platform-tools/idi/tests/generation/crd/test_schema_walker.py` |