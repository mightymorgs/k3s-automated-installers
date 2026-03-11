I now have comprehensive understanding of the codebase structure, the plan, the TDD stubs, and the reference implementation. Let me compose the section.

# Section 11: Topological Sort with Cycle Handling

## Overview

This section implements a new module `dep_adapters/topo_sort.py` providing topological execution ordering for the dependency graph. The module combines iterative Tarjan's SCC (Strongly Connected Components) detection with Kahn's topological sort to produce deterministic execution layers. This is entirely new capability -- no execution ordering exists in the current REST pipeline.

**File to create:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/topo_sort.py`
**Test file to create:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_topo_sort.py`

**Dependencies on other sections:**
- Section 01 (data model): The `Dependency` dataclass from `dep_adapters/base.py` carries the edges that the topological sort consumes. The sort operates on a simplified `dict[str, set[str]]` adjacency list, so it does not depend on the `DetectionSource` enum additions, but it does read `Dependency.confidence` for threshold filtering.
- Section 08 (Phase B adapter elimination): This section is listed as parallelizable with sections 09, 10, and 12 after section 08 completes. The topo sort module is standalone and does not import from any adapter code -- it receives a pre-built adjacency graph.

**Blocks:** Section 13 (Phase C adapter slimming) depends on this section completing.

---

## Background

### Why Topological Sort

The IDI pipeline detects dependency edges between API operations (e.g., "POST /users produces user_id" and "POST /orders consumes user_id"). Without execution ordering, a test harness or deployment tool would attempt operations in arbitrary order, failing when a consumer runs before its producer.

Topological sort groups operations into layers. Layer 0 contains operations with no dependencies. Layer N depends only on layers 0..N-1. Operations within the same layer can execute in parallel.

### Why Tarjan's SCC

Real-world APIs can have circular dependencies. For example, a User has an `organization_id` FK, and an Organization has an `owner_id` FK pointing back to User. Both require the other to exist first. Tarjan's algorithm identifies these cycles as Strongly Connected Components (SCCs). Once identified, the SCC is condensed into a single node for sorting purposes, and the cycle-breaking strategy determines a creation order within the SCC.

### Design Decision: No External Dependencies

The implementation is hand-rolled (~250 LOC) rather than using networkx. The algorithm is well-defined, graph sizes are moderate (100-1000 nodes), and avoiding the networkx dependency keeps the package lightweight. The API is generic enough for CRD pipeline adoption later (the Kahn's sort readiness analysis for the CRD pipeline references this same module design).

### Reference Implementation

The Schemathesis project at `~/GitRepo/adapter-consolidation-refs/Schemathesis/src/schemathesis/specs/openapi/stateful/dependencies/layers.py` provides a reference implementation with Kahn's algorithm and Tarjan's SCC. Key differences from what we need:

- Schemathesis uses a recursive Tarjan's implementation -- we need iterative to handle large graphs without stack overflow.
- Schemathesis does not implement cycle-breaking (nullable FK identification) -- we need this.
- Schemathesis does not implement the early termination fallback for >1000 nodes -- we need this.

---

## Tests (Write First)

Create the test file at `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_topo_sort.py`. You will also need to create `__init__.py` files for the `tests/generation/rest/` directory.

```python
"""Tests for dep_adapters/topo_sort.py — Tarjan's SCC + Kahn's topological sort."""
import logging

import pytest

from idi.generation.dep_adapters.topo_sort import tarjan_scc, topological_layers


class TestTopologicalLayers:
    """Tests for the topological_layers public API."""

    def test_empty_graph_returns_empty_layers(self):
        """Empty graph (no nodes) produces empty layer list."""
        result = topological_layers({})
        assert result == []

    def test_single_node_no_deps(self):
        """Single node with no dependencies goes into its own layer."""
        result = topological_layers({"A": set()})
        assert result == [["A"]]

    def test_linear_chain(self):
        """Linear chain A->B->C produces three layers."""
        # A depends on nothing, B depends on A, C depends on B
        deps = {"A": set(), "B": {"A"}, "C": {"B"}}
        result = topological_layers(deps)
        assert result == [["A"], ["B"], ["C"]]

    def test_diamond_dependency(self):
        """Diamond: A->{B,C}->D produces three layers with B,C parallel."""
        deps = {"A": set(), "B": {"A"}, "C": {"A"}, "D": {"B", "C"}}
        result = topological_layers(deps)
        assert result[0] == ["A"]
        assert set(result[1]) == {"B", "C"}
        assert result[2] == ["D"]

    def test_simple_cycle_detected_as_scc(self):
        """A->B->A cycle: both placed in same layer."""
        deps = {"A": {"B"}, "B": {"A"}}
        result = topological_layers(deps)
        # Both must be in the same layer since they form a cycle
        assert len(result) == 1
        assert set(result[0]) == {"A", "B"}

    def test_cycle_with_nullable_fk(self):
        """Cycle-breaking identifies nullable FK field for create-update pattern."""
        # This test verifies the cycle metadata, not layer placement
        deps = {"A": {"B"}, "B": {"A"}}
        result = topological_layers(deps)
        assert set(result[0]) == {"A", "B"}

    def test_cycle_with_no_nullable_fk_emits_warning(self, caplog):
        """Cycle with no nullable FK emits a warning."""
        deps = {"A": {"B"}, "B": {"A"}}
        with caplog.at_level(logging.WARNING):
            topological_layers(deps)
        # Warning about unresolvable cycle should be present
        # (exact message checked in implementation)

    def test_complex_cycle_three_nodes(self):
        """3-node cycle A->B->C->A: all in same layer."""
        deps = {"A": {"C"}, "B": {"A"}, "C": {"B"}}
        result = topological_layers(deps)
        assert len(result) == 1
        assert set(result[0]) == {"A", "B", "C"}

    def test_disconnected_components(self):
        """Disconnected components: all represented in output."""
        deps = {"A": set(), "B": set(), "C": {"D"}, "D": set()}
        result = topological_layers(deps)
        all_nodes = {n for layer in result for n in layer}
        assert all_nodes == {"A", "B", "C", "D"}

    def test_large_graph_threshold_escalation(self):
        """Graph >1000 nodes triggers threshold escalation to 0.9."""
        # Build a graph with >1000 nodes
        nodes = {f"n{i}": set() for i in range(1001)}
        # Add some dependencies
        for i in range(1, 1001):
            nodes[f"n{i}"].add(f"n{i-1}")
        result = topological_layers(nodes)
        # Should still produce a valid result (all nodes present)
        all_nodes = {n for layer in result for n in layer}
        assert len(all_nodes) == 1001

    def test_large_graph_single_layer_fallback(self, caplog):
        """If threshold raise still leaves >1000 nodes, single-layer fallback with warning."""
        # Build dense graph >1000 nodes where threshold can't help
        # (no confidence info in pure adjacency list — fallback is tested
        # via the confidence-filtered variant)
        nodes = {f"n{i}": set() for i in range(1002)}
        with caplog.at_level(logging.WARNING):
            result = topological_layers(nodes)
        all_nodes = {n for layer in result for n in layer}
        assert len(all_nodes) == 1002

    def test_output_is_deterministic(self):
        """Same input produces same output across multiple runs."""
        deps = {"A": set(), "B": {"A"}, "C": {"A"}, "D": {"B", "C"}}
        results = [topological_layers(deps) for _ in range(10)]
        assert all(r == results[0] for r in results)

    def test_nodes_referenced_only_as_deps_included(self):
        """Nodes that appear only as dependencies (not keys) are included."""
        # "X" is referenced by A but not a key itself
        deps = {"A": {"X"}}
        result = topological_layers(deps)
        all_nodes = {n for layer in result for n in layer}
        assert "X" in all_nodes
        assert "A" in all_nodes

    def test_scc_with_external_deps(self):
        """SCC depends on external node: external in earlier layer."""
        # X is independent, A and B form a cycle, both depend on X
        deps = {"X": set(), "A": {"B", "X"}, "B": {"A"}}
        result = topological_layers(deps)
        # X must come before A and B
        x_layer = next(i for i, layer in enumerate(result) if "X" in layer)
        ab_layer = next(i for i, layer in enumerate(result) if "A" in layer)
        assert x_layer < ab_layer

    def test_scc_with_dependent_node(self):
        """Node depends on SCC: appears in later layer."""
        deps = {"A": {"B"}, "B": {"A"}, "C": {"A"}}
        result = topological_layers(deps)
        ab_layer = next(i for i, layer in enumerate(result) if "A" in layer)
        c_layer = next(i for i, layer in enumerate(result) if "C" in layer)
        assert c_layer > ab_layer


class TestTarjanSCC:
    """Tests for the tarjan_scc function directly."""

    def test_no_cycles(self):
        """Acyclic graph: each node is its own SCC."""
        graph = {"A": {"B"}, "B": {"C"}, "C": set()}
        sccs = tarjan_scc(graph)
        assert all(len(scc) == 1 for scc in sccs)
        all_nodes = {n for scc in sccs for n in scc}
        assert all_nodes == {"A", "B", "C"}

    def test_simple_cycle(self):
        """Two-node cycle detected as single SCC."""
        graph = {"A": {"B"}, "B": {"A"}}
        sccs = tarjan_scc(graph)
        cycle_sccs = [scc for scc in sccs if len(scc) > 1]
        assert len(cycle_sccs) == 1
        assert set(cycle_sccs[0]) == {"A", "B"}

    def test_complex_cycle(self):
        """Three-node cycle detected as single SCC."""
        graph = {"A": {"B"}, "B": {"C"}, "C": {"A"}}
        sccs = tarjan_scc(graph)
        cycle_sccs = [scc for scc in sccs if len(scc) > 1]
        assert len(cycle_sccs) == 1
        assert set(cycle_sccs[0]) == {"A", "B", "C"}

    def test_multiple_sccs(self):
        """Graph with two separate cycles."""
        graph = {
            "A": {"B"}, "B": {"A"},   # cycle 1
            "C": {"D"}, "D": {"C"},   # cycle 2
        }
        sccs = tarjan_scc(graph)
        cycle_sccs = [scc for scc in sccs if len(scc) > 1]
        assert len(cycle_sccs) == 2

    def test_empty_graph(self):
        """Empty graph produces no SCCs."""
        assert tarjan_scc({}) == []

    def test_single_node(self):
        """Single node with no edges is a trivial SCC."""
        sccs = tarjan_scc({"A": set()})
        assert len(sccs) == 1
        assert sccs[0] == ["A"]

    def test_self_loop(self):
        """Node with self-loop forms a single-node SCC (still detected)."""
        sccs = tarjan_scc({"A": {"A"}})
        assert len(sccs) == 1
        assert "A" in sccs[0]

    def test_returns_correct_sccs_for_known_graph(self):
        """Classic example graph with known SCC structure."""
        # Standard Tarjan's example:
        # 1->2, 2->3, 3->1 (cycle), 3->4, 4->5, 5->4 (cycle)
        graph = {
            "1": {"2"}, "2": {"3"}, "3": {"1", "4"},
            "4": {"5"}, "5": {"4"},
        }
        sccs = tarjan_scc(graph)
        scc_sets = [frozenset(scc) for scc in sccs]
        assert frozenset({"1", "2", "3"}) in scc_sets
        assert frozenset({"4", "5"}) in scc_sets
```

Additionally, create the required `__init__.py` files:
- `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/__init__.py` (empty file)

---

## Implementation Details

### File: `dep_adapters/topo_sort.py`

**Full path:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/dep_adapters/topo_sort.py`

**Estimated size:** ~250 LOC

### Public API

Two public functions:

```python
def topological_layers(dependencies: dict[str, set[str]]) -> list[list[str]]:
    """Return operations grouped into execution layers.
    
    Layer 0 has no dependencies. Layer N depends only on layers 0..N-1.
    Operations within the same layer can execute in parallel (if independent)
    or require cycle-breaking (if in an SCC).
    
    Args:
        dependencies: Adjacency list mapping each operation to the set of
            operations it depends on. Nodes referenced only as dependencies
            (appearing in value sets but not as keys) are implicitly included
            as zero-dependency nodes.
    
    Returns:
        List of layers, where each layer is a sorted list of operation names.
        Empty list for empty input.
    """
```

```python
def tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find all strongly connected components using iterative Tarjan's.
    
    Args:
        graph: Adjacency list mapping each node to its successors (nodes it
            points to). For dependency graphs, this means each key points to
            the nodes it depends on.
    
    Returns:
        List of SCCs, where each SCC is a list of node names. Single-node
        SCCs (no cycle) are included.
    """
```

### Algorithm (4 Steps)

**Step 1 -- Collect all nodes:** Before running any algorithm, collect the full node set from both keys and values of the adjacency list. Nodes that appear only as dependency targets (in value sets but not as keys) must be added with empty dependency sets. This prevents silent node loss.

**Step 2 -- Tarjan's SCC (iterative):** Identify strongly connected components in the dependency graph. Use an iterative implementation with an explicit call stack to avoid Python's recursion limit on large graphs. The iterative version uses a stack of frames `(node, neighbor_iterator, lowlink)` to simulate the recursive DFS. State tracking requires:
- `index: dict[str, int]` -- discovery order
- `lowlink: dict[str, int]` -- minimum reachable index
- `on_stack: set[str]` -- nodes currently on the DFS stack
- `stack: list[str]` -- the Tarjan stack
- `index_counter: int` -- monotonically increasing counter

For each unvisited node, push a frame onto the call stack. Process neighbors iteratively. When all neighbors are processed, check if `lowlink[node] == index[node]` (root of SCC) and pop the SCC from the stack.

**Step 3 -- Condense:** Replace each multi-node SCC with a single representative node in a condensed graph. Build a mapping `node_to_scc: dict[str, int]` from each node to its SCC index. Build condensed adjacency list where edges between different SCCs become edges between their SCC representatives. Intra-SCC edges are dropped.

**Step 4 -- Kahn's sort on condensed DAG:** Compute in-degree for each SCC node. Initialize a queue with all zero-in-degree SCC nodes. Process layer by layer:
1. Drain the current queue into the current layer
2. For each processed SCC, decrement in-degree of all dependent SCCs
3. Add newly zero-in-degree SCCs to the queue for the next layer
4. Expand each SCC back to its original members within the layer

### Cycle-Breaking Strategy

When an SCC with multiple members is detected, the module should log information about the cycle for downstream consumers. The cycle-breaking strategy for REST APIs follows the create-create-update pattern:

1. Identify which FK in the cycle is nullable/optional (can be created with a null value)
2. Create the resource with the nullable FK first (null/dummy value)
3. Create the dependency resource using the first resource's ID
4. Update the first resource with the real FK value

The `topological_layers` function does not itself execute this pattern -- it identifies the SCC members and logs a warning. Downstream consumers (the execution engine) use the SCC membership information to apply the pattern. If no nullable FK can be identified from the graph structure alone, emit a `logging.WARNING` indicating the cycle cannot be automatically resolved.

### Early Termination Fallback

If the dependency graph exceeds 1000 nodes:
1. Log a warning about graph size
2. Attempt the sort anyway (the iterative Tarjan's and Kahn's are both O(V+E), so 1000 nodes is manageable)
3. If processing takes too long or produces degenerate results, fall back to placing all operations in a single layer with a warning

The >1000 node threshold is primarily about confidence filtering. When called with a confidence-filtered graph (a higher-level concern), the caller may raise the confidence threshold from 0.7 to 0.9 to reduce edge count before retrying. The `topo_sort.py` module itself operates on the pre-filtered adjacency list and does not filter by confidence -- that responsibility belongs to the caller.

### Determinism

Sort operations within each layer alphabetically (using `sorted()`) to ensure deterministic output. This is important for test stability and reproducible builds.

### Internal Helpers

```python
def _collect_all_nodes(dependencies: dict[str, set[str]]) -> dict[str, set[str]]:
    """Ensure all referenced nodes exist as keys with their dependency sets.
    
    Nodes that appear only in value sets are added with empty dependency sets.
    """
```

```python
def _condense_graph(
    sccs: list[list[str]],
    dependencies: dict[str, set[str]],
) -> tuple[dict[int, set[int]], dict[str, int], list[list[str]]]:
    """Build condensed DAG from SCCs.
    
    Returns:
        - scc_deps: adjacency list for condensed graph (SCC index -> dependent SCC indices)
        - node_to_scc: mapping from original node to SCC index
        - sccs: the SCC list (passed through for expansion)
    """
```

```python
def _kahns_sort(scc_deps: dict[int, set[int]], num_sccs: int) -> list[list[int]]:
    """Kahn's topological sort on condensed DAG.
    
    Returns list of layers, where each layer is a list of SCC indices.
    """
```

### Integration Point

The `topological_layers` function is called after the full pipeline has run and all `Dependency` objects have been collected. The caller builds the adjacency list from the dependency graph:

```python
# Example caller usage (not part of topo_sort.py):
deps_graph: dict[str, set[str]] = {}
for operation_name, operation_deps in all_detected_dependencies.items():
    deps_graph[operation_name] = {
        dep.target_resource for dep in operation_deps
        if dep.confidence >= 0.7  # confidence filtering happens at call site
    }
layers = topological_layers(deps_graph)
```

The topo_sort module is a pure graph algorithm with no awareness of `Dependency`, `Output`, `OperationInfo`, or any other pipeline types. It takes `dict[str, set[str]]` and returns `list[list[str]]`. This keeps it reusable across both REST and CRD pipelines.

### Note on Registry Integration

Unlike other dep_adapters (e.g., `link_deps.py`, `annotation_deps.py`), the topo_sort module is NOT a `DepAdapter` and is NOT registered in `DepAdapterRegistry`. It is a post-processing step called after all adapters have run and all dependencies have been collected. It does not implement `matches()`, `detect_dependencies()`, or `detect_outputs()`.

### Reference Source

The Schemathesis implementation at `~/GitRepo/adapter-consolidation-refs/Schemathesis/src/schemathesis/specs/openapi/stateful/dependencies/layers.py` provides the reference for the Kahn's + Tarjan's approach. Key adaptations from the reference:

1. **Iterative Tarjan's:** The Schemathesis `_find_sccs` uses recursive `strongconnect()`. Replace with an iterative version using an explicit frame stack to avoid Python's default 1000-frame recursion limit on large graphs.
2. **Standalone API:** Schemathesis couples the sort to its `DependencyGraph` model. Our implementation takes a plain `dict[str, set[str]]` adjacency list.
3. **Cycle-breaking metadata:** Schemathesis silently places cycle members in the same layer. Our implementation additionally logs cycle information for the create-create-update pattern.
4. **Deterministic sorting:** Use `sorted()` on layer members for reproducible output.

---

## Implementation Notes

**Implemented:** All items complete. Deviations from plan:

1. **Single-layer fallback skipped (user decision):** O(V+E) handles 10K+ nodes in <100ms. Fallback would hide real cycle problems. Confirmed with user that this scales to planned thousands-of-APIs use case.
2. **`_condense_graph` returns 2-tuple** instead of plan's 3-tuple — `sccs` already in caller scope.
3. **Kahn's post-condition assertion added** per code review — `RuntimeError` if placed SCCs != total (should be impossible after Tarjan's, but fail-fast).
4. **Dead duplicate test removed:** `test_cycle_with_nullable_fk` merged into `test_cycle_emits_warning` with actual log assertion.
5. **Large-graph tests strengthened:** Renamed with accurate docstrings, added structural assertions (layer count, warning content).

**Tests:** 22 tests in `tests/generation/rest/test_topo_sort.py`, all passing.

**Files created:** `dep_adapters/topo_sort.py` (~180 LOC), `tests/generation/rest/test_topo_sort.py` (~180 LOC)