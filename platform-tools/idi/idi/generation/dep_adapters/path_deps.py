"""Path parameter parent resource detection.

Extracted from ``polymorphic.extract_path_refs()``.
Enhanced with RESTler-style multi-level path hierarchy inference.
"""
from __future__ import annotations

import re

from idi.generation.dep_adapters.base import Dependency, DetectionSource, OperationInfo
from idi.generation.dep_adapters.naming import normalize_id_suffix, singularize

_EXCLUDED: frozenset[str] = frozenset({"namespace", "namespaces", "ns"})
_SKIP_SEGMENTS: re.Pattern = re.compile(r"^(v\d+|api|apis)$", re.IGNORECASE)

# Thresholds for statistical namespace detection.
_NS_FREQUENCY_THRESHOLD = 0.30  # param must appear in ≥30% of operations
_NS_DISPERSION_THRESHOLD = 5    # param must have ≥5 distinct child segments

# Suffixes stripped from path param names to infer the resource.
_FK_SUFFIXES: tuple[str, ...] = (
    "_id", "_pk", "_uuid", "_guid", "_key", "_ref", "_slug",
    "Id", "Pk", "Uuid", "Guid", "Key", "Ref", "Slug",
)


def detect_namespace_params(spec: dict) -> frozenset[str]:
    """Detect routing/namespace params from spec path structure.

    Two-factor rule:
      1. Frequency: param appears in ≥30% of operations
      2. Dispersion: param has ≥5 distinct non-param child segments

    Returns frozenset of lowercased param names classified as namespace params.
    """
    paths = spec.get("paths", {})
    if not paths:
        return frozenset()

    # Count total operations and per-param stats.
    total_ops = 0
    # param → set of operations it appears in (use path+method as key)
    param_ops: dict[str, set[str]] = {}
    # param → set of distinct child resource segments
    param_children: dict[str, set[str]] = {}

    _HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        segments = path.strip("/").split("/")
        for method in methods:
            if method not in _HTTP_METHODS:
                continue
            total_ops += 1
            op_key = f"{method}:{path}"

            for idx, seg in enumerate(segments):
                if not seg.startswith("{"):
                    continue
                param = seg.strip("{}").lower()
                param_ops.setdefault(param, set()).add(op_key)

                # Find first non-param segment after this param.
                for j in range(idx + 1, len(segments)):
                    child = segments[j]
                    if not child.startswith("{"):
                        param_children.setdefault(param, set()).add(child.lower())
                        break

    if total_ops == 0:
        return frozenset()

    result: set[str] = set()
    for param, ops in param_ops.items():
        frequency = len(ops) / total_ops
        dispersion = len(param_children.get(param, set()))
        if frequency >= _NS_FREQUENCY_THRESHOLD and dispersion >= _NS_DISPERSION_THRESHOLD:
            result.add(param)

    return frozenset(result)


def _match_segment(candidate: str, known_resources: set[str]) -> str | None:
    """Match a path segment against known resources with fuzzy fallbacks.

    Tries exact match, then suffix containment (e.g., "series" matches
    "api-v3-series"), then singular/plural variants.
    """
    candidate = candidate.replace("_", "-")  # Normalize to match resource names
    if candidate in known_resources:
        return candidate

    # Suffix match: "series" matches "api-v3-series"
    suffix_matches = [r for r in known_resources if r.endswith("-" + candidate)]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    if suffix_matches:
        return min(suffix_matches, key=len)

    # Singular/plural: "client" matches "clients" and vice versa
    singular = singularize(candidate)
    if singular != candidate and singular in known_resources:
        return singular
    plural = candidate + "s"
    if plural in known_resources:
        return plural

    # Suffix match with plural/singular
    for variant in (singular, plural):
        if variant == candidate:
            continue
        suffix_matches = [r for r in known_resources if r.endswith("-" + variant)]
        if suffix_matches:
            return min(suffix_matches, key=len)

    return None


def _infer_from_param_name(
    param: str, known_resources: set[str],
) -> str | None:
    """Infer a target resource from the parameter name itself.

    Handles cases like ``{realm}`` → ``realms``, ``{stage_uuid}`` → ``stages``.
    """
    p = param.lower()

    # Strip FK suffixes: stage_uuid -> stage, userId -> user
    stripped = p
    for suffix in _FK_SUFFIXES:
        s = suffix.lower()
        if stripped.endswith(s):
            stripped = stripped[: -len(s)]
            break

    # Normalize UUID/GUID synonyms: stage_uuid -> stage_id -> stage
    normalized = normalize_id_suffix(p)
    if normalized != p:
        for suffix in ("_id", "_pk"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break

    # Try all variants against known_resources
    for candidate in dict.fromkeys([stripped, normalized, p]):
        if not candidate:
            continue
        match = _match_segment(candidate, known_resources)
        if match:
            return match

    return None


def detect_path_deps(
    operation: OperationInfo,
    known_resources: set[str],
) -> list[Dependency]:
    """Extract parent resource deps from URL path parameters.

    Walks backwards to find the nearest matching ancestor segment for each
    path parameter. Only emits one edge per param (nearest ancestor).
    Falls back to param-name inference when no ancestor segment matches.
    """
    segments = operation.path.strip("/").split("/")
    results: list[Dependency] = []
    seen: set[tuple[str, str]] = set()
    excluded = _EXCLUDED | (operation.namespace_params or frozenset())

    for i, seg in enumerate(segments):
        if not seg.startswith("{"):
            continue
        param = seg.strip("{}")
        if param.lower() in excluded:
            continue

        # Skip params with enum constraints — routing selectors, not FKs
        param_schema = operation.path_param_schemas.get(param, {})
        if param_schema.get("enum"):
            continue

        # Walk backwards to find nearest matching ancestor segment.
        nearest_resource = None
        for j in range(i - 1, -1, -1):
            if segments[j].startswith("{"):
                continue
            candidate = segments[j].lower()
            if _SKIP_SEGMENTS.match(candidate):
                continue

            resource = _match_segment(candidate, known_resources)
            if resource is not None:
                nearest_resource = resource
                break

        if nearest_resource is not None:
            key = (param, nearest_resource)
            if key not in seen:
                results.append(Dependency(
                    field=param,
                    target_resource=nearest_resource,
                    fact_ref=f"facts://{operation.service}/{nearest_resource}#id",
                    confidence=0.8,
                    source="generic_odg:path",
                    detection_source=DetectionSource.DEFAULT,
                ))
                seen.add(key)
        else:
            # Fallback: infer from param name when no ancestor matched.
            inferred = _infer_from_param_name(param, known_resources)
            if inferred is not None:
                key = (param, inferred)
                if key not in seen:
                    results.append(Dependency(
                        field=param,
                        target_resource=inferred,
                        fact_ref=f"facts://{operation.service}/{inferred}#id",
                        confidence=0.6,
                        source="generic_odg:path",
                        detection_source=DetectionSource.DEFAULT,
                    ))
                    seen.add(key)

    return results
