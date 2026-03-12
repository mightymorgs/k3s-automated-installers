"""Tests for polymorphic ref output — multiple target_kind values for same field_path."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.output_writer import (
    _resolve_filenames,
    build_decomposed_skill,
    write_decomposed_skill,
)


def _make_crd_info(**overrides):
    """Build a minimal crd_info dict for testing."""
    base = {
        "kind": "HelmRelease",
        "group": "helm.toolkit.fluxcd.io",
        "version": "v2beta2",
        "plural": "helmreleases",
        "scope": "namespaced",
        "service": "flux",
        "description": "Test CRD",
    }
    base.update(overrides)
    return base


def _make_polymorphic_sourceref_fields():
    """Create 3 ClassifiedField entries for the sourceRef polymorphic pattern."""
    return [
        ClassifiedField(
            field="spec.chart.spec.sourceRef",
            role="input_ref",
            confidence=0.95,
            field_type="object",
            target_kind="HelmRepository",
            target_group="source.toolkit.fluxcd.io",
            detection_source="ref_tuple",
        ),
        ClassifiedField(
            field="spec.chart.spec.sourceRef",
            role="input_ref",
            confidence=0.95,
            field_type="object",
            target_kind="GitRepository",
            target_group="source.toolkit.fluxcd.io",
            detection_source="ref_tuple",
        ),
        ClassifiedField(
            field="spec.chart.spec.sourceRef",
            role="input_ref",
            confidence=0.95,
            field_type="object",
            target_kind="Bucket",
            target_group="source.toolkit.fluxcd.io",
            detection_source="ref_tuple",
        ),
    ]


def _make_single_ref_field():
    """Create 1 ClassifiedField for a non-polymorphic ref."""
    return ClassifiedField(
        field="spec.secretName",
        role="input_ref",
        confidence=0.9,
        field_type="string",
        target_kind="Secret",
        target_group="core",
        detection_source="suffix_kind",
    )


class TestPolymorphicPreservation:
    def test_all_targets_preserved(self):
        """build_decomposed_skill preserves all 3 targets for same field_path."""
        poly_fields = _make_polymorphic_sourceref_fields()
        single = _make_single_ref_field()
        all_fields = poly_fields + [single]
        crd_info = _make_crd_info()
        skill = build_decomposed_skill(crd_info, all_fields)
        assert len(skill["refs"]) == 4

    def test_polymorphic_filenames_include_target_kind(self):
        """Polymorphic filenames have -TargetKind suffix."""
        poly_fields = _make_polymorphic_sourceref_fields()
        crd_info = _make_crd_info()
        skill = build_decomposed_skill(crd_info, poly_fields)
        filenames = set(skill["refs"].keys())
        assert any("-HelmRepository" in f for f in filenames)
        assert any("-GitRepository" in f for f in filenames)
        assert any("-Bucket" in f for f in filenames)

    def test_single_target_no_suffix(self):
        """Single-target field uses plain leaf name, no kind suffix."""
        single = _make_single_ref_field()
        crd_info = _make_crd_info()
        skill = build_decomposed_skill(crd_info, [single])
        filenames = list(skill["refs"].keys())
        assert filenames == ["secretName"]

    def test_each_ref_has_correct_target(self):
        """Each ref entry in the skill has the correct target_kind value."""
        poly_fields = _make_polymorphic_sourceref_fields()
        crd_info = _make_crd_info()
        skill = build_decomposed_skill(crd_info, poly_fields)
        target_kinds = {v["target_kind"] for v in skill["refs"].values()}
        assert target_kinds == {"HelmRepository", "GitRepository", "Bucket"}


class TestPolymorphicCollisionCombined:
    def test_polymorphic_plus_leaf_collision(self):
        """Two polymorphic field_paths with same leaf get hyphen-joined paths."""
        fields = [
            ClassifiedField(
                field="spec.primary.sourceRef", role="input_ref", confidence=0.95,
                field_type="object", target_kind="HelmRepository",
                target_group="source.toolkit.fluxcd.io", detection_source="ref_tuple",
            ),
            ClassifiedField(
                field="spec.primary.sourceRef", role="input_ref", confidence=0.95,
                field_type="object", target_kind="GitRepository",
                target_group="source.toolkit.fluxcd.io", detection_source="ref_tuple",
            ),
            ClassifiedField(
                field="spec.secondary.sourceRef", role="input_ref", confidence=0.95,
                field_type="object", target_kind="HelmRepository",
                target_group="source.toolkit.fluxcd.io", detection_source="ref_tuple",
            ),
            ClassifiedField(
                field="spec.secondary.sourceRef", role="input_ref", confidence=0.95,
                field_type="object", target_kind="GitRepository",
                target_group="source.toolkit.fluxcd.io", detection_source="ref_tuple",
            ),
        ]
        result = _resolve_filenames(fields, "input_ref")
        # 4 entries, all distinct
        assert len(result) == 4
        filenames = set(result.values())
        assert len(filenames) == 4
        # Collision resolution should produce hyphen-joined + kind suffix
        for fname in filenames:
            assert "HelmRepository" in fname or "GitRepository" in fname


class TestResolveFilenamesDeterminism:
    def test_deterministic_across_runs(self):
        """_resolve_filenames returns identical output across multiple calls."""
        fields = _make_polymorphic_sourceref_fields()
        results = [_resolve_filenames(fields, "input_ref") for _ in range(10)]
        for r in results[1:]:
            assert r == results[0]

    def test_triple_key_count(self):
        """_resolve_filenames returns one entry per (field_path, group, kind) triple."""
        fields = _make_polymorphic_sourceref_fields()
        result = _resolve_filenames(fields, "input_ref")
        assert len(result) == 3


class TestWritePolymorphicRefFiles:
    def test_creates_all_ref_files(self, tmp_path):
        """write_decomposed_skill creates one JSON file per polymorphic target."""
        poly_fields = _make_polymorphic_sourceref_fields()
        single = _make_single_ref_field()
        all_fields = poly_fields + [single]
        crd_info = _make_crd_info()
        kind_dir = write_decomposed_skill(crd_info, all_fields, tmp_path)
        ref_files = list((kind_dir / "refs").glob("*.json"))
        assert len(ref_files) == 4

    def test_no_duplicate_assertion(self, tmp_path):
        """write_decomposed_skill does not hit the duplicate file guard."""
        poly_fields = _make_polymorphic_sourceref_fields()
        crd_info = _make_crd_info()
        # Should not raise AssertionError
        write_decomposed_skill(crd_info, poly_fields, tmp_path)

    def test_file_contents_have_correct_targets(self, tmp_path):
        """Each written ref JSON file contains the correct target_kind."""
        poly_fields = _make_polymorphic_sourceref_fields()
        crd_info = _make_crd_info()
        kind_dir = write_decomposed_skill(crd_info, poly_fields, tmp_path)
        ref_files = list((kind_dir / "refs").glob("*.json"))
        target_kinds = set()
        for ref_file in ref_files:
            data = json.loads(ref_file.read_text())
            target_kinds.add(data["target_kind"])
        assert target_kinds == {"HelmRepository", "GitRepository", "Bucket"}
