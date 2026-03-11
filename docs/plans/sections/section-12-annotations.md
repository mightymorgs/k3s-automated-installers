Now I have all the context. Let me produce the section content.

# Section 12: Annotation System (`dep_adapters/annotation_deps.py`)

## Overview

This section implements a new dependency adapter that parses user-declared annotations from OpenAPI vendor extensions. It provides an escape hatch for when heuristic FK detection fails: API authors can explicitly declare producer-consumer dependencies or mark fields as external (not FKs) using structured annotations embedded in their OpenAPI spec.

Two annotation formats are supported:

- **`x-idi-annotations`** — our native format, supporting both dependency declarations and field classification overrides
- **`x-restler-annotations`** — RESTler-compatible format for interoperability with the RESTler fuzzing toolchain

Annotations are near-ground-truth: they come from human authors who understand their API. Confidence is set to 0.99 (just below 1.0 which is reserved for OpenAPI `links`). Lineage type is `"explicit"`.

## Dependencies

- **section-01-data-model**: The `DetectionSource` enum must include `ANNOTATION = "rest:annotation"`. The `Dependency` dataclass must have `detection_source` and `lineage_type` fields.
- **section-08-phase-b-adapter-elimination**: This section runs after Phase B; the adapter registry infrastructure must be in place.
- **section-05-links-parser** (soft dependency): The OpenAPI links adapter (`link_deps.py`) is registered at highest priority. Annotations register just below it. If links are not yet implemented, annotations can still be registered at a high priority.

## File Paths

- **New file**: `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/annotation_deps.py`
- **New test file**: `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_annotation_deps.py`
- **Modified file**: `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/conftest.py` (add `spec_with_annotations` fixture)

## Tests (Write First)

Create the test file at `tests/generation/rest/test_annotation_deps.py`. Ensure `tests/generation/rest/__init__.py` exists. These tests validate the full behavior of the annotation adapter.

### Test Stubs

```python
"""Tests for dep_adapters/annotation_deps.py — annotation parsing adapter."""
import pytest

from idi.generation.dep_adapters.base import Dependency, OperationInfo


# --- x-idi-annotations: producer/consumer dependency ---

# Test: x-idi-annotations with producer/consumer declaration emits Dependency
#   at confidence 0.99, lineage_type "explicit", detection_source ANNOTATION.
#   Annotation: {producer_endpoint: "/users", producer_method: "POST",
#                producer_field: "id", consumer_field: "user_id"}

# Test: x-idi-annotations with classification "external" marks field
#   as excluded from FK detection (no Dependency emitted for that field;
#   instead, the adapter returns a classification marker or empty list).

# --- x-restler-annotations: RESTler compatibility ---

# Test: x-restler-annotations format parsed correctly.
#   Annotation: {producer_resource_name: "users", producer_method: "POST",
#                consumer_resource_name: "posts", consumer_method: "POST"}
#   Emits Dependency at confidence 0.99.

# --- Validation: reject invalid annotations ---

# Test: annotation referencing non-existent endpoint (e.g., "/nonexistent")
#   is rejected with a warning. No Dependency emitted.

# Test: annotation referencing non-existent method on a valid endpoint
#   (e.g., DELETE on an endpoint that only has GET/POST) is rejected
#   with a warning. No Dependency emitted.

# --- Edge cases ---

# Test: lineage_type = "explicit" for all annotation-sourced edges.

# Test: spec without any annotation keys -> matches() returns False.

# Test: both x-idi-annotations and x-restler-annotations present in same spec
#   -> both are parsed; dependencies from each are returned.

# Test: empty annotation list (x-idi-annotations: []) -> matches() returns True
#   but detect_dependencies returns empty list.

# Test: malformed annotation entry (missing required keys) -> skipped with
#   warning, does not crash.
```

### Shared Fixture

In `tests/generation/rest/conftest.py`, add:

```python
@pytest.fixture
def spec_with_annotations():
    """OpenAPI 3.0 spec containing both x-idi-annotations and x-restler-annotations."""
    # Minimal valid OAS 3.0 spec with:
    #   paths: /users (GET, POST), /users/{userId}/posts (GET, POST)
    #   x-idi-annotations at top level with producer/consumer and classification entries
    #   x-restler-annotations at top level with RESTler-format entries
    ...
```

## Implementation Details

### File: `dep_adapters/annotation_deps.py`

**Estimated size**: ~200 LOC

This file implements a single class, `AnnotationDepsAdapter`, that conforms to the `DepAdapter` protocol.

### Class: `AnnotationDepsAdapter`

```python
class AnnotationDepsAdapter:
    """Parse x-idi-annotations and x-restler-annotations from OpenAPI specs.

    User escape hatch for when heuristic FK detection fails. Annotations are
    near-ground-truth (confidence 0.99, lineage_type "explicit").

    Priority: just below OpenAPI links adapter.
    """

    name = "annotation_deps"
    priority = 92  # Below OLM (95), above discriminator (90); just below links

    ANNOTATION_KEYS = ["x-idi-annotations", "x-restler-annotations"]

    def matches(self, spec: dict, service_name: str) -> bool: ...
    def detect_dependencies(self, operation: OperationInfo, spec: dict, known_resources: set[str]) -> list[Dependency]: ...
    def detect_outputs(self, operation: OperationInfo, spec: dict) -> list[Output]: ...
```

### Method: `matches`

Returns `True` when either `x-idi-annotations` or `x-restler-annotations` is present as a top-level key in the OpenAPI spec. Does not check whether the annotation list is non-empty -- that is handled by `detect_dependencies` returning an empty list.

```python
def matches(self, spec: dict, service_name: str) -> bool:
    """Return True if the spec contains any recognized annotation keys."""
    return any(key in spec for key in self.ANNOTATION_KEYS)
```

### Method: `detect_dependencies`

Iterates over both annotation keys. For each annotation entry, delegates to the appropriate parser based on the key name. Validates that referenced endpoints and methods exist in the spec before emitting a Dependency.

Key behaviors:

1. **Annotation iteration**: For each key in `ANNOTATION_KEYS`, read `spec.get(key, [])` and iterate.
2. **Format dispatch**: `x-idi-annotations` entries are parsed by `_parse_idi_annotation()`. `x-restler-annotations` entries are parsed by `_parse_restler_annotation()`.
3. **Validation**: Before emitting, call `_validate_endpoint(spec, endpoint, method)` to confirm the referenced path and method exist in `spec["paths"]`. If validation fails, log a warning with the invalid annotation details and skip the entry.
4. **Classification entries**: `x-idi-annotations` entries with a `classification` key (e.g., `"external"`) are not producer-consumer dependencies. They indicate that a field should be excluded from FK detection. These do not emit Dependency objects -- they are informational. The adapter can return them as a separate data structure or log them for downstream use. For the initial implementation, log them as debug info; downstream FK exclusion integration is deferred to section-13.

### Method: `detect_outputs`

Returns an empty list. Annotations declare dependencies (edges), not output facts.

### Internal Method: `_parse_idi_annotation`

Parses our native format. Expected fields in each annotation dict:

| Field | Required | Description |
|-------|----------|-------------|
| `producer_endpoint` | Yes (for deps) | Path template, e.g., `"/users"` |
| `producer_method` | Yes (for deps) | HTTP method, e.g., `"POST"` |
| `producer_field` | Yes (for deps) | Response field name, e.g., `"id"` |
| `consumer_field` | Yes (for deps) | Request field name, e.g., `"user_id"` |
| `field` | Yes (for classification) | Field name to classify |
| `classification` | Yes (for classification) | One of `"external"`, `"credential"`, etc. |

If the entry has `producer_endpoint` + `producer_method` + `producer_field` + `consumer_field`, it is a dependency entry. Build and return a `Dependency` with:

- `field`: the `consumer_field` value
- `target_resource`: extracted from `producer_endpoint` (last path segment, stripped of braces)
- `fact_ref`: constructed as `"facts://{service}/{resource}#{producer_field}"`
- `confidence`: 0.99
- `source`: `"annotation_deps:x-idi-annotations"`
- `lineage_type`: `"explicit"`

If the entry has `field` + `classification`, it is a classification override. Log it and return `None`.

If required keys are missing, log a warning with the malformed entry and return `None`.

### Internal Method: `_parse_restler_annotation`

Parses RESTler-compatible format. Expected fields:

| Field | Required | Description |
|-------|----------|-------------|
| `producer_resource_name` | Yes | Resource name, e.g., `"users"` |
| `producer_method` | Yes | HTTP method, e.g., `"POST"` |
| `consumer_resource_name` | Yes | Consumer resource name |
| `consumer_method` | Yes | Consumer HTTP method |
| `producer_parameter_name` | No | Specific field (defaults to `"id"`) |
| `consumer_parameter_name` | No | Specific field (defaults to inferred from resource) |

Build and return a `Dependency` with:

- `field`: `consumer_parameter_name` or `"{producer_resource_name}_id"` as default
- `target_resource`: `producer_resource_name`
- `confidence`: 0.99
- `source`: `"annotation_deps:x-restler-annotations"`
- `lineage_type`: `"explicit"`

For RESTler format, validation is resource-name based rather than endpoint-path based. Check that `producer_resource_name` appears as a path segment in at least one path in `spec["paths"]`.

### Internal Method: `_validate_endpoint`

```python
def _validate_endpoint(self, spec: dict, endpoint: str, method: str) -> bool:
    """Check that endpoint+method exists in spec paths.

    Returns True if valid, False with logged warning if not.
    """
    ...
```

Checks `spec.get("paths", {}).get(endpoint, {})` for the method (case-insensitive). If the endpoint does not exist, or the method is not defined on that endpoint, return `False` and log a warning: `"Annotation references non-existent %s %s — skipping"`.

### Priority Selection Rationale

The adapter uses `priority = 92`. The existing priority hierarchy is:

| Priority | Adapter |
|----------|---------|
| 95 | OLM (ground-truth from operator author) |
| 92 | **Annotation deps** (this section) |
| 90 | Discriminator |
| 85 | Object pattern |
| 80 | CRD dep |
| 70 | RBAC |
| 50 | Generic ODG |

OpenAPI links (section-05) will register at even higher priority (e.g., 98) when implemented. Annotations at 92 sit just below OLM and just above discriminator, reflecting their near-ground-truth status. In the REST pipeline context (where OLM/CRD adapters do not match), annotations will effectively be the highest-priority adapter after links.

### Scope Decisions

- **Spec-level only**: Annotations are read from the top level of the OpenAPI document. Operation-level annotations (`x-idi-annotations` nested inside individual path operations) are not supported in this initial implementation. The spec-level format can express per-operation overrides via `producer_endpoint` + `producer_method` targeting.
- **No external file support**: RESTler supports loading annotations from a separate JSON file. This is deferred -- our format embeds annotations directly in the OpenAPI spec via vendor extensions.
- **No `except` clause support**: RESTler annotations support `except` clauses to exclude specific consumers. This is deferred for simplicity.
- **Classification entries are logged, not acted on**: The `"external"` classification tells downstream FK detectors to skip a field. Wiring that into the FK detection pipeline requires coordination with target_inference.py, which is handled in section-13 (Phase C adapter slimming). For now, the adapter parses and logs classification entries.

### Auto-Discovery

The adapter file name `annotation_deps.py` is not in the registry's `skip` set (which skips `__init__`, `base`, `registry`, `merge`, `yaml_adapter`, `body_fk`, `path_deps`, `target_inference`, `output_detection`). The `DepAdapterRegistry._discover_python()` method will auto-discover the `AnnotationDepsAdapter` class because it has `name`, `priority`, `matches`, `detect_dependencies`, and `detect_outputs` attributes. No changes to the registry or `__init__.py` are needed.

### Protocol Compliance

The class must match the `DepAdapter` protocol exactly:

```python
@runtime_checkable
class DepAdapter(Protocol):
    name: str
    priority: int

    def matches(self, spec: dict, service_name: str) -> bool: ...
    def detect_dependencies(self, operation: OperationInfo, spec: dict, known_resources: set[str]) -> list[Dependency]: ...
    def detect_outputs(self, operation: OperationInfo, spec: dict) -> list[Output]: ...
```

Note the `matches` signature includes `service_name: str`. The spec-level pseudocode in the design doc shows `matches(self, spec: dict)` without `service_name` -- the actual implementation must include it to satisfy the protocol. The `service_name` parameter is unused by this adapter (annotations are service-agnostic) but must be accepted.

Similarly, `detect_dependencies` receives `operation: OperationInfo` and `known_resources: set[str]` per the protocol. The adapter reads annotations from the spec (not from individual operations), so it should cache parsed annotations and filter or return all of them on each call. A practical approach: parse annotations lazily on first call (or in `matches`), cache the result, and return the full list from `detect_dependencies`. Since the registry calls `detect_dependencies` once per operation, and annotations are spec-global, returning the full annotation set each time is acceptable -- the merge layer in the registry handles deduplication.

### Error Handling

- Malformed annotation entries (missing required keys, wrong types) are logged as warnings and skipped. The adapter never raises exceptions.
- Invalid endpoint/method references are logged as warnings and the annotation is skipped.
- If `spec.get("paths")` is `None` or not a dict, all endpoint validations fail gracefully.

## Verification Checklist

After implementation, verify:

1. `AnnotationDepsAdapter` is auto-discovered by `DepAdapterRegistry` (no manual registration needed)
2. `matches()` returns `True` for specs with `x-idi-annotations`, `x-restler-annotations`, or both
3. `matches()` returns `False` for specs with neither key
4. Dependencies are emitted at confidence 0.99 with `lineage_type = "explicit"`
5. Invalid annotations (bad endpoint, bad method) produce warnings but no Dependencies
6. Both annotation formats parse correctly and produce equivalent Dependency objects
7. All 8 test cases from the TDD plan pass
8. The adapter does not appear in the registry skip set and is discovered automatically

---

## Implementation Notes

**Implemented:** All items complete. Deviations from plan:

1. **Lazy caching added** per code review — `id(spec)` keyed cache prevents re-parsing annotations on every per-operation call.
2. **RESTler fact_ref added** — plan didn't specify, but asymmetry with IDI format was flagged. Uses `facts://_/{resource}#id`.
3. **Path segment matching** instead of substring — `producer in path.strip("/").split("/")` prevents 'us' matching '/users'.
4. **isinstance guard** on annotation entries — non-dict entries logged and skipped instead of crashing.
5. **conftest.py fixture skipped** — plan called for shared fixture, but local fixtures in test file are sufficient.

**Tests:** 14 tests in `tests/generation/rest/test_annotation_deps.py`, all passing.

**Files created:** `dep_adapters/annotation_deps.py` (~170 LOC), `tests/generation/rest/test_annotation_deps.py` (~220 LOC)