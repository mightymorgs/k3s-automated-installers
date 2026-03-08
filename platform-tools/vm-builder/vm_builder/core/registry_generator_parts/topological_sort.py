"""Topological sort helper for app install order."""

from __future__ import annotations

from typing import Any


def topological_sort(apps: dict[str, dict[str, Any]]) -> list[str]:
    """Return deterministic dependency-first install order."""
    in_degree = {app_id: 0 for app_id in apps}
    graph = {app_id: [] for app_id in apps}

    for app_id, app in apps.items():
        for dependency in app.get("depends_on", []):
            if dependency in apps:
                graph[dependency].append(app_id)
                in_degree[app_id] += 1

    queue = [app_id for app_id, degree in in_degree.items() if degree == 0]
    result: list[str] = []

    while queue:
        queue.sort()
        node = queue.pop(0)
        result.append(node)

        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(apps):
        return list(apps.keys())
    return result


def compute_install_waves(apps: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Assign each app to a wave (tier) for parallel installation.

    Wave 0 apps have no intra-app dependencies and can all run in parallel.
    Wave N apps depend only on apps in waves 0..N-1.
    """
    in_degree = {app_id: 0 for app_id in apps}
    reverse_deps: dict[str, list[str]] = {app_id: [] for app_id in apps}

    for app_id, app in apps.items():
        for dependency in app.get("depends_on", []):
            if dependency in apps:
                reverse_deps[app_id].append(dependency)
                in_degree[app_id] += 1

    waves: dict[str, int] = {}
    remaining = set(apps.keys())

    wave = 0
    while remaining:
        # Apps whose dependencies are all resolved
        ready = sorted(app_id for app_id in remaining if in_degree[app_id] == 0)
        if not ready:
            # Cycle detected — dump everything into current wave
            for app_id in sorted(remaining):
                waves[app_id] = wave
            break
        for app_id in ready:
            waves[app_id] = wave
            remaining.discard(app_id)
            for other_id, deps in reverse_deps.items():
                if app_id in deps:
                    in_degree[other_id] -= 1
        wave += 1

    return waves
