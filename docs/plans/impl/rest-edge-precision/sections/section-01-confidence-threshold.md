# Section 01: Confidence Threshold

## Overview

Add centralized confidence threshold filtering to the REST dependency detection pipeline. Currently, confidence scores are computed but never enforced — every non-None match is emitted regardless of score. This section adds `filter_by_confidence()` to `merge.py` and calls it from `registry.py`.

**Phase:** 1 | **Dependencies:** None | **Blocks:** section-07

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/merge.py` | Modify: add `filter_by_confidence()` function |
| `platform-tools/idi/idi/generation/dep_adapters/registry.py` | Modify: call `filter_by_confidence()` in `detect()` |
| `platform-tools/idi/tests/generation/rest/test_confidence_filter.py` | Create: unit tests |

---

## Tests (Write First)

### test_confidence_filter.py

```python
# Test: filter_by_confidence removes body deps below 0.25
# Test: filter_by_confidence keeps body deps at exactly 0.25
# Test: filter_by_confidence removes path deps below 0.50
# Test: filter_by_confidence keeps path deps at exactly 0.50
# Test: filter_by_confidence never filters link deps (threshold 0.0)
# Test: filter_by_confidence never filters annotation deps (threshold 0.0)
# Test: filter_by_confidence uses default 0.25 for unknown source strings
# Test: filter_by_confidence preserves dep ordering
# Test: empty deps list returns empty list
```

### Update existing tests

Some existing tests in `test_merge.py` or integration tests may emit edges that now fall below threshold. Update expectations to match new filtering behavior.

---

## Implementation Details

### merge.py changes

Add a module-level dict mapping source strings to minimum confidence thresholds:

```python
_SOURCE_THRESHOLDS: dict[str, float] = {
    "generic_odg:body": 0.25,
    "generic_odg:path": 0.50,
    "generic_odg:query": 0.25,
    "generic_odg:link": 0.0,
    "generic_odg:annotation": 0.0,
}
_DEFAULT_THRESHOLD = 0.25
```

Add `filter_by_confidence(deps: list[Dependency]) -> list[Dependency]` that filters deps below their source-specific threshold.

### registry.py changes

In `detect()`, after the existing `merge_deps()` and `filter_self_refs()` calls, add:
```python
deps = filter_by_confidence(deps)
```

Import `filter_by_confidence` from `merge.py`.

### Why per-source thresholds

Body FK scores max at ~0.49 (0.7 × 0.7 × 1.0). A global 0.7 threshold would kill ALL body FKs. Path deps range 0.4–0.8. Links/annotations are explicit (confidence 1.0). Per-source thresholds respect each adapter's scoring model.

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_confidence_filter.py -v`
2. `uv run pytest tests/generation/rest/ -v` — verify no regressions in existing tests
3. Run pipeline on vault spec and verify edge count decreases (~35 fewer body FP edges)

---

## Implementation Notes

**Status:** IMPLEMENTED

**Tests:** 11 passing (9 planned + 1 query threshold + 1 float-arithmetic boundary from code review)

**Deviations from plan:**
- No existing tests needed updating — all existing confidence values are >= 0.7, well above all thresholds
- Added `test_float_arithmetic_boundary` per code review finding: verifies behavior with multiplication-produced floats near threshold (e.g. `0.7 * 0.7 * 0.5 = 0.245`)
- `filter_self_refs` changes visible in diff are pre-existing branch work, not section-01 scope

**Files modified:**
- `platform-tools/idi/idi/generation/dep_adapters/merge.py` — added `_SOURCE_THRESHOLDS`, `_DEFAULT_THRESHOLD`, `filter_by_confidence()`
- `platform-tools/idi/idi/generation/dep_adapters/registry.py` — added `filter_by_confidence()` call after `filter_self_refs()`

**Files created:**
- `platform-tools/idi/tests/generation/rest/test_confidence_filter.py` — 11 tests

**Full REST suite:** 312 tests passing, 0 regressions
