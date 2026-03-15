"""Stage 3: Multi-tier classification cascade (Tiers A-E).

Runs all tiers on every fact, logs all classification attempts,
and resolves winners by highest confidence. Builds internal indices
for O(1) sibling/descendant lookups.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from idi.generation.helm.constants import (
    CREDENTIAL_LEAF_KEYS,
    EXISTING_BINDING_MAP,
    TOGGLE_KEYS,
    heuristic_classify_shape,
)
from idi.generation.helm.models import Classification, HelmFact

if TYPE_CHECKING:
    from idi.generation.helm.context import HelmContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fact index
# ---------------------------------------------------------------------------

@dataclass
class FactIndex:
    by_path: dict[tuple[str, ...], HelmFact]
    by_parent: dict[tuple[str, ...], list[HelmFact]]


def build_fact_index(facts: list[HelmFact]) -> FactIndex:
    """Build lookup indices for O(1) sibling/descendant queries."""
    by_path: dict[tuple[str, ...], HelmFact] = {}
    by_parent: dict[tuple[str, ...], list[HelmFact]] = {}
    for f in facts:
        key = tuple(f.path_segments)
        by_path[key] = f
        parent = key[:-1]
        by_parent.setdefault(parent, []).append(f)
    return FactIndex(by_path=by_path, by_parent=by_parent)


def is_descendant_of(candidate: HelmFact, ancestor_segments: list[str]) -> bool:
    """True if candidate's path_segments starts with ancestor_segments and is longer."""
    n = len(ancestor_segments)
    return (
        len(candidate.path_segments) > n
        and candidate.path_segments[:n] == ancestor_segments
    )


def is_sibling_of(candidate: HelmFact, fact: HelmFact) -> bool:
    """True if both share the same parent path_segments (not equal)."""
    return (
        candidate.path_segments[:-1] == fact.path_segments[:-1]
        and candidate.path != fact.path
    )


def get_siblings(fact: HelmFact, index: FactIndex) -> list[HelmFact]:
    """Return all facts sharing the same parent, excluding the fact itself."""
    parent = tuple(fact.path_segments[:-1])
    return [f for f in index.by_parent.get(parent, []) if f.path != fact.path]


def get_descendants(ancestor_segments: list[str], facts: list[HelmFact]) -> list[HelmFact]:
    """Return all facts whose path_segments starts with ancestor_segments (not equal)."""
    return [f for f in facts if is_descendant_of(f, ancestor_segments)]


# ---------------------------------------------------------------------------
# NLP description patterns
# ---------------------------------------------------------------------------

_CREDENTIAL_PATTERNS = re.compile(
    r"\b(password|secret|credential|private.?key|token|api.?key)\b", re.IGNORECASE
)
_IDENTITY_PATTERNS = re.compile(
    r"\b(reference\s+to|name\s+of\s+the|identifier)\b", re.IGNORECASE
)
_ADDRESSABILITY_PATTERNS = re.compile(
    r"\b(URL|endpoint|host|hostname|address|FQDN)\b", re.IGNORECASE
)


def match_description_patterns(description: str) -> str | None:
    """Match description text against known NLP patterns."""
    if _CREDENTIAL_PATTERNS.search(description):
        return "credential"
    if _IDENTITY_PATTERNS.search(description):
        return "identity"
    if _ADDRESSABILITY_PATTERNS.search(description):
        return "addressability"
    return None


# ---------------------------------------------------------------------------
# KindRegistry adapter
# ---------------------------------------------------------------------------

def check_kind_registry(
    leaf_key: str,
    parent_path: str,
    kind_registry: Any,
) -> tuple[bool, str, str]:
    """Adapter wrapping KindRegistry.is_ref_field().

    Returns (is_ref, plural, group).
    Isolates Helm classifier from CRD registry internals.
    """
    if kind_registry is None:
        return (False, "", "")
    result = kind_registry.is_ref_field(leaf_key, parent_path)
    # Real KindRegistry returns 4-tuple: (is_ref, kind, plural, group)
    if len(result) == 4:
        is_ref, _kind, plural, group = result
        return (is_ref, plural or "", group or "")
    # Mock may return 3-tuple
    if len(result) == 3:
        return result
    return (False, "", "")


# ---------------------------------------------------------------------------
# Winner resolution
# ---------------------------------------------------------------------------

def resolve_winner(classifications: list[Classification], field: str) -> str | None:
    """Return the value of the highest-confidence classification for the given field."""
    field_cls = [c for c in classifications if c.field == field]
    if not field_cls:
        return None
    best = max(field_cls, key=lambda c: c.confidence)
    return best.value


def get_winning_method(classifications: list[Classification], field: str) -> str:
    """Return the method of the winning classification for the given field."""
    field_cls = [c for c in classifications if c.field == field]
    if not field_cls:
        return "heuristic_default"
    best = max(field_cls, key=lambda c: c.confidence)
    return best.method


def get_winning_confidence(classifications: list[Classification], field: str) -> float:
    """Return the confidence of the winning classification for the given field."""
    field_cls = [c for c in classifications if c.field == field]
    if not field_cls:
        return 0.50
    best = max(field_cls, key=lambda c: c.confidence)
    return best.confidence


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def classify_facts(facts: list[HelmFact], ctx: HelmContext) -> None:
    """Run the 5-tier classification cascade on all facts.

    Mutates facts in place: populates classifications[], shape, semantic_type,
    is_toggle, cross_app_signal, source, confidence, needs_review.
    """
    index = build_fact_index(facts)

    for fact in facts:
        classifications: list[Classification] = []
        seg_key = tuple(fact.path_segments)
        leaf_key = fact.path_segments[-1]
        parent_path = ".".join(fact.path_segments[:-1]) if len(fact.path_segments) > 1 else ""

        # ── Tier A: Schema-derived (0.80-0.95) ──
        _tier_a(fact, seg_key, ctx, classifications)

        # ── Tier B: Chart.yaml ground truth (0.90-0.95) ──
        _tier_b(fact, ctx, classifications)

        # ── Tier C: Structural analysis (0.65-0.90) ──
        _tier_c(fact, leaf_key, parent_path, ctx, index, facts, classifications)

        # ── Tier D: Annotation-derived (0.70-0.85) ──
        _tier_d(fact, seg_key, ctx, classifications)

        # ── Tier E: Heuristic fallback (0.50) ──
        _tier_e(fact, leaf_key, classifications)

        # ── Resolve winners ──
        fact.classifications = classifications
        fact.shape = resolve_winner(classifications, "shape") or "config"
        fact.semantic_type = resolve_winner(classifications, "semantic_type") or fact.type
        fact.is_toggle = resolve_winner(classifications, "is_toggle") == "true"
        fact.cross_app_signal = resolve_winner(classifications, "signal")
        fact.source = get_winning_method(classifications, "shape")
        fact.confidence = get_winning_confidence(classifications, "shape")
        fact.needs_review = fact.confidence < 0.7


# ---------------------------------------------------------------------------
# Tier implementations
# ---------------------------------------------------------------------------

def _tier_a(
    fact: HelmFact,
    seg_key: tuple[str, ...],
    ctx: HelmContext,
    cls: list[Classification],
) -> None:
    """Tier A: Schema-derived classifications (0.80-0.95)."""
    info = ctx.schema_overrides.get(seg_key)
    if info is None:
        return

    if info.format in ("password", "secret"):
        cls.append(Classification("shape", "credential", "schema_format", 0.95,
                                  f"schema format={info.format}"))
    if info.format in ("uri", "hostname"):
        cls.append(Classification("shape", "addressability", "schema_format", 0.95,
                                  f"schema format={info.format}"))
    if info.write_only:
        cls.append(Classification("shape", "credential", "schema_writeonly", 0.95,
                                  "schema writeOnly=true"))
    if info.type == "boolean":
        cls.append(Classification("shape", "config", "schema_type", 0.90,
                                  "schema type=boolean"))
    if info.description:
        nlp_shape = match_description_patterns(info.description)
        if nlp_shape:
            cls.append(Classification("shape", nlp_shape, "schema_description_nlp", 0.80,
                                      f"schema description matches '{nlp_shape}' pattern"))


def _tier_b(
    fact: HelmFact,
    ctx: HelmContext,
    cls: list[Classification],
) -> None:
    """Tier B: Chart.yaml ground truth (0.90-0.95)."""
    if fact.path in ctx.chart_conditions.values():
        cls.append(Classification("is_toggle", "true", "chartmeta_condition", 0.95,
                                  "referenced as condition in Chart.yaml dependency"))


def _tier_c(
    fact: HelmFact,
    leaf_key: str,
    parent_path: str,
    ctx: HelmContext,
    index: FactIndex,
    all_facts: list[HelmFact],
    cls: list[Classification],
) -> None:
    """Tier C: Structural analysis (0.65-0.90)."""

    # C.1: KindRegistry identity detection
    is_ref, plural, group = check_kind_registry(leaf_key, parent_path, ctx.kind_registry)
    if is_ref:
        cls.append(Classification("shape", "identity", "kind_registry", 0.90,
                                  f"key '{leaf_key}' matches Kind -> plural={plural}, group={group}"))

    # C.2: Reference tuple
    if fact.type == "object" and isinstance(fact.default_value, dict):
        subkeys = set(fact.default_value.keys())
        if "name" in subkeys and "namespace" in subkeys:
            cls.append(Classification("shape", "identity", "reference_tuple", 0.85,
                                      f"object contains name+namespace subkeys: {subkeys}"))

    # C.3: Sibling existing* analysis (narrowed)
    siblings = get_siblings(fact, index)
    existing_siblings = [s for s in siblings if s.path_segments[-1].startswith("existing")]
    if existing_siblings and fact.type in ("string", "null") and not leaf_key.startswith("existing"):
        if leaf_key in CREDENTIAL_LEAF_KEYS or (fact.format and fact.format in ("password",)):
            cls.append(Classification("shape", "credential", "sibling_secret_binding", 0.85,
                                      f"sibling '{existing_siblings[0].path}' is existing* binding + "
                                      f"leaf key '{leaf_key}' matches credential pattern"))
        else:
            cls.append(Classification("shape", "config", "sibling_secret_binding", 0.65,
                                      f"sibling '{existing_siblings[0].path}' is existing* binding, "
                                      f"but leaf key '{leaf_key}' is not a known credential pattern"))

    # C.4: Parent context (weak signal)
    auth_contexts = {"auth", "security", "tls", "ssl", "credentials", "secrets"}
    if any(p.lower() in auth_contexts for p in fact.path_segments[:-1]):
        if fact.type in ("string", "null", "integer"):
            context_part = next(p for p in fact.path_segments[:-1] if p.lower() in auth_contexts)
            cls.append(Classification("shape", "config", "parent_context", 0.65,
                                      f"inside '{context_part}' parent object, scalar value"))

    # C.5: Value URL pattern
    if isinstance(fact.default_value, str) and re.match(r"^https?://", fact.default_value):
        cls.append(Classification("shape", "addressability", "value_url_pattern", 0.85,
                                  f"value '{fact.default_value}' matches URL pattern"))

    # C.6: Value port range
    if isinstance(fact.default_value, int) and not isinstance(fact.default_value, bool):
        if 1 <= fact.default_value <= 65535:
            service_contexts = {"service", "server", "listen", "bind", "proxy", "ingress"}
            if any(p.lower() in service_contexts for p in fact.path_segments):
                ctx_part = next(p for p in fact.path_segments if p.lower() in service_contexts)
                cls.append(Classification("shape", "addressability", "value_port_range", 0.80,
                                          f"integer {fact.default_value} in port range, "
                                          f"inside '{ctx_part}' context"))

    # C.7: Service endpoint tuple
    # Include the current fact's leaf key in the group check
    sibling_keys = {s.path_segments[-1].lower() for s in siblings}
    sibling_keys.add(leaf_key.lower())
    endpoint_fields = {"host", "port", "protocol", "scheme"}
    if len(sibling_keys & endpoint_fields) >= 2:
        cls.append(Classification("shape", "addressability", "endpoint_tuple", 0.85,
                                  f"sibling group contains endpoint fields: "
                                  f"{sibling_keys & endpoint_fields}"))

    # C.8: Boolean-with-children toggle
    if (isinstance(fact.default_value, bool)
            or fact.default_value in ("-", "true", "false")):
        if leaf_key.lower() in TOGGLE_KEYS:
            parent_segments = fact.path_segments[:-1]
            if parent_segments:
                descendants = [
                    f for f in all_facts
                    if is_descendant_of(f, parent_segments)
                    and f.path != fact.path
                    and not (isinstance(f.default_value, bool)
                             and f.path_segments[-1].lower() in TOGGLE_KEYS)
                ]
            else:
                descendants = [
                    f for f in all_facts
                    if f.path != fact.path
                    and not (isinstance(f.default_value, bool)
                             and f.path_segments[-1].lower() in TOGGLE_KEYS)
                ]
            if len(descendants) > 0:
                toggle_parent = ".".join(parent_segments)
                cls.append(Classification("is_toggle", "true", "boolean_with_children", 0.80,
                                          f"boolean '{leaf_key}' key with {len(descendants)} "
                                          f"non-toggle descendants under '{toggle_parent}'"))

    # C.8b: String enum toggle
    if fact.enum and isinstance(fact.default_value, str) and len(fact.enum) >= 2:
        parent_prefix_segs = fact.path_segments[:-1]
        if parent_prefix_segs:
            enum_siblings = [
                f for f in all_facts
                if is_descendant_of(f, parent_prefix_segs) and f.path != fact.path
            ]
        else:
            enum_siblings = [f for f in all_facts if f.path != fact.path]
        if enum_siblings:
            enum_normalized = {v.lower().replace("-", "_").replace(" ", "_")
                               for v in fact.enum}
            matching = []
            for sf in enum_siblings:
                sf_segs = {seg.lower().replace("-", "_") for seg in sf.path_segments}
                if sf_segs & enum_normalized:
                    matching.append(sf)
            if matching:
                cls.append(Classification("is_toggle", "true", "enum_with_children", 0.80,
                                          f"string enum key with {len(fact.enum)} values, "
                                          f"{len(matching)} siblings match"))

    # C.9: Internal/external pattern
    if leaf_key.startswith("existing") and fact.type in ("string", "null"):
        suffix = leaf_key[len("existing"):]
        suffix_lower = suffix.lower()
        if suffix_lower in EXISTING_BINDING_MAP:
            signal_type, resource_type = EXISTING_BINDING_MAP[suffix_lower]
        else:
            is_known, _, plural, _ = ctx.kind_registry.is_ref_field(leaf_key, parent_path) if ctx.kind_registry else (False, None, None, None)
            if is_known and plural:
                signal_type = f"{plural.lower()}_binding"
                resource_type = plural
            else:
                signal_type = "unknown_binding"
                resource_type = suffix or "Unknown"
        cls.append(Classification("signal", signal_type, "internal_external_pattern", 0.85,
                                  f"existing* key '{leaf_key}' -> {signal_type} ({resource_type})"))

    # C.10: External host/URI signal
    parent_parts_lower = [p.lower() for p in fact.path_segments]
    external_parents = [p for p in parent_parts_lower if p.startswith("external")]
    if external_parents and leaf_key.lower() in ("host", "url", "endpoint", "server", "addr", "uri"):
        cls.append(Classification("signal", "external_service_dependency",
                                  "external_host_signal", 0.80,
                                  f"external service reference: {fact.path}"))


def _tier_d(
    fact: HelmFact,
    seg_key: tuple[str, ...],
    ctx: HelmContext,
    cls: list[Classification],
) -> None:
    """Tier D: Annotation-derived classifications (0.70-0.85)."""
    info = ctx.annotations.get(seg_key)
    if info is None:
        return

    if info.type:
        cls.append(Classification("semantic_type", info.type,
                                  f"annotation_{info.source}", 0.80,
                                  f"{info.source} annotation declares type={info.type}"))
    if info.description:
        nlp_shape = match_description_patterns(info.description)
        if nlp_shape:
            cls.append(Classification("shape", nlp_shape,
                                      f"annotation_{info.source}_nlp", 0.70,
                                      f"{info.source} annotation description matches "
                                      f"'{nlp_shape}' pattern"))


def _tier_e(
    fact: HelmFact,
    leaf_key: str,
    cls: list[Classification],
) -> None:
    """Tier E: Heuristic fallback (0.50). Only if no shape from A-D."""
    shape_cls = [c for c in cls if c.field == "shape"]
    if not shape_cls:
        heuristic_shape = heuristic_classify_shape(leaf_key, fact.default_value)
        cls.append(Classification("shape", heuristic_shape, "heuristic_keyword", 0.50,
                                  f"heuristic: key '{leaf_key}' -> {heuristic_shape}"))

    if not any(c.field == "shape" for c in cls):
        cls.append(Classification("shape", "config", "heuristic_default", 0.50,
                                  "no signal detected, defaulted to config"))
