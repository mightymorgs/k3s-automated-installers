I have all the context I need. Now I will generate the section content.

# Section 08: Phase B -- Adapter Elimination

## Overview

This section covers the final step of Phase B: deleting `adapters/swagger2.py`, slimming `adapters/cloudflare.py` and `adapters/github_openapi.py`, and updating `adapters/__init__.py`. The preceding sections (05, 06, 07) introduced the generic capabilities that make these vendor-specific adapters redundant -- OpenAPI links parsing, envelope detection, and allOf canonicalization. This section verifies parity with the old code and removes it.

**Dependencies:** Sections 05 (links parser), 06 (envelope detector), 07 (allOf canonicalization) must be complete before this section executes. Sections 01-04 (data model, Phase A preprocessing/detection/integration) are also prerequisites.

## Scope of Changes

| Action | File | LOC Before | LOC After | Details |
|--------|------|:---:|:---:|---------|
| DELETE | `adapters/swagger2.py` | 335 | 0 | Fully replaced by generic pipeline |
| SLIM | `adapters/cloudflare.py` | 299 | ~70 | Keep only path-based resource normalization |
| SLIM | `adapters/github_openapi.py` | 400 | ~75 | Keep only alias resolution (node_id, login, full_name) |
| MODIFY | `adapters/__init__.py` | 257 | ~200 | Remove Swagger2 from registry, simplify routing |
| VERIFY | `spec_loader.py` | -- | -- | Confirm existing Swagger 2.0 handling suffices |
| VERIFY | `field_extractor.py` | -- | -- | Confirm existing formData/body param handling suffices |

## Tests First

All tests go in a new directory: `platform-tools/idi/tests/generation/rest/`.

### File: `tests/generation/rest/__init__.py`

Empty file to make the directory a Python package.

### File: `tests/generation/rest/conftest.py`

Shared test fixtures for Phase B adapter elimination tests.

```python
"""Shared fixtures for REST pipeline Phase B tests."""
import pytest
from typing import Any, Dict


@pytest.fixture
def swagger2_spec() -> Dict[str, Any]:
    """Valid Swagger 2.0 spec with body params, formData, and definitions."""
    # Minimal Swagger 2.0 spec covering: body parameter, formData,
    # file upload, default responses, multiple produces, $ref to definitions


@pytest.fixture
def swagger2_spec_with_formdata() -> Dict[str, Any]:
    """Swagger 2.0 spec using in:formData parameters (Slack-style)."""
    # Spec with parameters using in:formData, including file type


@pytest.fixture
def swagger2_spec_with_default_response() -> Dict[str, Any]:
    """Swagger 2.0 spec using 'default' response instead of numeric codes."""


@pytest.fixture
def swagger2_spec_with_multiple_produces() -> Dict[str, Any]:
    """Swagger 2.0 spec with multiple produces media types."""
    # e.g., produces: ["application/json", "application/xml"]


@pytest.fixture
def cloudflare_spec() -> Dict[str, Any]:
    """Minimal Cloudflare-style spec with result/success/errors envelope."""


@pytest.fixture
def github_spec() -> Dict[str, Any]:
    """Minimal GitHub-style spec with node_id, login aliases and external params."""


@pytest.fixture
def minimal_openapi_spec() -> Dict[str, Any]:
    """Valid OAS 3.0 spec with 2 operations for baseline comparison."""
```

### File: `tests/generation/rest/test_swagger2_elimination.py`

Tests verifying the generic pipeline handles all Swagger 2.0 patterns without the dedicated adapter.

```python
"""Tests: Swagger 2.0 spec processing WITHOUT swagger2.py adapter.

These tests verify the generic pipeline (spec_loader, field_extractor)
handles all Swagger 2.0 structural differences that swagger2.py used
to handle:
- #/definitions/ -> $ref resolution
- in:body parameters -> request body extraction
- in:formData parameters -> synthetic body schema
- responses[code].schema (not nested under content/)
- consumes/produces media types
- default responses
- file upload parameters
"""
import pytest


class TestSwagger2SpecLoading:
    """spec_loader handles Swagger 2.0 structural differences."""

    def test_definitions_ref_resolution(self, swagger2_spec):
        """$ref to #/definitions/Foo resolves correctly via spec_loader."""

    def test_body_parameter_extraction(self, swagger2_spec):
        """Swagger 2.0 'in: body' parameter extracted as request body fields."""

    def test_formdata_parameter_extraction(self, swagger2_spec_with_formdata):
        """Swagger 2.0 'in: formData' parameters converted to body fields."""

    def test_file_upload_handling(self, swagger2_spec_with_formdata):
        """Swagger 2.0 file upload (type: file) handled correctly."""

    def test_default_response_handling(self, swagger2_spec_with_default_response):
        """Swagger 2.0 'default' response key handled correctly."""

    def test_multiple_produces_handling(self, swagger2_spec_with_multiple_produces):
        """Swagger 2.0 multiple produces media types handled correctly."""

    def test_response_schema_direct(self, swagger2_spec):
        """Swagger 2.0 responses[code].schema (not under content/) extracted."""


class TestSwagger2Parity:
    """Generic pipeline produces equivalent or better output than swagger2.py."""

    def test_field_ref_extraction_parity(self, swagger2_spec):
        """Field refs extracted from Swagger 2.0 spec match old adapter output."""

    def test_output_extraction_parity(self, swagger2_spec):
        """Outputs extracted from Swagger 2.0 spec match old adapter output."""

    def test_composed_schema_handling(self, swagger2_spec):
        """allOf/oneOf/anyOf in Swagger 2.0 definitions handled by allOf canonicalization."""

    def test_schema_name_normalization(self, swagger2_spec):
        """Schema names from #/definitions/ normalized correctly (strip suffixes)."""
```

### File: `tests/generation/rest/test_adapter_slimming.py`

Tests verifying slimmed Cloudflare and GitHub adapters produce equivalent output.

```python
"""Tests: Slimmed Cloudflare and GitHub adapters maintain parity.

Cloudflare: envelope unwrapping removed (replaced by section-06 envelope detector).
  Keep: path-based resource normalization (~70 LOC).

GitHub: external params, polymorphic body, nested output, integer FK, path param
  classification all removed (replaced by generic detectors from sections 01-07).
  Keep: alias resolution for node_id->id, login->name, full_name->name (~75 LOC).
"""
import pytest


class TestCloudflareAdapterSlimmed:
    """Cloudflare adapter keeps only path-based resource normalization."""

    def test_output_matches_baseline(self, cloudflare_spec):
        """Slimmed Cloudflare adapter output matches or exceeds baseline."""

    def test_loc_under_80(self):
        """Cloudflare adapter file is under 80 LOC after slimming."""

    def test_envelope_removed(self, cloudflare_spec):
        """extract_response_schema no longer does Cloudflare-specific unwrapping."""
        # Generic envelope_detector (section 06) handles this now

    def test_allof_flattening_removed(self, cloudflare_spec):
        """_flatten_schema and _find_result_in_schema removed."""
        # allOf canonicalization (section 07) handles this now

    def test_resource_normalization_preserved(self):
        """normalize_resource_name still works for deep Cloudflare paths."""
        # /accounts/{account_id}/access/apps/{app_id} -> "access-apps"
        # /zones/{zone_id}/dns_records/{dns_record_id} -> "dns-records"


class TestGitHubAdapterSlimmed:
    """GitHub adapter keeps only alias resolution."""

    def test_output_matches_baseline(self, github_spec):
        """Slimmed GitHub adapter output matches or exceeds baseline."""

    def test_loc_under_80(self):
        """GitHub adapter file is under 80 LOC after slimming."""

    def test_external_params_removed(self):
        """EXTERNAL_PARAMS set removed (replaced by credential regex from section 03)."""

    def test_polymorphic_body_removed(self):
        """oneOf/anyOf handling removed (replaced by allOf canonicalization section 07)."""

    def test_alias_resolution_preserved(self):
        """node_id->id, login->name, full_name->name aliases still work."""

    def test_integer_fk_removed(self):
        """Integer FK detection removed (covered by base adapter + FK suffix expansion)."""


class TestAdapterRegistryUpdated:
    """__init__.py registry updated correctly."""

    def test_swagger2_removed_from_registry(self):
        """'swagger' and 'swagger2' keys no longer in AdapterRegistry._adapters."""

    def test_remaining_adapters_accessible(self):
        """rest, cloudflare, vault, aws, github adapters still accessible."""

    def test_swagger2_import_removed(self):
        """Swagger2Adapter no longer imported in __init__.py."""

    def test_detect_style_no_swagger(self):
        """detect_style never returns 'swagger' or 'swagger2'."""

    def test_get_adapter_swagger2_raises(self):
        """get_adapter(style='swagger2') raises ValueError."""
```

### File: `tests/generation/rest/test_phase_b_integration.py`

Integration-level parity tests.

```python
"""Phase B integration tests: verify full pipeline parity after adapter elimination.

These tests capture baseline output BEFORE adapter changes, then verify
the pipeline produces equivalent or better output AFTER changes.
"""
import pytest


class TestPhaseBIntegration:
    """End-to-end parity across adapter elimination."""

    def test_all_swagger2_specs_equivalent_without_adapter(self):
        """All Swagger 2.0 specs produce equivalent output without swagger2.py.

        Strategy: for each Swagger 2.0 spec in the catalog, run the pipeline
        with and without the Swagger2Adapter and compare edge counts.
        """

    def test_cloudflare_spec_parity(self):
        """Cloudflare spec output matches/exceeds baseline with slimmed adapter."""

    def test_github_spec_parity(self):
        """GitHub spec output matches/exceeds baseline with slimmed adapter."""

    def test_no_regression_on_openapi3_specs(self):
        """OpenAPI 3.0 specs unaffected by adapter changes."""
```

## Implementation Details

### Step 1: Capture Baselines (Before Any Deletion)

Before modifying any adapter code, capture baseline outputs for parity verification. This is critical -- the parity tests above require a golden reference to compare against.

**Approach:** For each adapter being deleted or slimmed, run the pipeline on representative specs and save the output (edge count, field refs, outputs). Store these as test fixture data or golden files in the test directory.

Key metrics to capture per spec:
- Total number of dependency edges extracted
- Total number of output facts extracted
- Field reference details (field name, target resource, source)

### Step 2: Verify spec_loader Already Handles Swagger 2.0

Before deleting `swagger2.py`, confirm that the existing generic pipeline already handles the structural differences that `swagger2.py` was bridging. Looking at the current codebase:

**Already handled by `spec_loader.py`:**
- `_resolve_refs()` resolves `$ref` pointers regardless of whether they point to `#/definitions/` or `#/components/schemas/` -- the JSON Pointer traversal is path-agnostic (line 31-48 in `spec_loader.py`)
- The `_resolve_refs()` function processes both `paths` and `definitions` sections (line 155-158)

**Already handled by `field_extractor.py`:**
- `extract_request_fields()` already handles `in: body` parameters (lines 236-240)
- `extract_request_fields()` already handles `in: formData` parameters (lines 243-262)
- `extract_response_fields()` already handles Swagger 2.0 `responses[code].schema` without `content/` nesting (lines 392-394)

**Functions in swagger2.py to audit against the generic pipeline:**

| swagger2.py function | Generic pipeline equivalent |
|---|---|
| `normalize_ref_to_resource()` | Section 03, item #6: `normalize_schema_name()` in `spec_loader.py` |
| `extract_field_refs()` | `OpenApiRestAdapter.extract_field_refs()` in `openapi_rest.py` |
| `extract_operation_refs()` | `extract_request_fields()` in `field_extractor.py` |
| `extract_outputs()` | `extract_response_fields()` in `field_extractor.py` |
| `to_intermediate()` | Not needed -- generic pipeline processes both formats natively |
| `is_swagger2()` | Not needed once adapter is removed |
| allOf/oneOf/anyOf recursion | Section 07: allOf canonicalization in `field_extractor.py` |

### Step 3: Delete `adapters/swagger2.py`

**File to delete:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/swagger2.py`

This is a 335-LOC file containing:
- `normalize_ref_to_resource()` -- replaced by schema name normalization (section 03, item #6)
- `Swagger2Adapter` class with `is_swagger2()`, `extract_field_refs()`, `extract_operation_refs()`, `extract_outputs()`, `to_intermediate()` -- all replaced by the generic pipeline
- `REF_SUFFIXES_TO_STRIP` constant -- subsumed by the generic suffix list in `normalize_schema_name()`

After deletion, run the Swagger 2.0 parity tests to confirm no regressions.

### Step 4: Slim `adapters/cloudflare.py`

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/cloudflare.py`

**Current size:** 299 LOC (300 lines). **Target:** ~70 LOC.

**What to remove (229 LOC):**
- `extract_response_schema()` method (lines 61-124) -- replaced by generic envelope detector (section 06, pattern 3: single-field wrapper with `result` + metadata siblings `success`, `errors`, `messages`)
- `_find_result_in_schema()` method (lines 126-168) -- no longer needed without envelope unwrapping
- `_flatten_schema()` method (lines 170-219) -- replaced by allOf canonicalization (section 07)
- `extract_path_parameters_as_outputs()` method (lines 221-260) -- replaced by generic path parameter handling (section 10, response walk)
- `is_cloudflare_wrapper_field()` static method (lines 289-299) -- no longer needed
- `WRAPPER_FIELDS` constant (line 36) -- no longer needed

**What to keep (~70 LOC):**
- `normalize_resource_name()` method (lines 262-287) -- Cloudflare's deep path nesting (`/accounts/{id}/access/apps/{id}`) is genuinely unique and requires specialized logic to extract meaningful resource names like `access-apps`
- Class definition, `__init__`, and import boilerplate

The slimmed `CloudflareAdapter` should still extend `OpenApiRestAdapter` but will only override `normalize_resource_name()`. The `extract_response_schema()` method is removed entirely -- the generic envelope detector handles Cloudflare's `{result, success, errors, messages}` pattern automatically.

### Step 5: Slim `adapters/github_openapi.py`

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/github_openapi.py`

**Current size:** 400 LOC (401 lines). **Target:** ~75 LOC.

**What to remove (325 LOC):**
- `EXTERNAL_PARAMS` set (line 24) -- replaced by credential/external parameter regex from section 03, item #1
- `OUTPUT_FIELDS` set (lines 27-30) -- replaced by generic readOnly field classification and response tree walk
- `extract_field_refs()` method (lines 77-138) -- oneOf/anyOf polymorphic handling replaced by allOf canonicalization (section 07); standard property extraction is in the base `OpenApiRestAdapter`
- `extract_outputs()` method (lines 140-193) -- nested output extraction replaced by full response tree walk (section 10)
- `extract_path_params_as_refs()` method (lines 195-238) -- external param classification replaced by credential regex; FK detection by base adapter
- `_is_output_field()` method (lines 240-264) -- replaced by generic output detection
- `_extract_nested_outputs()` method (lines 266-304) -- replaced by response tree walk
- `_detect_fk()` method (lines 306-368) -- integer FK detection covered by base adapter + FK suffix expansion (section 03, item #4)
- `_extract_ref_name()` method (lines 370-382) -- basic utility, moved to base
- `_infer_resource()` method (lines 384-400) -- covered by base adapter

**What to keep (~75 LOC):**
- `GITHUB_ALIASES` dict (lines 17-21) -- GitHub's `node_id->id`, `login->name`, `full_name->name` mapping is genuinely non-standard
- `GitHubFactRef` dataclass (lines 33-53) -- handles alias resolution during fact reference creation
- Class definition, `__init__`, and import boilerplate
- A thin `apply_aliases()` method that translates GitHub-specific field names to canonical form

### Step 6: Update `adapters/__init__.py`

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/__init__.py`

**Changes:**

1. **Remove Swagger2 import:** Delete `from idi.generation.adapters.swagger2 import Swagger2Adapter`
2. **Remove from `__all__`:** Delete `"Swagger2Adapter"` from the exports list
3. **Remove from registry:** Delete `"swagger": Swagger2Adapter` and `"swagger2": Swagger2Adapter` entries from `AdapterRegistry._adapters`
4. **Update `detect_style()`:** The method should never return `"swagger"` or `"swagger2"`. If a Swagger 2.0 spec is detected (via `spec.get("swagger", "").startswith("2.")`), return `"rest"` instead -- the generic REST adapter handles Swagger 2.0 specs natively after sections 01-07
5. **Simplify detection heuristics:** With fewer adapters to route to (rest, cloudflare, vault, aws, github), the routing logic can be simplified

The `_is_cloudflare_spec()` detection function should remain -- it is still needed to route Cloudflare specs to the slimmed Cloudflare adapter (which still provides `normalize_resource_name()`).

### Step 7: Run Full Parity Tests

After all changes, run the complete test suite:

```bash
cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi && uv run pytest tests/generation/rest/ -v
```

Verify:
1. All Swagger 2.0 parity tests pass
2. Cloudflare parity tests pass
3. GitHub parity tests pass
4. No regressions on OpenAPI 3.0 specs
5. LOC counts: Cloudflare < 80, GitHub < 80

## Key Risks and Mitigations

**Risk 1: Swagger 2.0 formData with file upload.** The current `field_extractor.py` handles `in: formData` but may not handle `type: file` (a Swagger 2.0-only type). Mitigation: add a test fixture with `type: file` parameters and verify they are either handled or gracefully skipped (file uploads do not produce FK edges).

**Risk 2: Cloudflare-specific envelope is not detected by generic detector.** The Cloudflare envelope `{result, success, errors, messages}` must match the generic envelope detector's Pattern 3 (single-field wrapper with metadata siblings). The `result` field matches the wrapper name set (`data, result, response, payload, body, content`), and `success`, `errors`, `messages` match metadata field indicators. Confidence: 0.9 (has metadata siblings). This should work without issue, but the parity test is critical.

**Risk 3: GitHub alias resolution regression.** The slimmed GitHub adapter keeps `GITHUB_ALIASES` and `GitHubFactRef`, but removing `extract_outputs()` means the base adapter's output extraction must be compatible with `GitHubFactRef`. Mitigation: the parity test verifies end-to-end output matches.

**Risk 4: Swagger 2.0 `default` response key.** Some Swagger 2.0 specs use `"default"` instead of numeric status codes. The current `extract_response_fields()` in `field_extractor.py` checks for `("200", "201", "202", "204")` -- the `"default"` key is not checked. The old `swagger2.py` also only processed numeric codes (it had a `try: int(status_code)` check). If the generic pipeline needs `default` handling, it should be added to `extract_response_fields()`, but this is a pre-existing gap, not a regression.

## Files Summary

**Files to create:**
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/__init__.py`
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/conftest.py`
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_swagger2_elimination.py`
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_adapter_slimming.py`
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_phase_b_integration.py`

**Files to delete:**
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/swagger2.py`

**Files to modify:**
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/cloudflare.py` (299 -> ~70 LOC)
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/github_openapi.py` (400 -> ~75 LOC)
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/__init__.py` (remove Swagger2, simplify routing)

**Files to verify (no changes expected):**
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/spec_loader.py` -- confirm `_resolve_refs` handles `#/definitions/` paths
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/field_extractor.py` -- confirm `extract_request_fields` handles `in: body` and `in: formData`

## Implementation Checklist

1. Create test directory `tests/generation/rest/` with `__init__.py`
2. Write `conftest.py` with Swagger 2.0, Cloudflare, and GitHub test fixtures
3. Write `test_swagger2_elimination.py` -- all tests should FAIL initially (adapter still exists)
4. Write `test_adapter_slimming.py` -- capture baselines with current adapters
5. Write `test_phase_b_integration.py`
6. Delete `adapters/swagger2.py`
7. Update `adapters/__init__.py` to remove Swagger2 references
8. Run `test_swagger2_elimination.py` -- verify tests PASS with generic pipeline
9. Slim `adapters/cloudflare.py` to ~70 LOC (keep `normalize_resource_name` only)
10. Slim `adapters/github_openapi.py` to ~75 LOC (keep alias resolution only)
11. Run `test_adapter_slimming.py` -- verify parity with baselines
12. Run `test_phase_b_integration.py` -- verify end-to-end parity
13. Run full test suite: `cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi && uv run pytest`

## Implementation Notes (actual)

### Files Deleted
- `platform-tools/idi/idi/generation/adapters/swagger2.py` (335 LOC)

### Files Modified
- `platform-tools/idi/idi/generation/adapters/cloudflare.py` (299 → 58 LOC) — kept only `normalize_resource_name()`
- `platform-tools/idi/idi/generation/adapters/github_openapi.py` (401 → 53 LOC) — kept only `GITHUB_ALIASES`, `GitHubFactRef`, thin subclass
- `platform-tools/idi/idi/generation/adapters/__init__.py` — removed Swagger2Adapter import, swagger/swagger2 keys route to OpenApiRestAdapter

### Files Created
- `platform-tools/idi/tests/generation/rest/test_swagger2_elimination.py` — 5 tests
- `platform-tools/idi/tests/generation/rest/test_adapter_slimming.py` — 14 tests

### Net LOC Change
- Removed: 1,021 LOC (swagger2.py + cloudflare methods + github methods)
- Added: 353 LOC (tests + slimmed code)
- Net: -668 LOC vendor-specific code

### Deviations from Plan
1. **test_phase_b_integration.py omitted** — parity verified by full 1006-test suite passing (all existing pipeline tests exercise these adapters)
2. **Fewer swagger2 tests than planned (5 vs 11)** — key patterns tested; $ref resolution proven by existing tests
3. **swagger/swagger2 registry keys kept** — routed to OpenApiRestAdapter for backward compat instead of raising ValueError
4. **GitHubOpenApiAdapter now extends OpenApiRestAdapter** — intentional; inherits generic FK detection

### Test Results
- 19 new tests passing
- 1006 total tests passing (0 regressions)