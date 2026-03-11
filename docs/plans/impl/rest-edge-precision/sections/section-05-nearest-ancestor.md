# Section 05: Nearest Ancestor Preference

## Overview

Change `detect_path_deps()` to emit only the nearest matching ancestor segment instead of all ancestors. Currently, for `/users/{id}/groups/{groupId}`, it matches `{groupId}` to both `groups` (correct) and `users` (wrong). The fix takes the first match and stops.

**Phase:** 2 | **Dependencies:** section-04 | **Blocks:** section-07

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/path_deps.py` | Modify: change ancestor walk in `detect_path_deps()` |
| `platform-tools/idi/tests/generation/rest/test_path_deps.py` | Modify: add/update nearest ancestor tests |

---

## Tests (Write First)

8 tests in `TestNearestAncestor` class:
- `test_multi_level_only_nearest` — groupId → groups ONLY, no users edge
- `test_triple_level_only_nearest` — z → c (nearest), NOT a or b
- `test_single_level_unchanged` — /users/{id} → users
- `test_no_ancestor_falls_back_to_param_name` — /api/v1/{realmId} → realms (confidence 0.6)
- `test_nearest_ancestor_confidence_0_8` — confidence always 0.8
- `test_structural_match_over_param_name` — {groupId} under /entries/ → "entries" (structural wins)
- `test_consistent_param_no_override` — {userId} under /users/ → "users"
- `test_existing_multi_level_gets_single_edge` — 3-level path, 1 dep per param

---

## Implementation Details (Actual)

### detect_path_deps() changes

The backward walk was changed to `break` on first match from `_match_segment()`:

1. On first match, emit the edge and **break** out of the backward walk.
2. Removed `matched_ancestor` flag and `depth` counter — replaced by the break.
3. If the loop completes without matching, falls back to `_infer_from_param_name()` as before.

**Cross-check removed during code review:** The planned param-name cross-check was removed because it unconditionally overrides structural position, which violates precision-first design. Example: `{roleId}` under `/bindings/` would incorrectly override "bindings" → "roles". Structural matching is more reliable than param-name inference.

### Confidence

The nearest ancestor always gets confidence 0.8. No more distance decay. Fallback param-name inference keeps confidence 0.6.

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_path_deps.py -v`
2. Run pipeline on keycloak spec, verify `{groupId}` no longer produces edge to `users`
