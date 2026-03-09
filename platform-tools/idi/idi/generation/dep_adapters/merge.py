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


def filter_self_refs(
    deps: list[Dependency],
    current_resource: str,
) -> list[Dependency]:
    """Remove dependencies that point back to the current resource."""
    return [d for d in deps if d.target_resource != current_resource]
