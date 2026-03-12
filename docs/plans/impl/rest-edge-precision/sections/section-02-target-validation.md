# Section 02: Target Existence Validation

## Overview

Validate that dependency target paths actually exist before emitting them. Currently, `cli.py` constructs `dep_path = "service/resource/create"` without checking whether that operation was generated. Resources from GET-only endpoints appear in `known_resources` but have no POST, creating phantom targets like `csr/create`.

**Phase:** 1 | **Dependencies:** None | **Blocks:** None

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/cli.py` | Modify: add existence check in depends_on construction |
| `platform-tools/idi/tests/generation/rest/test_target_validation.py` | Create: unit tests |

---

## Tests (Write First)

### test_target_validation.py

```python
# Test: dep to skill path present in ctx.generated_skill_paths is kept
# Test: dep to skill path NOT in ctx.generated_skill_paths is dropped
# Test: dep with target_service set constructs path correctly for validation
# Test: depends_on list has no phantom targets after filtering
# Test: valid deps are preserved with all fields intact (path, source, field, fact_ref, etc.)
```

---

## Implementation Details

### cli.py changes

In `_generate_json_v2()`, the `depends_on` list comprehension (currently lines ~230–241) builds all deps unconditionally. Change from a list comprehension to a loop with a guard:

```python
depends_on = []
for d in deps_detected:
    dep_path = f"{d.target_service or ctx.api_name}/{d.target_resource}/{_resolve_target_operation(...)}"
    if dep_path not in ctx.generated_skill_paths:
        continue  # Phantom target — skip
    depends_on.append({...})
```

`ctx.generated_skill_paths` is already populated in Pass 1 (lines 100–110) before Pass 2 begins, so the data is available.

### Why this works

The pipeline has two independent resource name sets:
1. `known_resources` — includes resources from ALL paths (GET, LIST, DELETE, etc.)
2. `ctx.generated_skill_paths` — only real generated operation paths

Detection matches against `known_resources` (which contains GET-only resources), then emits `target_operation="create"`. The constructed path like `vault/csr/create` may not exist because `csr` has no POST endpoint. This guard closes that gap.

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_target_validation.py -v`
2. Run pipeline on vault spec, verify no edges to phantom targets like `csr/create`, `token-max-ttl/create`

---

## Implementation Notes

**Status:** IMPLEMENTED

**Tests:** 7 passing (5 planned + cross-service bypass + non-create operation)

**Deviations from plan:**
- Cross-service deps bypass existence check (user decision): when `d.target_service` is set, skip validation since `generated_skill_paths` only has current-service paths
- field_refs_map and all_field_refs now iterate `validated_deps` (not raw `deps_detected`) to prevent phantom leaks downstream
- Removed dead `_OPERATION_PREFERENCE`, `resource_ops`, and no-op `_resolve_target_operation` function
- Added `logging.getLogger(__name__)` and `logger.debug` for dropped phantom targets
- Changed list comprehension to loop with dep_path as `d.target_operation` directly (removed `_resolve_target_operation` call)

**Files modified:**
- `platform-tools/idi/idi/generation/cli.py` — phantom guard, cross-service bypass, dead code removal, logging

**Files created:**
- `platform-tools/idi/tests/generation/rest/test_target_validation.py` — 7 tests
