"""Helm extraction pipeline orchestrator.

Runs stages 1-5 + 7 in sequence and returns the populated HelmContext.
Stage 6 (edges/signals) is added in Slice 3.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from idi.generation.helm.annotations import parse_annotations
from idi.generation.helm.classifier import classify_facts
from idi.generation.helm.context import HelmContext
from idi.generation.helm.enrichment import enrich_facts
from idi.generation.helm.output_writer import sanitize_chart_name, write_skill_output
from idi.generation.helm.schema_loader import load_schema
from idi.generation.helm.uri import generate_uris
from idi.generation.helm.walker import walk_values

logger = logging.getLogger(__name__)


def _create_core_registry() -> Any:
    """Create a KindRegistry with core K8s resources, or a minimal fallback."""
    try:
        from idi.generation.crd.kind_registry import KindRegistry
        return KindRegistry()
    except ImportError:
        logger.warning("KindRegistry not available; using empty fallback")
        return _FallbackRegistry()


class _FallbackRegistry:
    """Minimal registry when CRD pipeline is not available."""

    def is_ref_field(self, _field_name: str, **_kw: Any) -> tuple[bool, str, str, str]:
        return (False, "", "", "")


def _load_yaml_safe(path: Path) -> dict[str, Any]:
    """Load a YAML file using ruamel.yaml YAML 1.2 safe loader."""
    yaml = YAML(typ="safe")
    with open(path) as f:
        documents = list(yaml.load_all(f))
    if len(documents) > 1:
        logger.warning("Multi-document YAML in %s — using first document only", path)
    return documents[0] if documents else {}


def _parse_chart_meta(chart_data: dict[str, Any]) -> dict[str, Any]:
    """Extract pipeline-relevant metadata from Chart.yaml contents."""
    chart_name = sanitize_chart_name(str(chart_data.get("name", "unknown")))
    chart_version = str(chart_data.get("version", "0.0.0"))
    app_version = str(chart_data.get("appVersion", chart_version))

    # Derive repository from home or sources
    repository = chart_data.get("home", "")
    if not repository:
        sources = chart_data.get("sources", [])
        repository = sources[0] if sources else ""

    # Classify dependencies
    library_deps: list[str] = []
    subchart_deps: list[dict[str, Any]] = []
    for dep in chart_data.get("dependencies", []):
        dep_name = dep.get("name", "")
        # Library charts are commonly named "common" or tagged
        tags = dep.get("tags", [])
        if "bitnami-common" in tags or dep_name == "common":
            library_deps.append(dep_name)
        else:
            subchart_deps.append({
                "name": dep_name,
                "version": dep.get("version", ""),
                "repository": dep.get("repository", ""),
                "condition": dep.get("condition", ""),
            })

    # Parse comma-separated conditions from dependencies
    chart_conditions: dict[str, str] = {}
    for dep in chart_data.get("dependencies", []):
        condition_str = dep.get("condition", "")
        dep_name = dep.get("name", "")
        if condition_str:
            for cond in condition_str.split(","):
                cond = cond.strip()
                if cond:
                    chart_conditions[cond] = dep_name

    return {
        "chart_name": chart_name,
        "chart_version": chart_version,
        "app_version": app_version,
        "repository": repository,
        "library_deps": library_deps,
        "subchart_deps": subchart_deps,
        "chart_conditions": chart_conditions,
    }


def run_helm_pipeline(
    values_path: str | Path,
    chart_path: str | Path,
    schema_path: str | Path | None = None,
    kind_registry: Any | None = None,
    output_dir: str | Path = "catalog/skills/helm",
) -> HelmContext:
    """Run the full Helm extraction pipeline.

    Stages: 1 (load) -> 2 (walk) -> 3 (classify) -> 4 (enrich) -> 5 (URI) -> 7 (output).
    Stage 6 (edges) is added in Slice 3.

    Args:
        values_path: Path to values.yaml
        chart_path: Path to Chart.yaml
        schema_path: Optional path to values.schema.json
        kind_registry: Shared KindRegistry. If None, creates core-only registry.
        output_dir: Base output directory. Chart output goes to {output_dir}/{chart_name}/

    Returns:
        Populated HelmContext with all facts classified and written to disk.
        On error, returns a context with empty facts and no output written.
    """
    values_path = Path(values_path)
    chart_path = Path(chart_path)

    # ── Stage 1: Load ────────────────────────────────────────────────────

    # Load Chart.yaml
    try:
        chart_data = _load_yaml_safe(chart_path)
    except Exception as exc:
        logger.error("Failed to parse Chart.yaml at %s: %s", chart_path, exc)
        return HelmContext(
            chart_name="unknown", chart_version="0.0.0", app_version="0.0.0",
            repository="", values={}, chart_meta={}, values_text="",
            kind_registry=kind_registry,
        )

    meta = _parse_chart_meta(chart_data)

    # Library chart — skip extraction
    if chart_data.get("type") == "library":
        logger.info("Skipping library chart: %s", meta["chart_name"])
        return HelmContext(
            chart_name=meta["chart_name"],
            chart_version=meta["chart_version"],
            app_version=meta["app_version"],
            repository=meta["repository"],
            values={}, chart_meta=chart_data, values_text="",
            kind_registry=kind_registry,
            library_deps=meta["library_deps"],
            subchart_deps=meta["subchart_deps"],
        )

    # Load values.yaml
    try:
        values = _load_yaml_safe(values_path)
        values_text = values_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to parse values.yaml at %s: %s", values_path, exc)
        return HelmContext(
            chart_name=meta["chart_name"],
            chart_version=meta["chart_version"],
            app_version=meta["app_version"],
            repository=meta["repository"],
            values={}, chart_meta=chart_data, values_text="",
            kind_registry=kind_registry,
        )

    if values is None:
        values = {}

    # Load schema (non-fatal)
    schema_overrides: dict[tuple[str, ...], Any] = {}
    if schema_path is not None:
        try:
            schema_overrides, _diag = load_schema(schema_path)
        except Exception as exc:
            logger.warning("Schema load failed for %s: %s", schema_path, exc)

    # Create KindRegistry if needed
    if kind_registry is None:
        kind_registry = _create_core_registry()

    # Construct context
    ctx = HelmContext(
        chart_name=meta["chart_name"],
        chart_version=meta["chart_version"],
        app_version=meta["app_version"],
        repository=meta["repository"],
        values=values,
        chart_meta=chart_data,
        values_text=values_text,
        kind_registry=kind_registry,
        schema_overrides=schema_overrides,
        library_deps=meta["library_deps"],
        subchart_deps=meta["subchart_deps"],
        chart_conditions=meta["chart_conditions"],
    )

    # ── Stage 2: Walk ────────────────────────────────────────────────────
    try:
        ctx.facts = walk_values(values)
    except Exception as exc:
        logger.error("Walker failed for %s: %s", meta["chart_name"], exc)
        return ctx

    # Parse annotations (non-fatal, needs valid_paths from walk)
    valid_paths = {tuple(f.path_segments) for f in ctx.facts}
    try:
        ctx.annotations, _skipped = parse_annotations(values_text, valid_paths)
    except Exception as exc:
        logger.warning("Annotation parsing failed for %s: %s", meta["chart_name"], exc)

    # ── Stage 3: Classify ────────────────────────────────────────────────
    try:
        classify_facts(ctx.facts, ctx)
    except Exception as exc:
        logger.error("Classifier failed for %s: %s", meta["chart_name"], exc)
        return ctx

    # ── Stage 4: Enrich ──────────────────────────────────────────────────
    try:
        enrich_facts(ctx.facts, ctx)
    except Exception as exc:
        logger.warning("Enrichment failed for %s: %s", meta["chart_name"], exc)

    # ── Stage 5: URI ─────────────────────────────────────────────────────
    generate_uris(ctx.facts, ctx.chart_name)

    # ── Stage 7: Output ──────────────────────────────────────────────────
    try:
        write_skill_output(ctx, output_dir)
    except Exception as exc:
        logger.error("Output writer failed for %s: %s", meta["chart_name"], exc)

    return ctx
