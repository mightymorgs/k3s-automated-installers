# Section 08: Statistical Namespace Detection

## Overview

Detect routing/namespace path parameters programmatically from the spec instead of maintaining a manual exclusion list. The current `_EXCLUDED = {"namespace", "namespaces", "ns"}` misses `{realm}` (Keycloak), `{tenant}` (multi-tenant APIs), and `{*_mount_path}` (Vault).

**Phase:** 2 | **Dependencies:** section-06 | **Blocks:** None

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/base.py` | Modified: added `namespace_params: frozenset[str]` to OperationInfo |
| `platform-tools/idi/idi/generation/dep_adapters/path_deps.py` | Modified: added `detect_namespace_params()`, merged with `_EXCLUDED` in `detect_path_deps()` |
| `platform-tools/idi/idi/generation/cli.py` | Modified: precompute namespace params per spec, pass to DepOpInfo |
| `platform-tools/idi/tests/generation/rest/test_namespace_detection.py` | Created: 10 tests |

---

## Tests — 10 tests

**Detection (7 tests):**
- param in 80% of ops with 20 distinct children → namespace
- param in 10% of ops → NOT namespace (low frequency)
- param in 50% of ops with 2 children → NOT namespace (low dispersion)
- keycloak-like spec with {realm} in most paths → detected
- vault {pki_mount_path} in 15% of paths → NOT namespace
- multiple namespace params detected simultaneously
- spec with no high-frequency params → empty set

**Integration (3 tests):**
- namespace param excluded from path dep detection
- non-namespace params still produce edges
- base _EXCLUDED set (namespace, ns) still works

---

## Implementation Details

### detect_namespace_params(spec) — path_deps.py

Two-factor rule:
1. **Frequency:** param appears in ≥30% of operations
2. **Dispersion:** param has ≥5 distinct non-param child segments

Uses positive HTTP method allowlist (`get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `trace`) to count operations — avoids counting OAS path-level keys like `summary`/`description`.

### Integration — path_deps.py

Excluded set hoisted above loop (computed once):
```python
excluded = _EXCLUDED | (operation.namespace_params or frozenset())
```

### Precomputation — cli.py

`detect_namespace_params(ctx.schema)` called once per spec, result passed to every `DepOpInfo` via the `namespace_params` field.

### Code review fixes applied

1. **HTTP method allowlist** — replaced negative blocklist with positive set of 8 HTTP methods
2. **Hoisted excluded set** — moved computation above the for-loop

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_namespace_detection.py -v` — 10 passed
2. `uv run pytest tests/generation/rest/ -v` — 390 passed, full regression clean
