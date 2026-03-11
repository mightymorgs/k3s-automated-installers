Now I have all the context I need. Let me produce the section content.

# Section 10: Response Walk and Read-Only Field Detection

## Overview

This section implements two closely related enhancements to `dep_adapters/output_detection.py`:

1. **Full Response Schema Tree Walk (#13):** Replace current top-level-only response field extraction with a recursive walk to depth 5. Every leaf field (string, integer, number, boolean) is registered as a potential producer with its JSON path, type, format, and readOnly status.

2. **Read-Only Field Detection via Set Difference (#14):** For specs that do not declare `readOnly` attributes, infer server-generated fields by comparing PUT request schemas vs GET response schemas for the same resource path. Fields present in the response but absent from the request are inferred read-only.

Both changes target the same file and work together: the tree walk discovers nested producers, and the set-difference logic enriches their confidence when inferred as read-only.

**File to modify:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/output_detection.py`

**Test file to create:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_response_walk_readonly.py`

**Precision constraint:** False edges are worse than missing edges. readOnly producers at confidence 0.9, non-readOnly producers at 0.7 (minimum emission threshold), set-difference inferred readOnly at 0.85.

## Dependencies

- **Section 01 (Data Model):** `DetectionSource` enum must exist in `base.py` with members `RESPONSE_WALK` and `READONLY_DIFF`. The `Dependency` dataclass must have `detection_source` and `lineage_type` fields.
- **Section 03 (Phase A Detection):** `readOnly`/`writeOnly` field classification (#2) provides spec-declared readOnly signals at confidence 0.9. Spec-declared readOnly overrides diff-inferred readOnly.
- **Section 06 (Envelope Detector):** The `detect_envelope()` function from `adapters/envelope_detector.py` is used to unwrap envelopes before walking. If this section is implemented before section 06, the envelope unwrapping call should be guarded with a try/import or left as a stub call site.
- **Section 08 (Phase B Adapter Elimination):** Phase B must be complete so the generic pipeline is in place. The producer validity rules (#7 from section 03) define which HTTP methods produce outputs.

## Tests First

Create the test file at `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_response_walk_readonly.py`. Ensure `__init__.py` files exist for `tests/generation/rest/`.

### Shared Fixtures

```python
"""Tests for full response schema tree walk (#13) and read-only set difference (#14)."""
import pytest
from idi.generation.dep_adapters.base import OperationInfo, Output
from idi.generation.dep_adapters.output_detection import (
    walk_response_schema,
    infer_readonly_by_diff,
    detect_outputs,
)

@pytest.fixture
def base_operation():
    """Factory for OperationInfo with configurable response_schema."""
    def _make(method="POST", path="/users", response_schema=None, body_schema=None):
        return OperationInfo(
            service="test-service",
            resource="users",
            operation=f"{method.lower()}_users",
            path=path,
            method=method,
            body_schema=body_schema or {},
            response_schema=response_schema or {},
        )
    return _make
```

### 5.2 Full Response Schema Tree Walk Tests

```python
class TestWalkResponseSchema:
    """Tests for recursive response schema walking to depth 5."""

    # Test: depth-1 response field -> registered as producer
    def test_depth_1_field_registered(self, base_operation): ...

    # Test: depth-3 response field (metadata.labels.app) -> registered as producer
    def test_depth_3_nested_field(self, base_operation): ...

    # Test: depth-5 response field -> registered as producer
    def test_depth_5_field_registered(self, base_operation): ...

    # Test: depth-6 response field -> NOT registered (depth limit)
    def test_depth_6_field_excluded(self, base_operation): ...

    # Test: readOnly nested field -> confidence 0.9
    def test_readonly_nested_field_confidence_09(self, base_operation): ...

    # Test: non-readOnly nested field -> confidence 0.7
    def test_non_readonly_field_confidence_07(self, base_operation): ...

    # Test: recursive schema (User.manager -> User) -> cycle detected, recursion halts
    def test_recursive_schema_cycle_detection(self, base_operation): ...

    # Test: array items with object type -> walked correctly (conditions[].type)
    def test_array_items_walked(self, base_operation): ...

    # Test: envelope unwrapping applied before walking
    def test_envelope_unwrap_before_walk(self, base_operation): ...

    # Test: JSON path format correct for nested fields (e.g., "metadata.uid")
    def test_json_path_format(self, base_operation): ...
```

### 5.3 Read-Only Set Difference Tests

```python
class TestReadOnlySetDifference:
    """Tests for inferring read-only fields via PUT request vs GET response comparison."""

    # Test: PUT request {name, email} vs GET response {id, name, email, created_at}
    #       -> {id, created_at} inferred read-only
    def test_basic_set_difference(self): ...

    # Test: spec with PUT + GET on /users/{id} -> schemas compared correctly
    def test_put_get_pairing(self): ...

    # Test: spec with POST + GET but no PUT -> set-diff NOT applied (POST excluded)
    def test_post_excluded_from_diff(self): ...

    # Test: spec with PATCH + GET but no PUT -> set-diff NOT applied (PATCH excluded)
    def test_patch_excluded_from_diff(self): ...

    # Test: spec-declared readOnly overrides diff-inferred readOnly
    def test_spec_declared_overrides_diff(self): ...

    # Test: confidence 0.85 for diff-inferred read-only fields
    def test_diff_inferred_confidence_085(self): ...

    # Test: operations grouped by resource path template correctly
    def test_grouping_by_path_template(self): ...
```

### Key Test Schemas

The tests need several synthetic schemas. Here are the patterns the implementer must construct:

**Nested response schema (depth 5):**
```python
# Schema structure for depth tests:
# {
#   "type": "object",
#   "properties": {
#     "id": {"type": "string"},                                     # depth 1
#     "metadata": {
#       "type": "object",
#       "properties": {
#         "uid": {"type": "string", "readOnly": True},             # depth 2
#         "labels": {
#           "type": "object",
#           "properties": {
#             "app": {"type": "string"},                            # depth 3
#             "nested": {
#               "type": "object",
#               "properties": {
#                 "deep": {"type": "string"},                       # depth 4
#                 "deeper": {
#                   "type": "object",
#                   "properties": {
#                     "leaf": {"type": "string"},                   # depth 5 (included)
#                     "too_deep": {
#                       "type": "object",
#                       "properties": {
#                         "excluded": {"type": "string"}            # depth 6 (excluded)
#                       }
#                     }
#                   }
#                 }
#               }
#             }
#           }
#         }
#       }
#     }
#   }
# }
```

**Recursive schema (cycle detection):**
```python
# Schema with $ref cycle:
# User has "manager" field pointing back to User
# {
#   "type": "object",
#   "properties": {
#     "id": {"type": "string"},
#     "name": {"type": "string"},
#     "manager": {"$ref": "#/components/schemas/User"}
#   }
# }
# The walk must detect the cycle via visited set and halt that branch.
```

**Array items schema:**
```python
# Schema with array containing objects:
# {
#   "type": "object",
#   "properties": {
#     "conditions": {
#       "type": "array",
#       "items": {
#         "type": "object",
#         "properties": {
#           "type": {"type": "string"},
#           "status": {"type": "string", "readOnly": True}
#         }
#       }
#     }
#   }
# }
# Expected: "conditions[].type" and "conditions[].status" registered
```

**Set-difference paired specs:**
```python
# PUT /users/{id} request body: {name, email, role}
# GET /users/{id} response: {id, name, email, role, created_at, updated_at}
# Inferred read-only: {id, created_at, updated_at}
```

## Implementation Details

### Current State of `output_detection.py`

The existing file at `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/output_detection.py` is ~85 lines. It contains:

- `_ID_FIELD_PRECEDENCE`: list of known ID field names
- `_METHOD_PRIORITY`: maps POST=3, PUT=2, PATCH=1
- `detect_outputs()`: only looks at top-level `response_schema.get("properties", {})` and checks against `_ID_FIELD_PRECEDENCE`
- `_has_resource_id_in_path()`: checks if the path ends with a resource ID parameter

### Changes Required

#### 1. Add `walk_response_schema()` Function

Add a new function that recursively walks the response schema tree to depth 5, registering leaf fields as producers.

**Signature:**
```python
def walk_response_schema(
    schema: dict,
    service: str,
    resource: str,
    *,
    max_depth: int = 5,
    resolve_ref: Callable[[str], dict] | None = None,
) -> list[Output]:
    """Walk response schema tree to depth ``max_depth``, registering leaf fields as producers.

    Leaf fields (string, integer, number, boolean) are registered with their
    full JSON-path (e.g. "metadata.uid"). readOnly fields get confidence 0.9,
    non-readOnly fields get 0.7.

    Cycle detection: maintains a visited set of $ref pointers. If a $ref has
    been seen in the current path lineage, recursion halts for that branch.

    Array items are walked by appending "[]" to the path component
    (e.g. "conditions[].type").
    """
```

**Algorithm:**

1. If the envelope detector is available (imported from section 06), unwrap the response schema before walking. Guard with a try/import so this section works independently.
2. Initialize `visited: set[str]` for $ref cycle detection.
3. Use an internal recursive helper `_walk(schema, path_prefix, depth, visited)`:
   - If `depth > max_depth`, return (depth limit).
   - If schema has `$ref`, check if the ref string is in `visited`. If yes, halt. If no, add to visited, resolve the ref, and recurse with the resolved schema.
   - If schema `type` is a leaf type (`string`, `integer`, `number`, `boolean`), register as an `Output` with the current JSON path.
   - If schema `type` is `object` and has `properties`, iterate each property and recurse with `path_prefix.prop_name` at `depth + 1`.
   - If schema `type` is `array` and has `items` of type `object`, recurse into items with `path_prefix[]` at `depth + 1`.
4. Confidence assignment: check `readOnly: true` on the field schema. If readOnly, confidence maps to priority adjustment (readOnly fields get 0.9 equivalent priority boost). Non-readOnly fields get baseline 0.7.

**JSON path format:** Use dot-separated paths. Array items use `[]` notation. Examples: `"id"`, `"metadata.uid"`, `"conditions[].type"`, `"spec.template.containers[].image"`.

#### 2. Add `infer_readonly_by_diff()` Function

Add a function that compares PUT request schemas vs GET response schemas to infer which fields are server-generated.

**Signature:**
```python
def infer_readonly_by_diff(
    operations: list[OperationInfo],
) -> dict[str, set[str]]:
    """Infer read-only fields by comparing PUT request vs GET response schemas.

    Groups operations by resource path template. For each group that has both
    a PUT and a GET, computes GET_response_fields - PUT_request_fields.
    Fields in the difference set are inferred as server-generated (read-only).

    Only PUT vs GET is used. POST and PATCH are explicitly excluded:
    - POST schemas omit optional fields with server defaults (not read-only)
    - PATCH schemas are entirely optional by design (false positives)

    Returns a dict mapping resource path template to set of inferred read-only
    field names. Confidence for diff-inferred fields is 0.85.
    """
```

**Algorithm:**

1. Group operations by resource path template. The path template is the path with all `{param}` segments preserved (e.g., `/users/{id}` groups GET and PUT together, `/users` is a separate group).
2. For each group, find the PUT operation (request body schema) and GET operation (response schema).
3. If both exist, extract top-level property names from each:
   - `put_fields = set(PUT.body_schema.get("properties", {}).keys())`
   - `get_fields = set(GET.response_schema.get("properties", {}).keys())`
4. Compute `inferred_readonly = get_fields - put_fields`.
5. Return the mapping.

**Integration with walk:** When `detect_outputs()` uses the tree walk, it should check the diff-inferred readonly set. If a field appears in the inferred set, its confidence is boosted to 0.85 (above baseline 0.7 but below spec-declared 0.9). Spec-declared `readOnly: true` always takes precedence at 0.9.

#### 3. Update `detect_outputs()` Function

Modify the existing `detect_outputs()` to use the tree walk instead of the current top-level-only approach.

**Changes:**
- Update `_METHOD_PRIORITY` to include `GET: 1` (section 03 may already do this; if not, add it here). DELETE, HEAD, OPTIONS remain excluded (return empty).
- Replace the current top-level property scan with a call to `walk_response_schema()`.
- Incorporate the inferred readonly set from `infer_readonly_by_diff()` into confidence scoring.
- Set `detection_source` on each output: `DetectionSource.RESPONSE_WALK` for tree-walk-discovered producers, `DetectionSource.READONLY_DIFF` for diff-inferred readonly fields.

**Priority for confidence:**
| Source | Confidence |
|--------|:----------:|
| Spec-declared `readOnly: true` | 0.9 |
| Set-difference inferred read-only | 0.85 |
| Non-readOnly response field | 0.7 |

#### 4. Cycle Detection Implementation

The cycle detection must use a `visited: set[str]` that tracks `$ref` pointer strings encountered in the **current path lineage** (not globally). This means each recursive branch gets its own copy of `visited` (or more efficiently, add before recursing and remove after returning).

This is critical for schemas like:
- `User.manager -> User` (direct cycle)
- `Order.items[].product -> Product.reviews[].author -> User.orders[].items[].product` (transitive cycle)

Without cycle detection, these schemas cause infinite recursion or exponential path explosion.

### File Structure After Changes

The file `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/output_detection.py` should grow from ~85 LOC to approximately ~200-250 LOC. The new functions are:

1. `walk_response_schema()` — public, ~80 LOC (including the recursive helper)
2. `_walk_recursive()` — private helper for the tree walk, called by `walk_response_schema()`
3. `infer_readonly_by_diff()` — public, ~40 LOC
4. `_group_by_path_template()` — private helper that groups operations by their path template
5. Updated `detect_outputs()` — modified to call the tree walk, ~30 LOC (replaces current ~20 LOC)

### Edge Cases to Handle

1. **Empty response schema:** `{}` or no `properties` key. Return empty list.
2. **Schema with only `additionalProperties`:** Treat as opaque, do not walk.
3. **`$ref` that cannot be resolved:** Skip that branch, log a warning.
4. **Multiple array fields at same level:** Walk all of them (each gets `[]` notation).
5. **Null/missing type field:** Use type inference from sibling keys (section 02) if available, otherwise skip.
6. **Field appears at multiple depths:** Register only the shallowest occurrence to avoid duplicate producers for the same logical field.

### Integration With Envelope Detector (Section 06)

The tree walk should call `detect_envelope()` on the response schema before walking. This unwraps patterns like `{data: {actual_resource}}` or `{items: [...], total: N}` so the walk processes the actual resource schema, not the wrapper.

If the envelope detector is not yet implemented (section 06 is a parallel dependency), guard the import:

```python
try:
    from idi.generation.adapters.envelope_detector import detect_envelope
except ImportError:
    detect_envelope = None
```

When `detect_envelope` is available and returns a non-None result, use the unwrapped schema. Otherwise, walk the raw response schema.

### Testing Strategy Summary

- **Unit tests:** Synthetic schemas exercising depth limits, cycle detection, array walking, JSON path formatting, readOnly classification, set-difference logic.
- **False-positive tests:** Ensure depth-6 fields are excluded. Ensure POST/PATCH are not used for set-difference. Ensure recursive schemas terminate.
- **Integration consideration:** After section 13 (Phase C Adapter Slimming), the full pipeline should be tested against benchmark specs to verify the tree walk produces at least as many producers as the current top-level-only approach.

---

## Implementation Notes

**Files modified:**
- `idi/generation/dep_adapters/output_detection.py` — added `walk_response_schema()`, `infer_readonly_by_diff()`, envelope unwrap integration
- `tests/generation/rest/test_response_walk_readonly.py` — 19 tests (12 walk, 7 set-difference)

**Deviations from plan:**
- `detect_outputs()` NOT modified to call `walk_response_schema`. It is called per-operation by the existing pipeline. `walk_response_schema` is a standalone function; full pipeline integration deferred to section 13 (adapter slimming).
- Output dataclass not extended with `confidence` or `detection_source` — uses existing `source` string field and `priority` int to differentiate tiers. Data model changes belong to section 01.
- `resolve_ref` parameter added to `walk_response_schema` signature but not implemented — schemas are already $ref-resolved by `spec_loader.py`. Cycle detection uses `id()` (Python object identity).
- Field-path dedup instead of shallowest-occurrence. Different physical fields sharing a canonical name (e.g., `id` and `metadata.uid` → `#id`) are both registered. Circular-ref duplicates handled by visited-set cycle detection.

**Code review fixes applied:**
- Objects with `properties` but no explicit `type` now walked as objects
- Added `test_spec_declared_overrides_diff`, `test_different_paths_same_canonical`, `test_object_without_explicit_type`