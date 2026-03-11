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

    def test_cycle_emits_warning(self, caplog):
        """Cycle detection emits a warning for downstream consumers."""
        deps = {"A": {"B"}, "B": {"A"}}
        with caplog.at_level(logging.WARNING):
            topological_layers(deps)
        assert any("Cycle detected" in r.message for r in caplog.records)

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

    def test_large_graph_linear_chain(self):
        """Sort handles >1000 node linear chain correctly."""
        nodes = {f"n{i}": set() for i in range(1001)}
        for i in range(1, 1001):
            nodes[f"n{i}"].add(f"n{i-1}")
        result = topological_layers(nodes)
        all_nodes = {n for layer in result for n in layer}
        assert len(all_nodes) == 1001
        assert len(result) == 1001  # linear chain = one node per layer

    def test_large_graph_independent_nodes(self, caplog):
        """Sort handles >1000 independent nodes with size warning."""
        nodes = {f"n{i}": set() for i in range(1002)}
        with caplog.at_level(logging.WARNING):
            result = topological_layers(nodes)
        all_nodes = {n for layer in result for n in layer}
        assert len(all_nodes) == 1002
        assert len(result) == 1  # all independent = single layer
        assert any("Large dependency graph" in r.message for r in caplog.records)

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


class TestConfidenceCycleBreaking:
    """Tests for confidence-based cycle breaking in topological_layers."""

    def test_lowest_confidence_edge_removed(self):
        """SCC with edges at different confidence — lowest-confidence edge removed."""
        # A depends on B (conf 0.9), B depends on A (conf 0.3)
        deps = {"A": {"B"}, "B": {"A"}}
        confs = {("A", "B"): 0.9, ("B", "A"): 0.3}
        result = topological_layers(deps, edge_confidences=confs)
        # B→A (0.3) removed → B has no deps, A depends on B
        assert result == [["B"], ["A"]]

    def test_scc_breaks_into_valid_ordering(self):
        """After removing lowest edge, SCC breaks into valid ordering."""
        # 3-node cycle: A depends on C, B depends on A, C depends on B
        deps = {"A": {"C"}, "B": {"A"}, "C": {"B"}}
        confs = {("A", "C"): 0.8, ("B", "A"): 0.7, ("C", "B"): 0.3}
        result = topological_layers(deps, edge_confidences=confs)
        # Remove C→B (0.3): C no longer depends on B
        # Remaining: A→C, B→A → layers [C], [A], [B]
        assert result == [["C"], ["A"], ["B"]]

    def test_standard_breaking_takes_precedence(self):
        """When no edge_confidences provided, cycles stay grouped (standard behavior)."""
        deps = {"A": {"B"}, "B": {"A"}}
        result = topological_layers(deps)
        # Without confidences, SCC stays grouped in same layer
        assert len(result) == 1
        assert set(result[0]) == {"A", "B"}

    def test_confidence_breaking_only_when_confidences_provided(self):
        """Confidence-based breaking only activates when edge_confidences is provided."""
        deps = {"A": {"B"}, "B": {"A"}}
        # Without confidences — standard behavior (grouped)
        result_no_conf = topological_layers(deps)
        assert len(result_no_conf) == 1

        # With confidences — cycle broken
        confs = {("A", "B"): 0.9, ("B", "A"): 0.3}
        result_with_conf = topological_layers(deps, edge_confidences=confs)
        assert len(result_with_conf) == 2

    def test_equal_confidence_deterministic(self):
        """SCC with all equal confidence — deterministic edge removal (alphabetical)."""
        deps = {"A": {"B"}, "B": {"A"}}
        confs = {("A", "B"): 0.5, ("B", "A"): 0.5}
        result = topological_layers(deps, edge_confidences=confs)
        # Equal confidence: tiebreak by (source, target) alphabetically
        # ("A", "B") < ("B", "A") → remove A→B first
        # A no longer depends on B, B still depends on A → [A], [B]
        assert result == [["A"], ["B"]]

        # Verify determinism
        for _ in range(10):
            assert topological_layers(deps, edge_confidences=confs) == result

    def test_multiple_sccs_broken_independently(self):
        """Multiple SCCs — each broken independently."""
        deps = {
            "A": {"B"}, "B": {"A"},  # SCC 1
            "C": {"D"}, "D": {"C"},  # SCC 2
        }
        confs = {
            ("A", "B"): 0.9, ("B", "A"): 0.2,  # Remove B→A (lowest)
            ("C", "D"): 0.3, ("D", "C"): 0.8,  # Remove C→D (lowest)
        }
        result = topological_layers(deps, edge_confidences=confs)
        all_nodes = {n for layer in result for n in layer}
        assert all_nodes == {"A", "B", "C", "D"}
        # SCC1: A depends on B (kept) → [B, A]
        # SCC2: D depends on C (kept) → [C, D]
        # No cross-deps → [B, C] then [A, D]
        assert result == [["B", "C"], ["A", "D"]]

    def test_removed_edges_logged(self, caplog):
        """Removed edges are reported/logged with reason low_confidence_break."""
        deps = {"A": {"B"}, "B": {"A"}}
        confs = {("A", "B"): 0.9, ("B", "A"): 0.30}
        with caplog.at_level(logging.WARNING):
            topological_layers(deps, edge_confidences=confs)
        cycle_msgs = [r.message for r in caplog.records if "Cycle break" in r.message]
        assert len(cycle_msgs) >= 1
        assert "low_confidence_break" in cycle_msgs[0]

    def test_self_loop_removed(self):
        """Single-node SCC (self-loop) — edge removed."""
        deps = {"A": {"A"}}
        confs = {("A", "A"): 0.5}
        result = topological_layers(deps, edge_confidences=confs)
        assert result == [["A"]]
        # Self-loop should be removed, A placed normally

    def test_broken_edges_collector(self):
        """Caller can collect removed edges via broken_edges parameter."""
        deps = {"A": {"B"}, "B": {"A"}}
        confs = {("A", "B"): 0.9, ("B", "A"): 0.3}
        collector: list[tuple[str, str, float]] = []
        topological_layers(deps, edge_confidences=confs, broken_edges=collector)
        assert len(collector) == 1
        assert collector[0] == ("B", "A", 0.3)

    def test_broken_edges_none_by_default(self):
        """Without broken_edges param, no error and no collection."""
        deps = {"A": {"B"}, "B": {"A"}}
        confs = {("A", "B"): 0.9, ("B", "A"): 0.3}
        # Should work fine without collector
        result = topological_layers(deps, edge_confidences=confs)
        assert len(result) == 2

    def test_missing_confidence_defaults_high(self):
        """Edges not in edge_confidences default to 1.0 — preserved preferentially."""
        # A↔B cycle, only one edge has confidence
        deps = {"A": {"B"}, "B": {"A"}}
        # Only B→A has a score; A→B is missing → defaults to 1.0
        confs = {("B", "A"): 0.2}
        result = topological_layers(deps, edge_confidences=confs)
        # B→A (0.2) removed, A→B (default 1.0) kept → [B], [A]
        assert result == [["B"], ["A"]]

    def test_large_scc_iterative_removal(self):
        """Large SCC (10+ nodes) — iteratively removes edges until acyclic."""
        # 12-node ring: n0 depends on n11, n1 depends on n0, etc.
        nodes = [f"n{i}" for i in range(12)]
        deps = {nodes[i]: {nodes[(i - 1) % 12]} for i in range(12)}
        # Each edge gets increasing confidence
        confs = {
            (nodes[i], nodes[(i - 1) % 12]): 0.1 + i * 0.05
            for i in range(12)
        }
        result = topological_layers(deps, edge_confidences=confs)
        all_nodes = {n for layer in result for n in layer}
        assert all_nodes == set(nodes)
        # Ring broken by removing lowest edge → linear chain → 12 layers
        assert len(result) == 12
