"""Tests for Helm edges and signals (Stage 6 — Slice 3)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from idi.generation.helm.context import HelmContext
from idi.generation.helm.models import Classification, HelmFact, HelmSignal, VALID_SIGNAL_TYPES
from idi.generation.helm.edges import (
    detect_edges_and_signals,
    find_nearest_ancestor_toggle,
    build_consumes,
    build_conditional_produces,
)

# Repo root for fixture charts
_REPO_ROOT = Path(__file__).resolve().parents[5]
_HELM_SPECS = _REPO_ROOT / "catalog" / "specs" / "helm"


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
    if "path_segments" in kw and "uri" not in kw:
        segs = kw["path_segments"]
        if len(segs) == 1:
            defaults["uri"] = f"helmfacts://t/#{segs[0]}"
        else:
            defaults["uri"] = f"helmfacts://t/{'.'.join(segs[:-1])}#{segs[-1]}"
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
# Ancestor toggle detection
# ---------------------------------------------------------------------------

class TestFindNearestAncestorToggle:
    def test_finds_immediate_parent(self):
        parent = _fact(path_segments=["server"], is_toggle=True)
        child = _fact(path_segments=["server", "port"])
        result = find_nearest_ancestor_toggle(child, [parent, child])
        assert result is parent

    def test_skips_non_toggle_ancestors(self):
        grandparent = _fact(path_segments=["server"], is_toggle=True)
        parent = _fact(path_segments=["server", "service"], is_toggle=False)
        child = _fact(path_segments=["server", "service", "port"])
        result = find_nearest_ancestor_toggle(child, [grandparent, parent, child])
        assert result is grandparent

    def test_root_level_returns_none(self):
        fact = _fact(path_segments=["port"])
        result = find_nearest_ancestor_toggle(fact, [fact])
        assert result is None

    def test_toggle_with_no_ancestor_returns_none(self):
        toggle = _fact(path_segments=["server", "enabled"], is_toggle=True)
        result = find_nearest_ancestor_toggle(toggle, [toggle])
        assert result is None

    def test_finds_closest_ancestor(self):
        grandparent = _fact(path_segments=["a"], is_toggle=True)
        parent = _fact(path_segments=["a", "b"], is_toggle=True)
        child = _fact(path_segments=["a", "b", "c"])
        result = find_nearest_ancestor_toggle(child, [grandparent, parent, child])
        assert result is parent


# ---------------------------------------------------------------------------
# Intra-chart edges
# ---------------------------------------------------------------------------

class TestIntraChartEdges:
    def test_toggle_with_ancestor_produces_edge(self):
        parent = _fact(path_segments=["server"], is_toggle=True, confidence=0.85,
                       uri="helmfacts://t/#server")
        child = _fact(path_segments=["server", "enabled"], is_toggle=True, confidence=0.80,
                      uri="helmfacts://t/server#enabled")
        ctx = _ctx([parent, child])
        detect_edges_and_signals(ctx)
        assert len(ctx.edges) >= 1
        edge = ctx.edges[0]
        assert edge.type == "DEPENDS_ON"

    def test_toggle_without_ancestor_no_edge(self):
        toggle = _fact(path_segments=["server", "enabled"], is_toggle=True, confidence=0.80)
        ctx = _ctx([toggle])
        detect_edges_and_signals(ctx)
        # No ancestor -> no edge (no global fallback by default)
        assert len(ctx.edges) == 0

    def test_sentinel_toggle_with_ancestor_produces_edge(self):
        parent = _fact(path_segments=["server"], is_toggle=True, confidence=0.85,
                       uri="helmfacts://t/#server")
        child = _fact(path_segments=["server", "ha"], is_toggle=True,
                      default_value="-", confidence=0.70,
                      uri="helmfacts://t/server#ha")
        ctx = _ctx([parent, child])
        detect_edges_and_signals(ctx)
        assert len(ctx.edges) >= 1
        edge = [e for e in ctx.edges if "sentinel" in e.method]
        assert len(edge) >= 1

    def test_sentinel_non_toggle_no_edge(self):
        parent = _fact(path_segments=["server"], is_toggle=True, confidence=0.85)
        child = _fact(path_segments=["server", "config"], is_toggle=False,
                      default_value="-", confidence=0.50)
        ctx = _ctx([parent, child])
        detect_edges_and_signals(ctx)
        # Non-toggle sentinel should NOT create an edge
        sentinel_edges = [e for e in ctx.edges if "sentinel" in e.method]
        assert len(sentinel_edges) == 0

    def test_edge_confidence_capped(self):
        parent = _fact(path_segments=["server"], is_toggle=True, confidence=0.95,
                       uri="helmfacts://t/#server")
        child = _fact(path_segments=["server", "ha"], is_toggle=True, confidence=0.80,
                      uri="helmfacts://t/server#ha")
        ctx = _ctx([parent, child])
        detect_edges_and_signals(ctx)
        assert len(ctx.edges) >= 1
        # Confidence should be min(ancestor_confidence, rule_cap)
        assert ctx.edges[0].confidence <= 0.90

    def test_edge_needs_review_low_confidence(self):
        parent = _fact(path_segments=["server"], is_toggle=True, confidence=0.55,
                       uri="helmfacts://t/#server")
        child = _fact(path_segments=["server", "ha"], is_toggle=True, confidence=0.50,
                      uri="helmfacts://t/server#ha")
        ctx = _ctx([parent, child])
        detect_edges_and_signals(ctx)
        assert len(ctx.edges) >= 1
        assert ctx.edges[0].needs_review is True

    def test_all_edges_emitted_no_threshold(self):
        parent = _fact(path_segments=["a"], is_toggle=True, confidence=0.30,
                       uri="helmfacts://t/#a")
        child = _fact(path_segments=["a", "b"], is_toggle=True, confidence=0.30,
                      uri="helmfacts://t/a#b")
        ctx = _ctx([parent, child])
        detect_edges_and_signals(ctx)
        assert len(ctx.edges) >= 1

    def test_global_enabled_fallback_only_with_chart_condition(self):
        """Global.enabled fallback only fires when Chart.yaml confirms it."""
        global_toggle = _fact(
            path_segments=["global", "enabled"], is_toggle=True, confidence=0.85,
            uri="helmfacts://t/global#enabled",
        )
        child_toggle = _fact(
            path_segments=["server", "enabled"], is_toggle=True, confidence=0.80,
            default_value="-",
            uri="helmfacts://t/server#enabled",
        )
        # Without chart_conditions, no global fallback
        ctx = _ctx([global_toggle, child_toggle])
        detect_edges_and_signals(ctx)
        global_edges = [e for e in ctx.edges if "global" in e.method]
        assert len(global_edges) == 0

        # With chart_conditions referencing global.enabled, should get fallback
        ctx2 = _ctx(
            [global_toggle, child_toggle],
            chart_conditions={"global.enabled": "server"},
        )
        detect_edges_and_signals(ctx2)
        global_edges2 = [e for e in ctx2.edges if "global" in e.method]
        assert len(global_edges2) >= 1


# ---------------------------------------------------------------------------
# Cross-chart signals
# ---------------------------------------------------------------------------

class TestCrossChartSignals:
    def test_secret_binding_produces_signal(self):
        fact = _fact(
            path_segments=["db", "existingSecret"],
            cross_app_signal="secret_binding",
            confidence=0.85,
        )
        ctx = _ctx([fact])
        detect_edges_and_signals(ctx)
        assert len(ctx.signals) >= 1
        sig = ctx.signals[0]
        assert sig.signal_type == "secret_binding"
        assert sig.resource_type == "Secret"

    def test_signal_resource_type_mapping(self):
        mappings = {
            "secret_binding": "Secret",
            "pvc_binding": "PersistentVolumeClaim",
            "configmap_binding": "ConfigMap",
            "external_service_dependency": "Service",
            "unknown_binding": "Unknown",
        }
        for sig_type, resource_type in mappings.items():
            fact = _fact(
                path_segments=["x", sig_type.replace("_", "")],
                cross_app_signal=sig_type,
                confidence=0.85,
            )
            ctx = _ctx([fact])
            detect_edges_and_signals(ctx)
            sigs = [s for s in ctx.signals if s.signal_type == sig_type]
            assert len(sigs) == 1, f"Missing signal for {sig_type}"
            assert sigs[0].resource_type == resource_type

    def test_related_facts_for_existing_secret(self):
        secret_fact = _fact(
            path_segments=["db", "existingSecret"],
            cross_app_signal="secret_binding",
            confidence=0.85,
        )
        key_fact = _fact(
            path_segments=["db", "secretKeys", "password"],
            confidence=0.50,
        )
        ctx = _ctx([secret_fact, key_fact])
        detect_edges_and_signals(ctx)
        sigs = [s for s in ctx.signals if s.signal_type == "secret_binding"]
        assert len(sigs) == 1

    def test_subchart_dep_with_condition_produces_signal(self):
        condition_fact = _fact(
            path_segments=["redis", "enabled"],
            is_toggle=True, confidence=0.85,
            uri="helmfacts://t/redis#enabled",
        )
        ctx = _ctx(
            [condition_fact],
            subchart_deps=[{
                "name": "redis", "version": "1.0.0",
                "repository": "https://charts.bitnami.com",
                "condition": "redis.enabled",
            }],
        )
        detect_edges_and_signals(ctx)
        subchart_sigs = [s for s in ctx.signals if s.signal_type == "subchart_dependency"]
        assert len(subchart_sigs) == 1
        assert subchart_sigs[0].confidence == 0.90

    def test_subchart_dep_without_condition_produces_signal(self):
        ctx = _ctx(
            [],
            subchart_deps=[{
                "name": "common", "version": "1.0.0",
                "repository": "https://charts.bitnami.com",
                "condition": "",
            }],
        )
        detect_edges_and_signals(ctx)
        subchart_sigs = [s for s in ctx.signals if s.signal_type == "subchart_dependency"]
        assert len(subchart_sigs) == 1
        assert "chart://" in subchart_sigs[0].uri

    def test_all_signal_types_valid(self):
        fact = _fact(
            path_segments=["x"],
            cross_app_signal="secret_binding",
            confidence=0.85,
        )
        ctx = _ctx([fact])
        detect_edges_and_signals(ctx)
        for sig in ctx.signals:
            assert sig.signal_type in VALID_SIGNAL_TYPES


# ---------------------------------------------------------------------------
# Feature grouping
# ---------------------------------------------------------------------------

class TestFeatureGrouping:
    def test_fact_under_toggle_gets_conditional_on(self):
        toggle = _fact(
            path_segments=["server", "enabled"], is_toggle=True, confidence=0.85,
        )
        child = _fact(path_segments=["server", "service", "port"])
        ctx = _ctx([toggle, child])
        detect_edges_and_signals(ctx)
        assert child.conditional_on == "server.enabled"
        assert child.feature == "server"

    def test_fact_under_injector_gets_feature(self):
        toggle = _fact(
            path_segments=["injector", "enabled"], is_toggle=True, confidence=0.85,
        )
        child = _fact(path_segments=["injector", "replicas"])
        ctx = _ctx([toggle, child])
        detect_edges_and_signals(ctx)
        assert child.feature == "injector"

    def test_ungated_fact_no_feature(self):
        fact = _fact(path_segments=["replicaCount"])
        ctx = _ctx([fact])
        detect_edges_and_signals(ctx)
        assert fact.conditional_on is None
        assert fact.feature is None


# ---------------------------------------------------------------------------
# Consumes
# ---------------------------------------------------------------------------

class TestConsumes:
    def test_mandatory_signal(self):
        signal = HelmSignal(
            uri="helmfacts://t/db#existingSecret",
            path="db.existingSecret",
            signal_type="secret_binding",
            resource_type="Secret",
            evidence="existingSecret pattern",
            method="structural_existing",
            confidence=0.85,
        )
        fact = _fact(
            path_segments=["db", "existingSecret"],
            default_value="", default_empty=True, required=True,
        )
        consumes, conditional = build_consumes([signal], [fact], [])
        mandatory = [c for c in consumes if c.get("satisfaction") == "mandatory"]
        assert len(mandatory) >= 1

    def test_optional_signal(self):
        signal = HelmSignal(
            uri="helmfacts://t/db#existingSecret",
            path="db.existingSecret",
            signal_type="secret_binding",
            resource_type="Secret",
            evidence="existingSecret pattern",
            method="structural_existing",
            confidence=0.85,
        )
        fact = _fact(
            path_segments=["db", "existingSecret"],
            default_value="my-secret", default_empty=False, required=False,
        )
        consumes, conditional = build_consumes([signal], [fact], [])
        optional = [c for c in consumes if c.get("satisfaction") == "optional_with_default"]
        assert len(optional) >= 1

    def test_subchart_unconditional_mandatory(self):
        signal = HelmSignal(
            uri="chart://test/deps/common",
            path="",
            signal_type="subchart_dependency",
            resource_type="Chart",
            evidence="chart dependency",
            method="chartmeta_dependency",
            confidence=0.90,
        )
        consumes, conditional = build_consumes([signal], [], [])
        mandatory = [c for c in consumes if c.get("satisfaction") == "mandatory"]
        assert len(mandatory) >= 1

    def test_conditional_consumes_groups(self):
        toggle = _fact(
            path_segments=["redis", "enabled"], is_toggle=True, confidence=0.85,
        )
        signal = HelmSignal(
            uri="helmfacts://t/redis#host",
            path="redis.host",
            signal_type="external_service_dependency",
            resource_type="Service",
            evidence="external host pattern",
            method="structural_external",
            confidence=0.80,
        )
        fact = _fact(
            path_segments=["redis", "host"],
            default_value="", default_empty=True,
            conditional_on="redis.enabled",
        )
        consumes, conditional = build_consumes([signal], [fact], [toggle])
        assert "redis.enabled" in conditional


# ---------------------------------------------------------------------------
# Conditional produces
# ---------------------------------------------------------------------------

class TestConditionalProduces:
    def test_gated_facts_in_conditional_produces(self):
        toggle = _fact(
            path_segments=["server", "enabled"], is_toggle=True,
            uri="helmfacts://t/server#enabled",
        )
        fact = _fact(
            path_segments=["server", "port"],
            uri="helmfacts://t/server#port",
            conditional_on="server.enabled",
        )
        conditional = build_conditional_produces([toggle, fact], [toggle])
        assert "server.enabled" in conditional
        assert "helmfacts://t/server#port" in conditional["server.enabled"]

    def test_ungated_not_in_conditional(self):
        fact = _fact(
            path_segments=["replicaCount"],
            uri="helmfacts://t/#replicaCount",
            conditional_on=None,
        )
        conditional = build_conditional_produces([fact], [])
        assert len(conditional) == 0


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestEdgesIntegration:
    def test_vault_has_toggle_edges(self, tmp_path):
        from idi.generation.helm.pipeline import run_helm_pipeline
        values = _HELM_SPECS / "vault-values.yaml"
        chart = _HELM_SPECS / "vault-chart.yaml"
        ctx = run_helm_pipeline(values, chart, output_dir=tmp_path)
        assert len(ctx.edges) >= 5, f"Expected 5+ edges, got {len(ctx.edges)}"

    def test_vault_has_features(self, tmp_path):
        from idi.generation.helm.pipeline import run_helm_pipeline
        values = _HELM_SPECS / "vault-values.yaml"
        chart = _HELM_SPECS / "vault-chart.yaml"
        ctx = run_helm_pipeline(values, chart, output_dir=tmp_path)
        features = {f.feature for f in ctx.facts if f.feature is not None}
        # Vault has server, injector, csi, ui
        assert len(features) >= 3, f"Expected 3+ features, got {features}"

    def test_postgresql_has_signals(self, tmp_path):
        from idi.generation.helm.pipeline import run_helm_pipeline
        values = _HELM_SPECS / "postgresql-values.yaml"
        chart = _HELM_SPECS / "postgresql-chart.yaml"
        ctx = run_helm_pipeline(values, chart, output_dir=tmp_path)
        # PostgreSQL should have secret_binding signals from existing secret patterns
        signal_types = {s.signal_type for s in ctx.signals}
        # At minimum should have subchart_dependency from common lib
        assert len(ctx.signals) >= 1
