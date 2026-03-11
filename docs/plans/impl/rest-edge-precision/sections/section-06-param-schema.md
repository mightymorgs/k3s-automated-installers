# Section 06: Path Parameter Schema Passthrough

## Overview

Pass full OpenAPI parameter schemas through to `detect_path_deps()` so it can check enum constraints, format, and type. Currently `OperationInfo.path_params` is `list[str]` — just names. The full parameter objects are available in the spec but not propagated.

**Phase:** 2 | **Dependencies:** None | **Blocks:** section-08

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/base.py` | Modify: add `path_param_schemas` field to `OperationInfo` |
| `platform-tools/idi/idi/generation/cli.py` | Modify: extract param schemas when building `OperationInfo` |
| `platform-tools/idi/idi/generation/dep_adapters/path_deps.py` | Modify: check param schemas in `detect_path_deps()` |
| `platform-tools/idi/tests/generation/rest/test_param_schema.py` | Create: unit tests |

---

## Tests (Actual)

### test_param_schema.py — 11 tests

**TestOperationInfoParamSchemas (2):** accepts path_param_schemas, defaults to empty dict
**TestEnumParamSkipped (5):** enum skipped, non-enum processed, uuid format processed, missing schema default, enum among normal params
**TestParamSchemaExtraction (4):** OAS3 nested schema, Swagger2 fallback, operation-level override, query params ignored

---

## Implementation Details

### base.py changes

Add field to `OperationInfo`:
```python
path_param_schemas: dict[str, dict] = field(default_factory=dict)
```

### cli.py changes

When building the `OperationInfo` for each operation, extract param schemas from the operation's `parameters` array (and/or the path-level parameters):

```python
param_schemas = {}
for param in operation_obj.get("parameters", []):
    if param.get("in") == "path":
        param_schemas[param["name"]] = param.get("schema", param)  # OAS3 vs Swagger2
```

Pass `path_param_schemas=param_schemas` to the `OperationInfo` constructor.

Note: Swagger 2.0 specs have `type`/`enum` directly on the parameter object (no nested `schema`). The extraction should handle both formats.

### path_deps.py changes

In `detect_path_deps()`, after extracting the param name from `{param}`, check the schema:

```python
param_schema = operation.path_param_schemas.get(param, {})
if param_schema.get("enum"):
    continue  # Routing param with fixed values, not an FK
```

This catches params like `{type}` with values `["aws-kms", "pkcs11"]` that are routing selectors, not resource IDs.

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_param_schema.py -v`
2. `uv run pytest tests/generation/rest/test_path_deps.py -v` — verify no regressions
3. Run pipeline on vault spec, verify `{type}` params with enum no longer produce edges
