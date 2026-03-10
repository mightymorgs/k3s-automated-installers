"""Tests for build_shape_catalog script (C30)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from idi.generation.scripts.build_shape_catalog import build_shape_catalog


def _write_skill(skills_dir: Path, kind: str, group: str, refs: list[dict]) -> None:
    """Write a skill JSON file for testing."""
    skill_dir = skills_dir / group / "default" / kind
    skill_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "kind": kind,
        "group": group,
        "input_refs": refs,
        "output_declarations": [],
    }
    (skill_dir / "manifest.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8",
    )


class TestBuildShapeCatalog:
    def test_empty_skills_dir(self, tmp_path):
        """Empty skills directory -> empty catalog."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        output = tmp_path / "catalog.json"
        result = build_shape_catalog(str(skills_dir), str(output))
        assert result["version"] == "1.0"
        assert result["shapes"] == []
        assert output.is_file()

    def test_nonexistent_skills_dir(self, tmp_path):
        """Non-existent skills directory -> empty catalog."""
        output = tmp_path / "catalog.json"
        result = build_shape_catalog(str(tmp_path / "no_such_dir"), str(output))
        assert result["shapes"] == []

    def test_shapes_from_two_crds(self, tmp_path):
        """Shape confirmed in 2 CRDs -> included with confidence 0.80."""
        skills_dir = tmp_path / "skills"
        ref1 = {
            "source": "ref_detector:kind_registry",
            "target_kind": "Secret",
            "schema": {
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"},
                },
                "required": ["name"],
            },
        }
        _write_skill(skills_dir, "SecretStore", "external-secrets.io", [ref1])
        ref2 = {
            "source": "ref_detector:kind_registry",
            "target_kind": "Secret",
            "schema": {
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"},
                },
                "required": ["name"],
            },
        }
        _write_skill(skills_dir, "ExternalSecret", "external-secrets.io", [ref2])

        output = tmp_path / "catalog.json"
        result = build_shape_catalog(str(skills_dir), str(output))
        assert len(result["shapes"]) >= 1
        shape = result["shapes"][0]
        assert shape["target_kind"] == "Secret"
        assert shape["confidence"] == 0.80
        assert len(shape["confirmed_in"]) == 2

    def test_shapes_from_three_crds(self, tmp_path):
        """Shape confirmed in 3+ CRDs -> confidence 0.85."""
        skills_dir = tmp_path / "skills"
        ref_template = {
            "source": "ref_detector:kind_registry",
            "target_kind": "Secret",
            "schema": {
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"},
                },
                "required": ["name"],
            },
        }
        for kind_name in ("SecretStore", "ExternalSecret", "PushSecret"):
            _write_skill(skills_dir, kind_name, "external-secrets.io", [ref_template])

        output = tmp_path / "catalog.json"
        result = build_shape_catalog(str(skills_dir), str(output))
        assert len(result["shapes"]) >= 1
        assert result["shapes"][0]["confidence"] == 0.85
        assert len(result["shapes"][0]["confirmed_in"]) == 3

    def test_single_crd_excluded(self, tmp_path):
        """Shape confirmed in only 1 CRD -> excluded."""
        skills_dir = tmp_path / "skills"
        ref = {
            "source": "ref_detector:kind_registry",
            "target_kind": "Secret",
            "schema": {
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        }
        _write_skill(skills_dir, "OnlyCRD", "example.com", [ref])

        output = tmp_path / "catalog.json"
        result = build_shape_catalog(str(skills_dir), str(output))
        assert result["shapes"] == []

    def test_collision_handling(self, tmp_path):
        """Same fingerprint maps to Secret in CRD1, ConfigMap in CRD2 -> excluded."""
        skills_dir = tmp_path / "skills"
        ref1 = {
            "source": "ref_detector:kind_registry",
            "target_kind": "Secret",
            "schema": {
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        _write_skill(skills_dir, "CRD1", "example.com", [ref1])
        ref2 = {
            "source": "ref_detector:kind_registry",
            "target_kind": "ConfigMap",
            "schema": {
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        _write_skill(skills_dir, "CRD2", "example.com", [ref2])

        output = tmp_path / "catalog.json"
        result = build_shape_catalog(str(skills_dir), str(output))
        assert result["shapes"] == []

    def test_seeding_filter(self, tmp_path):
        """Only refs from detect_ref and detect_ref_tuple sources are seeded."""
        skills_dir = tmp_path / "skills"
        # This ref has an excluded source.
        ref1 = {
            "source": "ref_detector:constraint_fk",
            "target_kind": "Secret",
            "schema": {
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        _write_skill(skills_dir, "CRD1", "example.com", [ref1])
        ref2 = {
            "source": "ref_detector:constraint_fk",
            "target_kind": "Secret",
            "schema": {
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        _write_skill(skills_dir, "CRD2", "example.com", [ref2])

        output = tmp_path / "catalog.json"
        result = build_shape_catalog(str(skills_dir), str(output))
        assert result["shapes"] == []

    def test_output_json_schema(self, tmp_path):
        """Generated catalog has correct JSON structure."""
        skills_dir = tmp_path / "skills"
        ref = {
            "source": "ref_detector:kind_registry",
            "target_kind": "Secret",
            "schema": {
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"},
                },
                "required": ["name"],
            },
        }
        _write_skill(skills_dir, "CRD1", "a.io", [ref])
        _write_skill(skills_dir, "CRD2", "b.io", [ref])

        output = tmp_path / "catalog.json"
        build_shape_catalog(str(skills_dir), str(output))

        data = json.loads(output.read_text())
        assert "version" in data
        assert "generated" in data
        assert "shapes" in data
        for shape in data["shapes"]:
            assert "fingerprint" in shape
            assert "target_kind" in shape
            assert "confirmed_in" in shape
            assert "confidence" in shape
            assert "required_properties" in shape

    def test_roundtrip_with_shape_catalog(self, tmp_path):
        """Generated catalog can be loaded by ShapeCatalog.load."""
        from idi.generation.crd.ref_detector import ShapeCatalog

        skills_dir = tmp_path / "skills"
        ref = {
            "source": "ref_detector:kind_registry",
            "target_kind": "Secret",
            "schema": {
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"},
                },
                "required": ["name"],
            },
        }
        _write_skill(skills_dir, "CRD1", "a.io", [ref])
        _write_skill(skills_dir, "CRD2", "b.io", [ref])

        output = tmp_path / "catalog.json"
        build_shape_catalog(str(skills_dir), str(output))

        catalog = ShapeCatalog.load(str(output))
        assert len(catalog.shapes) >= 1
