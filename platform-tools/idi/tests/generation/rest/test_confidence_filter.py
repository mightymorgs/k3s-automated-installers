"""Tests for confidence threshold filtering in merge.py."""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency
from idi.generation.dep_adapters.merge import filter_by_confidence


def _dep(source: str, confidence: float, field: str = "f", target: str = "t") -> Dependency:
    return Dependency(field=field, target_resource=target, confidence=confidence, source=source)


class TestFilterByConfidence:
    """filter_by_confidence enforces per-source thresholds."""

    def test_removes_body_deps_below_025(self):
        deps = [_dep("generic_odg:body", 0.24)]
        assert filter_by_confidence(deps) == []

    def test_keeps_body_deps_at_exactly_025(self):
        deps = [_dep("generic_odg:body", 0.25)]
        assert len(filter_by_confidence(deps)) == 1

    def test_removes_path_deps_below_050(self):
        deps = [_dep("generic_odg:path", 0.49)]
        assert filter_by_confidence(deps) == []

    def test_keeps_path_deps_at_exactly_050(self):
        deps = [_dep("generic_odg:path", 0.50)]
        assert len(filter_by_confidence(deps)) == 1

    def test_never_filters_link_deps(self):
        deps = [_dep("generic_odg:link", 0.0)]
        assert len(filter_by_confidence(deps)) == 1

    def test_never_filters_annotation_deps(self):
        deps = [_dep("generic_odg:annotation", 0.0)]
        assert len(filter_by_confidence(deps)) == 1

    def test_default_threshold_for_unknown_source(self):
        # Unknown sources use default threshold 0.25
        deps = [_dep("some_other:source", 0.24)]
        assert filter_by_confidence(deps) == []
        deps2 = [_dep("some_other:source", 0.25)]
        assert len(filter_by_confidence(deps2)) == 1

    def test_preserves_dep_ordering(self):
        deps = [
            _dep("generic_odg:body", 0.30, field="a"),
            _dep("generic_odg:body", 0.40, field="b"),
            _dep("generic_odg:body", 0.35, field="c"),
        ]
        result = filter_by_confidence(deps)
        assert [d.field for d in result] == ["a", "b", "c"]

    def test_empty_list_returns_empty(self):
        assert filter_by_confidence([]) == []

    def test_query_deps_use_025_threshold(self):
        deps = [_dep("generic_odg:query", 0.24)]
        assert filter_by_confidence(deps) == []
        deps2 = [_dep("generic_odg:query", 0.25)]
        assert len(filter_by_confidence(deps2)) == 1

    def test_float_arithmetic_boundary(self):
        # Real pipeline: 0.7 * 0.7 * 0.5 = 0.245 (below 0.25 body threshold)
        deps = [_dep("generic_odg:body", 0.7 * 0.7 * 0.5)]
        assert filter_by_confidence(deps) == []
        # 0.5 * 0.5 = 0.25 exactly
        deps2 = [_dep("generic_odg:body", 0.5 * 0.5)]
        assert len(filter_by_confidence(deps2)) == 1
