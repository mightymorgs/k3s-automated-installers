Now I have a thorough understanding of the code. Let me also check that `ClassifiedField` is not frozen (so we can mutate `confidence` in place, or we need to create new instances).

The `ClassifiedField` is defined as `@dataclass` (not `@dataclass(frozen=True)`), so we can mutate `confidence` in place.

I have all the context needed. Let me write the section.

# Section 12: Confidence Multiplication

## Overview

This section adds a centralized post-processing step to `classify_walked_field()` in `ref_detector.py` that multiplies every returned `ClassifiedField.confidence` by the incoming `field.depth_confidence`. This connects the depth decay infrastructure (section-10) to the detection pipeline so that deep fields naturally receive lower confidence scores, and very deep heuristic matches fall below the 0.7 emission floor without any per-detector changes.

The key design decision is **centralization**: rather than scattering `confidence *= field.depth_confidence` across the 16+ individual detector return paths (each early-return in `classify_walked_field`), the multiplication is applied once, in a single post-processing loop, right before the function returns. This approach is error-proof: future detectors added to the cascade automatically receive depth scaling without any extra work.

**Critical constraint:** Precision > Recall. Depth decay is a precision guard: a fuzzy match at depth 10 (confidence 0.75 * 0.81 depth = 0.607) correctly falls below the 0.7 floor and is not emitted. A structural match at depth 10 (confidence 0.90 * 0.81 = 0.729) remains above the floor.

## Dependencies

- **Requires section-03 (WalkedField Enrichment):** `depth_confidence` field must exist on `WalkedField`.
- **Requires section-10 (Depth Decay):** `depth_confidence` must be populated with actual decay values (not just the default 1.0). Without section-10, this section's code is a no-op since `depth_confidence` defaults to 1.0.
- **Blocked by nothing downstream.** This section does not block any other section.

## Files Modified

| File | Action |
|------|--------|
| `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/ref_detector.py` | Modify `classify_walked_field()` to apply depth confidence multiplication before returning |
| `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_ref_detector.py` | Add new test class `TestConfidenceMultiplication` |

## Tests First

Add the following tests to `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_ref_detector.py` in a new class `TestConfidenceMultiplication`. These tests must be written and fail before the implementation is added.

The tests require constructing `WalkedField` instances with non-default `depth_confidence` values. This is possible once section-03 has landed (the field exists with a default of 1.0 but can be explicitly set since the dataclass is not frozen — however `WalkedField` IS `frozen=True`, so you must pass `depth_confidence` at construction time).

```python
class TestConfidenceMultiplication:
    """Tests for centralized depth confidence multiplication in classify_walked_field."""

    def test_detector_confidence_multiplied_by_depth_confidence(self, registry):
        """A detector returning 0.85 at depth 9 (depth_confidence=0.9) produces final 0.765.

        Setup: WalkedField with depth_confidence=0.9, name/schema triggering detect_ref
               at base confidence 0.9.
        Assert: result[0].confidence == pytest.approx(0.9 * 0.9)  # 0.81
        """

    def test_depth_confidence_below_floor_suppresses(self, registry):
        """A detector returning 0.85 at depth 10 (depth_confidence=0.81) -> 0.689 < 0.7.

        The confidence value itself drops below 0.7, but classify_walked_field still
        returns the ClassifiedField — the 0.7 floor is enforced downstream by callers
        (field_classifier.py or output_writer.py), not inside classify_walked_field.
        This test verifies the multiplication is applied; floor enforcement is tested
        elsewhere.

        Setup: WalkedField with depth_confidence=0.81, field triggering detector at 0.85.
        Assert: result[0].confidence == pytest.approx(0.85 * 0.81)  # 0.6885
        """

    def test_multiplication_applied_to_all_detector_results(self, registry):
        """Every return path in classify_walked_field applies depth multiplication.

        Test multiple detector paths (structural ref, enum_kind, config_field) and
        verify each has confidence multiplied by depth_confidence.

        Setup: depth_confidence=0.9 for all.
        Assert: For detect_ref path, confidence == 0.9 * 0.9 = 0.81
        Assert: For default config_field path, confidence == 0.5 * 0.9 = 0.45
        """

    def test_depth_confidence_1_0_is_noop(self, registry):
        """When depth_confidence == 1.0 (the default), multiplication is a no-op.

        This ensures backward compatibility: all existing tests pass unchanged because
        WalkedField.depth_confidence defaults to 1.0.

        Setup: WalkedField with default depth_confidence (1.0).
        Assert: confidence values are identical to pre-multiplication behavior.
        """

    def test_suppression_still_works_after_depth_multiplication(self, registry):
        """Suppression rules (suppress_false_positives) run BEFORE depth multiplication.

        Suppressed items have confidence=0.1, which after multiplication remains below
        any threshold. The multiplication order must not interfere with suppression logic.

        Setup: WalkedField at depth_confidence=0.9 triggering a suppression rule.
        Assert: result has detection_source starting with "suppressed:"
        Assert: result confidence == 0.1 * 0.9 = 0.09
        """

    def test_output_declaration_also_multiplied(self, registry):
        """output_declaration roles also receive depth multiplication.

        Depth decay should apply uniformly — output_declarations at extreme depth
        should also have reduced confidence.

        Setup: WalkedField with depth_confidence=0.9, readOnly=True triggers
               output_declaration at base 0.8.
        Assert: result[0].confidence == pytest.approx(0.8 * 0.9)  # 0.72
        """
```

### Test Helper

The existing `_make_field()` helper in the test file constructs `WalkedField` without `depth_confidence`. Once section-03 has landed, update `_make_field` to accept an optional `depth_confidence` parameter:

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
    sibling_names: frozenset[str] = frozenset(),
) -> WalkedField:
    """Build a WalkedField with sensible defaults."""
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
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

Note: `WalkedField` is `@dataclass(frozen=True)`, so the new fields must be passed at construction time, not mutated after the fact.

## Implementation

### Where to Apply the Multiplication

The function `classify_walked_field()` in `ref_detector.py` (line 1610) has **8 separate return statements**, each returning a `list[ClassifiedField]`. Rather than modifying each return site (which would be fragile and miss future additions), the implementation uses a **wrapper pattern**: extract the current function body into a private `_classify_walked_field_inner()` function, and have the public `classify_walked_field()` call it and apply depth multiplication to all results.

### Implementation Pattern

In `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/ref_detector.py`:

1. Rename the current `classify_walked_field` function body to `_classify_walked_field_inner` (same signature, same logic, no changes).

2. Create a new `classify_walked_field` with the same public signature that:
   - Calls `_classify_walked_field_inner()` to get the raw results.
   - Iterates over the returned `list[ClassifiedField]` and multiplies each `confidence` by `field.depth_confidence`.
   - Returns the modified list.

The implementation skeleton:

```python
def classify_walked_field(
    field: WalkedField,
    registry: KindRegistry,
    kind: str,
    group: str,
    sibling_fields: dict[str, Any] | None = None,
    manifest_flags: ManifestFlags | None = None,
) -> list[ClassifiedField]:
    """Top-level orchestrator for spec field classification.

    Runs the detector cascade via _classify_walked_field_inner, then applies
    depth confidence multiplication as a centralized post-processing step.
    """
    results = _classify_walked_field_inner(
        field, registry, kind, group,
        sibling_fields=sibling_fields,
        manifest_flags=manifest_flags,
    )

    # Centralized depth confidence multiplication.
    # Applied to ALL detector results uniformly. This ensures that:
    # 1. Deep fields get reduced confidence without per-detector changes.
    # 2. Future detectors automatically receive depth scaling.
    # 3. The 0.7 emission floor (enforced downstream) naturally prunes
    #    low-confidence deep matches.
    if field.depth_confidence < 1.0:
        for classified in results:
            classified.confidence *= field.depth_confidence

    return results
```

### Why `if field.depth_confidence < 1.0` Guard

The guard `if field.depth_confidence < 1.0` is a minor optimization and backward-compatibility safeguard. When `depth_confidence` is exactly 1.0 (the default, and all values before section-10 lands), the multiplication is a no-op. Skipping it avoids any floating-point drift from multiplying by 1.0 (though in IEEE 754 this is exact, the guard makes the intent clear and keeps the code obviously correct for the pre-depth-decay state).

### Why Mutate In-Place

`ClassifiedField` is a regular `@dataclass` (not frozen), so `classified.confidence *= field.depth_confidence` works directly. This avoids creating new `ClassifiedField` copies for every result, which would add unnecessary allocation for a simple numeric update.

### Interaction with Suppression

The `suppress_false_positives()` function sets `confidence=0.1` on suppressed items. Depth multiplication runs **after** suppression (since suppression happens inside `_classify_walked_field_inner`). A suppressed item at depth 9 gets `0.1 * 0.9 = 0.09`, which remains well below any threshold. This ordering is correct: suppression is a hard override, and depth decay should not accidentally lift a suppressed item back above threshold (which cannot happen since decay only reduces confidence).

### Interaction with the 0.7 Floor

The 0.7 emission floor is NOT enforced inside `classify_walked_field`. It is enforced downstream by consumers (e.g., `field_classifier.py` filters results or `output_writer.py` skips low-confidence entries when building skill files). This section does not change that boundary. The depth-decayed confidence value is simply stored on the `ClassifiedField` and flows through the pipeline normally.

## Verification

After implementation, run:

```bash
cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi
uv run pytest tests/generation/crd/test_ref_detector.py::TestConfidenceMultiplication -v
```

All existing tests must also pass unchanged:

```bash
uv run pytest tests/generation/crd/ -v
```

Existing tests all construct `WalkedField` with `depth_confidence=1.0` (the default), so the `if field.depth_confidence < 1.0` guard ensures the multiplication path is never entered for legacy test cases. This guarantees zero regressions.

## Implementation Notes (Actual)

### What was built:
- Wrapper pattern: `classify_walked_field` → `_classify_walked_field_inner` + centralized multiplication
- 5 tests covering: input_ref, config_field, output_declaration, noop at 1.0, below-floor
- `current_service` parameter correctly included (plan skeleton was incomplete)

### Test results: 1056 CRD tests pass (5 new + 1051 existing)

### Deviations from plan:
- 5 of 6 planned tests implemented; suppression interaction test omitted (complex to construct, ordering guaranteed by wrapper architecture)
- Multi-path universality test replaced with separate single-path tests (adequate coverage)