Good -- no existing kind-like concept, so this is entirely new. I have everything I need now.

# Section 08: Enum Kindness Ratio

## Overview

This section modifies the existing `detect_enum_kind` function in `ref_detector.py` to add two precision guards that prevent false-positive enum-based Kind detection. The current implementation matches **any** enum value that happens to share a name with a registered Kind, leading to false edges when K8s API constants (like `"Orphan"`, `"Cluster"`, `"Foreground"`) or low-ratio enums accidentally collide with Kind names.

**Problem example:** Kyverno's `deletionPropagationPolicy` field has enum `["Orphan", "Background", "Foreground"]`. If `Orphan` or `Background` happens to match a registered Kind, the detector emits a false dependency edge. Similarly, an enum like `["HelmRepository", "SomeRandomThing"]` where only 50% of values match should not trigger detection because the field is likely not a Kind discriminator.

**Critical constraint:** Precision > Recall. False edges create phantom cycles in Kahn's algorithm, deadlocking deployment. Missing edges only produce suboptimal ordering.

**No dependencies on other sections.** This section can be implemented in parallel with any other section in Batch 1.

## Files Modified

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/crd/ref_detector.py` | Modify `detect_enum_kind` |
| `platform-tools/idi/tests/generation/crd/test_ref_detector.py` | Add new tests to `TestDetectEnumKind` |

## Tests (Write First)

**File:** `platform-tools/idi/tests/generation/crd/test_ref_detector.py`

Add the following tests to the existing `TestDetectEnumKind` class. These tests use the existing `registry` fixture (provides core K8s kinds + cert-manager/external-secrets CRDs) and the existing `_make_field` helper.

### Test 1: K8S_API_CONSTANTS denylist filters all values, returning empty

```python
def test_api_constants_denylist_filters_all(self, registry):
    """Enum with only K8s API constants — all filtered by denylist, no matches."""
    field = _make_field("deletionPropagationPolicy", schema={
        "type": "string",
        "enum": ["Orphan", "Background", "Foreground"],
    }, path="spec.deletionPropagationPolicy")
    results = detect_enum_kind(field, registry)
    assert results == []
```

**Rationale:** `"Orphan"`, `"Background"`, `"Foreground"` are K8s API constants, not Kind names. Even if one happens to match a registered Kind, they must be excluded before ratio calculation.

### Test 2: Valid Kind enum on kind-like field name succeeds

```python
def test_valid_kind_enum_on_kind_field(self, registry):
    """Enum of known Kinds on field named 'kind' — ratio 1.0, kind-like field → match."""
    field = _make_field("kind", schema={
        "type": "string",
        "enum": ["Issuer", "ClusterIssuer"],
    }, path="spec.issuerRef.kind", parent_path="spec.issuerRef")
    sibling = {"name": {"type": "string"}, "kind": {"type": "string"}}
    results = detect_enum_kind(field, registry, sibling_fields=sibling)
    assert len(results) == 2
    kinds = {r.target_kind for r in results}
    assert kinds == {"Issuer", "ClusterIssuer"}
```

**Rationale:** This is the happy-path case -- existing behavior should be preserved. Field name `"kind"` is kind-like, ratio is 1.0 (both values match).

### Test 3: Low kindness ratio (below 0.6) returns empty

```python
def test_low_kindness_ratio_rejected(self, registry):
    """Enum with ratio 0.5 (1/2 match) on kind-like field — below 0.6 threshold, no match."""
    field = _make_field("kind", schema={
        "type": "string",
        "enum": ["Issuer", "SomeRandomThing"],
    }, path="spec.ref.kind")
    results = detect_enum_kind(field, registry)
    assert results == []
```

**Rationale:** Only 1 of 2 values matches a known Kind. Ratio 0.5 < 0.6 threshold. This prevents partial-match false positives.

### Test 4: Non-kind-like field name rejects even with good ratio

```python
def test_non_kind_like_field_name_rejected(self, registry):
    """Enum of known Kinds on field 'deletionPolicy' — not kind-like, no match."""
    field = _make_field("deletionPolicy", schema={
        "type": "string",
        "enum": ["Issuer", "ClusterIssuer"],
    }, path="spec.deletionPolicy")
    results = detect_enum_kind(field, registry)
    assert results == []
```

**Rationale:** Even though both enum values match Kinds (ratio 1.0), the field name `"deletionPolicy"` is not a kind-discriminator pattern. The field likely contains values that coincidentally share names with Kinds.

### Test 5: targetKind is kind-like and passes with good ratio

```python
def test_target_kind_field_name_accepted(self, registry):
    """Enum on field 'targetKind' — kind-like field name + ratio 1.0 → match."""
    field = _make_field("targetKind", schema={
        "type": "string",
        "enum": ["Issuer", "ClusterIssuer"],
    }, path="spec.targetKind")
    results = detect_enum_kind(field, registry)
    assert len(results) == 2
    kinds = {r.target_kind for r in results}
    assert kinds == {"Issuer", "ClusterIssuer"}
```

**Rationale:** `"targetKind"` is in the kind-like field name set. Combined with ratio 1.0, this should match.

### Test 6: Denylist filtering adjusts ratio denominator correctly

```python
def test_denylist_adjusts_ratio_denominator(self, registry):
    """Enum with mix of denylist and real Kinds — ratio computed after filtering."""
    # "Cluster" is in K8S_API_CONSTANTS denylist, "Issuer" is a real Kind
    # After denylist: 1 remaining value, 1 match → ratio 1.0
    # But need 'kind' as field name (kind-like)
    field = _make_field("kind", schema={
        "type": "string",
        "enum": ["Cluster", "Issuer"],
    }, path="spec.ref.kind", parent_path="spec.ref")
    sibling = {"name": {"type": "string"}}
    results = detect_enum_kind(field, registry, sibling_fields=sibling)
    assert len(results) == 1
    assert results[0].target_kind == "Issuer"
```

**Rationale:** `"Cluster"` is filtered by denylist. After filtering, only `"Issuer"` remains. One remaining value, one match: ratio 1.0. Field name is kind-like. Match proceeds.

### Test 7: resourceKind is kind-like

```python
def test_resource_kind_field_name_accepted(self, registry):
    """Enum on field 'resourceKind' — kind-like name."""
    field = _make_field("resourceKind", schema={
        "type": "string",
        "enum": ["Certificate", "Issuer"],
    }, path="spec.resourceKind")
    results = detect_enum_kind(field, registry)
    assert len(results) == 2
```

### Test 8: Existing tests remain passing (regression guard)

The existing tests in `TestDetectEnumKind` that use field name `"kind"` and full-Kind enums should continue to pass after this change. Specifically:

- `test_issuer_cluster_issuer_with_sibling_name` -- field name `"kind"` is kind-like, ratio 1.0
- `test_results_point_to_sibling_name_path` -- field name `"kind"` is kind-like, ratio 1.0
- `test_no_sibling_name_falls_back` -- field name `"kind"` is kind-like, ratio 1.0
- `test_no_kind_matches_empty_list` -- no Kind matches, returns empty (unchanged behavior)
- `test_case_insensitive_match` -- field name `"kind"`, ratio 1.0

**One existing test needs update:** `test_partial_matches` currently expects `["Issuer", "unknown"]` on field name `"kind"` to return 1 result. After this change, ratio = 1/2 = 0.5 < 0.6, so it should return empty. Update this test to expect `results == []`. If backward compatibility is needed for partial-match behavior, change the test enum to `["Issuer", "ClusterIssuer", "unknown"]` (ratio 2/3 = 0.67 >= 0.6) and expect 2 results.

## Implementation Details

### Constants to Add

At module level in `ref_detector.py`, add two constants:

```python
K8S_API_CONSTANTS: frozenset[str] = frozenset({
    "Orphan", "Background", "Foreground",
    "Cluster", "Namespaced",
    "Allow", "Deny", "Ignore",
})
```

These are standard K8s API enum values that collide with potential Kind names but are never actual Kind discriminators.

```python
_KIND_LIKE_FIELD_NAMES: frozenset[str] = frozenset({
    "kind", "targetKind", "resourceKind", "type",
})
```

These are field names that plausibly serve as Kind discriminators. The enum-kind detector should only fire when the field name (case-sensitive match on the leaf name) is in this set.

**Note on `"type"`:** Including `"type"` is borderline. Some CRDs use `type` as a Kind discriminator (e.g., Flux sourceRef's `type` field). However, `type` is extremely common for non-Kind purposes. The kindness ratio guard (>= 0.6) provides sufficient protection: if most enum values in a `type` field are not Kinds, the ratio will be too low to emit.

### Modification to `detect_enum_kind`

The function signature remains unchanged. The internal logic gains two new guard checks inserted after the existing empty-enum check and before the kind-matching loop:

1. **Kind-like field name guard:** Check `field.name` against `_KIND_LIKE_FIELD_NAMES`. If the field name is not kind-like, return `[]` immediately. This is the first new guard.

2. **Denylist filtering:** Before matching enum values against the registry, filter out any values present in `K8S_API_CONSTANTS`. This removes known false positives from both the match pool and the denominator.

3. **Kindness ratio check:** After matching remaining enum values against the registry, compute `match_ratio = len(matched_kinds) / len(remaining_enum_values)`. If `match_ratio < 0.6`, return `[]`. This prevents partial-match enums from generating edges.

The modified function flow:

```
detect_enum_kind(field, registry, sibling_fields):
    1. Extract enum_values from field.schema (existing)
    2. Guard: if not enum_values → return [] (existing)
    3. NEW: Guard: if field.name not in _KIND_LIKE_FIELD_NAMES → return []
    4. NEW: Filter enum_values through K8S_API_CONSTANTS denylist
    5. Guard: if no remaining values after filtering → return []
    6. Match remaining values against registry (existing logic)
    7. NEW: Compute match_ratio; if < 0.6 → return []
    8. Build ClassifiedField results (existing logic)
```

### Confidence Values

Confidence values remain unchanged from the existing implementation:
- With sibling `name` field: 0.95
- Without sibling `name` field: 0.80

The kindness ratio and field-name guards are **gatekeepers** (pass/fail), not confidence modifiers. They either allow the detector to proceed or block it entirely.

### Existing Test Update

The existing `test_partial_matches` test must be updated because the partial-match scenario `["Issuer", "unknown"]` on field `"kind"` now falls below the 0.6 ratio threshold (1/2 = 0.5). Two options:

**Option A (recommended):** Update the test to verify the new behavior -- partial match below threshold returns empty:

```python
def test_partial_matches_below_ratio(self, registry):
    """Enum ["Issuer", "unknown"] — ratio 0.5 < 0.6 → no match."""
    field = _make_field("kind", schema={
        "type": "string",
        "enum": ["Issuer", "unknown"],
    }, path="spec.issuerRef.kind")
    results = detect_enum_kind(field, registry)
    assert results == []
```

**Option B:** Change the test's enum to have a higher ratio (e.g., `["Issuer", "ClusterIssuer", "unknown"]` for ratio 2/3 = 0.67) and expect 2 results.

## Implementation Notes

**Implemented as planned** with 3 code review auto-fixes:
1. Fixed test_no_kind_matches_empty_list field name from "state" to "kind" (was testing field-name guard, not no-match path)
2. Renamed K8S_API_CONSTANTS → _K8S_API_CONSTANTS for naming consistency
3. Added boundary test at exactly 0.6 ratio (test_exact_ratio_boundary_accepted)

Used Option A for test_partial_matches update (verify ratio 0.5 returns empty).

**Files modified:**
- `platform-tools/idi/idi/generation/crd/ref_detector.py` — Added _K8S_API_CONSTANTS, _KIND_LIKE_FIELD_NAMES, 3 guards in detect_enum_kind
- `platform-tools/idi/tests/generation/crd/test_ref_detector.py` — Updated 2 existing tests, added 8 new tests

**Test counts:** 16 TestDetectEnumKind tests, 1022 total CRD tests passing.

## Verification

After implementation, run:

```bash
cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi
uv run pytest tests/generation/crd/test_ref_detector.py::TestDetectEnumKind -v
```

All existing `TestDetectEnumKind` tests must pass (with the one updated test), plus all new tests. Then run the full CRD test suite to confirm no regressions:

```bash
uv run pytest tests/generation/crd/ -v
```

The cycle-diff gate (described in the plan's testing strategy but not part of this section) should be run after all Phase 1 sections land to verify no new cycles were introduced.