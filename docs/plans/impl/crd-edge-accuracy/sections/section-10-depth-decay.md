No existing depth decay code. Let me also check the `walk_crd_status` to confirm its signature and understand how both entry points work.

Now I have all the context needed. Let me produce the section content.

# Section 10: Depth Confidence Decay

## Overview

The CRD schema walker in `schema_walker.py` currently uses a hard `max_depth=8` cutoff. Any field beyond depth 8 is silently dropped, creating a "depth wall" that misses legitimate references in deeply nested schemas (e.g., ArgoCD ApplicationSet generators, Istio nested routing configs). This section replaces the hard wall with a confidence decay model:

- Fields at depth 1-8 retain full confidence (`1.0`).
- Fields at depths 9-12 receive exponentially decaying confidence (`0.9^(depth - 8)`).
- The `max_depth` limit is raised from 8 to 12, so the walker yields fields at all depths up to 12.
- The `depth_confidence` value is populated on each `WalkedField` (the field was added in section-03 with a default of `1.0`).

Downstream code in `ref_detector.py` (section-12) multiplies each detection's confidence by `depth_confidence`, naturally pruning low-quality deep detections below the 0.7 emission floor. This section does NOT implement the multiplication step; it only produces the decay values.

**Critical constraint:** Precision > Recall. The decay model is conservative: 8 levels of full confidence covers all known production schemas. The decay zone (9-12) allows tentative detection while preventing false edges at extreme depths.

## Dependencies

- **Requires section-03** (WalkedField enrichment): The `depth_confidence` field must already exist on `WalkedField` with a default of `1.0`.
- **Blocks section-11** (memoization): Memoization needs to recompute `depth_confidence` from actual depth during cache replay. The decay formula must be established before memoization can use it.
- **Blocks section-12** (confidence multiplication): The post-processing step that multiplies detector confidence by `depth_confidence` depends on this section populating the values.

## Files Modified

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/crd/schema_walker.py` | Modify `walk_crd_schema` signature; modify `_walk_recursive` to compute and populate `depth_confidence` |
| `platform-tools/idi/tests/generation/crd/test_schema_walker.py` | Add new test class `TestDepthConfidenceDecay` |

## Tests First

Add the following tests to `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_schema_walker.py` in a new class `TestDepthConfidenceDecay`. These tests must be written and fail before the implementation changes are made.

```python
class TestDepthConfidenceDecay:
    """Tests for depth_confidence decay on WalkedField (section-10)."""

    def test_depth_7_full_confidence(self):
        """Fields at depth 7 have depth_confidence == 1.0.

        Build a schema nested to depth 7 (within default full_confidence_depth=8).
        Assert the deepest field has depth_confidence == 1.0.
        """

    def test_depth_8_full_confidence(self):
        """Fields at exactly depth 8 (== full_confidence_depth) have depth_confidence == 1.0.

        Build a schema nested to depth 8. Assert depth_confidence == 1.0
        at the boundary.
        """

    def test_depth_9_decayed(self):
        """Fields at depth 9 have depth_confidence == 0.9.

        Formula: 0.9 ^ (9 - 8) = 0.9
        Requires max_depth >= 9 (the new default is 12).
        """

    def test_depth_10_decayed(self):
        """Fields at depth 10 have depth_confidence == 0.81.

        Formula: 0.9 ^ (10 - 8) = 0.81
        """

    def test_depth_11_decayed(self):
        """Fields at depth 11 have depth_confidence == 0.729.

        Formula: 0.9 ^ (11 - 8) = 0.729
        """

    def test_depth_12_decayed(self):
        """Fields at depth 12 have depth_confidence == 0.6561.

        Formula: 0.9 ^ (12 - 8) = 0.6561
        This is the maximum depth with the new default max_depth=12.
        """

    def test_custom_full_confidence_depth(self):
        """Custom full_confidence_depth changes the decay start point.

        With full_confidence_depth=5, depth 6 should have confidence 0.9.
        Formula: 0.9 ^ (6 - 5) = 0.9
        """

    def test_walker_yields_fields_up_to_depth_12(self):
        """The walker now yields fields up to max_depth=12 (raised from 8).

        Build a schema nested to depth 12. Assert that depth-12 fields
        are yielded (they would have been dropped with the old max_depth=8).
        """

    def test_fields_beyond_max_depth_12_not_yielded(self):
        """Fields beyond the new max_depth=12 are NOT yielded.

        Build a schema nested to depth 13. Assert no field at depth 13
        appears in the output.
        """

    def test_default_max_depth_is_12(self):
        """walk_crd_schema with no explicit max_depth uses 12 as default.

        Build a schema deep enough and verify the walker reaches depth 12
        but not depth 13, without passing max_depth explicitly.
        """

    def test_walk_crd_status_unaffected(self):
        """walk_crd_status retains its own max_depth=3 and does NOT apply decay.

        walk_crd_status is for shallow status fields and should not
        be modified by this change. Its depth_confidence should remain 1.0
        at all depths (max_depth=3 is within full_confidence_depth=8).
        """
```

### Test Details

**How to build deeply nested schemas for tests:** Use a helper function that generates a schema with N levels of nesting:

```python
def _make_deep_schema(depth: int) -> dict:
    """Build a schema nested to the given depth.

    Returns a properties dict suitable for walk_crd_schema().
    At each level, there is one property named "level_N" (where N is the depth)
    with type "object" and a single nested property at the next level.
    The deepest level has type "string" (a leaf).
    """
    if depth <= 1:
        return {"level_1": {"type": "string"}}
    inner = _make_deep_schema(depth - 1)
    # Shift all keys: level_1 -> level_2, etc.
    shifted = {}
    for k, v in inner.items():
        n = int(k.split("_")[1])
        shifted[f"level_{n + 1}"] = v
    return {
        "level_1": {
            "type": "object",
            "properties": shifted,
        },
    }
```

Alternatively, a simpler iterative approach builds the schema inside-out:

```python
def _make_deep_schema(target_depth: int) -> dict:
    """Build a properties dict that nests to target_depth levels."""
    schema = {"leaf": {"type": "string"}}
    for d in range(target_depth - 1, 0, -1):
        schema = {f"d{d}": {"type": "object", "properties": schema}}
    return schema
```

With this helper, `walk_crd_schema(_make_deep_schema(12))` yields fields from depth 1 (`spec.d1`) through depth 12 (`spec.d1.d2...leaf`).

**`test_depth_7_full_confidence` / `test_depth_8_full_confidence`:** Build schemas nested to 7 and 8 respectively. Walk with default parameters. Find the deepest yielded field. Assert `field.depth_confidence == 1.0`.

**`test_depth_9_decayed` through `test_depth_12_decayed`:** Build a schema nested to depth 12. Walk with default parameters (new defaults: `max_depth=12`, `full_confidence_depth=8`, `depth_decay=0.9`). For each test, find the field at the target depth and assert `depth_confidence == pytest.approx(expected_value)`:
- depth 9: `0.9 ** 1 = 0.9`
- depth 10: `0.9 ** 2 = 0.81`
- depth 11: `0.9 ** 3 = 0.729`
- depth 12: `0.9 ** 4 = 0.6561`

Use `pytest.approx()` for floating-point comparison.

**`test_custom_full_confidence_depth`:** Call `walk_crd_schema(schema, full_confidence_depth=5)` on a schema nested to depth 7. Assert depth 5 has confidence 1.0, depth 6 has confidence 0.9, depth 7 has confidence 0.81.

**`test_walker_yields_fields_up_to_depth_12`:** Build a schema nested to 12 levels. Walk with default parameters. Assert a field at depth 12 exists in the output. This verifies the `max_depth` was raised from 8 to 12.

**`test_fields_beyond_max_depth_12_not_yielded`:** Build a schema nested to 14 levels. Walk with default parameters (`max_depth=12`). Assert no field at depth 13 or 14 is yielded.

**`test_default_max_depth_is_12`:** Walk a 14-deep schema WITHOUT passing `max_depth`. Assert maximum depth in yielded fields is 12. This verifies the default changed from 8 to 12.

**`test_walk_crd_status_unaffected`:** Call `walk_crd_status` on a schema 3 levels deep. Assert all fields have `depth_confidence == 1.0`. `walk_crd_status` uses its own `max_depth=3` and is not modified in this section. Since depth 3 is well within `full_confidence_depth=8`, no decay applies. This confirms the status walker is unaffected.

### Backward Compatibility Tests

The existing `TestWalkMaxDepth` tests use explicit `max_depth=2` arguments, so they are unaffected by the default change from 8 to 12. However, verify that `test_fields_beyond_max_depth_not_yielded` still works correctly — it uses `max_depth=2` explicitly, which should continue to cut off at depth 2 regardless of the new defaults.

## Implementation

### 1. Modify walk_crd_schema signature

In `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/schema_walker.py`, change the `walk_crd_schema` function signature to accept new parameters:

```python
def walk_crd_schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
    prefix: str = "spec",
    max_depth: int = 12,              # CHANGED: raised from 8
    full_confidence_depth: int = 8,    # NEW: full confidence up to this depth
    depth_decay: float = 0.9,          # NEW: multiplier per level beyond threshold
) -> Iterator[WalkedField]:
    """Recursively yield every field in a CRD spec schema.

    Args:
        properties: The properties dict from the spec schema.
        required: Required field names at this level.
        prefix: Dot-path prefix (default: "spec").
        max_depth: Maximum traversal depth (default: 12).
            Raised from 8 to 12 to support depth confidence decay.
        full_confidence_depth: Depth up to which depth_confidence stays 1.0 (default: 8).
        depth_decay: Confidence multiplier per level beyond full_confidence_depth (default: 0.9).
            At depth 9: 0.9, depth 10: 0.81, depth 11: 0.729, depth 12: 0.6561.

    Yields:
        WalkedField for each property at every level.
    """
```

The function body passes `full_confidence_depth` and `depth_decay` to `_walk_recursive`.

### 2. Modify _walk_recursive signature and body

Add `full_confidence_depth` and `depth_decay` parameters to `_walk_recursive`:

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
    full_confidence_depth: int = 8,    # NEW
    depth_decay: float = 0.9,          # NEW
) -> Iterator[WalkedField]:
```

### 3. Compute depth_confidence

Inside `_walk_recursive`, before the `yield WalkedField(...)` statement, compute `depth_confidence`:

```python
# Compute depth confidence decay.
if current_depth <= full_confidence_depth:
    depth_confidence = 1.0
else:
    depth_confidence = depth_decay ** (current_depth - full_confidence_depth)
```

This follows the formula from the plan:
- `depth <= full_confidence_depth` results in `1.0`
- `depth > full_confidence_depth` results in `depth_decay ^ (depth - full_confidence_depth)`

### 4. Pass depth_confidence to WalkedField

Update the `yield WalkedField(...)` statement to include `depth_confidence`:

```python
yield WalkedField(
    path=field_path,
    name=prop_name,
    schema=prop_schema,
    depth=current_depth,
    is_array_item=is_array_item,
    required=field_required,
    parent_path=prefix,
    sibling_names=siblings,          # from section-03
    depth_confidence=depth_confidence,  # NEW
)
```

### 5. Pass parameters through recursive calls

Both recursive call sites in `_walk_recursive` (object recursion and array recursion) must forward the new parameters:

For the object recursion (`if effective_schema.get("type") == "object"` branch):
```python
yield from _walk_recursive(
    properties=effective_schema["properties"],
    required=effective_schema.get("required", []),
    prefix=field_path,
    max_depth=max_depth,
    current_depth=current_depth + 1,
    is_array_item=is_array_item,
    skip_envelope=False,
    skip_status_in_excluded=skip_status_in_excluded,
    full_confidence_depth=full_confidence_depth,  # NEW
    depth_decay=depth_decay,                      # NEW
)
```

For the array recursion (`if effective_schema.get("type") == "array"` branch):
```python
yield from _walk_recursive(
    properties=items["properties"],
    required=items.get("required", []),
    prefix=field_path,
    max_depth=max_depth,
    current_depth=current_depth + 1,
    is_array_item=True,
    skip_envelope=False,
    skip_status_in_excluded=skip_status_in_excluded,
    full_confidence_depth=full_confidence_depth,  # NEW
    depth_decay=depth_decay,                      # NEW
)
```

### 6. Update walk_crd_schema body

The `walk_crd_schema` function must pass the new parameters to `_walk_recursive`:

```python
yield from _walk_recursive(
    properties=properties,
    required=required or [],
    prefix=prefix,
    max_depth=max_depth,
    current_depth=1,
    is_array_item=False,
    skip_envelope=True,
    skip_status_in_excluded=True,
    full_confidence_depth=full_confidence_depth,  # NEW
    depth_decay=depth_decay,                      # NEW
)
```

### 7. walk_crd_status is NOT modified

`walk_crd_status` keeps its own `max_depth=3` and does not accept `full_confidence_depth` or `depth_decay` parameters. Since it calls `_walk_recursive` with `max_depth=3`, and `_walk_recursive` now has defaults `full_confidence_depth=8` and `depth_decay=0.9`, no decay will ever apply (max_depth=3 is well below `full_confidence_depth=8`). All status fields will have `depth_confidence=1.0`.

This is the correct behavior: status fields are shallow and should never be subject to depth decay.

### Summary of Changes

The total change to `schema_walker.py` is approximately 15 lines:

- `walk_crd_schema` signature: change `max_depth` default from 8 to 12, add 2 new parameters
- `_walk_recursive` signature: add 2 new parameters with defaults
- 3 lines of depth_confidence computation logic
- 1 keyword argument added to `yield WalkedField(...)`
- 2 keyword arguments added to each of the 2 recursive `yield from _walk_recursive(...)` calls
- 2 keyword arguments added to the `yield from _walk_recursive(...)` call in `walk_crd_schema`

No changes to `walk_crd_status`. No changes to any other production file. No changes to existing tests (all existing tests pass `max_depth` explicitly or use the default, which was 8 and is now 12 but produces the same depth_confidence=1.0 behavior at depths 1-8).

### Verification

After implementing, run:
```bash
cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi
uv run pytest tests/generation/crd/test_schema_walker.py -v
```

Then verify the full suite:
```bash
uv run pytest tests/generation/crd/ -v
```

All existing tests must pass with zero modifications. The new `TestDepthConfidenceDecay` tests must also pass.

### Existing Test Impact Assessment

Review the existing `TestWalkMaxDepth` tests:

- `test_fields_at_max_depth_yielded`: Uses `max_depth=2` explicitly. Unaffected.
- `test_fields_beyond_max_depth_not_yielded`: Uses `max_depth=2` explicitly. Unaffected.
- `test_custom_max_depth_2`: Uses `max_depth=2` explicitly. Unaffected.

Review `TestWalkNested.test_depth_5_nesting`: Uses default `max_depth`. With the old default of 8, depth 5 was yielded. With the new default of 12, depth 5 is still yielded. `depth_confidence` at depth 5 is `1.0` (below `full_confidence_depth=8`). Unaffected.

No existing test relies on the walker stopping at depth 8 without explicitly specifying `max_depth=8`. The only tests that check max_depth behavior pass it explicitly.

## Implementation Notes

### Additional tests added (code review)
- `test_custom_depth_decay` — verifies depth_decay=0.5 produces correct values
- `test_depth_decay_through_array_nesting` — verifies decay through array recursion path

### Minor fix
- Updated walk_crd_status docstring "3 vs 5" → "3 vs 12"

### Final test count
- 13 tests in TestDepthConfidenceDecay (11 planned + 2 from review)
- 61 total tests in test_schema_walker.py
- 1044 tests in full CRD suite, all passing