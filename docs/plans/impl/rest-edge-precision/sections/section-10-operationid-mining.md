# Section 10: operationId Convention Mining

## Overview

New lightweight adapter that parses `operationId` and `summary` strings for patterns encoding cross-resource relationships. Most spec generators (Swagger-codegen, Autorest) embed verb+resource patterns like `CreateGroupForUser` or `AddUserToGroup`.

**Phase:** 3 | **Dependencies:** None | **Blocks:** None

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/operationid_deps.py` | Created: new adapter (~160 LOC) |
| `platform-tools/idi/tests/generation/rest/test_operationid_deps.py` | Created: 28 tests |
| `platform-tools/idi/idi/generation/dep_adapters/base.py` | Modified: added `DetectionSource.OPERATIONID` |
| `platform-tools/idi/idi/generation/dep_adapters/merge.py` | Modified: added threshold 0.50 |
| `platform-tools/idi/idi/generation/dep_adapters/registry.py` | Modified: added operationid to fenced sources |
| `platform-tools/idi/tests/generation/rest/test_data_model.py` | Modified: enum count 15→16 |

---

## Tests (Write First)

### test_operationid_deps.py

```python
# Test: "createGroupForUser" → dep from current resource to "users"
# Test: "addUserToGroup" → dep from current resource to "users" (or "group" depending on parse)
# Test: "listOrdersByCustomer" → dep from current resource to "customers"
# Test: "listUsers" → no cross-resource dependency extracted
# Test: "deleteUser" → no cross-resource dependency extracted
# Test: operationId with no recognizable pattern → empty list
# Test: None/empty operationId → empty list
# Test: matched resource must exist in known_resources (no phantom targets)
# Test: confidence capped at 0.5
# Test: source string is "generic_odg:operationid"
# Test: adapter matches all specs (universal adapter)
# Test: adapter priority is lower than links and annotations
```

---

## Implementation Details

### New adapter: operationid_deps.py

Create a new `DepAdapter` implementation:

```python
class OperationIdDepAdapter:
    name = "operationid"
    priority = 5  # Low priority — below links (100), annotations (90), generic (10)
```

**Detection logic:**

1. Get `operationId` from the operation (available via spec lookup using `operation.path` and `operation.method`)
2. Split camelCase/PascalCase into words
3. Look for cross-resource patterns:
   - `{verb}{Resource}For{Parent}` → depends on parent
   - `{verb}{Resource}By{Parent}` → depends on parent
   - `{verb}{Resource}To{Target}` → depends on target
   - `Add{X}To{Y}` → depends on both X and Y resources
4. Match extracted resource names against `known_resources` using `_match_segment()` or direct lookup
5. Emit `Dependency` with confidence 0.5 and `source="generic_odg:operationid"`

**Important constraints:**
- Only emit when matched resource exists in `known_resources`
- Confidence capped at 0.5 (convention-dependent, not structural)
- Don't duplicate edges already found by path/body detection (merge handles this)

### Integration

The adapter is auto-discovered by `registry.py:_discover_python()` since it's a `.py` file in `dep_adapters/`. It must implement the `DepAdapter` protocol: `name`, `priority`, `matches()`, `detect_dependencies()`, `detect_outputs()`.

`matches()` returns `True` for all specs (universal adapter). `detect_outputs()` returns empty list.

### Accessing operationId

The `OperationInfo` dataclass doesn't currently carry `operationId`. Two options:
1. Look it up from `spec["paths"][operation.path][operation.method.lower()]["operationId"]`
2. Add `operation_id: str | None` to `OperationInfo`

Option 1 avoids modifying the data model. The spec is already passed to `detect_dependencies()`.

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_operationid_deps.py -v` — 28 pass
2. Full suite: 1488 pass — zero regressions

## Deviations from Plan

- **summary parsing omitted** — summary text is freeform/unreliable; operationId only
- **Option 1 chosen** for operationId access (spec lookup, no data model change)
- **Code review fixes:** safe singular (`[:-1]` not `rstrip('s')`), `DetectionSource.OPERATIONID` enum, threshold raised to 0.50, duplicate suppression in registry
