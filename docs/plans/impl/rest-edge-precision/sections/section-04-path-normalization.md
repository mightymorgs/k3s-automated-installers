# Section 04: Underscore/Hyphen Path Normalization

## Overview

Normalize underscores to hyphens in `_match_segment()` so URL path segments match resource names. `build_resource_name()` produces hyphenated names (`tag-protections`) but URL segments use underscores (`tag_protections`). Without normalization, the immediate parent can't match and the param falls through to a distant (wrong) ancestor.

**Phase:** 1 | **Dependencies:** None | **Blocks:** section-05

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/path_deps.py` | Modified: 1-line normalization in `_match_segment()` |
| `platform-tools/idi/tests/generation/rest/test_path_deps.py` | Created: 6 tests for underscore/hyphen normalization |

---

## Tests (Write First)

Add to existing `test_path_deps.py`:

```python
# Test: _match_segment("tag_protections", {"tag-protections"}) → "tag-protections"
# Test: _match_segment("user_groups", {"user-groups"}) → "user-groups"
# Test: _match_segment("groups", {"groups"}) → "groups" (no underscore, unchanged)
# Test: _match_segment("api_v3_series", {"api-v3-series"}) → "api-v3-series"
# Test: detect_path_deps on /repos/{owner}/tag_protections/{id} resolves {id} to tag-protections
```

---

## Implementation Details

One-line fix at the top of `_match_segment()`:

```python
def _match_segment(candidate: str, known_resources: set[str]) -> str | None:
    candidate = candidate.replace("_", "-")  # Normalize to match resource names
    # ... rest of function unchanged
```

This is safe because resource names are always hyphenated (produced by `build_resource_name()`). URL segments may use underscores or hyphens depending on the API. Normalizing to hyphens makes the comparison consistent.

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_path_deps.py -v`
2. Run pipeline on gitea spec, verify `{id}` in underscore-named paths resolves to correct parent

## Implementation Notes

- Test file was **created** (not modified) — no pre-existing `test_path_deps.py`
- Added 1 extra test beyond plan: `test_already_hyphenated_still_matches` and `test_no_match_returns_none`
- Full test suite: 1402 passing, 0 regressions
