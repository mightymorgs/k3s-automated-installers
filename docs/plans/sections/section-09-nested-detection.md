Now I have all the information needed. Let me generate the section content.

# Section 09: Nested Object Producer Resolution and Enhanced Nested FK Detection

## Overview

This section implements two closely related enhancements to `dep_adapters/body_fk.py`:

1. **Nested Object Producer Resolution (#12)** -- Detect when a request body contains a nested object whose container name corresponds to a known API resource (e.g., `{Subnet: {id: <value>}}` implies an FK to the `subnets` resource).

2. **Enhanced Nested FK Detection (#15)** -- Layer richer detection logic (expanded FK suffixes, credential exclusion, nested object producer patterns) into the existing depth-8 recursive walk, with depth-based confidence adjustment and circular `$ref` cycle detection.

Both changes modify the same file and share the same walk mechanism, so they are implemented together.

**File to modify:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/body_fk.py`

**Test file to create:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_nested_detection.py`

**Dependencies on other sections:**
- **section-01-data-model**: The `DetectionSource` enum must exist in `base.py` with members `NESTED_PRODUCER` and `NESTED_FK`. The `Dependency` dataclass must have the `detection_source` field. If section-01 is not yet implemented, hardcode `detection_source` as a string and update later.
- **section-02-phase-a-preprocessing** (item #6): Schema name normalization via `naming.py` is already available in the existing `normalize()` and `singularize()` functions. No blockers.
- **section-03-phase-a-detection** (item #1): Credential exclusion regex. If not yet implemented, add the credential regex directly in body_fk.py and refactor later. Item #4 (FK suffix expansion) provides `uuid`/`guid` suffix variants -- if not yet available, add them to `_COMMON_FK_SUFFIXES` in `target_inference.py`.
- **section-08-phase-b-adapter-elimination**: This section's index entry says section-09 depends on section-08. Functionally, the nested detection logic is self-contained within body_fk.py. The dependency is structural (Phase C follows Phase B in the overall plan). Implementation can proceed in parallel as long as body_fk.py is not being concurrently modified by section-08.

---

## Tests First

Create the test file at `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_nested_detection.py`. This requires creating the `tests/generation/rest/` directory and its `__init__.py` and `conftest.py` files.

### Directory Setup

Create these files:
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/__init__.py` (empty)
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/conftest.py` (shared fixtures)

### conftest.py Fixtures

The conftest should provide a `known_resources` fixture with a realistic set of resource names for FK matching:

```python
# conftest.py
import pytest

@pytest.fixture
def known_resources():
    """Set of known resource names for FK matching in tests."""
    return {
        "subnets", "secrets", "configmaps", "users", "accounts",
        "certificates", "volumes", "networks", "instances",
        "clusters", "namespaces", "projects", "roles",
    }
```

### Test Stubs: Nested Object Producer Resolution (#12)

```python
# test_nested_detection.py — Section 5.1 tests

class TestNestedObjectProducerResolution:
    """Tests for detecting FKs from container-name-to-resource matching.

    Pattern: body contains {Subnet: {id: <value>}} where 'Subnet' matches
    known resource 'subnets'. The inner 'id' field is resolved as FK.
    """

    def test_subnet_id_resolves_to_subnets(self, known_resources):
        """body with {Subnet: {id: <val>}} + 'subnets' in known_resources -> FK resolved."""

    def test_secret_ref_name_resolves_to_secrets(self, known_resources):
        """body with {secretRef: {name: <val>}} + 'secrets' in known_resources -> FK resolved."""

    def test_configmap_ref_name_resolves_to_configmaps(self, known_resources):
        """body with {configMapRef: {name: <val>}} + 'configmaps' in known_resources -> FK resolved."""

    def test_ambiguous_container_skipped(self, known_resources):
        """Container name matching two resources -> skipped (ambiguity guard)."""

    def test_container_without_id_field_skipped(self, known_resources):
        """Container with no id/name/uuid field -> skipped."""

    def test_container_not_in_known_resources_skipped(self, known_resources):
        """Container name not matching any known resource -> skipped."""

    def test_confidence_0_8_on_single_match(self, known_resources):
        """Single-match resolution emits confidence 0.8."""

    def test_singularize_pluralize_container_name(self, known_resources):
        """Container name is singularized/pluralized for resource matching."""
```

### Test Stubs: Enhanced Nested FK Detection (#15)

```python
# test_nested_detection.py — Section 5.4 tests

class TestEnhancedNestedFKDetection:
    """Tests for depth-based confidence, expanded suffixes, and cycle detection
    layered into the existing body schema walk.
    """

    def test_fk_depth_1_confidence_0_8(self, known_resources):
        """FK at depth 1 -> confidence 0.8."""

    def test_fk_depth_3_confidence_0_75(self, known_resources):
        """FK at depth 3 -> confidence 0.75."""

    def test_expanded_fk_suffix_uuid_at_nested_depth(self, known_resources):
        """Expanded FK suffix (uuid, guid) detected at nested depth."""

    def test_nested_object_producer_at_nested_depth(self, known_resources):
        """Nested object producer pattern detected at nested depth."""

    def test_credential_field_excluded_at_nested_depth(self, known_resources):
        """Credential-matching field excluded at nested depth."""

    def test_circular_ref_visited_set_prevents_loop(self, known_resources):
        """Circular $ref at nested depth -> visited set prevents infinite loop."""

    def test_array_items_walked_for_fk(self, known_resources):
        """Array items walked for FK detection at nested depth."""
```

---

## Implementation Details

### 1. Nested Object Producer Resolution (add to body_fk.py)

Add a new function `_detect_nested_producer()` that checks whether a container field name corresponds to a known resource. This function is called from within `_walk_body()` for every object-typed property.

**Algorithm in `_detect_nested_producer()`:**

1. Accept the container field name, inner properties dict, `known_resources`, and `service`.
2. Check if the inner properties include any of `{"id", "name", "uuid"}` -- the identity fields that signal this nested object refers to an external resource.
3. If no identity field is found, return `None`.
4. Normalize the container name using `naming.normalize()`. Also generate singularized and pluralized forms using `naming.singularize()` and `inflect.engine().plural_noun()`.
5. Check all three forms (normalized, singular, plural) against `known_resources`. Collect all matches.
6. **Ambiguity guard:** If more than one distinct resource matches, return `None`. Only single-match resolution emits an edge. This is the precision-over-recall principle in action.
7. If exactly one match, return a `Dependency` with confidence 0.8, `source="generic_odg:body"`, and `detection_source=DetectionSource.NESTED_PRODUCER` (or the string `"rest:nested_producer"` if the enum is not yet available).

**Signature:**

```python
def _detect_nested_producer(
    container_name: str,
    inner_properties: dict[str, Any],
    known_resources: set[str],
    service: str,
) -> Dependency | None:
    """Resolve a nested object container name to a known resource FK.

    Returns a Dependency if the container name matches exactly one known resource
    and the inner object has an identity field (id, name, uuid). Returns None on
    ambiguity or no match.
    """
```

**Integration into `_walk_body()`:**

Before the existing `infer_target()` call for each property, check if the property is an object type with inner properties. If so, call `_detect_nested_producer()`. If it returns a Dependency, append it to results and continue (do not also run `infer_target()` on the same field -- the nested producer match is more specific and higher confidence).

The check should be:

```python
# In _walk_body(), inside the property loop, before infer_target():
if field_info.get("type") == "object" and "properties" in field_info:
    nested_dep = _detect_nested_producer(
        container_name=field_name,
        inner_properties=field_info["properties"],
        known_resources=known_resources,
        service=service,
    )
    if nested_dep is not None:
        results.append(nested_dep)
        # Still recurse into the nested object for deeper FKs
        _recurse_nested(...)
        continue
```

### 2. Enhanced Nested FK Detection (modify body_fk.py)

This enhancement modifies the existing `_walk_body()` function to add three capabilities at every depth level:

**a) Depth-based confidence adjustment:**

Add a confidence multiplier based on the current recursion depth:
- Depth 0-2: multiplier 1.0 (confidence from `infer_target()` used as-is, producing ~0.8 for good matches)
- Depth 3+: multiplier 0.9375 (reduces effective confidence, e.g., 0.8 * 0.9375 = 0.75)

This is implemented as a simple conditional applied to the confidence returned by `infer_target()`:

```python
# After infer_target() returns (target, confidence):
if depth >= 3:
    confidence *= 0.9375  # Depth penalty: 0.8 -> 0.75
```

The specific multiplier 0.9375 is chosen so that a base confidence of 0.8 (single-resource match) becomes 0.75 at depth 3+, matching the plan's stated values. A base confidence of 0.7 would become ~0.656, which falls below the 0.7 emission floor and would be dropped -- this is correct behavior since low-confidence FKs at deep nesting are likely false positives.

**b) Circular `$ref` cycle detection:**

Add a `visited: set[str]` parameter to `_walk_body()` and `_recurse_nested()` that tracks `$ref` pointers encountered in the current walk path. Before recursing into a `$ref`-resolved schema, check if the ref pointer is already in `visited`. If so, halt recursion for that branch.

The `visited` set must be passed through the call chain:
- `detect_body_deps()` creates the initial empty set
- `_walk_body()` accepts it as a parameter
- `_recurse_nested()` accepts it and passes it to recursive `_walk_body()` calls
- When encountering a `$ref`, add the pointer string to a copy of `visited` before recursing

Since body schemas in the current pipeline are already `$ref`-resolved by `spec_loader.py`, the cycle detection should operate on schema identity. Use `id(schema)` as the visited key (Python object identity) as a practical fallback when `$ref` pointers are not available in the resolved schema:

```python
def _walk_body(
    schema: dict[str, Any],
    known_resources: set[str],
    service: str,
    resource: str,
    response_fields: set[str],
    json_path: list[str],
    depth: int,
    results: list[Dependency],
    visited: set[int] | None = None,  # NEW: tracks schema object ids
) -> None:
    if depth > _MAX_DEPTH or not isinstance(schema, dict):
        return
    if visited is None:
        visited = set()
    schema_id = id(schema)
    if schema_id in visited:
        return  # Circular reference detected
    visited = visited | {schema_id}  # Copy-on-add for branch isolation
    # ... rest of function
```

The copy-on-add pattern (`visited | {schema_id}`) ensures that sibling branches do not see each other's visited sets. Only the current path's ancestors are tracked. This prevents false cycle detection in diamond-shaped schema references.

**c) Credential exclusion at nested depth:**

The credential exclusion regex from section-03 (item #1) should be applied at every depth. If section-03 is not yet implemented, add a minimal credential pattern directly:

```python
_CREDENTIAL_PATTERN = re.compile(
    r"(?:^|_|-)"
    r"(?:client[_-]?secret|access[_-]?token|refresh[_-]?token|"
    r"id[_-]?token|api[_-]?key|password|secret|bearer[_-]?token)"
    r"$",
    re.IGNORECASE,
)
```

Apply this as an early-return guard inside the property loop in `_walk_body()`, before `infer_target()`:

```python
if _CREDENTIAL_PATTERN.search(field_name):
    # Skip credential fields at any depth -- not FKs
    _recurse_nested(...)
    continue
```

If section-03 has already been implemented and the credential regex is available via `target_inference.py`, import and reuse it instead of duplicating.

### 3. Summary of Changes to `_walk_body()` Signature

The existing `_walk_body()` function signature gains one new parameter (`visited`). The existing `_recurse_nested()` also gains the `visited` parameter to pass it through. All callers must be updated:

- `detect_body_deps()` passes `visited=None` (or `visited=set()`) to the initial `_walk_body()` call
- `_walk_body()` passes `visited` to `_recurse_nested()`  
- `_recurse_nested()` passes `visited` to all recursive `_walk_body()` calls (for nested objects, array items, allOf/oneOf/anyOf compositions)

### 4. Constant Additions

Add to the module-level constants:

```python
# Identity fields that signal a nested object refers to an external resource.
_IDENTITY_FIELDS: frozenset[str] = frozenset({"id", "name", "uuid"})

# Depth threshold above which FK confidence is reduced.
_DEEP_NESTING_THRESHOLD = 3

# Confidence multiplier for FKs found at depth >= _DEEP_NESTING_THRESHOLD.
_DEEP_CONFIDENCE_FACTOR = 0.9375  # 0.8 * 0.9375 = 0.75
```

### 5. Import Additions

```python
import re
from idi.generation.dep_adapters.naming import normalize, singularize, _engine
```

The `_engine` import provides access to `inflect.engine().plural_noun()` for pluralization during resource matching in `_detect_nested_producer()`.

---

## Precision Safeguards

All changes must respect the project's precision-over-recall constraint:

1. **Ambiguity guard in nested producer:** If a container name matches more than one resource, do not emit any edge. Ambiguous matches are worse than missing edges.

2. **Confidence floor:** No edge should be emitted with confidence below 0.7. The depth penalty can push low-confidence matches below the floor, which is the intended behavior -- uncertain deep FKs are dropped.

3. **Credential exclusion:** Credential-like fields must never be emitted as FKs, regardless of depth. False FK edges to credential parameters cause phantom dependencies.

4. **Cycle detection:** Infinite recursion on circular schemas would produce duplicate or nonsensical edges. The visited-set mechanism guarantees termination.

---

## Verification Checklist

After implementation, verify:

- [x] `_detect_nested_producer()` returns `None` when container name matches 0 or 2+ resources
- [x] `_detect_nested_producer()` returns a `Dependency` with confidence 0.8 for single-match
- [x] Container name normalization handles camelCase (`secretRef` -> `secret`), snake_case (`config_map_ref` -> `config_map`), and PascalCase (`Subnet` -> `subnet`)
- [x] Depth-based confidence: depth 0-2 FK at base confidence, depth 3+ FK at base * 0.9375 (applies to both infer_target and nested producer results)
- [x] Circular schema references terminate without stack overflow
- [x] Credential-pattern fields are excluded at all depths
- [x] Existing `detect_body_deps()` behavior is preserved for non-nested, non-circular schemas (1139 tests pass)
- [x] All new edges include `detection_source` field (NESTED_PRODUCER or NESTED_FK enum values)
- [x] Test file runs with `cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi && uv run pytest tests/generation/rest/test_nested_detection.py`

---

## Implementation Notes

**Files modified:**
- `idi/generation/dep_adapters/body_fk.py` — added `_detect_nested_producer()`, `visited` set for cycle detection, depth-based confidence penalty, credential exclusion at all depths
- `tests/generation/rest/test_nested_detection.py` — 17 tests (8 producer, 9 enhanced detection)

**Deviations from plan:**
- Depth confidence values: plan stated "depth 0-2 FK at confidence 0.8" but actual max from `infer_target()` is ~0.49 due to multi-factor confidence scoring. Tests verify relative depth penalty (base * 0.9375) rather than absolute values.
- Credential exclusion: reuses existing `_CREDENTIAL_PARAMS` from `target_inference.py` (anchored `^...$` regex) rather than creating a separate looser pattern. The `_has_fk_suffix` guard already exempts FK-suffixed credential fields.
- `field=container_name` in nested producer Dependency (e.g., field='Subnet' not 'Subnet.id'). The FK edge points from the container field; downstream consumers reference the container.

**Code review fixes applied:**
- Added depth penalty to nested producer edges (not just infer_target edges)
- Added missing `test_expanded_fk_suffix_uuid_at_nested_depth` test
- Strengthened ambiguity test and replaced vacuous confidence floor assertion