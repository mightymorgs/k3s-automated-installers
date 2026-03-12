"""Tests for _deduplicate_classifications — CRD Phase 3 Section 01."""
from __future__ import annotations

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.ref_detector import _deduplicate_classifications


def _make_cf(
    field: str = "spec.x",
    role: str = "input_ref",
    confidence: float = 0.8,
    target_kind: str | None = "Secret",
    target_group: str | None = "core",
    detection_source: str = "test",
) -> ClassifiedField:
    return ClassifiedField(
        field=field,
        role=role,
        confidence=confidence,
        field_type="string",
        target_kind=target_kind,
        target_group=target_group,
        detection_source=detection_source,
    )


class TestDeduplicateClassifications:
    def test_empty_returns_empty(self):
        assert _deduplicate_classifications([]) == []

    def test_no_duplicates_unchanged(self):
        items = [
            _make_cf(field="spec.a", target_kind="Secret"),
            _make_cf(field="spec.b", target_kind="ConfigMap"),
        ]
        result = _deduplicate_classifications(items)
        assert len(result) == 2

    def test_same_key_keeps_highest_confidence(self):
        low = _make_cf(confidence=0.8, detection_source="low")
        high = _make_cf(confidence=0.95, detection_source="high")
        result = _deduplicate_classifications([low, high])
        assert len(result) == 1
        assert result[0].confidence == 0.95
        assert result[0].detection_source == "high"

    def test_different_target_kind_not_deduped(self):
        a = _make_cf(target_kind="Secret")
        b = _make_cf(target_kind="ConfigMap")
        result = _deduplicate_classifications([a, b])
        assert len(result) == 2

    def test_different_role_not_deduped(self):
        a = _make_cf(role="input_ref")
        b = _make_cf(role="output_declaration")
        result = _deduplicate_classifications([a, b])
        assert len(result) == 2

    def test_different_field_path_not_deduped(self):
        a = _make_cf(field="spec.a")
        b = _make_cf(field="spec.b")
        result = _deduplicate_classifications([a, b])
        assert len(result) == 2

    def test_different_target_group_not_deduped(self):
        a = _make_cf(target_group="core")
        b = _make_cf(target_group="apps")
        result = _deduplicate_classifications([a, b])
        assert len(result) == 2
