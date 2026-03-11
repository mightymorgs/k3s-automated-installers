"""Path parameter parent resource detection.

Extracted from ``polymorphic.extract_path_refs()``.
Enhanced with RESTler-style multi-level path hierarchy inference.
"""
from __future__ import annotations

import re

from idi.generation.dep_adapters.base import Dependency, DetectionSource, OperationInfo

_EXCLUDED: frozenset[str] = frozenset({"namespace", "namespaces", "ns"})
_SKIP_SEGMENTS: re.Pattern = re.compile(r"^(v\d+|api|apis)$", re.IGNORECASE)


def detect_path_deps(
    operation: OperationInfo,
    known_resources: set[str],
) -> list[Dependency]:
    """Extract parent resource deps from URL path parameters.

    Walks all ancestor resource segments for each path parameter,
    not just the immediate parent. Confidence decreases with distance.
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
        depth = 0
        for j in range(i - 1, -1, -1):
            if segments[j].startswith("{"):
                continue
            candidate = segments[j].lower()
            if _SKIP_SEGMENTS.match(candidate):
                continue

            if candidate in known_resources:
                key = (param, candidate)
                if key not in seen:
                    # Confidence: 0.8 for immediate parent, -0.1 per level.
                    confidence = max(0.4, 0.8 - depth * 0.1)
                    results.append(Dependency(
                        field=param,
                        target_resource=candidate,
                        fact_ref=f"facts://{operation.service}/{candidate}#id",
                        confidence=confidence,
                        source="generic_odg:path",
                        detection_source=DetectionSource.DEFAULT,
                    ))
                    seen.add(key)
                depth += 1

    return results
