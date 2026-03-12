# Section 11: Confidence-Based Cycle Breaking

## Overview

Extend the existing topo_sort.py cycle handling to remove the lowest-confidence edge from SCCs when standard breaking strategies fail. This provides a safety net for Kahn's sort — even with residual false positive edges that create false cycles, the sort will produce a valid ordering.

**Phase:** 3 | **Dependencies:** None | **Blocks:** None

---

## File Inventory

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/dep_adapters/topo_sort.py` | Modify: add confidence-based cycle breaking |
| `platform-tools/idi/tests/generation/rest/test_topo_sort.py` | Modify: add confidence-based breaking tests |

---

## Tests (Write First)

Add to existing `test_topo_sort.py`:

```python
# Test: SCC with edges at different confidence levels — lowest-confidence edge removed
# Test: after removing lowest edge, SCC breaks into valid ordering
# Test: standard cycle breaking (nullable FK) takes precedence over confidence-based
# Test: confidence-based breaking only invoked when standard breaking fails
# Test: SCC with all equal confidence — deterministic edge removal (e.g., alphabetical)
# Test: multiple SCCs — each broken independently
# Test: removed edges are reported/logged with reason "low_confidence_break"
# Test: single-node SCC (self-loop) — edge removed
# Test: large SCC (10+ nodes) — iteratively removes edges until acyclic
```

---

## Implementation Details

### Extension to existing cycle handling

The existing `_break_cycle()` method identifies nullable FKs and uses a 3-step create-create-update pattern. When this succeeds, confidence-based breaking is not invoked.

Add a fallback that activates when `_break_cycle()` returns without resolving the SCC:

1. Collect all edges within the SCC
2. Each edge should carry confidence from the `Dependency` it was derived from
3. Sort edges by confidence (ascending)
4. Remove the lowest-confidence edge
5. Re-check if the SCC is broken
6. If still cyclic, repeat (remove next lowest)
7. Log each removed edge with its confidence and the reason

### Confidence propagation

Currently, edges in the topo sort graph may not carry confidence scores from the original `Dependency` objects. The integration point is where `depends_on` entries (from `cli.py`) are converted into graph edges. The confidence must be preserved through this transformation.

If the topo sort currently uses a simple adjacency representation without weights, extend it to carry confidence per edge. This may require changing the edge representation from `(source, target)` to `(source, target, confidence)` or using a dict.

### Determinism

When multiple edges have equal confidence, break ties deterministically (e.g., by alphabetical order of `(source, target)` pair). This ensures same spec → same output.

### Logging

Log each confidence-based edge removal at WARNING level:
```
Cycle break: removed edge {source} → {target} (confidence={conf:.2f}) from SCC of {n} nodes
```

This makes it visible when the safety net activates, so users can investigate whether the removed edge was a real dependency.

---

## Implementation Notes

### Deviations from plan
- **No `_break_cycle()` standard method** — The spec referenced an existing nullable-FK-based breaker that doesn't exist. Confidence-based breaking is the sole cycle-breaking mechanism for now. Standard breaking can be added as a prior step later.
- **Added `broken_edges` collector parameter** — Code review identified that discarding removed edges left no programmatic access for downstream consumers. Added optional `broken_edges: list | None` parameter to `topological_layers` so callers can collect `(source, target, confidence)` tuples without changing the return type.
- **Added iteration cap** — `_break_cycles_by_confidence` uses `for _ in range(max_iterations)` instead of `while True` to prevent unbounded looping on pathological inputs.
- **Fixed falsy empty dict** — Guard changed from `if edge_confidences:` to `if edge_confidences is not None:`.

### Files modified
- `platform-tools/idi/idi/generation/dep_adapters/topo_sort.py` — Added `_break_cycles_by_confidence()` helper (~45 LOC) and extended `topological_layers` signature with `edge_confidences` and `broken_edges` params.
- `platform-tools/idi/tests/generation/rest/test_topo_sort.py` — Added `TestConfidenceCycleBreaking` class with 12 tests.

### Test count
- 34 total in test_topo_sort.py (22 existing + 12 new)
- Full suite: 1532 passed, 1 pre-existing CRD failure

---

## Verification

1. `cd platform-tools/idi && uv run pytest tests/generation/rest/test_topo_sort.py -v`
2. Run topo sort on all 6 enterprise specs after applying phases 1-2
3. Verify all specs produce valid orderings (no unresolved cycles)
4. Check logs for any confidence-based breaks — investigate whether they represent real or false cycles
