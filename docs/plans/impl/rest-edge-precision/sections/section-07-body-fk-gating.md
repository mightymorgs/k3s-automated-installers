# Section 07: Body FK Activation Gating (Approach E Core)

## Overview

Restrict body FK detection to fire only when path hierarchy can't explain the dependency. This is the core of Approach E: the path skeleton is the authoritative backbone, and the fuzzy body FK matcher is fenced to ~30% of its current activation surface.

**Phase:** 2 | **Dependencies:** section-01, section-03, section-05 | **Blocks:** None

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/registry.py` | Modified: suppress body deps covered by path deps |
| `platform-tools/idi/idi/generation/dep_adapters/body_fk.py` | Modified: precondition gate + fn_lower hoist + resource_hint propagation + array type gate |
| `platform-tools/idi/tests/generation/rest/test_body_fk_gating.py` | Created: 15 tests (4 suppression + 10 precondition + 1 integration) |

---

## Tests

### test_body_fk_gating.py — 15 tests

**Level 1 (suppression):** 4 tests
- body dep suppressed when path dep covers same target resource
- body dep kept when target NOT covered by any path dep
- body deps to different targets than path deps are kept
- multiple path targets — body deps to any of them suppressed

**Level 2 (precondition gate):** 10 tests
- body field with _id suffix passes precondition gate
- body field with _uuid suffix passes precondition gate
- body field with format: uuid passes precondition gate
- body field with type: integer passes precondition gate
- body field "description" (string, no FK suffix) blocked at precondition
- body field "priority" (integer, no FK suffix) still passes (integer is strong type)
- body field "enabled" (boolean) blocked — not strong type, no suffix
- body field "token_max_ttl" (string) blocked — no suffix, not strong type
- array-of-integer passes gate (review fix)
- array-of-uuid passes gate (review fix)

**Integration:** 1 test
- path dep to "users" suppresses body dep to "users" on same operation

---

## Implementation Details

### Level 1: Post-detection suppression (registry.py)

In `registry.py:detect()`, after confidence filter (section-01), suppress body deps whose target is already covered by a path dep:

```python
path_targets = {d.target_resource for d in deps if d.source == "generic_odg:path"}
if path_targets:
    deps = [
        d for d in deps
        if d.source != "generic_odg:body" or d.target_resource not in path_targets
    ]
```

### Level 2: Pre-detection precondition (body_fk.py)

In `_walk_body()`, before calling `infer_target()`, check FK evidence:

```python
has_fk_suffix = _has_fk_suffix(fn_lower)
items = field_info.get("items", {}) if field_info.get("type") == "array" else {}
is_strong_type = (
    field_info.get("format") == "uuid"
    or field_info.get("type") == "integer"
    or (isinstance(items, dict) and items.get("type") == "integer")
    or (isinstance(items, dict) and items.get("format") == "uuid")
)
if not has_fk_suffix and not is_strong_type:
    _recurse_nested(...)
    continue
```

### Code review fixes applied

1. **fn_lower hoisted** — computed once at top of loop, reused in excluded check, credential check, and precondition gate
2. **resource_hint propagated** — added `resource_hint` parameter to `_recurse_nested()` and threaded through all 5 call sites in `_walk_body` and all 4 `_walk_body` calls inside `_recurse_nested`
3. **Array-of-integer/uuid gate** — precondition now checks array item types, not just direct field type
4. **Staging cleaned** — only section-07 files committed (unrelated changes from prior work unstaged)

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_body_fk_gating.py -v` — 15 passed
2. `uv run pytest tests/generation/rest/ -v` — 380 passed, full regression clean
