"""Tests for helm output writer (Stage 7 — Slices 1 & 3)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from idi.generation.helm.context import HelmContext
from idi.generation.helm.models import (
    Classification, HelmEdge, HelmFact, HelmSignal,
    VALID_SHAPES, VALID_SIGNAL_TYPES,
)
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


# ---------------------------------------------------------------------------
# Slice 3: Features, Signals, Full Install
# ---------------------------------------------------------------------------

class TestFeatureOutput:
    def test_features_one_per_group(self, tmp_path):
        toggle = _fact(
            path_segments=["server", "enabled"], is_toggle=True,
            uri="helmfacts://t/server#enabled",
            classifications=[
                Classification("is_toggle", "true", "boolean_with_children", 0.80, "test"),
                Classification("shape", "config", "heuristic_default", 0.50, "test"),
            ],
            feature="server",
        )
        child1 = _fact(path_segments=["server", "port"], feature="server",
                       conditional_on="server.enabled")
        child2 = _fact(path_segments=["server", "host"], feature="server",
                       conditional_on="server.enabled")
        ctx = _ctx([toggle, child1, child2])
        write_skill_output(ctx, tmp_path)
        feature_files = list((tmp_path / "test-chart" / "features").glob("*.json"))
        assert len(feature_files) == 1
        assert feature_files[0].name == "server.json"

    def test_feature_has_toggle_info(self, tmp_path):
        toggle = _fact(
            path_segments=["server", "enabled"], is_toggle=True,
            uri="helmfacts://t/server#enabled", default_value=True,
            classifications=[
                Classification("is_toggle", "true", "boolean_with_children", 0.80, "test"),
                Classification("shape", "config", "heuristic_default", 0.50, "test"),
            ],
            feature="server",
        )
        child = _fact(path_segments=["server", "port"], feature="server",
                      conditional_on="server.enabled")
        ctx = _ctx([toggle, child])
        write_skill_output(ctx, tmp_path)
        data = json.loads((tmp_path / "test-chart" / "features" / "server.json").read_text())
        assert data["toggle_uri"] == "helmfacts://t/server#enabled"
        assert data["toggle_path"] == "server.enabled"
        assert data["toggle_default"] is True
        assert data["toggle_method"] == "boolean_with_children"
        assert data["toggle_confidence"] == 0.80

    def test_feature_facts_sorted(self, tmp_path):
        toggle = _fact(
            path_segments=["svc", "enabled"], is_toggle=True,
            uri="helmfacts://t/svc#enabled",
            classifications=[
                Classification("is_toggle", "true", "boolean_with_children", 0.80, "test"),
                Classification("shape", "config", "heuristic_default", 0.50, "test"),
            ],
            feature="svc",
        )
        b = _fact(path_segments=["svc", "b"], feature="svc", conditional_on="svc.enabled")
        a = _fact(path_segments=["svc", "a"], feature="svc", conditional_on="svc.enabled")
        ctx = _ctx([toggle, b, a])
        write_skill_output(ctx, tmp_path)
        data = json.loads((tmp_path / "test-chart" / "features" / "svc.json").read_text())
        assert data["facts"] == sorted(data["facts"])

    def test_feature_intra_edges(self, tmp_path):
        toggle = _fact(
            path_segments=["server", "enabled"], is_toggle=True,
            uri="helmfacts://t/server#enabled",
            classifications=[
                Classification("is_toggle", "true", "boolean_with_children", 0.80, "test"),
                Classification("shape", "config", "heuristic_default", 0.50, "test"),
            ],
            feature="server",
        )
        child = _fact(path_segments=["server", "port"], feature="server",
                      uri="helmfacts://t/server#port")
        ctx = _ctx([toggle, child])
        ctx.edges.append(HelmEdge(
            source="helmfacts://t/server#port", target="helmfacts://t/server#enabled",
            type="DEPENDS_ON", method="toggle_hierarchy", confidence=0.85,
            evidence="test", conditional_value=None, needs_review=False,
        ))
        write_skill_output(ctx, tmp_path)
        data = json.loads((tmp_path / "test-chart" / "features" / "server.json").read_text())
        assert len(data["intra_edges"]) == 1
        assert data["intra_edges"][0]["source"] == "helmfacts://t/server#port"


class TestSignalOutput:
    def test_signal_file_created(self, tmp_path):
        fact = _fact(
            path_segments=["db", "existingSecret"],
            cross_app_signal="secret_binding",
        )
        ctx = _ctx([fact])
        ctx.signals.append(HelmSignal(
            uri="helmfacts://t/db#existingSecret",
            path="db.existingSecret",
            signal_type="secret_binding",
            resource_type="Secret",
            evidence="existing secret pattern",
            method="structural_existing",
            confidence=0.85,
        ))
        write_skill_output(ctx, tmp_path)
        signal_files = list((tmp_path / "test-chart" / "signals").glob("*.json"))
        assert len(signal_files) == 1

    def test_signal_file_valid_json(self, tmp_path):
        ctx = _ctx([_fact()])
        ctx.signals.append(HelmSignal(
            uri="helmfacts://t/#x",
            path="x",
            signal_type="secret_binding",
            resource_type="Secret",
            evidence="test",
            method="test",
            confidence=0.85,
        ))
        write_skill_output(ctx, tmp_path)
        signal_files = list((tmp_path / "test-chart" / "signals").glob("*.json"))
        assert len(signal_files) == 1
        data = json.loads(signal_files[0].read_text())
        assert data["signal_type"] in VALID_SIGNAL_TYPES
        assert data["resource_type"] == "Secret"
        assert "evidence" in data
        assert "related_facts" in data


class TestFullInstallJson:
    def test_conditional_produces_populated(self, tmp_path):
        toggle = _fact(
            path_segments=["server", "enabled"], is_toggle=True,
            uri="helmfacts://t/server#enabled",
            feature="server", conditional_on=None,
        )
        child = _fact(
            path_segments=["server", "port"],
            uri="helmfacts://t/server#port",
            feature="server", conditional_on="server.enabled",
        )
        ungated = _fact(
            path_segments=["replicaCount"],
            uri="helmfacts://t/#replicaCount",
            conditional_on=None,
        )
        ctx = _ctx([toggle, child, ungated])
        write_skill_output(ctx, tmp_path)
        install = json.loads((tmp_path / "test-chart" / "install.json").read_text())
        assert "server.enabled" in install["conditional_produces"]
        assert "helmfacts://t/server#port" in install["conditional_produces"]["server.enabled"]
        assert "helmfacts://t/#replicaCount" in install["produces"]
        # Gated fact should NOT be in base produces
        assert "helmfacts://t/server#port" not in install["produces"]

    def test_intra_edges_populated(self, tmp_path):
        ctx = _ctx([_fact()])
        ctx.edges.append(HelmEdge(
            source="helmfacts://t/#a", target="helmfacts://t/#b",
            type="DEPENDS_ON", method="toggle_hierarchy", confidence=0.85,
            evidence="test", conditional_value=None, needs_review=False,
        ))
        write_skill_output(ctx, tmp_path)
        install = json.loads((tmp_path / "test-chart" / "install.json").read_text())
        assert len(install["intra_edges"]) == 1
        edge = install["intra_edges"][0]
        assert edge["source"] == "helmfacts://t/#a"
        assert edge["type"] == "DEPENDS_ON"
        assert edge["method"] == "toggle_hierarchy"
        assert "confidence" in edge
        assert "needs_review" in edge

    def test_intra_edges_sorted(self, tmp_path):
        ctx = _ctx([_fact()])
        ctx.edges.append(HelmEdge(
            source="helmfacts://t/#z", target="helmfacts://t/#y",
            type="DEPENDS_ON", method="toggle_hierarchy", confidence=0.85,
            evidence="test", conditional_value=None, needs_review=False,
        ))
        ctx.edges.append(HelmEdge(
            source="helmfacts://t/#a", target="helmfacts://t/#b",
            type="DEPENDS_ON", method="toggle_hierarchy", confidence=0.85,
            evidence="test", conditional_value=None, needs_review=False,
        ))
        write_skill_output(ctx, tmp_path)
        install = json.loads((tmp_path / "test-chart" / "install.json").read_text())
        sources = [e["source"] for e in install["intra_edges"]]
        assert sources == sorted(sources)

    def test_consumes_from_signals(self, tmp_path):
        fact = _fact(
            path_segments=["db", "existingSecret"],
            default_value="", default_empty=True, required=True,
        )
        ctx = _ctx([fact])
        ctx.signals.append(HelmSignal(
            uri="helmfacts://t/db#existingSecret",
            path="db.existingSecret",
            signal_type="secret_binding",
            resource_type="Secret",
            evidence="test",
            method="structural_existing",
            confidence=0.85,
        ))
        write_skill_output(ctx, tmp_path)
        install = json.loads((tmp_path / "test-chart" / "install.json").read_text())
        assert len(install["consumes"]) >= 1


class TestSlice3Integration:
    def test_vault_has_features(self, tmp_path):
        from pathlib import Path as P
        from idi.generation.helm.pipeline import run_helm_pipeline
        specs = P(__file__).resolve().parents[5] / "catalog" / "specs" / "helm"
        ctx = run_helm_pipeline(specs / "vault-values.yaml", specs / "vault-chart.yaml",
                                output_dir=tmp_path)
        chart_dir = tmp_path / "vault"
        feature_files = list((chart_dir / "features").glob("*.json"))
        assert len(feature_files) >= 3
        manifest = json.loads((chart_dir / "manifest.json").read_text())
        assert len(manifest["features"]) == len(feature_files)

    def test_vault_has_intra_edges(self, tmp_path):
        from pathlib import Path as P
        from idi.generation.helm.pipeline import run_helm_pipeline
        specs = P(__file__).resolve().parents[5] / "catalog" / "specs" / "helm"
        ctx = run_helm_pipeline(specs / "vault-values.yaml", specs / "vault-chart.yaml",
                                output_dir=tmp_path)
        install = json.loads((tmp_path / "vault" / "install.json").read_text())
        assert len(install["intra_edges"]) >= 5

    def test_manifest_signal_count_matches(self, tmp_path):
        from pathlib import Path as P
        from idi.generation.helm.pipeline import run_helm_pipeline
        specs = P(__file__).resolve().parents[5] / "catalog" / "specs" / "helm"
        ctx = run_helm_pipeline(specs / "postgresql-values.yaml", specs / "postgresql-chart.yaml",
                                output_dir=tmp_path)
        chart_dir = tmp_path / "postgresql"
        manifest = json.loads((chart_dir / "manifest.json").read_text())
        signal_files = list((chart_dir / "signals").glob("*.json"))
        assert manifest["signal_count"] == len(signal_files)
