Now I have all the context I need. Let me generate the section content.

# Section 02: Phase A Preprocessing

## Overview

This section covers four independent schema preprocessing improvements that enhance the REST pipeline's ability to extract fields and parameters from OpenAPI/Swagger specs. All four changes are preprocessing steps -- they run before detection and do not alter the detection algorithm itself.

**Depends on:** section-01-data-model (DetectionSource enum must exist)
**Blocks:** section-04-phase-a-integration (regression tests)
**Parallelizable with:** section-03-phase-a-detection

### Items Covered

| Item | Description | File |
|------|-------------|------|
| #3 | Single-item combinator unwrapping | `field_extractor.py` |
| #5 | Type inference from sibling keys | `field_extractor.py` |
| #6 | Schema name normalization | `spec_loader.py` |
| #9 | RFC 6570 URI template parser | `path_extractor.py` |

All paths below are relative to `platform-tools/idi/idi/generation/`.

---

## Tests First

Create the test directory and files. All tests go in `platform-tools/idi/tests/generation/rest/`.

### File: `tests/generation/rest/__init__.py`

Empty file to make this a Python package.

### File: `tests/generation/rest/conftest.py`

Shared fixtures used across all Phase A preprocessing tests. This file is also used by section-03, so both sections may contribute to it. If section-03 has already created it, add fixtures rather than overwriting.

```python
"""Shared fixtures for REST pipeline tests."""
import pytest
from typing import Any, Dict


@pytest.fixture
def minimal_openapi_spec() -> Dict[str, Any]:
    """A valid OAS 3.0 spec with 2 operations for basic pipeline tests."""
    # Provide a minimal but complete OAS 3.0 spec with paths, components,
    # and info blocks. Include at least a POST and a GET on the same resource.
    ...


@pytest.fixture
def swagger2_spec() -> Dict[str, Any]:
    """A valid Swagger 2.0 spec for backward-compatibility tests."""
    ...
```

### File: `tests/generation/rest/test_combinator_unwrap.py`

Tests for item #3 -- single-item combinator unwrapping.

```python
"""Tests for single-item combinator unwrapping (#3).

The function under test is `unwrap_single_item_combinator()` added to
field_extractor.py. It collapses allOf/oneOf/anyOf wrappers that contain
exactly one schema into just that schema, recursively.
"""

# Test: allOf with single $ref -> unwrapped to ref'd schema
# Test: oneOf with single schema -> unwrapped
# Test: anyOf with single schema -> unwrapped
# Test: allOf with 2+ items -> NOT unwrapped (returned as-is)
# Test: nested single-item (allOf: [oneOf: [schema]]) -> recursively unwrapped
# Test: parent metadata (description, title) preserved after unwrapping
# Test: non-combinator schema -> returned unchanged
```

Each test should construct a synthetic schema dict and call the unwrap function directly, then assert on the output structure. The key behaviors to validate:

- A single-element `allOf`, `oneOf`, or `anyOf` list collapses to its sole child.
- Multi-element lists are returned unchanged.
- Nested trivial wrappers (e.g., `allOf: [oneOf: [schema]]`) are recursively unwrapped in one call.
- Parent-level metadata keys (`description`, `title`) from the wrapper are preserved and merged into the unwrapped schema (wrapper metadata takes precedence only if the child lacks those keys).
- A schema with no combinator keywords passes through unchanged.

### File: `tests/generation/rest/test_type_inference.py`

Tests for item #5 -- type inference from sibling keys.

```python
"""Tests for type inference from sibling keys (#5).

The function under test is `infer_schema_type()` added to field_extractor.py.
It fills in a missing 'type' field based on sibling properties in the schema.
"""

# Test: schema with "properties" but no "type" -> inferred as "object"
# Test: schema with "items" but no "type" -> inferred as "array"
# Test: schema with "enum" of strings but no "type" -> inferred as "string"
# Test: schema with "enum" of integers -> inferred as "integer"
# Test: schema with explicit "type" -> unchanged (no inference needed)
# Test: schema with no type-inferring siblings -> left as-is
```

Each test constructs a minimal schema dict, calls the inference function, and asserts the `type` field is correctly set or left alone. The enum type inference should inspect the first element of the enum list to determine the type (string, integer, number, boolean).

### File: `tests/generation/rest/test_schema_name_normalization.py`

Tests for item #6 -- schema name normalization.

```python
"""Tests for schema name normalization (#6).

The function under test is `normalize_schema_name()` added to spec_loader.py.
It strips common suffixes/prefixes from schema names for resource matching.
"""

# Test: "UserResponse" -> "User"
# Test: "UserDTO" -> "User"
# Test: "CreateUser" -> "User" (prefix stripping)
# Test: "UserModel" -> "User"
# Test: "User" -> "User" (no suffix to strip)
# Test: "Model" -> "Model" (guard: result would be empty, keep original)
# Test: "DTO" -> "DTO" (guard: result <= 2 chars, keep original)
# Test: "UserResponseDTO" -> strips first matching suffix only
```

The suffix list to strip (checked in order, first match wins): `Response`, `Output`, `Input`, `Request`, `DTO`, `Dto`, `Model`, `Schema`, `Resource`.

The prefix list to strip (checked in order, first match wins): `Create`, `Update`, `Patch`.

Guard conditions:
- If stripping would leave an empty string, keep the original name.
- If stripping would leave a name of 2 or fewer characters, keep the original name.
- Only strip one suffix OR one prefix per call (not both). Suffix stripping is attempted first; if no suffix matched, prefix stripping is attempted.

### File: `tests/generation/rest/test_rfc6570_parser.py`

Tests for item #9 -- RFC 6570 URI template parser.

```python
"""Tests for RFC 6570 URI template parser (#9).

The function under test is `extract_template_params()` in path_extractor.py,
which is extended to handle RFC 6570 operators beyond simple {param}.
"""

# Test: "{param}" -> simple path parameter
# Test: "{+param}" -> reserved expansion, classified as path
# Test: "{#param}" -> fragment
# Test: "{/param}" -> path segment
# Test: "{;param}" -> semicolon expansion
# Test: "{?param,other}" -> two query parameters extracted
# Test: "{&param}" -> query continuation
# Test: query params from RFC 6570 -> marked as optional by default
# Test: query param also in parameters list with required: true -> promoted to required
# Test: mixed template "{/id}{?filter,sort}" -> 1 path + 2 query params
```

The parser should return a list of parameter dicts, each with at least `name`, `location` (`"path"` or `"query"`), and `required` (bool). The RFC 6570 operator determines location:

| Operator | RFC 6570 Name | Location | Required |
|----------|--------------|----------|----------|
| (none) | Simple | path | True |
| `+` | Reserved | path | True |
| `#` | Fragment | path | False |
| `/` | Path Segment | path | True |
| `;` | Semicolon | path | False |
| `?` | Query | query | False |
| `&` | Query Continuation | query | False |
| `.` | Label | path | False |

Query parameters from RFC 6570 templates (`{?filter,sort}`) are marked optional by default. They should only be promoted to required if the parameter also appears in the operation's `parameters` list with `required: true`.

---

## Implementation Details

### Item #3: Single-Item Combinator Unwrapping

**File to modify:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/field_extractor.py`

**What to add:** A new function `unwrap_single_item_combinator(schema: Dict[str, Any]) -> Dict[str, Any]` that:

1. Checks if the schema has exactly one of `allOf`, `oneOf`, or `anyOf` containing a single-element list.
2. If so, extracts the single child schema.
3. Merges any parent-level metadata (`description`, `title`, `nullable`, `deprecated`, `readOnly`, `writeOnly`) into the child (child values take precedence if both exist).
4. Recursively calls itself on the result to handle nested trivial wrapping (e.g., `allOf: [oneOf: [schema]]`).
5. Returns the unwrapped schema, or the original schema unchanged if no single-item combinator is found.

**Integration point:** Call `unwrap_single_item_combinator(schema)` at the top of `extract_schema_fields()`, before the existing `allOf` handling and property extraction. This is a pure preprocessing step that reduces an unnecessary indirection layer. The current `extract_schema_fields()` function (lines 30-94 in the existing file) should call the unwrap function on the incoming `schema` argument before proceeding.

**Current code context:** The existing `extract_schema_fields()` at line 54 checks `if not schema or max_depth <= 0`. The unwrap call should go between that guard and the `result` dict construction at line 57. This ensures the schema is simplified before any field extraction begins.

The function signature:

```python
def unwrap_single_item_combinator(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse single-item allOf/oneOf/anyOf to the inner schema.

    Recursively unwraps trivial combinator wrappers. Parent metadata
    (description, title) is preserved if the child lacks those keys.

    Args:
        schema: The schema dict to potentially unwrap.

    Returns:
        The unwrapped schema, or the original if no single-item combinator.
    """
```

### Item #5: Type Inference from Sibling Keys

**File to modify:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/field_extractor.py`

**What to add:** A new function `infer_schema_type(schema: Dict[str, Any]) -> Dict[str, Any]` that fills in a missing `type` field based on sibling properties:

- If `"properties"` key exists and no `"type"` key exists, set `type` to `"object"`.
- If `"items"` key exists and no `"type"` key exists, set `type` to `"array"`.
- If `"enum"` key exists and no `"type"` key exists, inspect the first element of the enum list:
  - `str` instance -> `"string"`
  - `int` instance -> `"integer"`
  - `float` instance -> `"number"`
  - `bool` instance -> `"boolean"` (check before `int` since `bool` is a subclass of `int` in Python)
- If `"type"` already exists, return unchanged.
- If no type-inferring sibling is found, return unchanged.

**Integration point:** Call `infer_schema_type(schema)` at the top of `extract_schema_fields()`, after the combinator unwrap (#3) but before field extraction. Also apply it inside the property loop (lines 72-93) to each `prop_schema` before type extraction. This ensures nested schemas without explicit types are handled correctly.

The function should mutate a copy, not the original:

```python
def infer_schema_type(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Infer missing 'type' from sibling schema keys.

    If a schema has 'properties' but no 'type', it is inferred as 'object'.
    If it has 'items' but no 'type', inferred as 'array'.
    If it has 'enum' but no 'type', inferred from the enum values' types.

    Args:
        schema: The schema dict to inspect.

    Returns:
        The schema dict with 'type' filled in if inference succeeded,
        or unchanged if type was already present or no inference possible.
    """
```

**Note on `$ref` resolution memoization:** The plan mentions adding a memoization cache as a prerequisite for type inference. This cache should be added to the `_resolve_refs` function in `spec_loader.py`. The cache is keyed by `$ref` path string, and stores the resolved schema dict. This prevents O(N^2) behavior on large specs with many shared `$ref` targets. Implementation: add a `memo: Optional[Dict[str, Any]] = None` parameter to `_resolve_refs()`. When a `$ref` is encountered and its path is in `memo`, return the cached result directly. Otherwise, resolve and store in `memo`. Pass the same `memo` dict through all recursive calls. The cache should be initialized once per `load_spec()` call (in the `resolved` section loop at line 155-158 of `spec_loader.py`).

### Item #6: Schema Name Normalization

**File to modify:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/spec_loader.py`

**What to add:** A new function `normalize_schema_name(name: str) -> str` that strips common suffixes and prefixes from schema names used in `$ref` paths.

**Suffix list** (checked in order, first match wins):
`"Response"`, `"Output"`, `"Input"`, `"Request"`, `"DTO"`, `"Dto"`, `"Model"`, `"Schema"`, `"Resource"`

**Prefix list** (checked in order, if no suffix matched):
`"Create"`, `"Update"`, `"Patch"`

**Guards:**
- If stripping would result in an empty string, keep original.
- If stripping would result in a name with 2 or fewer characters, keep original.
- Apply suffix stripping first. Only try prefix stripping if no suffix was stripped.

**Integration point:** This function is called during `$ref` resolution in `extract_schema_fields()` (in `field_extractor.py`), not in `spec_loader.py` itself. However, the function lives in `spec_loader.py` because it operates on schema name strings extracted from `$ref` paths like `#/components/schemas/UserResponse`. The normalized name is used only for resource matching downstream -- the original `$ref` path is preserved for schema lookup.

The function signature:

```python
def normalize_schema_name(name: str) -> str:
    """Strip common suffixes/prefixes from a schema name for resource matching.

    Attempts suffix stripping first (Response, DTO, Model, etc.), then
    prefix stripping (Create, Update, Patch) if no suffix matched.

    Guards against producing empty or very short names (<=2 chars).

    Args:
        name: Raw schema name from a $ref path.

    Returns:
        Normalized name suitable for resource matching.
    """
```

### Item #9: RFC 6570 URI Template Parser

**File to modify:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/path_extractor.py`

**What to change:** The current path template parsing in `path_extractor.py` handles only simple `{param}` templates. Extend or replace `extract_template_params()` (or the equivalent template-matching regex) to support all RFC 6570 operators.

**Current state:** The existing code at line 51 uses a simple regex pattern to find `{param}` segments:
```python
resource_parts = [p for p in parts if not p.startswith("{")]
```
and at line 307:
```python
namespaced = "{namespace}" in path or "namespaces" in parts
```

The template parsing is currently implicit -- path segments starting with `{` are treated as parameters. There is no explicit `extract_template_params()` function yet. The implementation should add one.

**New function:** `parse_rfc6570_template(template: str) -> List[Dict[str, Any]]`

This function parses an RFC 6570 URI template string and returns a list of parameter dicts. The regex pattern to match RFC 6570 expressions:

```
\{([+#./;?&]?)([^}]+)\}
```

Group 1 captures the optional operator character. Group 2 captures the variable list (comma-separated parameter names, each optionally followed by `:maxlen` or `*` modifier).

For each match:
1. Extract the operator (empty string for simple expansion).
2. Split the variable list on commas.
3. For each variable name, strip any `:maxlen` suffix or `*` modifier.
4. Classify the location and required-ness based on the operator (see table in test section above).

**Integration point:** This function is called from `extract_parameters()` or from the path-level parameter extraction logic. When RFC 6570 query parameters (`{?param}`) are found, they are added to the query parameters list with `required: False`. They should only be promoted to FK candidates if the parameter also appears in the operation's explicit `parameters` list with `required: true`.

The function signature:

```python
def parse_rfc6570_template(template: str) -> List[Dict[str, Any]]:
    """Parse an RFC 6570 URI template into parameter descriptors.

    Handles all RFC 6570 operators: simple, reserved (+), fragment (#),
    label (.), path segment (/), semicolon (;), query (?), and
    query continuation (&).

    Args:
        template: An RFC 6570 URI template string
            (e.g., "/users/{id}{?filter,sort}").

    Returns:
        List of dicts with 'name' (str), 'location' ('path' or 'query'),
        and 'required' (bool) keys.
    """
```

---

## File Summary

| Action | File Path |
|--------|-----------|
| Create | `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/__init__.py` |
| Create | `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/conftest.py` |
| Create | `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_combinator_unwrap.py` |
| Create | `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_type_inference.py` |
| Create | `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_schema_name_normalization.py` |
| Create | `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_rfc6570_parser.py` |
| Modify | `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/field_extractor.py` |
| Modify | `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/spec_loader.py` |
| Modify | `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/path_extractor.py` |

---

## Constraints and Gotchas

1. **No new dependencies.** All four items use only Python stdlib (`re`, `copy`) and existing project imports.

2. **Precision > Recall.** These are preprocessing steps that improve input quality for downstream detectors. They should never introduce false positives. Combinator unwrapping and type inference are conservative by design -- they only act when the signal is unambiguous.

3. **Backward compatibility.** All changes are additive or replace behavior with a superset. Existing schemas that already have explicit `type` fields, no combinator wrapping, standard names, and simple `{param}` templates should produce identical output after these changes.

4. **Python `bool` is subclass of `int`.** In the type inference function (#5), the `isinstance(val, bool)` check must come BEFORE `isinstance(val, int)`, otherwise booleans in enum lists will be misclassified as integers.

5. **`$ref` memoization scope.** The memoization cache for `_resolve_refs` must be scoped to a single `load_spec()` call. Do not use a module-level cache -- different spec files have different `$ref` targets, and a shared cache would produce incorrect resolutions.

6. **Schema name normalization is for matching only.** The `normalize_schema_name()` function is used downstream for resource matching (section-03's target inference). It must never alter the `$ref` path used for actual schema lookup. The original name and the normalized name are both kept.

7. **RFC 6570 `explode` modifier.** The `*` (explode) modifier on template variables (e.g., `{?list*}`) should be stripped from the parameter name but does not change the location or required classification. Do not attempt to interpret its semantic meaning for FK detection.

8. **Test command.** Run tests with: `cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi && uv run pytest tests/generation/rest/ -v`

---

## Implementation Notes

**Implemented:** All 4 items complete. Deviations from plan:

1. **Integration points added per code review**: unwrap_single_item_combinator and infer_schema_type wired into extract_schema_fields (top-level + property loop). parse_rfc6570_template integrated into extract_parameters via new `path` parameter.
2. **Memo sharing**: load_spec now creates a single memo dict shared across _resolve_refs calls for paths/components/definitions.
3. **normalize_schema_name**: Defined in spec_loader.py but not yet called from field_extractor.py (downstream use in section-03 target inference).
4. **Test fix**: "UserResponseDTO" test expectation corrected — endswith checks suffix list in order, "DTO" matches before "Response".

**Tests:** 41 new tests across 4 test files. Total: 863 passing (53 REST + 810 CRD).

**Files modified:** field_extractor.py, spec_loader.py, path_extractor.py
**Files created:** test_combinator_unwrap.py, test_type_inference.py, test_schema_name_normalization.py, test_rfc6570_parser.py