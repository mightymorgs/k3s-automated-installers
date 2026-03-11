"""Topological sort with cycle handling for dependency graphs.

Combines iterative Tarjan's SCC detection with Kahn's topological sort
to produce deterministic execution layers. Pure graph algorithm with no
awareness of pipeline types -- takes dict[str, set[str]] adjacency lists.
"""
from __future__ import annotations

import logging
from collections import deque

logger = logging.getLogger(__name__)

_LARGE_GRAPH_THRESHOLD = 1000


def _collect_all_nodes(dependencies: dict[str, set[str]]) -> dict[str, set[str]]:
    """Ensure all referenced nodes exist as keys with their dependency sets.

    Nodes that appear only in value sets are added with empty dependency sets.
    """
    full = dict(dependencies)
    for deps in dependencies.values():
        for dep in deps:
            if dep not in full:
                full[dep] = set()
    return full


def tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find all strongly connected components using iterative Tarjan's.

    Args:
        graph: Adjacency list mapping each node to its successors (nodes it
            points to). For dependency graphs, each key maps to nodes it
            depends on.

    Returns:
        List of SCCs, where each SCC is a sorted list of node names.
        Single-node SCCs (no cycle) are included.
    """
    if not graph:
        return []

    index_counter = 0
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []

    # Iterative Tarjan's using an explicit call stack.
    # Each frame is (node, neighbor_iterator, is_root_call).
    # We use a sentinel to know when we're returning from a recursive call.
    for start in sorted(graph):
        if start in index:
            continue

        # call_stack frames: (node, neighbor_iter)
        call_stack: list[tuple[str, list[str], int]] = []

        # Initialize start node
        index[start] = lowlink[start] = index_counter
        index_counter += 1
        stack.append(start)
        on_stack.add(start)
        neighbors = sorted(graph.get(start, set()))
        call_stack.append((start, neighbors, 0))

        while call_stack:
            node, nbrs, ni = call_stack[-1]

            if ni < len(nbrs):
                # Advance neighbor index
                call_stack[-1] = (node, nbrs, ni + 1)
                w = nbrs[ni]

                if w not in index:
                    # Push new frame for unvisited neighbor
                    index[w] = lowlink[w] = index_counter
                    index_counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    w_nbrs = sorted(graph.get(w, set()))
                    call_stack.append((w, w_nbrs, 0))
                elif w in on_stack:
                    lowlink[node] = min(lowlink[node], index[w])
            else:
                # All neighbors processed -- check if root of SCC
                if lowlink[node] == index[node]:
                    scc: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        scc.append(w)
                        if w == node:
                            break
                    sccs.append(sorted(scc))

                # Pop frame and update parent's lowlink
                call_stack.pop()
                if call_stack:
                    parent = call_stack[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])

    return sccs


def _condense_graph(
    sccs: list[list[str]],
    dependencies: dict[str, set[str]],
) -> tuple[dict[int, set[int]], dict[str, int]]:
    """Build condensed DAG from SCCs.

    Returns:
        - scc_deps: adjacency list for condensed graph (SCC index -> set of
          SCC indices it depends on)
        - node_to_scc: mapping from original node to SCC index
    """
    node_to_scc: dict[str, int] = {}
    for i, scc in enumerate(sccs):
        for node in scc:
            node_to_scc[node] = i

    scc_deps: dict[int, set[int]] = {i: set() for i in range(len(sccs))}
    for node, deps in dependencies.items():
        src_scc = node_to_scc[node]
        for dep in deps:
            dst_scc = node_to_scc[dep]
            if dst_scc != src_scc:
                scc_deps[src_scc].add(dst_scc)

    return scc_deps, node_to_scc


def _kahns_sort(scc_deps: dict[int, set[int]], num_sccs: int) -> list[list[int]]:
    """Kahn's topological sort on condensed DAG.

    Returns list of layers, where each layer is a sorted list of SCC indices.
    """
    # Build in-degree map
    in_degree: dict[int, int] = {i: 0 for i in range(num_sccs)}
    # scc_deps[i] = set of SCC indices that SCC i depends on
    # So for each dependency edge i -> j, j has an "outgoing" to i
    # We need reverse: for each i, which SCCs depend on i?
    reverse: dict[int, set[int]] = {i: set() for i in range(num_sccs)}
    for scc_idx, deps in scc_deps.items():
        in_degree[scc_idx] = len(deps)
        for dep_idx in deps:
            reverse[dep_idx].add(scc_idx)

    # Start with zero in-degree nodes
    queue = deque(sorted(i for i in range(num_sccs) if in_degree[i] == 0))
    layers: list[list[int]] = []

    while queue:
        layer = sorted(queue)
        queue.clear()
        layers.append(layer)

        for scc_idx in layer:
            for dependent in sorted(reverse[scc_idx]):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

    # Safety: verify all SCCs were placed
    placed = sum(len(layer) for layer in layers)
    if placed != num_sccs:
        raise RuntimeError(
            f"Kahn's sort placed {placed}/{num_sccs} SCCs — "
            "condensed graph may contain a cycle (should be impossible after Tarjan's)"
        )

    return layers


def _break_cycles_by_confidence(
    dependencies: dict[str, set[str]],
    edge_confidences: dict[tuple[str, str], float],
) -> tuple[dict[str, set[str]], list[tuple[str, str, float]]]:
    """Remove lowest-confidence edges from SCCs until graph is acyclic.

    Args:
        dependencies: Adjacency list (deep-copied internally).
        edge_confidences: Mapping (source, target) -> confidence score.

    Returns:
        - Modified dependencies with cycle-causing edges removed.
        - List of removed edges as (source, target, confidence).
    """
    deps = {k: set(v) for k, v in dependencies.items()}
    removed: list[tuple[str, str, float]] = []

    while True:
        sccs = tarjan_scc(deps)
        # Find cyclic SCCs: multi-node or single-node with self-loop
        cyclic = [
            scc
            for scc in sccs
            if len(scc) > 1
            or (len(scc) == 1 and scc[0] in deps.get(scc[0], set()))
        ]
        if not cyclic:
            break

        for scc in cyclic:
            scc_set = set(scc)
            # Collect edges within this SCC
            scc_edges: list[tuple[str, str, float]] = []
            for node in scc:
                for dep in deps.get(node, set()):
                    if dep in scc_set:
                        conf = edge_confidences.get((node, dep), 1.0)
                        scc_edges.append((node, dep, conf))

            if not scc_edges:
                continue

            # Sort by confidence ascending, then alphabetically for determinism
            scc_edges.sort(key=lambda e: (e[2], e[0], e[1]))

            # Remove the lowest-confidence edge
            src, tgt, conf = scc_edges[0]
            deps[src].discard(tgt)
            removed.append((src, tgt, conf))
            logger.warning(
                "Cycle break: removed edge %s → %s "
                "(confidence=%.2f, reason=low_confidence_break) "
                "from SCC of %d nodes",
                src,
                tgt,
                conf,
                len(scc),
            )

    return deps, removed


def topological_layers(
    dependencies: dict[str, set[str]],
    edge_confidences: dict[tuple[str, str], float] | None = None,
) -> list[list[str]]:
    """Return operations grouped into execution layers.

    Layer 0 has no dependencies. Layer N depends only on layers 0..N-1.
    Operations within the same layer can execute in parallel (if independent)
    or require cycle-breaking (if in an SCC).

    Args:
        dependencies: Adjacency list mapping each operation to the set of
            operations it depends on. Nodes referenced only as dependencies
            (appearing in value sets but not as keys) are implicitly included
            as zero-dependency nodes.
        edge_confidences: Optional mapping of (source, target) -> confidence.
            When provided, cycles are broken by iteratively removing the
            lowest-confidence edge from each SCC.

    Returns:
        List of layers, where each layer is a sorted list of operation names.
        Empty list for empty input.
    """
    if not dependencies:
        return []

    # Step 1: Collect all nodes
    full_deps = _collect_all_nodes(dependencies)

    if len(full_deps) > _LARGE_GRAPH_THRESHOLD:
        logger.warning(
            "Large dependency graph (%d nodes) — sort may be slow", len(full_deps)
        )

    # Step 2: Confidence-based cycle breaking (when scores available)
    if edge_confidences:
        full_deps, _removed = _break_cycles_by_confidence(full_deps, edge_confidences)

    # Step 3: Tarjan's SCC detection
    sccs = tarjan_scc(full_deps)

    # Log cycle warnings for any remaining SCCs
    for scc in sccs:
        if len(scc) > 1:
            logger.warning(
                "Cycle detected (%d nodes): %s — "
                "downstream consumer should apply create-create-update pattern",
                len(scc),
                ", ".join(scc),
            )

    # Step 4: Condense graph
    scc_deps, node_to_scc = _condense_graph(sccs, full_deps)

    # Step 5: Kahn's sort on condensed DAG
    scc_layers = _kahns_sort(scc_deps, len(sccs))

    # Expand SCC indices back to node names
    result: list[list[str]] = []
    for scc_layer in scc_layers:
        layer_nodes: list[str] = []
        for scc_idx in scc_layer:
            layer_nodes.extend(sccs[scc_idx])
        result.append(sorted(layer_nodes))

    return result
