"""Dependency resolution for RegistryService."""

from __future__ import annotations


def resolve_deps(self, selected_apps: list[str]) -> list[str]:
    """Resolve transitive dependencies in dependency-first order."""
    data = self._load()
    apps = data.get("apps", {})

    for app_id in selected_apps:
        if app_id not in apps:
            raise KeyError(f"App not found: {app_id}")

    resolved: list[str] = []
    visited: set[str] = set()

    def _resolve(app_id: str) -> None:
        if app_id in visited:
            return
        visited.add(app_id)
        if app_id not in apps:
            raise KeyError(f"Dependency not found: {app_id}")
        for dependency in apps[app_id].get("dependencies", []):
            _resolve(dependency)
        resolved.append(app_id)

    for app_id in selected_apps:
        _resolve(app_id)

    return resolved
