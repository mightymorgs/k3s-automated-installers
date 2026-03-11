<!-- IMPLEMENTED: see commit below -->

# Section 06: Fuzzy Kind Name Detector Step

## Overview

This section adds a new detector step `detect_fuzzy_kind_name` to the ref_detector cascade in `idi/generation/crd/ref_detector.py`. The function calls `KindRegistry.fuzzy_resolve()` (implemented in section-05) for `string` and `string-array` fields that no prior detector has classified as an `input_ref`. It multiplies the fuzzy score by `field.depth_confidence` (populated by section-03) and only emits when the result meets the 0.7 confidence floor.

This is the final consumer of the fuzzy resolution infrastructure: section-04 added the `service` field to `KindEntry`, section-05 implemented `fuzzy_resolve()` on `KindRegistry`, and this section wires it into the live detection pipeline.

**Critical constraint:** Precision > Recall. A false edge creates a phantom cycle in Kahn's algorithm, deadlocking deployment. The fuzzy detector is intentionally conservative -- it only fires on string-typed fields, only when no higher-priority detector matched, and only when the fuzzy score (after depth decay) clears the 0.7 threshold.

## Dependencies

| Dependency | What It Provides |
|------------|-----------------|
| **section-03** (WalkedField enrichment) | `WalkedField.depth_confidence` (float, default 1.0) and `WalkedField.sibling_names` (frozenset of parent property names). Both must exist on the `WalkedField` dataclass before this section can use them. |
| **section-05** (fuzzy_resolve) | `KindRegistry.fuzzy_resolve(field_name, scope_service, require_unique)` returning `list[KindCandidate]` with `kind`, `api_group`, `score`, `match_type` attributes. Must be implemented and importable. |

## Files Modified

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/crd/ref_detector.py` | Add `detect_fuzzy_kind_name` function; wire it into `classify_walked_field` cascade |
| `platform-tools/idi/tests/generation/crd/test_ref_detector.py` | Add tests for the new detector step |

## Tests First

All tests go in `platform-tools/idi/tests/generation/crd/test_ref_detector.py` (modify existing file). The tests should be added as a new test class alongside the existing ones.

### Test file additions

```python
# In: platform-tools/idi/tests/generation/crd/test_ref_detector.py

from idi.generation.crd.ref_detector import detect_fuzzy_kind_name

class TestDetectFuzzyKindName:
    """Tests for detect_fuzzy_kind_name detector step."""

    # --- Setup: registry with CRD kinds ---

    @pytest.fixture
    def istio_registry(self) -> KindRegistry:
        """Registry with Istio kinds registered with service='istio'."""
        reg = KindRegistry()
        # Section-04 adds service param to register(); section-05 adds fuzzy_resolve()
        reg.register("Gateway", "gateways", "networking.istio.io", service="istio")
        reg.register("VirtualService", "virtualservices", "networking.istio.io", service="istio")
        reg.register("DestinationRule", "destinationrules", "networking.istio.io", service="istio")
        return reg

    @pytest.fixture
    def cilium_registry(self) -> KindRegistry:
        """Registry with Cilium kinds registered with service='cilium'."""
        reg = KindRegistry()
        reg.register("CiliumBGPPeerConfig", "ciliumbgppeerconfigs", "cilium.io", service="cilium")
        reg.register("CiliumNetworkPolicy", "ciliumnetworkpolicies", "cilium.io", service="cilium")
        return reg

    # --- Test: fires for string field with plural match ---
    # Input: field name "gateways", type "array" with items.type "string", Istio registry
    # Assert: returns ClassifiedField with role="input_ref", target_kind="Gateway"
    # Assert: detection_source contains "fuzzy_kind_name" and "plural_exact"

    # --- Test: fires for string field with suffix match ---
    # Input: field name "peerConfigRef", type "string", Cilium registry, service="cilium"
    # Assert: returns ClassifiedField with target_kind="CiliumBGPPeerConfig"
    # Assert: detection_source contains "suffix_unique"

    # --- Test: does NOT fire for object-type fields ---
    # Input: field name "gateways", type "object" with properties
    # Assert: returns None (object fields handled by structural detectors)

    # --- Test: does NOT fire when fuzzy score * depth_confidence < 0.7 ---
    # Input: field with depth_confidence=0.81 and a fuzzy match at score 0.80
    #        → 0.80 * 0.81 = 0.648 < 0.7
    # Assert: returns None

    # --- Test: does fire when fuzzy score * depth_confidence >= 0.7 ---
    # Input: field with depth_confidence=0.9 and a fuzzy match at score 0.80
    #        → 0.80 * 0.9 = 0.72 >= 0.7
    # Assert: returns ClassifiedField

    # --- Test: detection_source includes match_type ---
    # Input: field matching via "plural_exact"
    # Assert: detection_source == "ref_detector:fuzzy_kind_name:plural_exact"

    # --- Test: does NOT fire for integer/boolean/object fields ---
    # Input: field name "gateways", type "integer"
    # Assert: returns None

    # --- Test: fires for array field with items.type string ---
    # Input: schema = {"type": "array", "items": {"type": "string"}}, name "gateways"
    # Assert: returns ClassifiedField (arrays of strings are valid ref lists)


class TestFuzzyDetectorInCascade:
    """Tests that detect_fuzzy_kind_name is wired into classify_walked_field correctly."""

    # --- Test: fuzzy detector does NOT fire when prior detector already classified ---
    # Input: field "secretName" (matched by detect_ref at step 1)
    # Assert: result has detection_source starting with "ref_detector:" (not fuzzy)

    # --- Test: fuzzy detector fires when no prior detector matches ---
    # Input: field "gateways" (no suffix match, no SKS, no ref_tuple)
    #        with Istio Gateway registered
    # Assert: one of the results has detection_source containing "fuzzy_kind_name"

    # --- Test: integration with real Istio VirtualService schema ---
    # Synthetic schema with spec.gateways as array of strings
    # Assert: gateways field classified as input_ref targeting Gateway
    # Note: use classify_walked_field with appropriate registry

    # --- Test: integration with real Cilium peerConfigRef ---
    # Synthetic schema with spec.peerConfigRef as string
    # Assert: field classified as input_ref targeting CiliumBGPPeerConfig
```

### Helper for building WalkedField with new fields

Tests will need to construct `WalkedField` instances that include the `depth_confidence` and `sibling_names` attributes added by section-03. The existing `_make_field` helper in the test file should be updated (or a local variant created) to accept these:

```python
def _make_field(
    name: str,
    schema: dict | None = None,
    path: str | None = None,
    depth: int = 1,
    is_array_item: bool = False,
    required: bool = False,
    parent_path: str = "spec",
    depth_confidence: float = 1.0,
    sibling_names: frozenset[str] | None = None,
) -> WalkedField:
    """Build a WalkedField with sensible defaults (extended for section-03 fields)."""
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
    if sibling_names is None:
        sibling_names = frozenset()
    return WalkedField(
        path=path,
        name=name,
        schema=schema,
        depth=depth,
        is_array_item=is_array_item,
        required=required,
        parent_path=parent_path,
        depth_confidence=depth_confidence,
        sibling_names=sibling_names,
    )
```

## Implementation Details

### 1. Add `detect_fuzzy_kind_name` function

**File:** `platform-tools/idi/idi/generation/crd/ref_detector.py`

Add a new function near the end of the detector functions (before `classify_walked_field`, around line 1600):

```python
def detect_fuzzy_kind_name(
    field: WalkedField,
    registry: KindRegistry,
    current_group: str,
    current_service: str,
) -> ClassifiedField | None:
    """Detect refs via fuzzy Kind name matching (plural, suffix, camel, bare).

    Called only when no prior detector produced an input_ref classification.
    Uses KindRegistry.fuzzy_resolve() to find candidate Kind matches.

    Type guards:
    - Only runs on type: string or type: array with items.type: string.
    - Object-typed fields are already handled by structural detectors.

    Confidence:
    - Takes the top-scoring candidate from fuzzy_resolve().
    - Multiplies candidate score by field.depth_confidence.
    - Only emits if result >= 0.7.

    Args:
        field: WalkedField from schema walker.
        registry: KindRegistry with fuzzy_resolve() method.
        current_group: The source CRD's API group.
        current_service: The source CRD's service name for scoping.

    Returns:
        ClassifiedField if a match is found above threshold, else None.
    """
```

**Algorithm:**

1. **Type guard check:** Extract `field_type` from `field.schema.get("type")`. If `field_type == "string"`, proceed. If `field_type == "array"`, check `field.schema.get("items", {}).get("type") == "string"` -- if so, proceed. Otherwise, return `None`.

2. **Call fuzzy_resolve:** `candidates = registry.fuzzy_resolve(field.name, scope_service=current_service, require_unique=True)`. If empty, return `None`.

3. **Take top candidate:** `best = candidates[0]` (fuzzy_resolve returns candidates sorted by score descending).

4. **Apply depth decay:** `final_confidence = best.score * field.depth_confidence`.

5. **Floor check:** If `final_confidence < 0.7`, return `None`.

6. **Build result:** Return a `ClassifiedField` with:
   - `field=field.path`
   - `role="input_ref"`
   - `confidence=final_confidence`
   - `field_type=field.schema.get("type", "string")`
   - `target_kind=best.kind`
   - `target_group=best.api_group`
   - `required=field.required`
   - `description=field.schema.get("description", "")`
   - `detection_source=f"ref_detector:fuzzy_kind_name:{best.match_type}"`
   - `fact_shape="identity"`
   - `target_field="name"`

### 2. Wire into `classify_walked_field` cascade

**File:** `platform-tools/idi/idi/generation/crd/ref_detector.py`

**Location:** Inside `classify_walked_field()`, after the additive detectors block (after the `if additive_results:` block around line 1751-1754) and before the "Step 11: Side-effect NLP" block (around line 1756).

The fuzzy detector should be inserted as a new step between the additive results return and the side-effect NLP fallback. It only fires when:
- No exclusive detector matched (steps 0-4 all returned None/empty)
- No additive detectors produced results (the `additive_results` list was empty)

Add a new code block:

```python
    # Step 10.5: Fuzzy Kind name matching (between additive block and NLP fallback).
    # Only fires when no prior detector produced an input_ref.
    fuzzy_result = detect_fuzzy_kind_name(field, registry, group, current_service)
    if fuzzy_result is not None:
        return suppress_false_positives(field, [fuzzy_result])
```

**Important:** The `current_service` parameter does not exist on the current `classify_walked_field` signature. It must be added:

```python
def classify_walked_field(
    field: WalkedField,
    registry: KindRegistry,
    kind: str,
    group: str,
    sibling_fields: dict[str, Any] | None = None,
    manifest_flags: ManifestFlags | None = None,
    current_service: str = "",  # NEW: for fuzzy detector service scoping
) -> list[ClassifiedField]:
```

The caller in `field_classifier.py` (`classify_fields()`) will need to pass `current_service` through. Add `current_service: str = ""` to `classify_fields()` signature and pass it along. This is a backward-compatible change (default empty string).

### 3. Update `classify_fields` to pass service context

**File:** `platform-tools/idi/idi/generation/crd/field_classifier.py`

Add `current_service: str = ""` parameter to `classify_fields()` and pass it through to `classify_walked_field()`:

```python
def classify_fields(
    spec_properties: dict[str, Any],
    spec_required: list[str],
    group: str,
    kind: str,
    registry: KindRegistry | None = None,
    prefix: str = "spec",
    current_service: str = "",  # NEW
) -> list[ClassifiedField]:
    ...
    classified_list = classify_walked_field(
        field, registry, kind, group,
        sibling_fields=sibling_fields,
        current_service=current_service,  # NEW
    )
```

This is backward-compatible; all existing callers that do not pass `current_service` get the default empty string, which means no service scoping and no cross-service penalty in fuzzy_resolve.

### 4. Cascade position rationale

The fuzzy detector sits at position ~13 in the effective cascade (plan says "position ~13, before suppress_false_positives"). In the actual code flow, this means:

1. **Exclusive detectors (steps 0-4):** Side-effect dict, detect_ref, detect_sks, detect_parent_kind_name, detect_ref_tuple -- all return early if matched.
2. **Additive detectors (steps 5-12):** kubernetes_extensions, enum_kind, example_kinds, apigroup_literal, passthrough_manifest, constraint_fk, embedded_workload, cataloged_shape -- accumulated and returned if any matched.
3. **Fuzzy detector (NEW):** Only reached if both exclusive AND additive blocks produced nothing. Calls `fuzzy_resolve`, applies depth decay, checks floor.
4. **NLP fallback (step 11):** Only for `*Name` fields.
5. **readOnly fallback (step 12).**
6. **Default config_field (step 13).**

The fuzzy detector runs through `suppress_false_positives` before returning, ensuring that any suppression rules (including the credential exclusion from section-09, if implemented) can override it.

### 5. Integration test patterns

For integration tests, construct schemas that mimic real CRD patterns:

**Istio VirtualService `gateways[]`:**
```python
schema = {
    "type": "object",
    "properties": {
        "gateways": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The names of gateways that should apply these routes.",
        }
    }
}
```
With an Istio-aware registry (Gateway registered with service="istio"), `detect_fuzzy_kind_name` on the `gateways` field should return a `ClassifiedField` targeting Gateway via "plural_exact" match at score 0.80.

**Cilium BGPClusterConfig `peerConfigRef`:**
```python
schema = {"type": "string", "description": "Reference to a CiliumBGPPeerConfig."}
```
With CiliumBGPPeerConfig registered, the suffix match strips "Ref" leaving "peerConfig", which suffix-matches CiliumBGPPeerConfig at score 0.75.

## Edge Cases and Guards

1. **Empty field name or very short names:** `fuzzy_resolve` handles these (returns empty for single characters, returns empty for strings shorter than 4 chars after suffix stripping). The detector inherits these guards.

2. **Object-typed fields:** Explicitly rejected by the type guard. Structural detectors (SKS, ref_tuple) handle object fields.

3. **Fields already classified by higher-priority detectors:** The cascade structure ensures fuzzy never runs when a higher-priority detector matched. No explicit check needed inside `detect_fuzzy_kind_name` itself.

4. **Denylisted nouns:** Handled by `fuzzy_resolve`'s `_FUZZY_DENYLIST`. Fields like "service", "role", "policy" without corroborating structural markers return empty candidates.

5. **Cross-service references:** Penalized by `fuzzy_resolve`'s cross-service penalty (score * 0.7). Combined with depth decay, many cross-service fuzzy matches will fall below the 0.7 floor naturally.

6. **Suppression pipeline:** The result is passed through `suppress_false_positives` before returning, so any suppression rules (credential exclusion, target_kind_not_at_word_boundary, etc.) still apply.

## Verification Checklist

- [x] `detect_fuzzy_kind_name` function added to `ref_detector.py`
- [x] Function accepts `WalkedField`, `KindRegistry`, `current_group`, `current_service`
- [x] Type guard: only `string` or `array[string]` fields proceed
- [x] Calls `registry.fuzzy_resolve()` with `scope_service=current_service` + `sibling_names`
- [x] Multiplies candidate score by `field.depth_confidence`
- [x] Returns `None` when final confidence < 0.7
- [x] `detection_source` format: `"ref_detector:fuzzy_kind_name:{match_type}"`
- [x] Wired into `classify_walked_field` after additive block, before NLP fallback
- [x] Result passed through `suppress_false_positives`
- [x] `classify_walked_field` signature updated with `current_service: str = ""`
- [x] `classify_fields` in `field_classifier.py` updated to accept and forward `current_service`
- [x] `generate_all.py` updated to pass `current_service=name` (review fix)
- [x] All existing tests pass unchanged (1004 total, 0 regressions)
- [x] 11 new tests: string, array, object/integer rejection, depth decay, detection_source, cascade ordering, Istio/Cilium integration

## Implementation Notes (Post-Implementation)

### Deviations from Plan
1. **sibling_names passed to fuzzy_resolve:** Plan omitted this, but it's needed for denylist corroboration. Improves correctness.
2. **generate_all.py updated (review fix):** Plan mentioned this was needed but didn't list the file. Fixed during review.
3. **current_group unused:** Accepted but unused parameter for future same-group preference logic.

### Files Modified
- `ref_detector.py` — Added `detect_fuzzy_kind_name` (~50 LOC), wired into cascade at step 12.5
- `field_classifier.py` — Added `current_service` parameter, forwarded to `classify_walked_field`
- `generate_all.py` — Pass `current_service=name` to enable fuzzy detection in production
- `test_ref_detector.py` — Updated `_make_field` helper, added 11 tests in 2 new classes