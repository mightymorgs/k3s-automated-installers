"""Stage 6: Detect intra-chart edges, cross-chart signals, and feature grouping.

Mutates HelmContext in place: populates ctx.edges, ctx.signals,
and sets fact.conditional_on / fact.feature for all facts.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from idi.generation.helm.models import HelmEdge, HelmSignal, VALID_RESOURCE_TYPES

if TYPE_CHECKING:
    from idi.generation.helm.context import HelmContext
    from idi.generation.helm.models import HelmFact

logger = logging.getLogger(__name__)

# Signal type -> resource type mapping
_SIGNAL_RESOURCE_MAP: dict[str, str] = {
    "secret_binding": "Secret",
    "pvc_binding": "PersistentVolumeClaim",
    "configmap_binding": "ConfigMap",
    "role_binding": "Role",
    "serviceaccount_binding": "ServiceAccount",
    "external_service_dependency": "Service",
    "unknown_binding": "Unknown",
}


def find_nearest_ancestor_toggle(
    fact: HelmFact,
    all_toggle_facts: list[HelmFact],
) -> HelmFact | None:
    """Find the nearest ancestor toggle by walking up path_segments.

    A toggle at path X.enabled (or X.enable) gates all facts under X.
    We look for toggles whose parent path is a prefix of the fact's path.
    For example, toggle at ["server", "enabled"] gates ["server", "service", "port"]
    because ["server"] is a prefix of ["server", "service", "port"].

    Also matches direct prefix toggles (e.g., toggle at ["server"] gates ["server", "port"]).

    Returns the closest ancestor toggle, or None if none exists.
    """
    # Build lookup: map parent-prefix -> toggle fact
    # For a toggle at ["server", "enabled"], the parent-prefix is ("server",)
    # For a toggle at ["server"], the parent-prefix is ("server",)
    toggle_by_prefix: dict[tuple[str, ...], HelmFact] = {}
    _TOGGLE_LEAF_NAMES = frozenset({"enabled", "enable", "disabled", "disable"})

    for f in all_toggle_facts:
        if not f.is_toggle:
            continue
        segs = tuple(f.path_segments)
        # If the toggle's leaf key is "enabled"/"enable", the gating prefix is the parent
        if len(segs) >= 2 and segs[-1].lower() in _TOGGLE_LEAF_NAMES:
            prefix = segs[:-1]
        else:
            prefix = segs
        # Don't overwrite if we already have a more specific toggle
        if prefix not in toggle_by_prefix:
            toggle_by_prefix[prefix] = f

    segments = tuple(fact.path_segments)
    # Walk from the longest prefix down to root
    for i in range(len(segments) - 1, 0, -1):
        prefix = segments[:i]
        if prefix in toggle_by_prefix:
            candidate = toggle_by_prefix[prefix]
            if candidate is not fact:
                return candidate

    return None


def detect_edges_and_signals(ctx: HelmContext) -> None:
    """Detect intra-chart edges, cross-chart signals, and feature grouping.

    Mutates ctx in place: populates ctx.edges, ctx.signals,
    and sets fact.conditional_on / fact.feature for all facts.
    """
    all_toggle_facts = [f for f in ctx.facts if f.is_toggle]

    # 1. Intra-chart toggle edges
    _detect_toggle_edges(ctx, all_toggle_facts)

    # 2. Cross-chart signals
    _detect_cross_chart_signals(ctx)
    _detect_subchart_signals(ctx)

    # 3. Feature grouping (sets conditional_on and feature on all facts)
    _assign_feature_groups(ctx, all_toggle_facts)


def _detect_toggle_edges(ctx: HelmContext, all_toggle_facts: list[HelmFact]) -> None:
    """Detect intra-chart toggle edges."""
    # Check if global.enabled is confirmed by Chart.yaml
    global_confirmed = any(
        "global.enabled" in str(v) or "global.enabled" in str(k)
        for k, v in ctx.chart_conditions.items()
    )
    global_toggle = None
    if global_confirmed:
        for f in all_toggle_facts:
            if f.path == "global.enabled":
                global_toggle = f
                break

    for fact in all_toggle_facts:
        edge_created = False

        # Rule 2: Sentinel "-" ancestor (B-08 fix)
        if fact.default_value == "-" and fact.is_toggle:
            ancestor = find_nearest_ancestor_toggle(fact, all_toggle_facts)
            if ancestor is not None:
                conf = min(ancestor.confidence, 0.90)
                ctx.edges.append(HelmEdge(
                    source=fact.uri,
                    target=ancestor.uri,
                    type="DEPENDS_ON",
                    method="sentinel_ancestor",
                    confidence=conf,
                    evidence=f"Sentinel '-' toggle {fact.path} -> ancestor {ancestor.path}",
                    conditional_value=None,
                    needs_review=conf < 0.7,
                ))
                edge_created = True
            elif global_toggle is not None and global_toggle is not fact:
                conf = min(global_toggle.confidence, 0.80)
                ctx.edges.append(HelmEdge(
                    source=fact.uri,
                    target=global_toggle.uri,
                    type="DEPENDS_ON",
                    method="sentinel_global_fallback",
                    confidence=conf,
                    evidence=f"Sentinel '-' toggle {fact.path} -> global.enabled (Chart.yaml confirmed)",
                    conditional_value=None,
                    needs_review=conf < 0.7,
                ))
                edge_created = True

        # Rule 3: Toggle hierarchy (if no edge yet)
        if not edge_created:
            ancestor = find_nearest_ancestor_toggle(fact, all_toggle_facts)
            if ancestor is not None:
                conf = min(ancestor.confidence, 0.85)
                ctx.edges.append(HelmEdge(
                    source=fact.uri,
                    target=ancestor.uri,
                    type="DEPENDS_ON",
                    method="toggle_hierarchy",
                    confidence=conf,
                    evidence=f"Toggle hierarchy: {fact.path} -> {ancestor.path}",
                    conditional_value=None,
                    needs_review=conf < 0.7,
                ))


def _detect_cross_chart_signals(ctx: HelmContext) -> None:
    """Detect cross-chart signals from classified facts."""
    for fact in ctx.facts:
        if fact.cross_app_signal is None:
            continue

        resource_type = _SIGNAL_RESOURCE_MAP.get(fact.cross_app_signal, "Unknown")
        related = _find_related_signal_facts(fact, ctx.facts)

        ctx.signals.append(HelmSignal(
            uri=fact.uri,
            path=fact.path,
            signal_type=fact.cross_app_signal,
            resource_type=resource_type,
            evidence=_get_signal_evidence(fact),
            method=_get_signal_method(fact),
            confidence=fact.confidence,
            related_facts=[r.uri for r in related],
        ))


def _detect_subchart_signals(ctx: HelmContext) -> None:
    """Detect signals from subchart dependencies."""
    fact_by_path: dict[str, HelmFact] = {f.path: f for f in ctx.facts}

    for dep in ctx.subchart_deps:
        dep_name = dep.get("name", "")
        condition = dep.get("condition", "")

        if condition and condition in fact_by_path:
            condition_fact = fact_by_path[condition]
            signal_uri = condition_fact.uri
        else:
            signal_uri = f"chart://{ctx.chart_name}/deps/{dep_name}"

        ctx.signals.append(HelmSignal(
            uri=signal_uri,
            path=condition or "",
            signal_type="subchart_dependency",
            resource_type="Chart",
            evidence=f"Chart.yaml dependency: {dep_name}",
            method="chartmeta_dependency",
            confidence=0.90,
            related_facts=[],
        ))


def _find_related_signal_facts(fact: HelmFact, all_facts: list[HelmFact]) -> list[HelmFact]:
    """Find sibling facts related to a signal fact."""
    if len(fact.path_segments) < 2:
        return []

    parent = tuple(fact.path_segments[:-1])
    related: list[HelmFact] = []

    for f in all_facts:
        if f is fact:
            continue
        if len(f.path_segments) >= 2 and tuple(f.path_segments[:len(parent)]) == parent:
            leaf = f.path_segments[-1].lower()
            # Related: secretKeys, key, keys, password, username, host, port, protocol
            if any(kw in leaf for kw in ("key", "password", "username", "host", "port", "protocol")):
                related.append(f)

    return related


def _get_signal_evidence(fact: HelmFact) -> str:
    """Build evidence string for a signal."""
    leaf = fact.path_segments[-1] if fact.path_segments else fact.path
    return f"{leaf} pattern in {fact.path}"


def _get_signal_method(fact: HelmFact) -> str:
    """Get the method that detected the signal."""
    for cls in fact.classifications:
        if cls.field == "signal":
            return cls.method
    return fact.source


def _assign_feature_groups(ctx: HelmContext, all_toggle_facts: list[HelmFact]) -> None:
    """Assign conditional_on and feature to all facts."""
    for fact in ctx.facts:
        ancestor = find_nearest_ancestor_toggle(fact, all_toggle_facts)
        if ancestor is not None:
            fact.conditional_on = ancestor.path
            # Feature is the first segment of the gating toggle's path
            fact.feature = ancestor.path_segments[0]
        else:
            fact.conditional_on = None
            fact.feature = None


def build_consumes(
    signals: list[HelmSignal],
    facts: list[HelmFact],
    toggle_facts: list[HelmFact],
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Build consumes and conditional_consumes from signals.

    Returns (consumes_list, conditional_consumes_dict).
    """
    fact_by_path: dict[str, HelmFact] = {f.path: f for f in facts}
    consumes: list[dict[str, Any]] = []
    conditional: dict[str, list[dict[str, Any]]] = {}

    for signal in signals:
        # Determine satisfaction
        if signal.uri.startswith("chart://"):
            satisfaction = "mandatory"
        else:
            sig_fact = fact_by_path.get(signal.path)
            if sig_fact and sig_fact.default_empty and sig_fact.required:
                satisfaction = "mandatory"
            else:
                satisfaction = "optional_with_default"

        entry = {
            "uri": signal.uri,
            "signal_type": signal.signal_type,
            "resource_type": signal.resource_type,
            "satisfaction": satisfaction,
            "confidence": signal.confidence,
        }

        # Check if the signal's fact has a conditional_on
        sig_fact = fact_by_path.get(signal.path)
        if sig_fact and sig_fact.conditional_on:
            key = sig_fact.conditional_on
            conditional.setdefault(key, []).append(entry)
        else:
            consumes.append(entry)

    return consumes, conditional


def build_conditional_produces(
    facts: list[HelmFact],
    toggle_facts: list[HelmFact],
) -> dict[str, list[str]]:
    """Build conditional_produces mapping from toggle path to list of gated fact URIs."""
    result: dict[str, list[str]] = {}

    for fact in facts:
        if fact.conditional_on is not None:
            result.setdefault(fact.conditional_on, []).append(fact.uri)

    # Sort URIs for determinism
    for key in result:
        result[key] = sorted(result[key])

    return result
