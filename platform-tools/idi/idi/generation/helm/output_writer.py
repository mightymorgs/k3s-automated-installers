"""Stage 7: Write decomposed skill JSON to disk.

Writes manifest.json, install.json, facts/*.json, features/*.json, signals/*.json.
Features and signals are populated when ctx.edges / ctx.signals are non-empty.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from idi.generation.helm.models import validate_fact, validate_signal

if TYPE_CHECKING:
    from idi.generation.helm.context import HelmContext

logger = logging.getLogger(__name__)

_SAFE_CHAR_RE = re.compile(r"[^a-zA-Z0-9_\-]")
_MAX_FILENAME_LEN = 200


def safe_filename(path_segments: list[str]) -> str:
    """Generate a filesystem-safe filename from path segments."""
    for seg in path_segments:
        if ".." in seg:
            raise ValueError(f"Path traversal detected in segment: {seg}")

    joined = "_".join(path_segments)
    safe = _SAFE_CHAR_RE.sub(lambda m: f"%{ord(m.group()):02X}", joined)

    if len(safe) > _MAX_FILENAME_LEN:
        hash_suffix = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:8]
        safe = safe[:180] + f"_{hash_suffix}"

    return f"{safe}.json"


def sanitize_chart_name(chart_name: str) -> str:
    """Sanitize chart name for use as a directory name."""
    name = chart_name.replace("../", "").replace("..\\", "")
    name = name.replace("/", "").replace("\\", "")
    name = re.sub(r"[^a-zA-Z0-9_\-]", "", name)
    return name or "unknown"


def write_skill_output(ctx: HelmContext, output_dir: str | Path) -> None:
    """Write decomposed skill JSON for a chart."""
    chart_slug = sanitize_chart_name(ctx.chart_name)
    chart_dir = Path(output_dir) / chart_slug
    facts_dir = chart_dir / "facts"
    features_dir = chart_dir / "features"
    signals_dir = chart_dir / "signals"

    chart_dir.mkdir(parents=True, exist_ok=True)
    facts_dir.mkdir(exist_ok=True)
    features_dir.mkdir(exist_ok=True)
    signals_dir.mkdir(exist_ok=True)

    # Validate before writing
    for fact in ctx.facts:
        errors = validate_fact(fact)
        for err in errors:
            logger.error("Validation error: %s", err)

    # Sort facts deterministically
    sorted_facts = sorted(ctx.facts, key=lambda f: tuple(f.path_segments))

    _write_manifest(ctx, sorted_facts, chart_dir)
    _write_install(ctx, sorted_facts, chart_dir)
    _write_facts(sorted_facts, facts_dir)
    _write_features(ctx, features_dir)
    _write_signals(ctx, signals_dir)


def _write_manifest(ctx: HelmContext, sorted_facts: list, chart_dir: Path) -> None:
    """Write manifest.json."""
    high = sum(1 for f in sorted_facts if f.confidence >= 0.85)
    medium = sum(1 for f in sorted_facts if 0.7 <= f.confidence < 0.85)
    needs_review = sum(1 for f in sorted_facts if f.confidence < 0.7)

    enrichment_sources = ["values.yaml", "Chart.yaml"]

    content_hash = _compute_content_hash(sorted_facts, ctx.signals)

    # Collect unique feature names
    features = sorted({f.feature for f in sorted_facts if f.feature is not None})

    manifest = {
        "schema_version": "2.0",
        "artifact_type": "helm",
        "chart": ctx.chart_name,
        "chart_version": ctx.chart_version,
        "app_version": ctx.app_version,
        "repository": ctx.repository,
        "service": ctx.chart_name,
        "enrichment_sources": enrichment_sources,
        "features": features,
        "fact_count": len(sorted_facts),
        "signal_count": len(ctx.signals),
        "library_deps": ctx.library_deps,
        "subchart_deps": ctx.subchart_deps,
        "review_summary": {
            "total_facts": len(sorted_facts),
            "high_confidence": high,
            "medium_confidence": medium,
            "needs_review": needs_review,
        },
        "diagnostics": {
            "arrays_opaque": True,
        },
        "content_hash": content_hash,
    }
    _write_json(chart_dir / "manifest.json", manifest)


def _write_install(ctx: HelmContext, sorted_facts: list, chart_dir: Path) -> None:
    """Write install.json with full edge/signal data."""
    from idi.generation.helm.edges import build_consumes, build_conditional_produces

    toggle_facts = [f for f in sorted_facts if f.is_toggle]

    # Unconditional produces: facts without conditional_on
    produces = sorted(f.uri for f in sorted_facts if f.conditional_on is None)

    # Conditional produces: facts grouped by their gating toggle
    conditional_produces = build_conditional_produces(sorted_facts, toggle_facts)
    # Sort keys for determinism
    conditional_produces = dict(sorted(conditional_produces.items()))

    # Consumes from signals
    consumes, conditional_consumes = build_consumes(
        ctx.signals, sorted_facts, toggle_facts,
    )
    consumes = sorted(consumes, key=lambda c: (c.get("signal_type", ""), c.get("uri", "")))
    conditional_consumes = dict(sorted(conditional_consumes.items()))

    # Intra-edges
    intra_edges = sorted(
        [
            {
                "source": e.source,
                "target": e.target,
                "type": e.type,
                "method": e.method,
                "confidence": e.confidence,
                "evidence": e.evidence,
                "needs_review": e.needs_review,
            }
            for e in ctx.edges
        ],
        key=lambda e: (e["source"], e["target"]),
    )

    install = {
        "schema_version": "2.0",
        "action_id": f"install.{ctx.chart_name}",
        "phase": "install",
        "executor": "helm",
        "service": ctx.chart_name,
        "executor_args": {
            "chart": ctx.chart_name,
            "namespace": ctx.chart_name,
            "repository": ctx.repository,
        },
        "produces": produces,
        "conditional_produces": conditional_produces,
        "consumes": consumes,
        "conditional_consumes": conditional_consumes,
        "intra_edges": intra_edges,
    }
    _write_json(chart_dir / "install.json", install)


def _write_facts(sorted_facts: list, facts_dir: Path) -> None:
    """Write one JSON file per fact."""
    for fact in sorted_facts:
        try:
            filename = safe_filename(fact.path_segments)
        except ValueError as exc:
            logger.error("Skipping fact %s: %s", fact.path, exc)
            continue

        sorted_classifications = sorted(
            [{"field": c.field, "value": c.value, "method": c.method,
              "confidence": c.confidence, "evidence": c.evidence}
             for c in fact.classifications],
            key=lambda c: (c["field"], -c["confidence"], c["method"]),
        )

        fact_data = {
            "uri": fact.uri,
            "path": fact.path,
            "shape": fact.shape,
            "type": fact.type,
            "semantic_type": fact.semantic_type,
            "default": fact.default_value,
            "required": fact.required,
            "enum": fact.enum,
            "format": fact.format,
            "has_template": fact.has_template,
            "default_empty": fact.default_empty,
            "default_truncated": fact.default_truncated,
            "conditional_on": fact.conditional_on,
            "feature": fact.feature,
            "description": fact.description,
            "source": fact.source,
            "confidence": fact.confidence,
            "needs_review": fact.needs_review,
            "classifications": sorted_classifications,
        }
        try:
            _write_json(facts_dir / filename, fact_data)
        except (OSError, TypeError) as exc:
            logger.error("Failed to write fact %s: %s", fact.path, exc)


def _write_features(ctx: HelmContext, features_dir: Path) -> None:
    """Write one JSON file per feature (toggle-gated section)."""
    # Group facts by feature
    feature_groups: dict[str, list] = {}
    for fact in ctx.facts:
        if fact.feature is not None:
            feature_groups.setdefault(fact.feature, []).append(fact)

    # Find toggle fact for each feature
    toggle_by_feature: dict[str, Any] = {}
    for fact in ctx.facts:
        if fact.is_toggle and fact.feature is not None:
            # The toggle for this feature is the one with the shortest path
            key = fact.feature
            if key not in toggle_by_feature or len(fact.path_segments) < len(toggle_by_feature[key].path_segments):
                toggle_by_feature[key] = fact

    # Also look for X.enabled pattern
    for fact in ctx.facts:
        if fact.is_toggle and len(fact.path_segments) >= 2:
            feature_name = fact.path_segments[0]
            if feature_name not in toggle_by_feature:
                toggle_by_feature[feature_name] = fact

    for feature_name, facts in sorted(feature_groups.items()):
        toggle = toggle_by_feature.get(feature_name)

        # Get toggle classification info
        toggle_method = "unknown"
        toggle_confidence = 0.50
        if toggle:
            for cls in toggle.classifications:
                if cls.field == "is_toggle":
                    toggle_method = cls.method
                    toggle_confidence = cls.confidence
                    break

        # Find intra-edges within this feature
        feature_uris = {f.uri for f in facts}
        feature_edges = [
            {
                "source": e.source,
                "target": e.target,
                "type": e.type,
                "method": e.method,
                "confidence": e.confidence,
                "evidence": e.evidence,
                "needs_review": e.needs_review,
            }
            for e in ctx.edges
            if e.source in feature_uris or e.target in feature_uris
        ]
        feature_edges.sort(key=lambda e: (e["source"], e["target"]))

        feature_data = {
            "schema_version": "2.0",
            "feature": feature_name,
            "toggle_uri": toggle.uri if toggle else None,
            "toggle_path": toggle.path if toggle else None,
            "toggle_default": toggle.default_value if toggle else None,
            "toggle_method": toggle_method,
            "toggle_confidence": toggle_confidence,
            "fact_count": len(facts),
            "facts": sorted(f.path for f in facts),
            "intra_edges": feature_edges,
        }

        filename = f"{feature_name}.json"
        try:
            _write_json(features_dir / filename, feature_data)
        except (OSError, TypeError) as exc:
            logger.error("Failed to write feature %s: %s", feature_name, exc)


def _write_signals(ctx: HelmContext, signals_dir: Path) -> None:
    """Write one JSON file per cross-app signal."""
    for signal in ctx.signals:
        errors = validate_signal(signal)
        for err in errors:
            logger.error("Signal validation error: %s", err)

        signal_data = {
            "uri": signal.uri,
            "path": signal.path,
            "signal_type": signal.signal_type,
            "resource_type": signal.resource_type,
            "method": signal.method,
            "confidence": signal.confidence,
            "evidence": signal.evidence,
            "related_facts": sorted(signal.related_facts),
        }

        path_parts = signal.path.split(".") if signal.path else [signal.signal_type]
        try:
            filename = safe_filename([signal.signal_type] + path_parts)
        except ValueError:
            filename = f"{signal.signal_type}.json"

        try:
            _write_json(signals_dir / filename, signal_data)
        except (OSError, TypeError) as exc:
            logger.error("Failed to write signal %s: %s", signal.path, exc)


def _compute_content_hash(sorted_facts: list, signals: list) -> str:
    """Compute deterministic content hash."""
    facts_data = [
        {"uri": f.uri, "path": f.path, "shape": f.shape, "confidence": f.confidence}
        for f in sorted_facts
    ]
    signals_data = [
        {"uri": s.uri, "signal_type": s.signal_type, "confidence": s.confidence}
        for s in sorted(signals, key=lambda s: s.uri)
    ]
    raw = json.dumps(
        {"facts": facts_data, "signals": signals_data},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _write_json(path: Path, data: Any) -> None:
    """Write JSON with deterministic formatting."""
    path.write_text(
        json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
