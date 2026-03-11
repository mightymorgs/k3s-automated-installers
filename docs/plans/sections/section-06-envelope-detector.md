Now I have everything I need. Let me compose the section.

# Section 06: Envelope Detector

## Overview

This section implements a **generic response envelope detector** in a new file `adapters/envelope_detector.py`. The detector identifies and unwraps 4 common response wrapper patterns, replacing the per-vendor `extract_response_schema()` methods that currently exist in `cloudflare.py`, `vault.py`, and `github_openapi.py`. This is the key enabler for adapter elimination in section-08 -- once generic envelope detection works, vendor adapters that only do envelope unwrapping become redundant.

**New file:** `platform-tools/idi/idi/generation/adapters/envelope_detector.py`
**Modified file:** `platform-tools/idi/idi/generation/field_extractor.py` (integration point)
**Test file:** `platform-tools/idi/tests/generation/rest/test_envelope_detector.py`

### Dependencies

- **section-04-phase-a-integration** must be complete (this section executes after Phase A integration)
- **section-01-data-model** provides the `DetectionSource.ENVELOPE_UNWRAP` enum member used for traceability

### What Blocks on This Section

- **section-08-phase-b-adapter-elimination** depends on this section to delete/slim vendor-specific adapters

---

## Tests

All tests go in `platform-tools/idi/tests/generation/rest/test_envelope_detector.py`. The test file also requires a `conftest.py` in the same directory (see Shared Fixtures below).

### Test Stubs

```python
"""Tests for generic response envelope detection.

Tests the 4 envelope patterns: HAL _embedded, pagination, single-field wrapper,
and externally tagged. Each pattern has positive and negative test cases.
Confidence threshold behavior (>= 0.8 to act) is verified.
"""
import pytest

from idi.generation.adapters.envelope_detector import detect_envelope, EnvelopeResult


# --- HAL _embedded pattern ---

# Test: HAL _embedded with single resource -> unwrap path "_embedded.users", confidence 0.95
def test_hal_embedded_single_resource():
    """Response with _embedded.users array unwraps to '_embedded.users' at 0.95."""

# --- Pagination wrapper pattern ---

# Test: pagination {items: [...], total: 5, page: 1} -> unwrap "items", confidence 0.9
def test_pagination_items_with_metadata():
    """Standard pagination with items array + total/page metadata."""

# Test: pagination {items: [...], errors: [...], total: 5} -> unwrap "items" (multi-array OK)
def test_pagination_multiple_arrays():
    """Multiple arrays present; only the data-named array is selected."""

# Test: pagination {data: [...], results: [...], count: 5} -> unwrap "data" (first match)
def test_pagination_first_data_match():
    """When multiple data-named arrays exist, first match wins."""

# --- Single-field wrapper pattern ---

# Test: single-field {data: {properties...}} with errors sibling -> unwrap "data", confidence 0.9
def test_single_field_with_metadata_sibling():
    """Single data field with metadata sibling gets 0.9 confidence."""

# Test: single-field {data: {properties...}} WITHOUT metadata siblings -> confidence 0.7 (not acted on)
def test_single_field_without_metadata_sibling():
    """Single data field without metadata gets 0.7 — below action threshold."""

# Test: single-field {data: [1,2,3]} (primitive array) -> NOT unwrapped (type guard)
def test_single_field_primitive_array_not_unwrapped():
    """Primitive arrays are never envelopes. Type guard prevents unwrapping."""

# Test: single-field {data: "string"} (primitive) -> NOT unwrapped (type guard)
def test_single_field_primitive_not_unwrapped():
    """Primitive values are never envelopes. Type guard prevents unwrapping."""

# --- Externally tagged pattern ---

# Test: externally tagged {users: [...]} on path /users -> unwrap "users", confidence 0.95
def test_externally_tagged_matches_path():
    """Property name matching last path segment unwraps at 0.95."""

# --- Negative / threshold tests ---

# Test: no envelope pattern matched -> returns None
def test_no_pattern_matched():
    """Schema with no envelope characteristics returns None."""

# Test: confidence < 0.8 -> logged but not acted on
def test_below_threshold_not_acted_on():
    """Results below 0.8 confidence are returned but caller must not unwrap."""

# Test: confidence >= 0.8 -> unwrap applied
def test_above_threshold_acted_on():
    """Results at or above 0.8 confidence are valid for unwrapping."""
```

### Shared Fixtures (conftest.py)

The `conftest.py` at `platform-tools/idi/tests/generation/rest/conftest.py` should include:

```python
"""Shared fixtures for REST pipeline tests."""
import pytest


@pytest.fixture
def spec_with_envelopes():
    """OAS 3.0 spec with all 4 envelope patterns across different paths.

    Includes:
    - /hal-resources: HAL _embedded pattern
    - /paginated-items: Pagination wrapper pattern
    - /wrapped-data: Single-field wrapper pattern
    - /users: Externally tagged pattern
    """
    # Build a synthetic spec with one path per pattern
    ...
```

---

## Implementation Details

### Data Model: `EnvelopeResult`

Create a dataclass to represent the detection result:

```python
@dataclass
class EnvelopeResult:
    unwrap_path: str      # Dot-separated path to actual data (e.g., "_embedded.users")
    pattern: str          # One of: 'hal_embedded', 'pagination', 'single_field', 'externally_tagged'
    confidence: float     # Pattern-specific confidence score (0.7 - 0.95)
```

### Public API: `detect_envelope()`

The module exposes a single public function:

```python
def detect_envelope(
    response_schema: dict[str, Any],
    path: str | None = None,
) -> EnvelopeResult | None:
    """Detect response envelope pattern and return unwrap instructions.

    Checks 4 patterns in priority order: HAL _embedded, pagination wrapper,
    single-field wrapper, externally tagged. Returns the first match, or
    None if no pattern is detected.

    Args:
        response_schema: The response schema dict with 'properties' at top level.
        path: The API path (needed for externally-tagged pattern matching).

    Returns:
        EnvelopeResult with unwrap_path, pattern name, and confidence score,
        or None if no envelope pattern is detected.
    """
```

### The 4 Patterns (checked in priority order)

Each pattern is implemented as a private function called by `detect_envelope()`. The first match wins.

#### Pattern 1: HAL `_embedded` (confidence 0.95)

Detect responses following the HAL (Hypertext Application Language) convention. The response has a `_embedded` property containing a single sub-property that is the actual resource array. Common in Spring Data REST APIs.

**Detection logic:**
1. Check if `properties` contains a key `_embedded`
2. The `_embedded` value must be an object-typed schema with its own `properties`
3. The `_embedded` object should contain exactly one sub-property (the resource array)
4. Return unwrap path `_embedded.{resourceName}`

**Confidence:** 0.95 -- the `_embedded` key is a very strong HAL signal.

#### Pattern 2: Pagination Wrapper (confidence 0.9)

Detect responses that wrap a resource list in a pagination envelope. The response has an array-typed property whose name matches a data-naming convention, plus sibling properties matching pagination indicators.

**Detection logic:**
1. Scan `properties` for array-typed properties whose name is in `{"items", "data", "results", "records", "entries"}` OR matches the resource name extracted from the path
2. Check for at least one sibling property matching pagination indicators: `{"count", "total", "total_count", "page", "per_page", "offset", "limit", "cursor", "has_more", "has_next", "next", "previous", "prev", "links", "meta", "result_info", "page_info", "pagination"}`
3. Do NOT require exactly one array property -- responses commonly have `{items: [...], errors: [...]}`. Only require exactly one array matching the "data naming" pattern
4. Return unwrap path `{arrayFieldName}`

**Confidence:** 0.9

#### Pattern 3: Single-Field Wrapper (confidence 0.9 or 0.7)

Detect responses where the actual data is wrapped in a single named field with optional metadata siblings.

**Detection logic:**
1. Check if exactly one property has a name in `{"data", "result", "response", "payload", "body", "content"}`
2. **Type guard (critical):** Only unwrap if the inner schema is an Object (`type: "object"` with `properties`) or an Array of Objects (`type: "array"` with `items.type: "object"` or `items.properties`). Primitives and arrays of primitives must NEVER be unwrapped. For example, `GET /metrics/{id}/data` returning `{data: [1,2,3]}` is not an envelope -- `data` IS the resource.
3. Check for metadata siblings: properties named `errors`, `success`, `message`, `meta`, `status`, `code`, `messages`, `result_info`, `error`
4. If at least one metadata sibling exists: confidence 0.9
5. If no metadata siblings: confidence 0.7 (below the 0.8 action threshold -- logged but not acted on unless confirmed by annotation)
6. Return unwrap path `{wrapperFieldName}`

**Why the type guard matters:** Without it, `GET /metrics/{id}/data` returning `{data: [1, 2, 3]}` (time series values) would incorrectly be unwrapped. The primitive array IS the response, not an envelope around it.

#### Pattern 4: Externally Tagged (confidence 0.95)

Detect responses where the entire response is wrapped in a single property whose name matches the last path segment.

**Detection logic:**
1. Extract the last non-parameter path segment from the API path (case-insensitive)
2. Check if the response schema has exactly one property
3. Check if that property's name matches the path segment (case-insensitive comparison)
4. The inner schema must be an Object or Array (same type guard as Pattern 3)
5. Return unwrap path `{tagFieldName}`

**Confidence:** 0.95 -- the path-name match is a very strong signal.

### Confidence Threshold Rule

The caller (in `field_extractor.py`) must only unwrap when `confidence >= 0.8`. Results at 0.7 are returned for diagnostic logging but must not trigger schema navigation. This threshold rule is enforced by the caller, not within `detect_envelope()` itself -- the function always returns the best match regardless of confidence.

### Integration into `field_extractor.py`

Modify `extract_response_fields()` in `platform-tools/idi/idi/generation/field_extractor.py` to call the envelope detector as a fallback when no vendor-specific adapter provides `extract_response_schema()`.

The current flow in `extract_response_fields()` is:
1. Try adapter-based extraction via `ctx.adapter.extract_response_schema()`
2. Fall back to direct schema property extraction

The new flow adds a step between 1 and 2:
1. Try adapter-based extraction via `ctx.adapter.extract_response_schema()`
2. **NEW:** If no adapter schema, try `detect_envelope(response_schema, path)`. If result has `confidence >= 0.8`, navigate into the response schema using `unwrap_path` before field extraction.
3. Fall back to direct schema property extraction (unchanged)

The navigation logic follows the dot-separated `unwrap_path`: for a path like `_embedded.users`, navigate `response_schema["properties"]["_embedded"]["properties"]["users"]` to reach the inner schema.

```python
def _navigate_unwrap_path(schema: dict, unwrap_path: str) -> dict | None:
    """Navigate into a schema following a dot-separated unwrap path.

    Args:
        schema: Response schema with 'properties'.
        unwrap_path: Dot-separated path like '_embedded.users'.

    Returns:
        The inner schema at the unwrap path, or None if navigation fails.
    """
```

### File Structure

The new file `platform-tools/idi/idi/generation/adapters/envelope_detector.py` should contain:

1. Module docstring explaining the 4 patterns and their confidence scores
2. `EnvelopeResult` dataclass
3. Constants: `DATA_FIELD_NAMES`, `PAGINATION_INDICATORS`, `WRAPPER_FIELD_NAMES`, `METADATA_FIELD_NAMES`
4. `detect_envelope()` public function
5. `_detect_hal_embedded()` private function
6. `_detect_pagination()` private function
7. `_detect_single_field()` private function
8. `_detect_externally_tagged()` private function
9. `_is_object_or_object_array()` type guard helper

### Constants

```python
# Array property names that indicate the "data" portion of a pagination envelope
DATA_FIELD_NAMES = frozenset({"items", "data", "results", "records", "entries"})

# Sibling property names that indicate pagination metadata
PAGINATION_INDICATORS = frozenset({
    "count", "total", "total_count", "page", "per_page", "offset", "limit",
    "cursor", "has_more", "has_next", "next", "previous", "prev",
    "links", "meta", "result_info", "page_info", "pagination",
})

# Property names that indicate a single-field wrapper
WRAPPER_FIELD_NAMES = frozenset({"data", "result", "response", "payload", "body", "content"})

# Sibling property names that indicate metadata alongside a wrapper field
METADATA_FIELD_NAMES = frozenset({
    "errors", "success", "message", "meta", "status", "code",
    "messages", "result_info", "error",
})
```

### Relationship to Existing Adapters

This module does NOT replace any existing adapters yet. It provides the generic capability that section-08 (Phase B Adapter Elimination) will use to justify deleting `swagger2.py` and slimming `cloudflare.py` and `github_openapi.py`. The integration into `field_extractor.py` runs as a fallback that coexists with existing adapter-based extraction.

Specifically, the Cloudflare adapter's `_find_result_in_schema()` method (which searches for the `result` property through allOf compositions) will be replaced by Pattern 3 (single-field wrapper detecting `result` with `success`/`errors`/`messages` metadata siblings at confidence 0.9). The Vault adapter's backend-specific response path navigation is more complex and will require Pattern 3 plus additional handling in section-13.

### Estimated Size

Approximately 120-150 LOC for `envelope_detector.py`, plus ~20 LOC of modifications to `field_extractor.py`.

---

## Implementation Notes (actual)

### Files created/modified
- `platform-tools/idi/idi/generation/adapters/envelope_detector.py` (~185 LOC)
- `platform-tools/idi/tests/generation/rest/test_envelope_detector.py` (~240 LOC)
- `platform-tools/idi/idi/generation/field_extractor.py` (added envelope fallback integration)

### Test results
- **21 tests pass** (2 HAL, 3 pagination, 4 single-field, 3 externally tagged, 5 negative/threshold, 4 navigate_unwrap_path)
- **969 total tests pass** (full suite, 0 regressions)

### Code review fixes applied
- Pagination type guard: prevents primitive array unwrapping
- Single-field "exactly one" guard: enforces plan precision requirement
- HAL implicit object type: allows `_embedded` without explicit `type: "object"`
- Path-based resource name matching in pagination detector
- `navigate_unwrap_path` tests added (4 tests)
- Strengthened weak test assertions (confidence value checks instead of tautologies)
- Top-level import in field_extractor.py

### Deviations from plan
- Plan estimated 12 tests; implementation has 21 for more thorough coverage
- `DATA_FIELD_NAMES_ORDERED` tuple added alongside frozenset for deterministic matching
- `navigate_unwrap_path` is public (needed by field_extractor.py import)
- `DetectionSource.ENVELOPE_UNWRAP` not used — detector is a navigation tool, not dependency emitter