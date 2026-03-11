This confirms the bug clearly: `sourceRef` appears in the `fields` list (as a config_field) rather than appearing as 3 separate entries in `refs` with HelmRepository, GitRepository, Bucket targets. The `_resolve_filenames` dict keyed by `field_path` is deduplicating polymorphic refs.

Now I have all the context needed to write the section. Let me produce it.

# Section 01: Polymorphic Ref Output Fix

## Overview

The `output_writer.py` module in `idi/generation/crd/` has a data-loss bug. When multiple `ClassifiedField` entries share the same `field_path` but have different `target_kind` values (a polymorphic reference), only one survives serialization. This happens because `_resolve_filenames()` returns `dict[str, str]` keyed by `field_path`, and `build_decomposed_skill()` similarly uses `ref_names[f.field]` as the dict key for the refs output.

**Concrete example:** Flux HelmRelease has `spec.chart.spec.sourceRef` which is a ref_tuple with `kind` enum `["HelmRepository", "GitRepository", "Bucket"]`. The ref_detector correctly returns 3 `ClassifiedField` entries (one per target kind), but the output writer's dict-keyed-by-field_path keeps only the last one written. In the current generated output, `sourceRef` appears as a `config_field` rather than as 3 separate refs.

**Scope:** This section modifies only `output_writer.py` and creates a new test file `test_polymorphic_output.py`. No changes to detection logic.

**Dependencies:** None. This section is parallelizable with all other Batch 1 sections.

## Files Modified

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/crd/output_writer.py` | Modify `_resolve_filenames` and `build_decomposed_skill` |
| `platform-tools/idi/tests/generation/crd/test_polymorphic_output.py` | Create (new test file) |

## Background: The Bug Mechanism

The current `_resolve_filenames()` function (line 78 of `output_writer.py`) operates as follows:

1. It filters fields by role (e.g., `input_ref` with non-null `target_kind`).
2. It builds `path_to_leaf: dict[str, str]` mapping `field_path` to the leaf segment of the path.
3. It returns `result: dict[str, str]` mapping `field_path` to a safe filename.

The problem is at step 2: when two `ClassifiedField` entries have `field="spec.chart.spec.sourceRef"` with `target_kind="HelmRepository"` and `target_kind="GitRepository"` respectively, the second one overwrites the first in `path_to_leaf`. The returned dict has one entry, not two.

Then in `build_decomposed_skill()` (line 174), the refs loop iterates all fields with `role == "input_ref"`, but looks up `fname = ref_names[f.field]`. Multiple fields with the same `f.field` get the same filename, and the second write to `refs[fname]` overwrites the first.

## Tests (Write First)

**File:** `platform-tools/idi/tests/generation/crd/test_polymorphic_output.py`

This is a new file. Write four test cases before implementing the fix.

### Test 1: build_decomposed_skill preserves all 3 targets for same field_path

Construct 3 `ClassifiedField` entries with identical `field="spec.sourceRef"` but different `target_kind` values: `HelmRepository`, `GitRepository`, `Bucket`. Also include a non-polymorphic ref (e.g., `field="spec.secretName"` with `target_kind="Secret"`) for a total of 4 refs. Build a minimal `crd_info` dict.

Call `build_decomposed_skill(crd_info, fields)`.

Assert:
- `len(skill["refs"]) == 4` (all 4 refs preserved, none overwritten)
- The 3 polymorphic filenames contain the target kind as a suffix: verify that filenames include `"-HelmRepository"`, `"-GitRepository"`, and `"-Bucket"` substrings
- Each ref dict has the correct `target_kind` value

### Test 2: Single-target fields get no suffix

Construct 1 `ClassifiedField` with `field="spec.secretName"` and `target_kind="Secret"`. No other field shares the same `field_path`.

Call `build_decomposed_skill(crd_info, [field])`.

Assert:
- The filename key in `skill["refs"]` is `"secretName"` (plain leaf, no `-Secret` suffix)

### Test 3: _resolve_filenames deterministic ordering

Construct 3 `ClassifiedField` entries with the same `field_path` and different `target_kind` values. Call `_resolve_filenames` 10 times.

Assert:
- Output is identical across all 10 calls (deterministic)
- The returned dict has 3 entries (one per unique `(field_path, target_group, target_kind)` triple)

### Test 4: write_decomposed_skill creates all polymorphic ref files on disk

Construct fields simulating a HelmRelease-like schema: 3 polymorphic sourceRef targets plus several non-polymorphic refs (secretRef, configMapRef, serviceAccountName). Call `write_decomposed_skill()` with a `tmp_path`.

Assert:
- Count JSON files in `refs/` directory matches total ref count
- No `AssertionError` from the duplicate file guard in `write_decomposed_skill`
- Each JSON file contains the correct `target_kind`

### Test stubs

```python
"""Tests for polymorphic ref output — multiple target_kind values for same field_path."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.output_writer import (
    _resolve_filenames,
    build_decomposed_skill,
    write_decomposed_skill,
)


def _make_crd_info(**overrides):
    """Build a minimal crd_info dict for testing."""
    base = {
        "kind": "HelmRelease",
        "group": "helm.toolkit.fluxcd.io",
        "version": "v2beta2",
        "plural": "helmreleases",
        "scope": "namespaced",
        "service": "flux",
        "description": "Test CRD",
    }
    base.update(overrides)
    return base


def _make_polymorphic_sourceref_fields():
    """Create 3 ClassifiedField entries for the sourceRef polymorphic pattern."""
    # ...return list of 3 ClassifiedField with field="spec.chart.spec.sourceRef",
    #    target_kind in ["HelmRepository", "GitRepository", "Bucket"]


def _make_single_ref_field():
    """Create 1 ClassifiedField for a non-polymorphic ref."""
    # ...return ClassifiedField with field="spec.secretName", target_kind="Secret"


class TestPolymorphicPreservation:
    def test_all_targets_preserved(self):
        """build_decomposed_skill preserves all 3 targets for same field_path."""

    def test_polymorphic_filenames_include_target_kind(self):
        """Polymorphic filenames have -TargetKind suffix."""

    def test_single_target_no_suffix(self):
        """Single-target field uses plain leaf name, no kind suffix."""

    def test_each_ref_has_correct_target(self):
        """Each ref entry in the skill has the correct target_kind value."""


class TestResolveFilenamesDeterminism:
    def test_deterministic_across_runs(self):
        """_resolve_filenames returns identical output across multiple calls."""

    def test_triple_key_count(self):
        """_resolve_filenames returns one entry per (field_path, group, kind) triple."""


class TestWritePolymorphicRefFiles:
    def test_creates_all_ref_files(self, tmp_path):
        """write_decomposed_skill creates one JSON file per polymorphic target."""

    def test_no_duplicate_assertion(self, tmp_path):
        """write_decomposed_skill does not hit the duplicate file guard."""

    def test_file_contents_have_correct_targets(self, tmp_path):
        """Each written ref JSON file contains the correct target_kind."""
```

## Implementation Details

### Change 1: `_resolve_filenames` signature and key type

**Current signature:**
```python
def _resolve_filenames(fields: list[ClassifiedField], role: str) -> dict[str, str]:
```

**New signature:**
```python
def _resolve_filenames(
    fields: list[ClassifiedField], role: str,
) -> dict[tuple[str, str | None, str | None], str]:
    """Map (field_path, target_group, target_kind) -> filename.

    Appends -target_kind to filename when multiple targets share the same field_path.
    """
```

The triple key `(field_path, target_group, target_kind)` ensures each unique combination of field path and target gets its own filename entry.

### Change 2: `_resolve_filenames` internal logic

Replace the current logic that builds `path_to_leaf: dict[str, str]` (keyed by `field_path`) with logic that:

1. **Sorts fields** by `(field_path, target_kind or "", detection_source)` before processing, ensuring deterministic ordering.

2. **Builds `key_to_leaf`** as `dict[tuple[str, str | None, str | None], str]` keyed by the triple.

3. **Detects polymorphic paths**: For each `field_path`, count how many distinct `(target_group, target_kind)` pairs exist. If more than one, append `-{target_kind}` to the leaf name for each entry with that path.

4. **Detects leaf collisions** (case-insensitive) across all entries as before, using hyphen-joined paths when needed.

The polymorphic suffix is applied *before* collision detection, so `sourceRef-HelmRepository` and `sourceRef-GitRepository` are treated as distinct leaf names.

### Change 3: `build_decomposed_skill` refs loop

The current code does:
```python
ref_names = _resolve_filenames(fields, "input_ref")
# ...
for f in fields:
    if f.role != "input_ref" or not f.target_kind:
        continue
    fname = ref_names[f.field]  # BUG: same key for multiple targets
    refs[fname] = { ... }
```

Change the lookup to use the triple key:
```python
ref_names = _resolve_filenames(fields, "input_ref")
# ...
for f in fields:
    if f.role != "input_ref" or not f.target_kind:
        continue
    key = (f.field, f.target_group, f.target_kind)
    fname = ref_names[key]
    refs[fname] = { ... }
```

The same change applies to the `output_names` and `field_names` lookups, though polymorphic outputs and config_fields are unlikely. The fix should be applied uniformly to all three roles for consistency and future-proofing.

### Change 4: Sorting for determinism

Before calling `_resolve_filenames`, sort the input `fields` list by `(field_path, target_kind or "", detection_source)`. This ensures that when multiple fields share the same path, the filename assignment is deterministic regardless of the order they were classified.

In `_resolve_filenames`, sort `role_fields` before iterating:
```python
role_fields.sort(key=lambda f: (f.field, f.target_kind or "", f.target_group or "", f.detection_source))
```

### Detailed algorithm for _resolve_filenames

Here is the pseudocode for the new `_resolve_filenames`:

```
1. Filter fields to those matching the requested role (existing logic, unchanged).
2. Sort role_fields by (field, target_kind or "", target_group or "", detection_source).
3. Build key_to_leaf: for each field, compute triple key = (f.field, f.target_group, f.target_kind),
   leaf = f.field.rsplit(".", 1)[-1].
4. Detect polymorphic paths: group keys by field_path. For any field_path with >1 key,
   append "-{target_kind}" to the leaf for each key in that group.
5. Detect case-insensitive collisions across all leaf names (after polymorphic suffix).
   For collisions, use hyphen-joined path (strip "spec.", replace "." with "-"),
   plus "-{target_kind}" suffix if polymorphic.
6. Return dict mapping each triple key to its resolved filename string.
```

### Impact on existing tests

The return type of `_resolve_filenames` changes from `dict[str, str]` to `dict[tuple[str, str | None, str | None], str]`. The existing `TestCollisionDetection` tests in `test_output_writer.py` call `_resolve_filenames` directly and check `result["spec.tls.secretRef"]` etc. These must be updated to use triple keys: `result[("spec.tls.secretRef", "core", "Secret")]`.

Specifically, update these three tests in `platform-tools/idi/tests/generation/crd/test_output_writer.py`:

- `test_hyphen_joined_on_collision` — change dict lookups to use triple keys
- `test_case_insensitive_collision` — change dict lookups to use triple keys
- `test_no_collision_uses_leaf` — change dict lookups to use triple keys

The `ClassifiedField` entries used in those tests already have `target_kind` and `target_group` set, so the triple keys are straightforward to construct.

The `TestRoundTrip` tests (`test_all_input_refs_in_decomposed`, `test_total_count`) should now pass correctly for polymorphic schemas that previously lost entries.

### Impact on `TestDecomposedStructure` and other tests

The `build_decomposed_skill` function's external return type does not change — it still returns `dict[str, Any]` with `refs`, `outputs`, `fields` sub-dicts keyed by filename strings. The triple key is internal to `_resolve_filenames`. So tests that call `build_decomposed_skill` and inspect the returned skill dict are unaffected.

### Non-polymorphic behavior preserved

When a field_path has only one `(target_group, target_kind)` pair, no `-{target_kind}` suffix is appended. The filename is the same leaf name as before. This means all existing CRD outputs (cert-manager, external-secrets, traefik, etc.) produce identical filenames after the change.

## Verification Checklist

After implementing:

1. All existing tests in `test_output_writer.py` pass (with the 3 collision tests updated for triple keys)
2. All existing tests in `test_output_writer_passthrough.py` pass unchanged
3. New `test_polymorphic_output.py` tests pass
4. Running `uv run pytest tests/generation/crd/ -v` from `platform-tools/idi/` shows zero failures
5. Regenerating Flux HelmRelease skill shows `sourceRef` split into 3 separate refs instead of being a config_field

## Implementation Notes (Post-Implementation)

**Files modified:**
- `platform-tools/idi/idi/generation/crd/output_writer.py` — `_resolve_filenames` signature changed to triple-key, `build_decomposed_skill` updated for triple-key lookups
- `platform-tools/idi/tests/generation/crd/test_output_writer.py` — 3 collision tests updated for triple keys
- `platform-tools/idi/tests/generation/crd/test_polymorphic_output.py` — New file, 11 tests

**Code review fixes applied:**
- Moved `defaultdict` import from function-local to module-level
- Added `TestPolymorphicCollisionCombined` test class covering the intersection of polymorphic + leaf collision

**Test results:** 924 passed, 11 skipped, 0 failures (full CRD suite)