"""Dependency resolution from capabilities to app IDs."""

from __future__ import annotations

from typing import Any

from vm_builder.core.registry_generator_parts.constants import PLATFORM_PREREQUISITES


def resolve_dependencies(
    app: dict[str, Any],
    provides_map: dict[str, str],
    all_app_ids: set[str],
) -> dict[str, Any]:
    """Resolve one app's dependency capabilities to app IDs/platform deps."""
    dependencies = app.get("dependencies", [])
    depends_on_apps: list[str] = []
    platform_deps: list[str] = []

    for dep in dependencies:
        if dep in PLATFORM_PREREQUISITES:
            platform_dep = PLATFORM_PREREQUISITES[dep]
            if platform_dep:
                platform_deps.append(platform_dep)
            continue

        resolved_app = provides_map.get(dep)
        if resolved_app and resolved_app in all_app_ids:
            if resolved_app != app["id"]:
                depends_on_apps.append(resolved_app)
            continue

        inferred = (
            dep.replace("_installed", "")
            .replace("_deployed", "")
            .replace("_configured", "")
            .replace("_ready", "")
        )
        if inferred in all_app_ids and inferred != app["id"]:
            depends_on_apps.append(inferred)

    depends_on_apps = list(dict.fromkeys(depends_on_apps))
    platform_deps = list(dict.fromkeys(platform_deps))
    return {"depends_on": depends_on_apps, "platform_deps": platform_deps}
