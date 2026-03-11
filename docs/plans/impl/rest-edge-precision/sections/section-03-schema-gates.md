# Section 03: OpenAPI Schema Signal Gates

## Overview

Add non-FK signal detection to `_type_factor()` in `target_inference.py`. OpenAPI schemas contain multiple signals that prove a field is NOT a foreign key — enum constraints, readOnly, non-FK formats, and pattern constraints. These are currently ignored.

**Phase:** 1 | **Dependencies:** None | **Blocks:** section-07

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/target_inference.py` | Modified: added `_NON_FK_FORMATS` frozenset and 4 gate checks in `_type_factor()` |
| `platform-tools/idi/tests/generation/rest/test_target_inference.py` | Created: 20 tests (18 planned + 2 edge case from review) |

---

## Tests (Write First)

Add to existing `test_target_inference.py`:

```python
# Test: _type_factor returns 0.0 for field with enum: ["read", "write"]
# Test: _type_factor returns 0.0 for field with enum: [1, 2, 3] (integer enum)
# Test: _type_factor returns 0.0 for readOnly: true
# Test: _type_factor returns 0.0 for format: "date-time"
# Test: _type_factor returns 0.0 for format: "email"
# Test: _type_factor returns 0.0 for format: "uri"
# Test: _type_factor returns 0.0 for format: "ipv4"
# Test: _type_factor returns 0.0 for format: "duration"
# Test: _type_factor returns 0.0 for format: "hostname"
# Test: _type_factor returns 0.0 for format: "password"
# Test: _type_factor returns 0.1 for string with pattern constraint
# Test: _type_factor still returns 1.0 for integer without enum
# Test: _type_factor still returns 1.0 for format: "uuid"
# Test: enum check fires before type branching (integer+enum → 0.0, not 1.0)
# Test: readOnly check fires before type branching
```

---

## Implementation Details

### target_inference.py _type_factor() changes

Add three checks at the TOP of `_type_factor()`, before the type-based branching logic:

1. **Enum check** — `if field_info.get("enum"): return 0.0`
   - OpenAPI enums have a base type (string/integer), so they pass through existing type branches and never reach the catch-all. Must check before type branching.

2. **readOnly check** — `if field_info.get("readOnly"): return 0.0`
   - Server-generated fields can't be consumer inputs.

3. **Non-FK format check** — Define a frozen set of non-FK formats and return 0.0 if `fmt` is in it:
   ```python
   _NON_FK_FORMATS = frozenset({
       "date-time", "date", "time", "duration",
       "email", "idn-email", "uri", "uri-reference",
       "iri", "iri-reference", "ipv4", "ipv6",
       "hostname", "idn-hostname", "byte", "binary", "password",
   })
   ```
   This check goes after `fmt = field_info.get("format", "")` is extracted, before the type branching.

4. **Pattern constraint** — `if field_info.get("pattern") and ftype == "string": return 0.1`
   - Heavily penalized but not fully excluded (some IDs have patterns like UUID format).

### Order matters

The existing `_NEVER_FK_FIELDS` check stays first. Then: enum → readOnly → non-FK format → pattern → existing type branching.

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_target_inference.py -v`
2. Run pipeline on keycloak spec, verify enum fields like `permission`, `protocol` no longer produce edges

## Implementation Notes

- Test file was **created** (not modified) — no pre-existing `test_target_inference.py`
- Code review added 2 edge-case tests: `test_empty_enum_does_not_trigger_gate` and `test_readonly_false_does_not_trigger_gate`
- Updated stale catch-all comment ("Boolean, enum, etc." → "Boolean, object, etc.") since enum is now caught earlier
- Full test suite: 1389 passing, 0 regressions
