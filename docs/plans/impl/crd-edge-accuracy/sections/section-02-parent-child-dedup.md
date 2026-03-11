Now I have all the context needed. Let me generate the section content.

# Section 02: Parent-Child Dedup Fix

## Overview

The parent-child deduplication logic in `field_classifier.py` is overly aggressive. When a parent field like `spec.sourceRef` is classified as an `input_ref`, line 75 skips ALL descendants (any field whose path starts with `ref_path + "."`). This is correct for structural detectors like SecretKeySelector (SKS shape) and ref_tuple, which classify an entire object subtree as a single reference -- their children (e.g., `namespace`, `key`) are components of the reference, not independent refs. But non-structural detectors like `enum_kind` or `detect_example_kinds` classify a field without implying ownership over its children. A child field may reference a completely different Kind and should be emitted independently.

This section adds a `blocks_descendants: bool` field to `ClassifiedField` and modifies the dedup logic to only skip descendants of refs that explicitly declare subtree ownership.

**Files modified:**
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/field_classifier.py`
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/ref_detector.py`

**Files modified (tests):**
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_field_classifier.py`

**Dependencies:** None. This section is parallelizable with all other Batch 1 sections.

**Run tests:** `cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi && uv run pytest tests/generation/crd/ -v`

---

## Tests (Write First)

Add the following tests to the existing `TestDeduplication` class in `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_field_classifier.py`. Also add a test in `TestClassifiedFieldExtensions` for the new field default.

### Test 1: Non-structural ref does not block descendant classification

```python
# In class TestDeduplication:

def test_non_structural_ref_does_not_block_descendant(self):
    """Non-structural ref (e.g., enum_kind) at spec.x does NOT suppress spec.x.y."""
    # Schema: spec.typeSelector is an object with a "kind" enum that triggers
    # enum_kind detection (non-structural, blocks_descendants=False).
    # Its child spec.typeSelector.secretRef is an SKS-shaped object that
    # should be independently detected as input_ref -> Secret.
    props = {
        "typeSelector": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["Certificate", "Issuer"],
                },
                "secretRef": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "key": {"type": "string"},
                    },
                },
            },
        },
    }
    fields = classify_fields(props, [], "cert-manager.io", "Test",
                            registry=self.registry)
    refs = [f for f in fields if f.role == "input_ref"]
    ref_paths = {f.field for f in refs}
    # Both the enum_kind parent and the SKS child should appear
    assert "spec.typeSelector" in ref_paths or any(
        f.field == "spec.typeSelector" for f in fields if f.role == "input_ref"
    )
    assert "spec.typeSelector.secretRef" in ref_paths
```

### Test 2: Structural ref (SKS shape) still blocks descendants

```python
# In class TestDeduplication:

def test_structural_ref_still_blocks_descendants(self):
    """SKS-shape ref at spec.secretRef blocks spec.secretRef.namespace."""
    props = {
        "secretRef": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "key": {"type": "string"},
                "namespace": {"type": "string"},
            },
        },
    }
    fields = classify_fields(props, [], "core", "Test",
                            registry=self.registry)
    refs = [f for f in fields if f.role == "input_ref"]
    ref_paths = {f.field for f in refs}
    assert "spec.secretRef" in ref_paths
    # Children of structural ref must NOT appear as independent refs
    assert "spec.secretRef.namespace" not in ref_paths
    assert "spec.secretRef.name" not in ref_paths
    assert "spec.secretRef.key" not in ref_paths
```

### Test 3: ref_tuple detector sets blocks_descendants=True

```python
# In class TestDeduplication:

def test_ref_tuple_blocks_descendants(self):
    """ref_tuple detection ({kind, name, namespace}) blocks descendant classification."""
    props = {
        "sourceRef": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["Certificate"],
                },
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
            "required": ["name"],
        },
    }
    fields = classify_fields(props, [], "cert-manager.io", "Test",
                            registry=self.registry)
    refs = [f for f in fields if f.role == "input_ref"]
    ref_paths = {f.field for f in refs}
    assert "spec.sourceRef" in ref_paths
    # Descendants must be blocked by ref_tuple
    assert "spec.sourceRef.name" not in ref_paths
    assert "spec.sourceRef.namespace" not in ref_paths
```

### Test 4: blocks_descendants defaults to False

```python
# In class TestClassifiedFieldExtensions:

def test_blocks_descendants_defaults_to_false(self):
    """blocks_descendants defaults to False for backward compatibility."""
    cf = ClassifiedField(
        field="spec.foo", role="config_field",
        confidence=0.5, field_type="string",
    )
    assert cf.blocks_descendants is False
```

### Test 5: blocks_descendants can be set explicitly

```python
# In class TestClassifiedFieldExtensions:

def test_blocks_descendants_can_be_set_true(self):
    """blocks_descendants can be explicitly set to True."""
    cf = ClassifiedField(
        field="spec.secretRef", role="input_ref",
        confidence=0.85, field_type="object",
        target_kind="Secret", target_group="core",
        blocks_descendants=True,
    )
    assert cf.blocks_descendants is True
```

---

## Implementation

### Step 1: Add `blocks_descendants` to `ClassifiedField`

In `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/field_classifier.py`, add a new field to the `ClassifiedField` dataclass:

```python
@dataclass
class ClassifiedField:
    """A CRD field with its classified role."""

    field: str
    role: str
    confidence: float
    field_type: str
    target_kind: str | None = None
    target_group: str | None = None
    required: bool = False
    cross_namespace: bool = False
    description: str = ""
    detection_source: str = ""
    fact_shape: str = ""
    target_field: str = "name"
    blocks_descendants: bool = False  # True = structural ref whose children are ref components
```

The default of `False` ensures all existing code that constructs `ClassifiedField` without specifying this field continues to work without modification. All existing tests pass unchanged.

### Step 2: Set `blocks_descendants=True` on structural detectors

In `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/ref_detector.py`, the following detectors must set `blocks_descendants=True` on the `ClassifiedField` they return. These are the detectors that classify an entire object subtree as a single reference, where the child fields (`name`, `key`, `namespace`, etc.) are components of the parent reference:

1. **`detect_secret_key_selector`** (line ~726) -- The SKS shape `{key, name, namespace?, optional?}` is a single structural reference to a Secret. Add `blocks_descendants=True` to the returned `ClassifiedField`.

2. **`detect_ref_tuple`** (line ~904) -- The ref tuple pattern `{name, namespace?, kind?, apiGroup?}` is a single structural reference. Add `blocks_descendants=True` to each `ClassifiedField` appended to the results list (both the kind-enum resolution path and the apiGroup/apiVersion fallback path).

3. **`detect_ref`** (line ~608) -- Step 4 (structural ref: object + name + `*Ref` suffix) classifies an object whose children are ref components. Add `blocks_descendants=True` to the `ClassifiedField` returned at line ~684. Note: Step 3 (KindRegistry name match) may match string-type or object-type fields. For object-type fields with reference indicators (`name`, `key`, `namespace`) present, the structural check at lines 646-651 already validates this is a reference-shaped object, so `blocks_descendants=True` is appropriate. For string-type fields (e.g., `secretName`), `blocks_descendants` does not matter since strings have no children.

The following detectors must NOT set `blocks_descendants=True`:
- `detect_enum_kind` -- Classifies based on enum values, not subtree structure
- `detect_example_kinds` -- Classifies based on examples/defaults
- `detect_apigroup_literal` -- Classifies based on API group strings
- `detect_constraint_fk` -- Classifies based on field constraints
- `detect_embedded_workload` -- Classifies workload shapes (these DO have children, but embedded workload children may contain independent refs like `serviceAccountName`)
- `detect_cataloged_shape` -- Uses catalog fingerprints
- All NLP/side-effect detectors

### Step 3: Modify dedup logic in `classify_fields`

In `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/field_classifier.py`, change the dedup logic in `classify_fields()`:

1. Rename `classified_ref_paths` to `classified_blocking_ref_paths` for clarity.

2. Only add paths to this set when the classified field has `blocks_descendants=True`.

3. The skip check on line 75 remains structurally the same but uses the renamed set.

The modified `classify_fields` function body (relevant fragment):

```python
results: list[ClassifiedField] = []
classified_blocking_ref_paths: set[str] = set()

for field in walk_crd_schema(spec_properties, spec_required, prefix=prefix):
    # Parent-child deduplication: skip descendants of BLOCKING refs only.
    # Structural detectors (SKS, ref_tuple, structural_ref) set
    # blocks_descendants=True, meaning their children are ref components
    # (name, key, namespace) not independent references.
    if any(field.path.startswith(ref_path + ".") for ref_path in classified_blocking_ref_paths):
        continue

    # ... (sibling_fields logic unchanged) ...

    classified_list = classify_walked_field(
        field, registry, kind, group,
        sibling_fields=sibling_fields,
    )

    for classified in classified_list:
        if classified.role == "input_ref" and classified.blocks_descendants:
            classified_blocking_ref_paths.add(field.path)

    results.extend(classified_list)
```

Key behavioral change: A non-structural ref (e.g., `enum_kind` at `spec.foo`) no longer adds its path to the blocking set, so its child `spec.foo.bar` will still be walked and classified. A structural ref (e.g., SKS at `spec.secretRef`) continues to block `spec.secretRef.name` and `spec.secretRef.key` from being classified as independent refs.

### Verification Checklist

- All existing `TestDeduplication` tests pass unchanged (the existing `test_parent_child_dedup` test uses `secretRef` which is an SKS shape, so `blocks_descendants=True` is set and behavior is preserved)
- The existing `test_config_parent_does_not_suppress_child` test still passes (config_field parents were never in `classified_ref_paths`)
- The existing `test_sibling_refs_both_kept` test still passes (siblings are not descendants)
- All 810+ existing tests pass with zero modifications (the new field has a default value)
- The 3 new tests validate the corrected behavior

## Implementation Notes (Post-Implementation)

**Files modified:**
- `platform-tools/idi/idi/generation/crd/field_classifier.py` — Added `blocks_descendants` field, renamed `classified_ref_paths` → `classified_blocking_ref_paths`, conditional dedup
- `platform-tools/idi/idi/generation/crd/ref_detector.py` — Set `blocks_descendants=True` on SKS, structural_ref, ref_tuple (kind enum + apiGroup paths), kind_registry (object-type only)
- `platform-tools/idi/tests/generation/crd/test_field_classifier.py` — 5 new tests

**Test results:** 930 passed, 11 skipped, 0 failures