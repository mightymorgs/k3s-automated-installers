# Section 09: Suffix Containment Hardening

## Overview

Increase the minimum token length for suffix containment matching in `_match_resource()` from 4 to 7. Short tokens like `type` (4 chars), `mode` (4 chars), and `realm` (5 chars) produce false matches via suffix containment.

**Phase:** 3 | **Dependencies:** None | **Blocks:** None

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/target_inference.py` | Modify: change min length in suffix containment |
| `platform-tools/idi/tests/generation/rest/test_target_inference.py` | Modify: add/update suffix containment tests |

---

## Tests (Write First)

7 tests in `TestSuffixContainmentHardening` class:
- `test_4char_type_does_not_suffix_match` — asserts `result is None`
- `test_5char_realm_does_not_suffix_match` — asserts `result is None`
- `test_6char_method_does_not_suffix_match` — asserts `result is None`
- `test_6char_source_does_not_suffix_match` — asserts `result is None` (added in review)
- `test_7char_profile_does_suffix_match` — matches `qualityprofile`, conf 0.2
- `test_8char_provider_does_suffix_match` — matches `auth-provider`, conf 0.2
- `test_short_candidates_still_match_via_other_strategies` — exact match unaffected

---

## Implementation Details

One-line change in `_match_resource()` at the suffix containment block (line ~349):

```python
# Before:
if len(candidate) >= 4:

# After:
if len(candidate) >= 7:
```

This eliminates false matches like:
- `method` (6 chars) matching `sysmfamethod`
- `source` (6 chars) matching `managed-resources`
- `realm` (5 chars) matching `roles-composites-realm`
- `type` (4 chars) matching various resources

Tokens of 7+ chars are specific enough to be meaningful suffix matches (e.g., `profile` matching `qualityprofile`).

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_target_inference.py -v` — 27 pass
2. Full suite: 1459 pass — no recall loss on known true-positive suffix matches
3. Code review auto-fixes: strict `assert result is None` for negative tests, added `source` test
