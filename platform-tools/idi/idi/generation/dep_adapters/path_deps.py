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

# Suffixes stripped from path param names to infer the resource.
_FK_SUFFIXES: tuple[str, ...] = (
    "_id", "_pk", "_uuid", "_guid", "_key", "_ref", "_slug",
    "Id", "Pk", "Uuid", "Guid", "Key", "Ref", "Slug",
)


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

    Walks all ancestor resource segments for each path parameter,
    not just the immediate parent. Confidence decreases with distance.
    Falls back to param-name inference when no ancestor segment matches.
    """
    segments = operation.path.strip("/").split("/")
    results: list[Dependency] = []
    seen: set[tuple[str, str]] = set()

    for i, seg in enumerate(segments):
        if not seg.startswith("{"):
            continue
        param = seg.strip("{}")
        if param.lower() in _EXCLUDED:
            continue

        # Walk backwards through all ancestor resource segments.
        matched_ancestor = False
        depth = 0
        for j in range(i - 1, -1, -1):
            if segments[j].startswith("{"):
                continue
            candidate = segments[j].lower()
            if _SKIP_SEGMENTS.match(candidate):
                continue

            resource = _match_segment(candidate, known_resources)
            if resource is not None:
                key = (param, resource)
                if key not in seen:
                    confidence = max(0.4, 0.8 - depth * 0.1)
                    results.append(Dependency(
                        field=param,
                        target_resource=resource,
                        fact_ref=f"facts://{operation.service}/{resource}#id",
                        confidence=confidence,
                        source="generic_odg:path",
                        detection_source=DetectionSource.DEFAULT,
                    ))
                    seen.add(key)
                matched_ancestor = True
            depth += 1

        # Fallback: infer from param name when no ancestor matched.
        # Covers first-position params like {realm} and suffixed params
        # like {stage_uuid}.
        if not matched_ancestor:
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
