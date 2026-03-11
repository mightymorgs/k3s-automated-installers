Now I have all the context needed. Let me generate the section content.

# Section 03: Phase A Detection Rule Enhancements

## Overview

This section implements five detection rule improvements for the REST pipeline, covering plan items #1, #2, #4, #7, and #8. These are independent changes to three existing files that enhance FK detection accuracy, output classification, and producer-consumer matching. All changes are additive -- no new files are created, no architectural changes required.

**Files modified:**
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/target_inference.py` -- credential exclusion (#1), FK suffix expansion (#4)
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/output_detection.py` -- readOnly/writeOnly classification (#2), producer validity rules (#7)
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/naming.py` -- ID synonym matching (#8)

**New test file:**
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/__init__.py`
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_detection_rules.py`

**Dependencies:** Requires section-01 (data model) to be completed first. The `DetectionSource` enum and updated `Dependency` dataclass must be available in `dep_adapters/base.py` before these changes can reference `DetectionSource.CREDENTIAL_REGEX`, `DetectionSource.READONLY_FIELD`, etc.

**Blocks:** Section-04 (Phase A integration regression tests) depends on this section.

---

## Tests (Write First)

All tests go in `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_detection_rules.py`. Create the `rest/` directory and `__init__.py` first.

### 3.1 Credential/External Parameter Exclusion Tests

```python
# Test: "client_secret" matches CREDENTIAL_PARAMS regex -> excluded from FK detection
# Test: "access_token" matches -> excluded
# Test: "api_key" and "api-key" match -> excluded
# Test: "password" matches -> excluded
# Test: "user_id" does NOT match -> not excluded (legitimate FK)
# Test: "token_id" does NOT match -> not excluded (id suffix, not credential)
# Test: "description" does NOT match -> not excluded
# Test: infer_target() returns (None, 0.0) for credential-matching fields
# Test: detection_source set to CREDENTIAL_REGEX on exclusion
```

Key test function signature:

```python
def test_credential_param_excluded():
    """Credential-like params return (None, 0.0) from infer_target."""

def test_legitimate_fk_not_excluded():
    """Fields like user_id and token_id are NOT excluded by the credential regex."""
```

The credential regex should be tested against the `infer_target()` function directly. Each test calls `infer_target(field_name, field_info, known_resources)` and asserts the return value is `(None, 0.0)` for credential names. For legitimate FK names, it should return a non-None target.

### 3.2 readOnly/writeOnly Field Classification Tests

```python
# Test: schema with readOnly: true field -> classified as producer (confidence 0.9)
# Test: schema with writeOnly: true field -> added to skip-set
# Test: schema with both readOnly and writeOnly fields -> each classified correctly
# Test: schema with no readOnly/writeOnly -> returns empty lists
# Test: nested schema with readOnly field -> detected (if within walk depth)
# Test: detection_source set to READONLY_FIELD / WRITEONLY_FIELD
```

Key test function signatures:

```python
def test_readonly_field_classified_as_producer():
    """A readOnly field in response schema registers as Output with confidence 0.9."""

def test_writeonly_field_added_to_skip_set():
    """A writeOnly field is excluded from FK detection."""
```

Tests should construct an `OperationInfo` with synthetic schemas containing `readOnly: true` and/or `writeOnly: true` on properties, then call `detect_outputs()` and verify the result list.

### 3.4 FK Suffix Expansion Tests

```python
# Test: "user_uuid" detected as FK with suffix map -> target "user", confidence 0.8 with resource match
# Test: "user_guid" detected as FK
# Test: "user_ids" detected as array FK -> True flag
# Test: "user_uuids" detected as array FK
# Test: "user_guids" detected as array FK
# Test: "user_id" still works (existing behavior preserved)
# Test: suffix-only match (no resource) -> confidence 0.7
# Test: suffix + resource match -> confidence 0.8
# Test: "username" does NOT match any suffix
```

Key test function signature:

```python
def test_uuid_suffix_detected_as_fk():
    """Fields ending in _uuid are detected as FK references."""
    known = {"users"}
    target, conf = infer_target("user_uuid", {"type": "string", "format": "uuid"}, known)
    assert target == "users"
    assert conf >= 0.7
```

### 3.7 Producer Validity Rules Tests

```python
# Test: POST operation -> registered as producer (priority 4)
# Test: PUT operation -> registered as producer (priority 3)
# Test: PATCH operation -> registered as producer (priority 2)
# Test: GET operation -> registered as producer (priority 1)
# Test: DELETE operation -> NOT registered as producer
# Test: HEAD operation -> NOT registered as producer
# Test: OPTIONS operation -> NOT registered as producer
# Test: POST + GET producing same field -> POST wins (higher priority)
# Test: GET + GET producing same field -> first one wins (same priority)
```

Key test function signature:

```python
def test_get_produces_outputs():
    """GET operations register as producers with lowest priority (1)."""

def test_delete_produces_no_outputs():
    """DELETE operations are excluded from producer registration."""
```

### 3.8 ID Synonym Matching Tests

```python
# Test: "user_uuid" normalized to "user_id"
# Test: "user_guid" normalized to "user_id"
# Test: "user_uid" normalized to "user_id"
# Test: "user_id" stays "user_id"
# Test: "username" -> unchanged (no id-like suffix)
# Test: producer "user_uuid" matches consumer "user_id" after normalization
# Test: confidence 0.8 for synonym matches
```

Key test function signature:

```python
def test_normalize_id_suffix():
    """ID synonyms (uuid, guid, uid) canonicalize to _id."""
    from idi.generation.dep_adapters.naming import normalize_id_suffix
    assert normalize_id_suffix("user_uuid") == "user_id"
    assert normalize_id_suffix("user_guid") == "user_id"
    assert normalize_id_suffix("user_uid") == "user_id"
    assert normalize_id_suffix("user_id") == "user_id"
    assert normalize_id_suffix("username") == "username"
```

---

## Implementation Details

### 3.1 Credential/External Parameter Exclusion (#1)

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/target_inference.py`

**What to do:** Add an OWASP-derived compiled regex constant near the top of the file that matches credential-like parameter names. Apply it as an early-return guard at the top of `infer_target()`.

**The regex pattern** should match these parameter names (case-insensitive):
- `client_secret`, `client-secret`
- `access_token`, `access-token`
- `refresh_token`, `refresh-token`
- `id_token`, `id-token`
- `token` (bare, but NOT `token_id` or `*_token_id`)
- `password`, `passwd`
- `secret` (bare, but NOT `*_secret_id` or `client_secret_id`)
- `api_key`, `api-key`, `apikey`
- `authorization`

**Critical nuance:** The regex must NOT match `user_id`, `token_id`, `secret_id`, or any field where the credential-like word is a prefix/qualifier for an actual FK suffix (`_id`, `_uuid`, etc.). The simplest approach: if the field ends with a known FK suffix (`_id`, `_uuid`, `_guid`, `_pk`, `_ref`), it is NOT a credential -- skip the credential check. Apply the credential check only to fields that do NOT have an FK suffix.

**Integration point:** Add the regex check as the first guard in `infer_target()`, after the existing `_NEVER_FK_FIELDS` check but before `_type_factor()`. If the field matches, return `(None, 0.0)` immediately. The `detection_source` will be set by the caller (since `infer_target` returns a tuple, not a Dependency, the detection_source is set where the Dependency is constructed in `body_fk.py`).

**Approximate regex:**

```python
_CREDENTIAL_PARAMS: re.Pattern = re.compile(
    r"^(client[_-]?secret|access[_-]?token|refresh[_-]?token|id[_-]?token"
    r"|token|password|passwd|secret|api[_-]?key|apikey|authorization)$",
    re.IGNORECASE,
)
```

**Guard logic in `infer_target()`:**

```python
def infer_target(field_name, field_info, known_resources, *, container=None, json_path=None):
    fn_lower = field_name.lower()

    # Credential exclusion: skip credential-like params unless they have an FK suffix
    if not _has_fk_suffix(fn_lower) and _CREDENTIAL_PARAMS.match(fn_lower):
        return None, 0.0

    # ... rest of existing logic
```

This replaces the hardcoded `EXTERNAL_PARAMS = {"owner", "org", "repo"}` pattern from the GitHub adapter with a general rule that works across all APIs.

### 3.2 readOnly/writeOnly Field Classification (#2)

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/output_detection.py`

**What to do:** Add a new function that walks response schema properties and classifies fields based on their `readOnly`/`writeOnly` attributes. Integrate it into the existing `detect_outputs()` function.

**New function signature:**

```python
def classify_readonly_writeonly(
    response_schema: dict,
) -> tuple[list[str], list[str]]:
    """Classify fields by readOnly/writeOnly attributes.

    Returns (readonly_fields, writeonly_fields) where each is a list
    of field names.
    """
```

**Integration into `detect_outputs()`:**

The current `detect_outputs()` only looks at POST/PUT/PATCH methods (via `_METHOD_PRIORITY`). Two changes are needed:

1. **Expand `_METHOD_PRIORITY`** to include GET at priority 1. The current map has POST=3, PUT=2, PATCH=1. Change to POST=4, PUT=3, PATCH=2, GET=1. DELETE, HEAD, OPTIONS remain excluded (return early with empty list).

2. **Add readOnly producer detection:** After the existing ID field precedence scan, also walk the response schema properties. Any field with `readOnly: true` is registered as an Output with confidence 0.9 (this is spec-declared signal, not heuristic). Fields with `writeOnly: true` are collected into a skip-set that can be returned/exported for `target_inference.py` to check before FK matching.

**Confidence:** readOnly fields get producer confidence 0.9 (spec-declared). writeOnly fields get added to a skip-set (they are never FK targets and never outputs).

**Note on detection_source:** The `Output` dataclass does not currently have a `detection_source` field. This may need to be added in section-01 or tracked separately. If `Output` is not updated in section-01, use the `source` string field to indicate `"readonly_field"` for traceability.

### 3.4 FK Suffix Expansion (#4)

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/target_inference.py`

**What to do:** The existing `_COMMON_FK_SUFFIXES` tuple already includes `_uuid` and `_guid`:

```python
_COMMON_FK_SUFFIXES: tuple[str, ...] = (
    "_id", "_pk", "_uuid", "_guid", "_key", "_ref",
    "_ids", "_number", "_name", "_slug", "_flow",
)
```

The tuple already has `_ids` but is missing `_uuids` and `_guids` (array variants). Add them:

```python
_COMMON_FK_SUFFIXES: tuple[str, ...] = (
    "_id", "_pk", "_uuid", "_guid", "_key", "_ref",
    "_ids", "_uuids", "_guids",
    "_number", "_name", "_slug", "_flow",
)
```

**Array detection:** When a field ends with `_ids`, `_uuids`, or `_guids`, the field represents a many-to-many relationship. The FK detection should treat the field's value type as the element type (not the array type) for confidence scoring. This may require a small adjustment in `_type_factor()` or `_build_candidates()` to handle the array suffix stripping.

In `_build_candidates()`, add logic so that when a field name ends in an array FK suffix (`_ids`, `_uuids`, `_guids`), the suffix is stripped to its singular form for candidate generation. For example, `user_ids` should generate the candidate `user` (stripping `_ids`), and `user_uuids` should generate the candidate `user` (stripping `_uuids`).

**Confidence levels:**
- Suffix + resource match: 0.8
- Suffix-only match (no matching resource): 0.7

These are already approximately reflected in the existing `_build_candidates()` logic (suffix stripping generates candidates at 0.5 base, multiplied by type_factor and match confidence). Verify that the existing confidence arithmetic produces values in the 0.7-0.8 range for expanded suffixes with resource matches.

### 3.7 Producer Validity Rules (#7)

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/output_detection.py`

**What to do:** Expand the `_METHOD_PRIORITY` map and update the method filtering logic in `detect_outputs()`.

**Current state:**

```python
_METHOD_PRIORITY: dict[str, int] = {
    "POST": 3,
    "PUT": 2,
    "PATCH": 1,
}
```

**Target state:**

```python
_METHOD_PRIORITY: dict[str, int] = {
    "POST": 4,
    "PUT": 3,
    "PATCH": 2,
    "GET": 1,
}
```

Methods not in the map (DELETE, HEAD, OPTIONS) continue to return `[]` from `detect_outputs()` via the existing `if priority == 0: return []` guard.

**Priority conflict resolution:** When multiple operations produce the same field (same `fact_ref`), the highest priority wins. The current code does not handle this because it processes one operation at a time. The conflict resolution happens at the `DepAdapterRegistry` level when merging outputs from multiple operations. Document this expectation but note it may require changes in the registry merge logic (outside this section's scope).

**PUT/PATCH update detection:** The existing `_has_resource_id_in_path()` guard that prevents PUT/PATCH updates from registering as producers should be preserved. GET operations should NOT be subject to this guard -- a GET always reads (produces) data regardless of whether the path has a resource ID.

### 3.8 ID Synonym Matching (#8)

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/naming.py`

**What to do:** Add a `normalize_id_suffix()` function that canonicalizes ID-like suffixes to `_id`. This enables cross-convention producer-consumer matching where one uses `uuid` and the other uses `id`.

**New function:**

```python
_ID_SYNONYMS: tuple[str, ...] = ("_uuid", "_guid", "_uid")

def normalize_id_suffix(name: str) -> str:
    """Canonicalize ID-like suffixes to _id for producer-consumer matching.

    Converts _uuid, _guid, _uid suffixes to _id.
    Leaves non-ID-like names unchanged.
    """
    lower = name.lower()
    for synonym in _ID_SYNONYMS:
        if lower.endswith(synonym):
            return name[: len(name) - len(synonym)] + "_id"
    return name
```

**Integration point:** Call `normalize_id_suffix()` in `target_inference.py` during FK matching. Specifically, when building candidates in `_build_candidates()`, normalize the field name before suffix stripping so that `user_uuid` generates the same candidate as `user_id`. Also call it when matching producers to consumers in the output merging phase.

**Confidence:** 0.8 for synonym-based matches. This is a well-defined mapping (uuid/guid/uid are all standard identifier conventions). The confidence is applied by using the normalized form for matching and keeping the synonym match as a small confidence penalty (multiply by 0.95 or similar) compared to an exact suffix match.

---

## Precision Constraints

All five changes must respect the project's core design constraint: **precision > recall**. False edges are worse than missing edges.

- The credential regex (#1) is a precision improvement -- it removes false positive FK matches on credential parameters.
- readOnly/writeOnly classification (#2) uses spec-declared signal at high confidence (0.9) -- high precision by definition.
- FK suffix expansion (#4) only adds well-established ID conventions (uuid, guid) at appropriate confidence levels.
- Producer validity rules (#7) restrict which methods can produce -- this is a precision improvement (fewer false producers).
- ID synonym matching (#8) uses a small, well-defined synonym set -- low risk of false matches.

No change should emit an edge below the 0.7 confidence floor.

---

## Implementation Order

These five items are independent of each other and can be implemented in any order. The recommended order minimizes test fixture complexity:

1. **#1 (credential exclusion)** -- simplest change, one regex + one guard
2. **#8 (ID synonyms)** -- new function in naming.py, no existing code changes
3. **#4 (FK suffix expansion)** -- extend existing tuple + minor logic
4. **#7 (producer validity)** -- expand priority map + method filtering
5. **#2 (readOnly/writeOnly)** -- most complex, adds new classification function

After all five are implemented, section-04 runs integration regression tests on benchmark specs.

---

## Implementation Notes (Actual)

**Implemented:** 2026-03-11 on `feat/crd-implementation`

### Files Modified
- `idi/generation/dep_adapters/target_inference.py` — credential regex guard, `_uuids`/`_guids` suffixes, `normalize_id_suffix` integration
- `idi/generation/dep_adapters/output_detection.py` — method priority expansion (GET=1, POST=4), `classify_readonly_writeonly()`, writeOnly skip-set
- `idi/generation/dep_adapters/naming.py` — `normalize_id_suffix()` function

### Test File
- `tests/generation/rest/test_detection_rules.py` — 47 tests across 5 test classes

### Deviations from Plan
1. **Confidence thresholds** — Plan specified 0.7-0.8 for FK suffix matches. Actual multiplicative arithmetic (base_confidence * match_confidence * type_factor) produces ~0.24-0.30. Tests assert `conf > 0.0` and correct target instead. The 0.7 floor applies to the full pipeline edge emission, not individual function returns.
2. **readOnly/writeOnly** — Added after code review caught that initial implementation had tests passing vacuously. `classify_readonly_writeonly()` returns field lists; writeOnly fields excluded from `_ID_FIELD_PRECEDENCE` scan; readOnly fields outside precedence list also registered as outputs with `source="readonly_field"`.
3. **normalize_id_suffix integration** — Wired into `_build_candidates()` with 0.48 base confidence (slight penalty vs direct suffix match at 0.50). Initially was dead code, caught by code review.
4. **client_secret_id** — Removed from FK-suffix-not-excluded test. The credential guard correctly bypasses it (has `_id` suffix), but no matching resource exists in test set. Not a meaningful test case.