"""Tests for helm output writer (Stage 7 — Slice 1)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from idi.generation.helm.context import HelmContext
from idi.generation.helm.models import HelmFact, Classification, VALID_SHAPES
from idi.generation.helm.output_writer import (
    safe_filename,
    sanitize_chart_name,
    write_skill_output,
)
from idi.generation.helm.walker import walk_values
from idi.generation.helm.classifier import classify_facts
from idi.generation.helm.uri import generate_uris


def _fact(**kw: Any) -> HelmFact:
    defaults = dict(
        path="x", path_segments=["x"], uri="helmfacts://t/#x", default_value="",
        type="string", semantic_type="string", has_template=False,
        default_empty=True, default_truncated=False, shape="config",
        format=None, required=False, enum=None, description=None,
        is_toggle=False, conditional_on=None, feature=None,
        cross_app_signal=None,
        classifications=[Classification("shape", "config", "heuristic_default", 0.50, "test")],
        source="heuristic_default", confidence=0.50, needs_review=True,
    )
    defaults.update(kw)
    if "path_segments" in kw and "path" not in kw:
        defaults["path"] = ".".join(kw["path_segments"])
    return HelmFact(**defaults)


def _ctx(facts: list[HelmFact] | None = None, **kw: Any) -> HelmContext:
    defaults = dict(
        chart_name="test-chart", chart_version="1.0.0", app_version="1.0.0",
        repository="https://example.com", values={}, chart_meta={}, values_text="",
        kind_registry=None,
    )
    defaults.update(kw)
    ctx = HelmContext(**defaults)
    if facts:
        ctx.facts = facts
    return ctx


# ---------------------------------------------------------------------------
# safe_filename
# ---------------------------------------------------------------------------

class TestSafeFilename:
    def test_simple_path(self):
        assert safe_filename(["server", "port"]) == "server_port.json"

    def test_special_chars(self):
        result = safe_filename(["podAnnotations", "foo/bar"])
        assert result.endswith(".json")
        assert "/" not in result.rstrip(".json")

    def test_long_path_hashed(self):
        segments = [f"segment{i}" for i in range(30)]
        result = safe_filename(segments)
        assert len(result) <= 220  # 200 + hash + .json
        assert result.endswith(".json")

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError):
            safe_filename(["..", "etc", "passwd"])

    def test_valid_chars_preserved(self):
        assert safe_filename(["my-key", "another_key"]) == "my-key_another_key.json"


class TestSanitizeChartName:
    def test_normal_name(self):
        assert sanitize_chart_name("vault") == "vault"

    def test_path_traversal(self):
        result = sanitize_chart_name("../vault")
        assert ".." not in result
        assert result == "vault"

    def test_slash_removed(self):
        result = sanitize_chart_name("org/chart")
        assert "/" not in result


# ---------------------------------------------------------------------------
# write_skill_output
# ---------------------------------------------------------------------------

class TestWriteSkillOutput:
    def test_creates_directory_structure(self, tmp_path):
        ctx = _ctx([_fact()])
        write_skill_output(ctx, tmp_path)
        chart_dir = tmp_path / "test-chart"
        assert (chart_dir / "manifest.json").exists()
        assert (chart_dir / "install.json").exists()
        assert (chart_dir / "facts").is_dir()
        assert (chart_dir / "features").is_dir()
        assert (chart_dir / "signals").is_dir()

    def test_manifest_has_required_fields(self, tmp_path):
        ctx = _ctx([_fact()])
        write_skill_output(ctx, tmp_path)
        manifest = json.loads((tmp_path / "test-chart" / "manifest.json").read_text())
        assert manifest["schema_version"] == "2.0"
        assert manifest["artifact_type"] == "helm"
        assert manifest["chart"] == "test-chart"
        assert "fact_count" in manifest
        assert "content_hash" in manifest

    def test_manifest_content_hash_deterministic(self, tmp_path):
        ctx = _ctx([_fact()])
        write_skill_output(ctx, tmp_path)
        hash1 = json.loads((tmp_path / "test-chart" / "manifest.json").read_text())["content_hash"]
        # Write again to different dir
        tmp2 = tmp_path / "second"
        write_skill_output(ctx, tmp2)
        hash2 = json.loads((tmp2 / "test-chart" / "manifest.json").read_text())["content_hash"]
        assert hash1 == hash2

    def test_manifest_diagnostics(self, tmp_path):
        ctx = _ctx([_fact()])
        write_skill_output(ctx, tmp_path)
        manifest = json.loads((tmp_path / "test-chart" / "manifest.json").read_text())
        assert "diagnostics" in manifest
        assert manifest["diagnostics"]["arrays_opaque"] is True

    def test_manifest_review_summary(self, tmp_path):
        facts = [
            _fact(path_segments=["a"], confidence=0.95, needs_review=False),
            _fact(path_segments=["b"], confidence=0.75, needs_review=False),
            _fact(path_segments=["c"], confidence=0.50, needs_review=True),
        ]
        ctx = _ctx(facts)
        write_skill_output(ctx, tmp_path)
        manifest = json.loads((tmp_path / "test-chart" / "manifest.json").read_text())
        summary = manifest["review_summary"]
        assert summary["high_confidence"] == 1
        assert summary["medium_confidence"] == 1
        assert summary["needs_review"] == 1
        assert summary["total_facts"] == 3

    def test_install_produces_sorted(self, tmp_path):
        facts = [
            _fact(path_segments=["b"], uri="helmfacts://t/#b"),
            _fact(path_segments=["a"], uri="helmfacts://t/#a"),
        ]
        ctx = _ctx(facts)
        write_skill_output(ctx, tmp_path)
        install = json.loads((tmp_path / "test-chart" / "install.json").read_text())
        assert install["produces"] == sorted(install["produces"])

    def test_install_slice1_empty_fields(self, tmp_path):
        ctx = _ctx([_fact()])
        write_skill_output(ctx, tmp_path)
        install = json.loads((tmp_path / "test-chart" / "install.json").read_text())
        assert install["conditional_produces"] == {}
        assert install["consumes"] == []
        assert install["conditional_consumes"] == {}
        assert install["intra_edges"] == []

    def test_facts_one_file_per_fact(self, tmp_path):
        facts = [
            _fact(path_segments=["a"]),
            _fact(path_segments=["b"]),
            _fact(path_segments=["c"]),
        ]
        ctx = _ctx(facts)
        write_skill_output(ctx, tmp_path)
        fact_files = list((tmp_path / "test-chart" / "facts").glob("*.json"))
        assert len(fact_files) == 3

    def test_fact_json_valid(self, tmp_path):
        ctx = _ctx([_fact(path_segments=["test", "key"], uri="helmfacts://t/test#key")])
        write_skill_output(ctx, tmp_path)
        fact_files = list((tmp_path / "test-chart" / "facts").glob("*.json"))
        assert len(fact_files) == 1
        data = json.loads(fact_files[0].read_text())
        assert "uri" in data
        assert "path" in data
        assert "shape" in data
        assert "classifications" in data
        assert data["shape"] in VALID_SHAPES

    def test_classifications_sorted(self, tmp_path):
        cls_list = [
            Classification("shape", "config", "heuristic_keyword", 0.50, "low"),
            Classification("shape", "credential", "schema_format", 0.95, "high"),
        ]
        ctx = _ctx([_fact(classifications=cls_list)])
        write_skill_output(ctx, tmp_path)
        fact_files = list((tmp_path / "test-chart" / "facts").glob("*.json"))
        data = json.loads(fact_files[0].read_text())
        # Higher confidence should come first (sorted by field, then -confidence)
        assert data["classifications"][0]["confidence"] >= data["classifications"][1]["confidence"]

    def test_features_empty_in_slice1(self, tmp_path):
        ctx = _ctx([_fact()])
        write_skill_output(ctx, tmp_path)
        feature_files = list((tmp_path / "test-chart" / "features").glob("*.json"))
        assert len(feature_files) == 0

    def test_signals_empty_in_slice1(self, tmp_path):
        ctx = _ctx([_fact()])
        write_skill_output(ctx, tmp_path)
        signal_files = list((tmp_path / "test-chart" / "signals").glob("*.json"))
        assert len(signal_files) == 0
