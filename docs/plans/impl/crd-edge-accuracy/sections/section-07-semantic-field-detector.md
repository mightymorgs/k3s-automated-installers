Good, nothing exists yet. Now I have all the context I need. Let me produce the section content.

# Section 07: Semantic Field Detector

## Overview

This section adds a new detector step, `detect_semantic_field`, to the ref_detector cascade in `idi/generation/crd/ref_detector.py`. The detector uses a static lookup table (`_SEMANTIC_FIELD_MAP`) to map well-known semantic field names to specific Kubernetes Kinds. It targets field names that reference a Kind without naming it directly -- for example, `credentialName` and `tlsSecret` both reference Secrets, but neither contains the substring "Secret" in a way the existing suffix-based `detect_ref` would catch (or in `tlsSecret`'s case, it does contain "Secret" but the semantics are worth codifying explicitly at high confidence).

This is a precision-first detector: the lookup table is curated manually and only entries with clear, unambiguous semantics are included. The detector only fires on `type: string` fields whose name exactly matches a key in the map.

**Dependency:** Section 03 (WalkedField Enrichment) must land first so that `WalkedField` has the `sibling_names` and `depth_confidence` fields. However, this detector does not use those fields directly -- it only needs them to exist on the dataclass so it can be instantiated in tests without errors.

**Critical constraint:** Precision > Recall. A false edge creates a phantom cycle in Kahn's algorithm, deadlocking deployment. Every entry in `_SEMANTIC_FIELD_MAP` must be verifiably correct across all known CRD services.

## Files to Create or Modify

| Action | File | Purpose |
|--------|------|---------|
| Modified | `platform-tools/idi/idi/generation/crd/ref_detector.py` | Add `_SEMANTIC_FIELD_MAP` and `detect_semantic_field()` function; wire into cascade |
| Modified | `platform-tools/idi/tests/generation/crd/test_ref_detector.py` | Add tests for detect_semantic_field |

## Tests (Write First)

All tests go in `platform-tools/idi/tests/generation/crd/test_ref_detector.py`. Add a new test class or test group for the semantic field detector.

The tests use `WalkedField` instances constructed inline. After Section 03 lands, `WalkedField` will have `sibling_names` and `depth_confidence` fields with defaults (`frozenset()` and `1.0` respectively), so test construction does not need to specify them.

### Test 1: credentialName maps to Secret at confidence 0.90

```python
# Test: credentialName → Secret at confidence 0.90
# Build a WalkedField with name="credentialName", schema={"type": "string"}
# Call detect_semantic_field(field, registry) where registry is a core_only_registry
# Assert: result is not None
# Assert: result.role == "input_ref"
# Assert: result.target_kind == "Secret"
# Assert: result.target_group == "core"
# Assert: result.confidence == 0.90
# Assert: result.detection_source == "ref_detector:semantic_field"
```

### Test 2: tlsSecret maps to Secret at confidence 0.90

```python
# Test: tlsSecret → Secret at confidence 0.90
# Build a WalkedField with name="tlsSecret", schema={"type": "string"}
# Call detect_semantic_field(field, registry)
# Assert: result is not None
# Assert: result.target_kind == "Secret"
# Assert: result.target_group == "core"
# Assert: result.confidence == 0.90
```

### Test 3: Unrecognized field name returns None

```python
# Test: randomFieldName → no match (not in map)
# Build a WalkedField with name="randomFieldName", schema={"type": "string"}
# Call detect_semantic_field(field, registry)
# Assert: result is None
```

### Test 4: Object-type field is rejected even if name matches

```python
# Test: credentialName with type: object → no match (only string fields)
# Build a WalkedField with name="credentialName", schema={"type": "object", "properties": {...}}
# Call detect_semantic_field(field, registry)
# Assert: result is None
```

### Test 5: Array-type field is rejected even if name matches

```python
# Test: credentialName with type: array → no match
# Build a WalkedField with name="credentialName", schema={"type": "array", "items": {"type": "string"}}
# Call detect_semantic_field(field, registry)
# Assert: result is None
```

### Test 6: Field name match is case-sensitive (exact match only)

```python
# Test: "credentialname" (lowercase) → no match
# Build a WalkedField with name="credentialname", schema={"type": "string"}
# Call detect_semantic_field(field, registry)
# Assert: result is None
```

### Test 7: ClassifiedField has correct metadata

```python
# Test: verify all ClassifiedField metadata is correctly populated
# Build a WalkedField with name="tlsSecret", path="spec.tls.tlsSecret",
#   schema={"type": "string", "description": "Name of TLS secret"},
#   required=True
# Call detect_semantic_field(field, registry)
# Assert: result.field == "spec.tls.tlsSecret"
# Assert: result.field_type == "string"
# Assert: result.required == True
# Assert: result.description == "Name of TLS secret"
# Assert: result.fact_shape == "identity"
```

## Implementation Details

### 1. Define the Semantic Field Map

Add this constant to `ref_detector.py`, near the top of the file with the other module-level constants:

```python
_SEMANTIC_FIELD_MAP: dict[str, tuple[str, str, float]] = {
    # field_name -> (target_kind, target_group, confidence)
    "credentialName": ("Secret", "core", 0.90),
    "tlsSecret": ("Secret", "core", 0.90),
}
```

**Design rationale for the two entries:**

- `credentialName` -- Used across multiple CRD ecosystems (e.g., Strimzi KafkaUser, Harbor configurations) to reference a Secret that contains credentials. The name is unambiguous: it always means "the name of a Secret that holds credentials."

- `tlsSecret` -- Used in ingress-related CRDs and service meshes (e.g., Istio Gateway, Traefik IngressRoute TLS config) to reference a Secret containing TLS certificate material. Always a Secret name.

**Explicitly excluded entries:**

- `caBundle` -- Considered but excluded. In most CRDs, `caBundle` is inline PEM-encoded bytes (e.g., `ValidatingWebhookConfiguration.webhooks[].clientConfig.caBundle`), not a reference to a Secret. Including it would create false edges.

- `secretName` -- Already handled by the existing `detect_ref` suffix matcher (the "Name" suffix + "Secret" prefix pattern). Adding it here would be redundant.

- `configMapName` -- Same reasoning as `secretName` -- already covered by suffix matching.

The map should be extended conservatively over time. Each new entry requires evidence from at least 2 independent CRD services using the same field name with the same semantic meaning.

### 2. Implement detect_semantic_field Function

```python
def detect_semantic_field(
    field: WalkedField,
    registry: KindRegistry,
) -> ClassifiedField | None:
    """Detect refs via curated semantic field name map.

    Lookup table for well-known field names that reference specific Kinds
    without naming them via standard suffix patterns. Only fires on
    type: string fields with exact name match.

    Returns ClassifiedField or None if no match.
    """
```

**Algorithm:**

1. Check `field.schema.get("type") == "string"`. If not string, return `None`. This is a strict type guard -- semantic field names like `credentialName` and `tlsSecret` are always scalar string references to a resource name, never objects or arrays.

2. Look up `field.name` (exact match, case-sensitive) in `_SEMANTIC_FIELD_MAP`. If not found, return `None`.

3. Extract `(target_kind, target_group, confidence)` from the map entry.

4. Construct and return a `ClassifiedField`:
   - `field=field.path`
   - `role="input_ref"`
   - `confidence=confidence` (from map, typically 0.90)
   - `field_type=field.schema.get("type", "string")`
   - `target_kind=target_kind`
   - `target_group=target_group`
   - `required=field.required`
   - `description=field.schema.get("description", "")`
   - `detection_source="ref_detector:semantic_field"`
   - `fact_shape="identity"`

### 3. Wire into the Detector Cascade

Insert `detect_semantic_field` into `classify_walked_field()` as a new step in the cascade. Per the plan, this should be at position ~14 (after the additive detector block, near the fuzzy detector from Section 06).

The exact insertion point is **after the additive results block** (which ends at the `suppress_false_positives` return on the current line 1754) and **before the Side-effect NLP step** (current Step 11, line 1756). The semantic field detector is exclusive -- if it matches, it returns immediately. It should be placed so it fires only when no prior detector (structural, enum, additive) has already classified the field.

In the current cascade flow, after the additive results merge and return, the function falls through to the NLP and readOnly steps. The semantic field detector should be inserted between the additive block's return and the NLP step:

```python
    # Merge additive results, then deduplicate and suppress.
    if additive_results:
        merged = _merge_additive_results(additive_results)
        merged = _deduplicate_classifications(merged)
        return suppress_false_positives(field, merged)

    # NEW: Semantic field map lookup.
    semantic_result = detect_semantic_field(field, registry)
    if semantic_result is not None:
        return [semantic_result]

    # Step 11: Side-effect NLP for *Name fields ...
```

This placement ensures that:
- Higher-priority structural detectors (detect_ref, SKS, parent_kind_name, ref_tuple) run first
- Additive detectors (enum_kind, examples, apigroup, etc.) run second
- Semantic field map runs third, catching well-known names that slip through structural and additive detection
- NLP and default classification run last as fallbacks

### 4. Update Cascade Docstring

Update the step numbering in the `classify_walked_field` docstring to include the new step. The semantic field step should be documented between the current suppression step and the NLP step:

```
    Step 13a: detect_semantic_field (0.90) — curated field name map
```

## Implementation Notes

**Implemented as planned.** All 7 unit tests + 3 cascade integration tests pass. Full CRD suite: 1014 pass, 0 fail.

**Files modified:**
- `platform-tools/idi/idi/generation/crd/ref_detector.py` — Added `_SEMANTIC_FIELD_MAP`, `detect_semantic_field()`, wired at Step 10.6 (after fuzzy, before NLP)
- `platform-tools/idi/tests/generation/crd/test_ref_detector.py` — Added `TestDetectSemanticField` (7 tests) + `TestSemanticFieldInCascade` (3 tests)

**Code review finding rejected:** Reviewer suggested wrapping result in `suppress_false_positives()` for consistency. Testing showed this incorrectly suppresses the semantic result via `target_kind_not_at_word_boundary` rule (the whole point of this detector is matching fields that don't name their target Kind). Plan was correct to skip suppression.

## Verification Checklist

After implementation, verify:

1. All 7 new tests pass
2. All existing 810+ tests pass unchanged (the new detector should not reclassify any field that was already classified by a prior step)
3. `uv run pytest tests/generation/crd/test_ref_detector.py -v` shows the new test class
4. The `_SEMANTIC_FIELD_MAP` contains exactly 2 entries (`credentialName`, `tlsSecret`)
5. The function signature matches the documented interface
6. The detector is correctly positioned in the cascade (after additive block, before NLP)

## Edge Cases and Precision Considerations

- **No partial matching:** The map uses exact `field.name` lookups, not substring or regex. A field named `myCredentialName` will NOT match. This is intentional -- partial matching would introduce ambiguity.

- **No case folding:** `credentialname` (all lowercase) does NOT match `credentialName`. CRD schemas use camelCase consistently; case folding would risk false positives on coincidental matches.

- **Object-type rejection:** A field named `credentialName` with `type: object` is rejected. In some CRDs, similarly-named fields might be objects containing `{name, namespace}` tuples -- those are handled by the structural detectors (SKS, ref_tuple) at higher priority.

- **No registry validation:** The detector does not verify that the target Kind exists in the KindRegistry. Since the targets are core K8s resources (Secret), they are always registered. If the map is extended to include non-core targets in the future, registry validation should be added.