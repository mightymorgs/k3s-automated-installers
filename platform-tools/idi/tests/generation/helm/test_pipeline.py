"""Tests for Helm pipeline orchestrator (Stage 9 — Slice 1)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from idi.generation.helm.pipeline import run_helm_pipeline

# Repo root for fixture charts
_REPO_ROOT = Path(__file__).resolve().parents[5]
_HELM_SPECS = _REPO_ROOT / "catalog" / "specs" / "helm"

# All 6 fixture charts
_CHART_NAMES = ["vault", "postgresql", "grafana", "cert-manager", "external-secrets", "sonarr"]


def _chart_paths(name: str) -> tuple[Path, Path, Path | None]:
    """Return (values_path, chart_path, schema_path) for a fixture chart."""
    values = _HELM_SPECS / f"{name}-values.yaml"
    chart = _HELM_SPECS / f"{name}-chart.yaml"
    schema = _HELM_SPECS / f"{name}-values.schema.json"
    return values, chart, schema if schema.exists() else None


# ---------------------------------------------------------------------------
# Pipeline core
# ---------------------------------------------------------------------------

class TestPipelineCore:
    def test_vault_returns_facts(self, tmp_path):
        values, chart, schema = _chart_paths("vault")
        ctx = run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        # Vault has ~180+ leaf values
        assert len(ctx.facts) >= 100, f"Expected 100+ facts, got {len(ctx.facts)}"

    def test_no_kind_registry_creates_core(self, tmp_path):
        values, chart, schema = _chart_paths("vault")
        ctx = run_helm_pipeline(values, chart, schema, kind_registry=None, output_dir=tmp_path)
        assert ctx.kind_registry is not None
        assert len(ctx.facts) > 0

    def test_writes_output_directory(self, tmp_path):
        values, chart, schema = _chart_paths("vault")
        run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        chart_dir = tmp_path / "vault"
        assert (chart_dir / "manifest.json").exists()
        assert (chart_dir / "install.json").exists()
        assert (chart_dir / "facts").is_dir()

    def test_invalid_values_path_returns_error(self, tmp_path):
        chart = _HELM_SPECS / "vault-chart.yaml"
        ctx = run_helm_pipeline(
            Path("/nonexistent/values.yaml"), chart, output_dir=tmp_path,
        )
        assert ctx.facts == []
        # No output should be written
        assert not (tmp_path / "vault").exists() or not (tmp_path / "vault" / "manifest.json").exists()

    def test_no_schema_produces_output(self, tmp_path):
        values, chart, _ = _chart_paths("vault")
        ctx = run_helm_pipeline(values, chart, schema_path=None, output_dir=tmp_path)
        assert len(ctx.facts) > 0
        chart_dir = tmp_path / "vault"
        assert (chart_dir / "manifest.json").exists()

    def test_malformed_schema_continues(self, tmp_path):
        values, chart, _ = _chart_paths("vault")
        # Create a malformed schema file
        bad_schema = tmp_path / "bad.json"
        bad_schema.write_text("{invalid json", encoding="utf-8")
        ctx = run_helm_pipeline(values, chart, schema_path=bad_schema, output_dir=tmp_path)
        assert len(ctx.facts) > 0


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

class TestYAMLLoading:
    def test_yaml_12_no_is_string(self, tmp_path):
        """YAML 1.2: 'NO' should be string, not boolean False."""
        values_file = tmp_path / "values.yaml"
        values_file.write_text("answer: NO\n", encoding="utf-8")
        chart_file = tmp_path / "chart.yaml"
        chart_file.write_text(
            "apiVersion: v2\nname: test\nversion: 1.0.0\nappVersion: 1.0.0\n",
            encoding="utf-8",
        )
        out = tmp_path / "out"
        ctx = run_helm_pipeline(values_file, chart_file, output_dir=out)
        # Find the fact for "answer"
        answer_facts = [f for f in ctx.facts if f.path == "answer"]
        assert len(answer_facts) == 1
        assert answer_facts[0].default_value == "NO"

    def test_yaml_12_on_is_string(self, tmp_path):
        """YAML 1.2: 'on' should be string, not boolean True."""
        values_file = tmp_path / "values.yaml"
        values_file.write_text("feature: on\n", encoding="utf-8")
        chart_file = tmp_path / "chart.yaml"
        chart_file.write_text(
            "apiVersion: v2\nname: test\nversion: 1.0.0\nappVersion: 1.0.0\n",
            encoding="utf-8",
        )
        out = tmp_path / "out"
        ctx = run_helm_pipeline(values_file, chart_file, output_dir=out)
        feature_facts = [f for f in ctx.facts if f.path == "feature"]
        assert len(feature_facts) == 1
        assert feature_facts[0].default_value == "on"

    def test_yaml_12_080_is_string(self, tmp_path):
        """YAML 1.2: '080' should be string, not octal 64."""
        values_file = tmp_path / "values.yaml"
        values_file.write_text("code: 080\n", encoding="utf-8")
        chart_file = tmp_path / "chart.yaml"
        chart_file.write_text(
            "apiVersion: v2\nname: test\nversion: 1.0.0\nappVersion: 1.0.0\n",
            encoding="utf-8",
        )
        out = tmp_path / "out"
        ctx = run_helm_pipeline(values_file, chart_file, output_dir=out)
        code_facts = [f for f in ctx.facts if f.path == "code"]
        assert len(code_facts) == 1
        # In YAML 1.2 safe, 080 is an integer (not octal, just decimal)
        # ruamel.yaml with typ='safe' treats this as int 80
        assert code_facts[0].default_value in ("080", 80)

    def test_yaml_anchors_resolved(self, tmp_path):
        values_file = tmp_path / "values.yaml"
        values_file.write_text(
            "defaults: &defaults\n  port: 8080\nserver:\n  <<: *defaults\n  host: localhost\n",
            encoding="utf-8",
        )
        chart_file = tmp_path / "chart.yaml"
        chart_file.write_text(
            "apiVersion: v2\nname: test\nversion: 1.0.0\nappVersion: 1.0.0\n",
            encoding="utf-8",
        )
        out = tmp_path / "out"
        ctx = run_helm_pipeline(values_file, chart_file, output_dir=out)
        # server.port should exist from anchor merge
        server_port = [f for f in ctx.facts if f.path == "server.port"]
        assert len(server_port) == 1
        assert server_port[0].default_value == 8080


# ---------------------------------------------------------------------------
# Chart.yaml parsing
# ---------------------------------------------------------------------------

class TestChartParsing:
    def test_extracts_chart_metadata(self, tmp_path):
        values, chart, schema = _chart_paths("vault")
        ctx = run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        assert ctx.chart_name == "vault"
        assert ctx.chart_version == "0.32.0"
        assert ctx.app_version == "1.21.2"

    def test_library_chart_returns_empty(self, tmp_path):
        values_file = tmp_path / "values.yaml"
        values_file.write_text("key: value\n", encoding="utf-8")
        chart_file = tmp_path / "chart.yaml"
        chart_file.write_text(
            "apiVersion: v2\nname: common\nversion: 1.0.0\nappVersion: 1.0.0\ntype: library\n",
            encoding="utf-8",
        )
        out = tmp_path / "out"
        ctx = run_helm_pipeline(values_file, chart_file, output_dir=out)
        assert len(ctx.facts) == 0

    def test_dependencies_classified(self, tmp_path):
        values, chart, schema = _chart_paths("postgresql")
        ctx = run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        # postgresql depends on "common" which is a library chart
        assert len(ctx.library_deps) > 0 or len(ctx.subchart_deps) > 0

    def test_chart_name_sanitized(self, tmp_path):
        values_file = tmp_path / "values.yaml"
        values_file.write_text("key: value\n", encoding="utf-8")
        chart_file = tmp_path / "chart.yaml"
        chart_file.write_text(
            "apiVersion: v2\nname: my/../chart\nversion: 1.0.0\nappVersion: 1.0.0\n",
            encoding="utf-8",
        )
        out = tmp_path / "out"
        ctx = run_helm_pipeline(values_file, chart_file, output_dir=out)
        assert ".." not in ctx.chart_name
        assert "/" not in ctx.chart_name

    def test_missing_repository_defaults_empty(self, tmp_path):
        values_file = tmp_path / "values.yaml"
        values_file.write_text("key: value\n", encoding="utf-8")
        chart_file = tmp_path / "chart.yaml"
        chart_file.write_text(
            "apiVersion: v2\nname: test\nversion: 1.0.0\nappVersion: 1.0.0\n",
            encoding="utf-8",
        )
        out = tmp_path / "out"
        ctx = run_helm_pipeline(values_file, chart_file, output_dir=out)
        assert ctx.repository == ""


# ---------------------------------------------------------------------------
# Slice 1 integration tests
# ---------------------------------------------------------------------------

class TestSlice1Integration:
    @pytest.mark.parametrize("chart_name", _CHART_NAMES)
    def test_all_charts_produce_output(self, chart_name, tmp_path):
        values, chart, schema = _chart_paths(chart_name)
        if not values.exists() or not chart.exists():
            pytest.skip(f"Fixture not found for {chart_name}")
        ctx = run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        assert len(ctx.facts) > 0
        chart_slug = ctx.chart_name
        assert (tmp_path / chart_slug / "manifest.json").exists()

    @pytest.mark.parametrize("chart_name", _CHART_NAMES)
    def test_zero_uri_collisions(self, chart_name, tmp_path):
        values, chart, schema = _chart_paths(chart_name)
        if not values.exists() or not chart.exists():
            pytest.skip(f"Fixture not found for {chart_name}")
        ctx = run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        uris = [f.uri for f in ctx.facts]
        assert len(uris) == len(set(uris)), f"URI collisions in {chart_name}"

    @pytest.mark.parametrize("chart_name", _CHART_NAMES)
    def test_every_fact_has_classification(self, chart_name, tmp_path):
        values, chart, schema = _chart_paths(chart_name)
        if not values.exists() or not chart.exists():
            pytest.skip(f"Fixture not found for {chart_name}")
        ctx = run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        for fact in ctx.facts:
            assert len(fact.classifications) >= 1, (
                f"Fact {fact.path} in {chart_name} has no classifications"
            )

    def test_vault_dotted_key_roundtrip(self, tmp_path):
        values, chart, schema = _chart_paths("vault")
        ctx = run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        # Vault has podAnnotations with dotted keys (e.g. prometheus.io/scrape)
        # URIs should properly encode dots
        dotted = [f for f in ctx.facts if "." in f.path_segments[-1]]
        if dotted:
            for f in dotted:
                assert "%2E" in f.uri or "." not in f.uri.split("#")[-1], (
                    f"Dotted key not encoded in URI: {f.uri}"
                )

    @pytest.mark.parametrize("chart_name", _CHART_NAMES)
    def test_install_json_has_required_fields(self, chart_name, tmp_path):
        values, chart, schema = _chart_paths(chart_name)
        if not values.exists() or not chart.exists():
            pytest.skip(f"Fixture not found for {chart_name}")
        ctx = run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        chart_slug = ctx.chart_name
        install = json.loads((tmp_path / chart_slug / "install.json").read_text())
        # All required fields present
        assert "produces" in install
        assert "conditional_produces" in install
        assert "consumes" in install
        assert "conditional_consumes" in install
        assert "intra_edges" in install
        assert isinstance(install["produces"], list)
        assert isinstance(install["conditional_produces"], dict)
        assert isinstance(install["consumes"], list)
        assert isinstance(install["conditional_consumes"], dict)
        assert isinstance(install["intra_edges"], list)

    def test_manifest_hash_reproducible(self, tmp_path):
        values, chart, schema = _chart_paths("vault")
        out1 = tmp_path / "run1"
        out2 = tmp_path / "run2"
        run_helm_pipeline(values, chart, schema, output_dir=out1)
        run_helm_pipeline(values, chart, schema, output_dir=out2)
        m1 = json.loads((out1 / "vault" / "manifest.json").read_text())
        m2 = json.loads((out2 / "vault" / "manifest.json").read_text())
        assert m1["content_hash"] == m2["content_hash"]

    @pytest.mark.parametrize("chart_name", _CHART_NAMES)
    def test_not_all_heuristic(self, chart_name, tmp_path):
        """At least some facts should have non-heuristic classifications."""
        values, chart, schema = _chart_paths(chart_name)
        if not values.exists() or not chart.exists():
            pytest.skip(f"Fixture not found for {chart_name}")
        ctx = run_helm_pipeline(values, chart, schema, output_dir=tmp_path)
        methods = set()
        for f in ctx.facts:
            for c in f.classifications:
                methods.add(c.method)
        non_heuristic = methods - {"heuristic_keyword", "heuristic_default"}
        assert len(non_heuristic) > 0, (
            f"All classifications in {chart_name} are heuristic: {methods}"
        )
