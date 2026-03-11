I now have a complete picture. Let me generate the section content.

# Section 01: Data Model Changes

## Overview

This section adds traceability metadata to the REST dependency detection pipeline. Two changes are required:

1. A new `DetectionSource` enum (a `str, Enum` subclass) with 15 members, providing typed algorithm identifiers for every edge the pipeline emits.
2. A new `detection_source` field on the `Dependency` dataclass that accepts this enum.

The existing `lineage_type` field on `Dependency` already exists (default `"copy"`). The plan calls for it to also accept `"explicit"` and `"inferred"` values. Since the field already exists as a plain `str`, no dataclass change is needed for `lineage_type` -- but all later sections will rely on the convention that `"explicit"` means ground-truth (confidence >= 0.95, from OpenAPI links or annotations) and `"inferred"` means heuristic detection.

Additionally, this section adds `$ref` resolution memoization to `spec_loader.py` to prevent O(N^2) behavior on large specs.

**This section has no dependencies and blocks every other section.**

---

## File Inventory

All paths are relative to the repository root `/Users/morgan/GitRepo/k3s-automated-installers/`.

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/base.py` | Modify: add `DetectionSource` enum, add `detection_source` field to `Dependency` |
| `platform-tools/idi/idi/generation/dep_adapters/__init__.py` | Modify: export `DetectionSource` |
| `platform-tools/idi/idi/generation/dep_adapters/body_fk.py` | Modify: set `detection_source=DetectionSource.DEFAULT` on emitted Dependencies |
| `platform-tools/idi/idi/generation/dep_adapters/path_deps.py` | Modify: set `detection_source=DetectionSource.DEFAULT` on emitted Dependencies |
| `platform-tools/idi/idi/generation/dep_adapters/query_fk.py` | Modify: set `detection_source=DetectionSource.DEFAULT` on emitted Dependencies |
| `platform-tools/idi/idi/generation/dep_adapters/obj_pattern.py` | Modify: set `detection_source=DetectionSource.DEFAULT` on emitted Dependencies |
| `platform-tools/idi/idi/generation/dep_adapters/discriminator.py` | Modify: set `detection_source=DetectionSource.DEFAULT` on emitted Dependencies |
| `platform-tools/idi/idi/generation/dep_adapters/yaml_adapter.py` | Modify: set `detection_source=DetectionSource.DEFAULT` on emitted Dependencies |
| `platform-tools/idi/idi/generation/dep_adapters/crd_dep.py` | Modify: set `detection_source=DetectionSource.DEFAULT` on emitted Dependencies |
| `platform-tools/idi/idi/generation/dep_adapters/olm_deps.py` | Modify: set `detection_source=DetectionSource.DEFAULT` on emitted Dependencies |
| `platform-tools/idi/idi/generation/dep_adapters/rbac_deps.py` | Modify: set `detection_source=DetectionSource.DEFAULT` on emitted Dependencies |
| `platform-tools/idi/idi/generation/spec_loader.py` | Modify: add memoization cache to `_resolve_refs` |
| `platform-tools/idi/tests/generation/rest/__init__.py` | Create: empty package init |
| `platform-tools/idi/tests/generation/rest/test_data_model.py` | Create: unit tests |
| `platform-tools/idi/tests/generation/rest/conftest.py` | Create: shared fixtures |

---

## Tests (Write First)

Create the test directory and files before implementation. The test file goes at `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_data_model.py`.

### test_data_model.py

```python
"""Tests for DetectionSource enum and Dependency dataclass changes."""
import json

import pytest

from idi.generation.dep_adapters.base import Dependency, DetectionSource


class TestDetectionSourceEnum:
    """DetectionSource enum members have correct string values and serialize to JSON."""

    def test_enum_members_have_correct_string_values(self):
        """Each member's value is a 'rest:xxx' namespaced string."""
        assert DetectionSource.DEFAULT == "rest:default"
        assert DetectionSource.CREDENTIAL_REGEX == "rest:credential_regex"
        assert DetectionSource.READONLY_FIELD == "rest:readonly_field"
        assert DetectionSource.WRITEONLY_FIELD == "rest:writeonly_field"
        assert DetectionSource.FK_SUFFIX == "rest:fk_suffix"
        assert DetectionSource.SCHEMA_NORMALIZE == "rest:schema_normalize"
        assert DetectionSource.PRODUCER_VALIDITY == "rest:producer_validity"
        assert DetectionSource.ID_SYNONYM == "rest:id_synonym"
        assert DetectionSource.OPENAPI_LINK == "rest:openapi_link"
        assert DetectionSource.ENVELOPE_UNWRAP == "rest:envelope_unwrap"
        assert DetectionSource.NESTED_PRODUCER == "rest:nested_producer"
        assert DetectionSource.RESPONSE_WALK == "rest:response_walk"
        assert DetectionSource.READONLY_DIFF == "rest:readonly_diff"
        assert DetectionSource.NESTED_FK == "rest:nested_fk"
        assert DetectionSource.ANNOTATION == "rest:annotation"

    def test_enum_is_str_subclass(self):
        """DetectionSource is a str subclass so it serializes to JSON without a custom encoder."""
        assert isinstance(DetectionSource.DEFAULT, str)

    def test_enum_json_serializable(self):
        """The enum value serializes directly to JSON without a custom encoder."""
        result = json.dumps({"source": DetectionSource.OPENAPI_LINK})
        assert '"rest:openapi_link"' in result

    def test_enum_has_15_members(self):
        """The enum has exactly 15 members."""
        assert len(DetectionSource) == 15


class TestDependencyDataclass:
    """Dependency dataclass accepts the new detection_source field."""

    def test_accepts_detection_source_enum(self):
        """Dependency can be constructed with a DetectionSource enum value."""
        dep = Dependency(
            field="user_id",
            target_resource="users",
            detection_source=DetectionSource.FK_SUFFIX,
        )
        assert dep.detection_source == DetectionSource.FK_SUFFIX

    def test_detection_source_defaults_to_default(self):
        """When detection_source is not specified, it defaults to DetectionSource.DEFAULT."""
        dep = Dependency(field="user_id", target_resource="users")
        assert dep.detection_source == DetectionSource.DEFAULT

    def test_lineage_type_explicit(self):
        """Dependency accepts lineage_type='explicit' for ground-truth edges."""
        dep = Dependency(
            field="user_id",
            target_resource="users",
            lineage_type="explicit",
        )
        assert dep.lineage_type == "explicit"

    def test_lineage_type_inferred(self):
        """Dependency accepts lineage_type='inferred' for heuristic edges."""
        dep = Dependency(
            field="user_id",
            target_resource="users",
            lineage_type="inferred",
        )
        assert dep.lineage_type == "inferred"

    def test_existing_fields_unchanged(self):
        """All pre-existing Dependency fields still work as before."""
        dep = Dependency(
            field="user_id",
            target_resource="users",
            target_operation="create",
            fact_ref="facts://myapi/users#id",
            confidence=0.8,
            source="generic_odg:body",
            lineage_type="copy",
            discriminator_value=None,
            target_service=None,
            satisfaction="required_value",
        )
        assert dep.field == "user_id"
        assert dep.confidence == 0.8
        assert dep.source == "generic_odg:body"


class TestExistingAdaptersEmitDefault:
    """Existing adapters should emit DetectionSource.DEFAULT when not overridden."""

    def test_default_value_on_construction_without_kwarg(self):
        """Constructing Dependency without detection_source gives DEFAULT."""
        dep = Dependency(
            field="org_id",
            target_resource="organizations",
            source="generic_odg:body",
        )
        assert dep.detection_source == DetectionSource.DEFAULT
```

### conftest.py

Create the shared fixtures file at `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/conftest.py`.

```python
"""Shared fixtures for REST pipeline improvement tests."""
import pytest


@pytest.fixture
def minimal_openapi_spec():
    """Valid OAS 3.0 spec with 2 operations for basic pipeline testing."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "email": {"type": "string"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/users/{user_id}": {
                "get": {
                    "operationId": "getUser",
                    "parameters": [
                        {"name": "user_id", "in": "path", "required": True}
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        }
                    },
                }
            },
        },
    }


@pytest.fixture
def known_resources():
    """Set of resource names for FK matching in tests."""
    return {"users", "organizations", "teams", "projects", "roles"}
```

### Test for $ref memoization

Add the following test to `test_data_model.py` (or a separate `test_ref_memoization.py` if preferred):

```python
class TestRefMemoization:
    """$ref resolution memoization prevents redundant work."""

    def test_same_ref_resolved_once(self):
        """When the same $ref is encountered multiple times, it is resolved from cache."""
        from idi.generation.spec_loader import _resolve_refs

        spec = {
            "components": {
                "schemas": {
                    "Shared": {"type": "object", "properties": {"id": {"type": "string"}}}
                }
            }
        }
        obj = {
            "a": {"$ref": "#/components/schemas/Shared"},
            "b": {"$ref": "#/components/schemas/Shared"},
            "c": {"$ref": "#/components/schemas/Shared"},
        }
        result = _resolve_refs(obj, spec)
        # All three should resolve to the same schema structure.
        assert result["a"]["properties"]["id"]["type"] == "string"
        assert result["b"]["properties"]["id"]["type"] == "string"
        assert result["c"]["properties"]["id"]["type"] == "string"
```

---

## Implementation Details

### 1. DetectionSource Enum in base.py

Add the `DetectionSource` enum to `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/base.py`, above the `Dependency` dataclass. It must:

- Inherit from both `str` and `Enum` (i.e., `class DetectionSource(str, Enum)`) so that instances are simultaneously valid strings. This means `json.dumps({"detection_source": DetectionSource.FK_SUFFIX})` works without a custom encoder.
- Have exactly 15 members with `"rest:xxx"` string values.

The full member list:

| Member | Value |
|--------|-------|
| `DEFAULT` | `"rest:default"` |
| `CREDENTIAL_REGEX` | `"rest:credential_regex"` |
| `READONLY_FIELD` | `"rest:readonly_field"` |
| `WRITEONLY_FIELD` | `"rest:writeonly_field"` |
| `FK_SUFFIX` | `"rest:fk_suffix"` |
| `SCHEMA_NORMALIZE` | `"rest:schema_normalize"` |
| `PRODUCER_VALIDITY` | `"rest:producer_validity"` |
| `ID_SYNONYM` | `"rest:id_synonym"` |
| `OPENAPI_LINK` | `"rest:openapi_link"` |
| `ENVELOPE_UNWRAP` | `"rest:envelope_unwrap"` |
| `NESTED_PRODUCER` | `"rest:nested_producer"` |
| `RESPONSE_WALK` | `"rest:response_walk"` |
| `READONLY_DIFF` | `"rest:readonly_diff"` |
| `NESTED_FK` | `"rest:nested_fk"` |
| `ANNOTATION` | `"rest:annotation"` |

Import requirements: add `from enum import Enum` to the imports in `base.py`.

### 2. Dependency Dataclass Update

Add a `detection_source` field to the `Dependency` dataclass with a default value of `DetectionSource.DEFAULT`. This must be placed after the existing `source` field to maintain backward compatibility with positional construction (though all existing call sites use keyword arguments, so ordering is a minor concern).

The field signature:

```python
detection_source: DetectionSource = DetectionSource.DEFAULT
```

The existing `lineage_type` field already exists with default `"copy"`. No change is needed to the field itself. Later sections will set it to `"explicit"` (for links/annotations at confidence >= 0.95) or `"inferred"` (for heuristic detection). The current adapters already use `"copy"` and `"reference"` -- these remain valid values.

### 3. Update __init__.py Exports

In `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/__init__.py`, add `DetectionSource` to both the import and `__all__`:

```python
from idi.generation.dep_adapters.base import (
    DepAdapter,
    Dependency,
    DetectionSource,
    OperationInfo,
    Output,
)

__all__ = [
    "DepAdapter",
    "DepAdapterRegistry",
    "Dependency",
    "DetectionSource",
    "OperationInfo",
    "Output",
]
```

### 4. Update All Existing Adapter Call Sites

Every file that constructs a `Dependency(...)` must be updated to include `detection_source=DetectionSource.DEFAULT`. Since the field has a default value, this is technically optional for backward compatibility -- but the plan explicitly states "all existing adapters should set `detection_source = DetectionSource.DEFAULT` as a baseline." Being explicit prevents future confusion about whether the default was intentional or an oversight.

Files with `Dependency(` constructor calls that need updating (10 files total):

1. **`body_fk.py`** -- line 106: 1 call site. Add `detection_source=DetectionSource.DEFAULT` and import `DetectionSource` from `.base`.
2. **`path_deps.py`** -- line 50: 1 call site. Same treatment.
3. **`query_fk.py`** -- line 112: 1 call site. Same treatment.
4. **`obj_pattern.py`** -- line 50: 1 call site. Same treatment.
5. **`discriminator.py`** -- line 33: 1 call site. Same treatment.
6. **`yaml_adapter.py`** -- line 54: 1 call site. Same treatment.
7. **`crd_dep.py`** -- line 126: 1 call site. Same treatment.
8. **`olm_deps.py`** -- line 73: 1 call site. Same treatment.
9. **`rbac_deps.py`** -- lines 238, 383, 455: 3 call sites. Same treatment.

Each file already imports `Dependency` from `idi.generation.dep_adapters.base`. Add `DetectionSource` to that import line.

**Important:** Since the `detection_source` field has a default value, existing tests that construct `Dependency` objects without specifying `detection_source` will continue to pass without modification. The 810 existing CRD tests should remain green after this change.

### 5. $ref Resolution Memoization in spec_loader.py

Add a memoization cache to `_resolve_refs` in `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/spec_loader.py`. The cache should be keyed by the `$ref` string and scoped to a single `load_spec` invocation (not global, to avoid stale cross-spec references).

Implementation approach:

- Add an optional `memo` parameter (default `None`) to `_resolve_refs`. When `None`, create a fresh `dict` on first call.
- When encountering a `$ref` that is already in `memo`, return a `copy.deepcopy` of the cached result instead of re-resolving.
- After resolving a `$ref` for the first time, store the result in `memo` before returning.
- Thread the `memo` dict through all recursive calls.

This is a pure performance optimization. The behavior is identical to the current implementation -- only the number of redundant `_follow_ref` + `_resolve_refs` calls changes. The existing cycle detection via the `seen` set remains unchanged and operates independently of the memo cache (the `seen` set tracks the current resolution stack to prevent infinite recursion; the `memo` cache stores previously-completed resolutions to prevent redundant work).

The cache should be keyed by the raw `$ref` string (e.g., `"#/components/schemas/User"`). The value stored is the fully-resolved schema dict. A `deepcopy` on cache retrieval is critical to prevent mutation of cached values by downstream consumers that modify resolved schemas in place.

### 6. Create Test Infrastructure

Create the test directory structure:

- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/__init__.py` -- empty file
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/conftest.py` -- shared fixtures (see Tests section above)
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_data_model.py` -- unit tests (see Tests section above)

The `tests/generation/` directory already has an `__init__.py` so no additional package init is needed at that level.

---

## Verification Checklist

After implementing this section, the following must be true:

1. `cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi && uv run pytest tests/generation/rest/test_data_model.py -v` passes all tests.
2. `cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi && uv run pytest tests/generation/crd/ -v` still passes all 810 existing CRD tests (no regressions from adding the new field with a default value).
3. `DetectionSource` is importable from `idi.generation.dep_adapters`.
4. `json.dumps({"detection_source": DetectionSource.FK_SUFFIX})` produces valid JSON without a custom encoder.
5. `Dependency(field="x", target_resource="y")` works without specifying `detection_source` and defaults to `DetectionSource.DEFAULT`.

---

## Implementation Notes

**Implemented:** All items complete. Deviations from plan:

1. **Deepcopy optimization:** Plan called for deepcopy on memo retrieval. Implementation also initially deepcopied on first resolution (double cost). Fixed per code review to only deepcopy on cache hits.
2. **All 12 adapter call sites updated** with explicit `detection_source=DetectionSource.DEFAULT` per plan requirement (initially skipped, caught in code review).
3. **Extra test added:** `test_memoized_results_are_independent_copies` validates deepcopy isolation (not in plan, added for safety).

**Tests:** 12 new tests in `tests/generation/rest/test_data_model.py`, 810 CRD tests unchanged. Total: 822 passing.

**Files modified:** base.py, __init__.py, spec_loader.py, body_fk.py, path_deps.py, query_fk.py, obj_pattern.py, discriminator.py, yaml_adapter.py, crd_dep.py, olm_deps.py, rbac_deps.py
**Files created:** tests/generation/rest/__init__.py, conftest.py, test_data_model.py

---

## Dependencies on Other Sections

This section has **no dependencies**. It is the foundation that all other sections build upon:

- **Section 02 (Phase A Preprocessing)** and **Section 03 (Phase A Detection)** will set specific `DetectionSource` values (e.g., `CREDENTIAL_REGEX`, `FK_SUFFIX`, `READONLY_FIELD`) on the Dependencies they emit.
- **Section 05 (Links Parser)** will use `DetectionSource.OPENAPI_LINK` with `lineage_type="explicit"`.
- **Section 12 (Annotations)** will use `DetectionSource.ANNOTATION` with `lineage_type="explicit"`.
- The `$ref` memoization cache benefits all phases that resolve schemas.