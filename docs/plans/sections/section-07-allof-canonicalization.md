I now have all the context needed. Let me generate the section content.

# Section 07: allOf Canonicalization

## Overview

This section implements proper `allOf`/`oneOf`/`anyOf` canonicalization in the REST pipeline's `field_extractor.py`. The current `extract_schema_fields()` function has only basic `allOf` handling (it iterates sub-schemas but does not handle conflict detection, discriminator preservation, `oneOf`/`anyOf` intersection semantics, or circular `$ref` protection). This section replaces that basic logic with a robust canonicalization function that can handle the full range of composed schemas found in real-world OpenAPI specs.

This is improvement item **#17** from the REST Pipeline Improvements plan, moved from Phase C to Phase B because `swagger2.py` deletion (section-08) depends on proper composed schema handling.

### Why This Matters

Many OpenAPI specs use `allOf` extensively for schema composition (base model + extension), inheritance (`allOf` + `discriminator`), and vendor-specific conventions. Swagger 2.0 specs converted to OpenAPI 3.0 often end up with deeply nested `allOf` chains. Without proper canonicalization, `extract_schema_fields()` misses properties hidden behind composition layers, producing incomplete dependency graphs.

### Precision Constraint

False edges are worse than missing edges. When property types conflict across `allOf` branches, the field must be marked ambiguous (confidence 0.5, below the 0.7 emission floor) rather than guessed. For `oneOf`/`anyOf`, only the **intersection** of properties across all branches is high-confidence; the union is advisory only (below floor) unless a `discriminator` is present.

## Dependencies

- **section-01-data-model**: The `DetectionSource` enum and updated `Dependency` dataclass must exist.
- **section-02-phase-a-preprocessing**: Single-item combinator unwrapping (item #3) is a prerequisite. The canonicalization function calls trivial unwrapping as a first step before merging.
- **section-04-phase-a-integration**: Phase A regression tests must pass, confirming baseline behavior.
- **$ref resolution memoization** (from section-02): The memoized `$ref` resolver should be in place so canonicalization does not re-resolve the same `$ref` targets repeatedly.

## File to Modify

**`/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/field_extractor.py`**

This is the sole file that needs modification. The new function is added to this file and called from `extract_schema_fields()` as a preprocessing step.

## Tests First

**Test file:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_allof_canonicalization.py`

The test directory `tests/generation/rest/` is new for the REST pipeline improvements. Create `__init__.py` in `tests/generation/rest/` if it does not already exist.

### Test Stubs

```python
"""Tests for allOf/oneOf/anyOf canonicalization in field_extractor.py."""
import pytest

from idi.generation.field_extractor import canonicalize_composed_schema


class TestAllOfMerge:
    """Test allOf property merging."""

    def test_allof_two_branches_merged(self):
        """allOf with two branches merges all properties into a flat schema."""
        # Schema: allOf: [{properties: {name: {type: string}}}, {properties: {age: {type: integer}}}]
        # Expected: properties has both 'name' and 'age'

    def test_allof_ref_plus_inline(self):
        """allOf with a resolved $ref schema + inline properties merges both."""
        # Schema: allOf: [{$ref resolved to {properties: {id: ...}}}, {properties: {role: ...}}]
        # Expected: properties has both 'id' and 'role'

    def test_allof_conflicting_property_types(self):
        """allOf with same property name but different types marks it ambiguous."""
        # Schema: allOf: [{properties: {value: {type: string}}}, {properties: {value: {type: integer}}}]
        # Expected: 'value' property has _ambiguous: True marker, confidence 0.5

    def test_allof_preserves_discriminator(self):
        """Discriminator field is preserved during allOf merge."""
        # Schema with discriminator: {propertyName: "type"} + allOf branches
        # Expected: merged result contains discriminator key

    def test_allof_preserves_readonly_writeonly_last_wins(self):
        """readOnly/writeOnly are preserved with last-wins semantics."""
        # allOf: [{properties: {x: {readOnly: false}}}, {properties: {x: {readOnly: true}}}]
        # Expected: merged 'x' has readOnly: true (last wins)

    def test_allof_required_fields_merged(self):
        """required lists from all allOf branches are merged and deduplicated."""
        # allOf: [{required: ["a", "b"]}, {required: ["b", "c"]}]
        # Expected: required = ["a", "b", "c"]

    def test_allof_empty_branches(self):
        """allOf with no branches returns schema as-is."""
        # Schema: {allOf: []}
        # Expected: returned unchanged

    def test_allof_nested_recursively_flattened(self):
        """Nested allOf (allOf within allOf) is recursively flattened."""
        # Schema: allOf: [{allOf: [{properties: {a: ...}}, {properties: {b: ...}}]}, {properties: {c: ...}}]
        # Expected: properties has a, b, c


class TestOneOfAnyOf:
    """Test oneOf/anyOf intersection semantics."""

    def test_oneof_intersection_high_confidence(self):
        """oneOf returns intersection of properties across all branches."""
        # oneOf: [{properties: {id, name, email}}, {properties: {id, name, phone}}]
        # Expected: only 'id' and 'name' in result (intersection)

    def test_oneof_with_discriminator_allows_union(self):
        """oneOf with discriminator allows union of all properties."""
        # oneOf with discriminator: {propertyName: "type"} + branches
        # Expected: union of all branch properties

    def test_anyof_intersection_high_confidence(self):
        """anyOf returns intersection of properties for high-confidence."""
        # anyOf: [{properties: {id, title}}, {properties: {id, body}}]
        # Expected: only 'id' in result


class TestCircularRefProtection:
    """Test circular $ref cycle detection."""

    def test_circular_ref_halts_recursion(self):
        """Circular $ref in composed schema detected via visited set, no infinite loop."""
        # Schema that references itself via allOf → $ref → back to same schema
        # Expected: function terminates, returns partial result without looping


class TestIntegrationWithExtractSchemaFields:
    """Test that canonicalization integrates with extract_schema_fields."""

    def test_extract_schema_fields_uses_canonicalization(self):
        """extract_schema_fields() applies canonicalization before walking properties."""
        # Compose a schema with allOf that would previously miss properties at max_depth=2
        # Expected: all composed properties appear in extracted result
```

### Shared Fixture (conftest.py)

Add the following fixture to `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/conftest.py`:

```python
"""Shared fixtures for REST pipeline tests."""
import pytest


@pytest.fixture
def composed_schema():
    """Schema with allOf/oneOf/anyOf for canonicalization tests."""
    return {
        "allOf": [
            {
                "properties": {
                    "id": {"type": "string", "format": "uuid", "readOnly": True},
                    "name": {"type": "string"},
                },
                "required": ["id"],
            },
            {
                "properties": {
                    "role": {"type": "string", "enum": ["admin", "user"]},
                    "email": {"type": "string", "format": "email"},
                },
                "required": ["role"],
            },
        ],
        "discriminator": {"propertyName": "role"},
    }


@pytest.fixture
def recursive_schema():
    """Schema with circular $ref for cycle-detection tests."""
    # Simulates a self-referential schema like User.manager -> User
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "manager": {
                "allOf": [
                    {"$ref": "#/components/schemas/User"},  # circular
                ],
            },
        },
    }
```

## Implementation Details

### New Function: `canonicalize_composed_schema`

Add a new top-level function to `field_extractor.py`. This function takes a schema dict and an optional visited set (for circular `$ref` detection), and returns a flattened schema with all composition resolved.

**Function signature:**

```python
def canonicalize_composed_schema(
    schema: Dict[str, Any],
    *,
    visited: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Flatten allOf/oneOf/anyOf compositions into a canonical flat schema.

    Algorithm:
    1. If the schema has no composition keywords, return as-is.
    2. Apply single-item combinator unwrapping (item #3 prerequisite).
    3. For allOf: merge all branches' properties and required fields.
       - Conflict detection: same property name with different types -> mark _ambiguous.
       - Preserve readOnly/writeOnly/deprecated/nullable with last-wins semantics.
       - Preserve additionalProperties from any branch.
    4. For oneOf/anyOf WITHOUT discriminator: use property intersection only.
       Properties present in ALL branches are high-confidence.
    5. For oneOf/anyOf WITH discriminator: allow property union.
    6. Preserve discriminator field during merge.
    7. Recurse into nested compositions. Track visited $ref pointers to halt cycles.
    8. Set type to "object" if properties exist and type is not set.

    Args:
        schema: The schema dict to canonicalize. May contain allOf/oneOf/anyOf.
        visited: Set of $ref pointer strings already visited (cycle detection).

    Returns:
        A new schema dict with composition flattened. Does not mutate input.
    """
```

### Algorithm Step-by-Step

**Step 1: Early return.** If the schema has none of `allOf`, `oneOf`, `anyOf`, return it unchanged.

**Step 2: Single-item unwrapping.** If any combinator has exactly one item, collapse it (this is item #3 from section-02). This step is applied first because many single-item combinators are formatting artifacts.

**Step 3: allOf merge.** Iterate each sub-schema in `allOf`:
- Recursively call `canonicalize_composed_schema` on each sub-schema (handles nested compositions).
- Merge `properties` dicts. For each property, check if it already exists in the merged result:
  - If the existing property has a different `type` than the new one, set `_ambiguous: True` on the property. This is a sentinel that downstream code uses to exclude the property from producer registration (confidence would be 0.5).
  - For `readOnly`, `writeOnly`, `deprecated`, `nullable`: last-wins semantics (later branch overrides earlier).
- Merge `required` lists with deduplication (preserve order).
- Preserve `additionalProperties` if present in any branch (last-wins if conflicting).

**Step 4: oneOf/anyOf without discriminator.** Compute the intersection of property names across all branches. Only properties present in every branch are included in the result. This is the conservative approach -- the intersection gives high-confidence fields that are guaranteed to exist regardless of which branch matches.

**Step 5: oneOf/anyOf with discriminator.** When `discriminator` is present at the schema level (or inherited from a parent), take the union of all branch properties instead of the intersection. The discriminator tells the consumer which branch applies, so all fields are valid in context.

**Step 6: Discriminator preservation.** Copy the `discriminator` key from the original schema to the merged result. This is critical for polymorphic schemas -- downstream code may need it for type dispatching.

**Step 7: Circular $ref detection.** Maintain a `visited: set[str]` tracking `$ref` pointer strings. Before resolving a `$ref`, check if it is in the visited set. If so, return `{}` immediately (halt recursion). Add the `$ref` to visited before recursing.

Note: In the current codebase, `$ref` resolution happens at spec load time in `spec_loader.py` (the `_resolve_refs` function resolves all `$ref` pointers before anything else runs). This means by the time `canonicalize_composed_schema` sees the schema, `$ref` pointers are already resolved to inline dicts. The circular `$ref` protection in this function is a defense-in-depth measure for cases where resolution is incomplete or where the function is called on partially-resolved schemas. Use a schema identity check (via `id()`) as the visited-set key when `$ref` strings are not available.

**Step 8: Type inference.** If the merged result has `properties` but no `type`, set `type` to `"object"`.

### Integration Point: Modifying `extract_schema_fields`

The `extract_schema_fields()` function at line 30 of `field_extractor.py` currently has basic `allOf` handling (lines 65-69). Replace that block with a call to `canonicalize_composed_schema`:

**Current code (lines 54-70):**
```python
if not schema or max_depth <= 0:
    return {"type": "object", "properties": {}, "required": []}

result: Dict[str, Any] = {
    "type": schema.get("type", "object"),
    "description": schema.get("description", ""),
    "required": list(schema.get("required", [])),
    "properties": {},
}

# Handle allOf (schema composition).
if "allOf" in schema:
    for sub in schema["allOf"]:
        merged = extract_schema_fields(ctx, sub, max_depth - 1)
        result["properties"].update(merged.get("properties", {}))
        result["required"].extend(merged.get("required", []))
```

**New code pattern:**
```python
if not schema or max_depth <= 0:
    return {"type": "object", "properties": {}, "required": []}

# Canonicalize composed schemas before field extraction.
schema = canonicalize_composed_schema(schema)

result: Dict[str, Any] = {
    "type": schema.get("type", "object"),
    "description": schema.get("description", ""),
    "required": list(schema.get("required", [])),
    "properties": {},
}

# The old allOf block is removed -- canonicalize_composed_schema handles it.
```

This is a drop-in replacement. The canonicalization produces a flat schema with `properties` and `required` already merged, so the subsequent property-walking loop (lines 72-93) works unchanged.

### Conflict Marking Convention

When a property appears in multiple `allOf` branches with conflicting types, add an `_ambiguous` sentinel:

```python
{
    "value": {
        "type": "string",    # type from first branch (arbitrary)
        "_ambiguous": True,  # sentinel: conflicting types detected
    }
}
```

Downstream code (output detection, FK inference) should check for `_ambiguous` and either skip the field or assign it confidence 0.5 (below the 0.7 emission floor). This convention is internal to the pipeline and does not appear in generated output.

### Reference: CRD Pipeline's `_flatten_composed`

The CRD pipeline has a similar function at `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/schema_walker.py` (lines 46-99). That implementation handles the basic case (allOf merge, single-item oneOf/anyOf unwrap) but does NOT handle:

- Conflict detection (it does `dict.update`, last-wins silently)
- Discriminator preservation
- oneOf/anyOf intersection semantics
- Circular `$ref` protection (the CRD pipeline relies on schema_walker's depth limit instead)

The REST pipeline's `canonicalize_composed_schema` is intentionally more thorough because REST API specs have more diverse composition patterns than CRD schemas.

### What NOT to Build

- Do not add `networkx` or any external graph library dependency.
- Do not modify `spec_loader.py` -- `$ref` resolution is already handled there.
- Do not modify any CRD pipeline code -- this is REST-only.
- Do not add `DetectionSource` values specific to canonicalization -- the function is a preprocessing step that makes properties visible to existing detectors, not a detector itself.

## Acceptance Criteria

1. All 12 test stubs pass (allOf merge, conflict detection, discriminator, readOnly/writeOnly, required merge, empty, nested, oneOf intersection, oneOf+discriminator union, anyOf intersection, circular ref, integration with `extract_schema_fields`).
2. The existing `extract_schema_fields` tests (if any) continue to pass -- the change is backward-compatible.
3. Composed schemas that previously hit the `max_depth=2` limit now extract all nested properties.
4. No infinite loops on circular schemas -- the visited-set protection terminates recursion.

## Implementation Notes (actual)

### Files Modified
- `platform-tools/idi/idi/generation/field_extractor.py` — added `canonicalize_composed_schema()` (~100 LOC), integrated into `extract_schema_fields()` preprocessing

### Files Created
- `platform-tools/idi/tests/generation/rest/test_allof_canonicalization.py` — 18 tests across 7 classes

### Deviations from Plan
1. **Parent-level properties alongside allOf**: Code review found that `unwrap_single_item_combinator` drops parent `properties` when collapsing single-item allOf. Fixed by capturing parent properties before unwrapping and merging them back.
2. **Redundant unwrap call removed**: `extract_schema_fields` no longer calls `unwrap_single_item_combinator` separately since `canonicalize_composed_schema` handles it internally.
3. **Cycle detection uses `id()`** as the plan suggested, rather than `$ref` strings, since specs are pre-resolved by spec_loader.
4. **`_ambiguous` marker** is set but not consumed by downstream code yet — consumption deferred to later sections.
5. **Conftest fixtures** (`composed_schema`, `recursive_schema`) from plan were not added; tests inline their schemas instead.

### Test Results
- 18 new tests passing
- 987 total tests passing (0 regressions)
5. Conflicting properties are marked `_ambiguous` rather than silently using last-wins.