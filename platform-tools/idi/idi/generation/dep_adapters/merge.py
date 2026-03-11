"""Confidence-based merge and post-merge filtering for dep adapters."""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency, Output


def merge_deps(deps: list[Dependency]) -> list[Dependency]:
    """Merge dependencies by (field, target_resource), keeping highest confidence."""
    best: dict[tuple[str, str], Dependency] = {}
    for dep in deps:
        key = (dep.field, dep.target_resource)
        existing = best.get(key)
        if existing is None or dep.confidence > existing.confidence:
            best[key] = dep
    return list(best.values())


def merge_outputs(outputs: list[Output]) -> list[Output]:
    """Deduplicate outputs by fact_ref, keeping highest priority."""
    seen: dict[str, Output] = {}
    for out in outputs:
        existing = seen.get(out.fact_ref)
        if existing is None or out.priority > existing.priority:
            seen[out.fact_ref] = out
    return list(seen.values())


_SOURCE_THRESHOLDS: dict[str, float] = {
    "generic_odg:body": 0.25,
    "generic_odg:path": 0.50,
    "generic_odg:query": 0.25,
    "generic_odg:link": 0.0,
    "generic_odg:annotation": 0.0,
}
_DEFAULT_THRESHOLD = 0.25


def filter_by_confidence(deps: list[Dependency]) -> list[Dependency]:
    """Remove deps below their source-specific confidence threshold."""
    return [
        d for d in deps
        if d.confidence >= _SOURCE_THRESHOLDS.get(d.source, _DEFAULT_THRESHOLD)
    ]


def filter_self_refs(
    deps: list[Dependency],
    current_resource: str,
    method: str = "POST",
) -> list[Dependency]:
    """Remove dependencies that point back to the current resource.

    Path-derived self-refs are kept for non-create operations because
    GET/PUT/DELETE on ``/{resource}/{id}`` legitimately depend on the
    create operation that produced the id.
    """
    result: list[Dependency] = []
    is_create = method.upper() in ("POST",)
    for d in deps:
        if d.target_resource != current_resource:
            result.append(d)
        elif not is_create and d.source == "generic_odg:path":
            # Same-resource path dep: e.g. GET /retentions/{id} depends
            # on POST /retentions — keep it.
            result.append(d)
    return result
