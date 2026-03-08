"""Top-level registry document generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from vm_builder.core.registry_generator_parts.build_provides_map import (
    build_provides_map,
)
from vm_builder.core.registry_generator_parts.constants import PLATFORM_PREREQUISITES
from vm_builder.core.registry_generator_parts.discover_apps import discover_apps
from vm_builder.core.registry_generator_parts.resolve_dependencies import (
    resolve_dependencies,
)
from vm_builder.core.registry_generator_parts.topological_sort import (
    compute_install_waves,
    topological_sort,
)


def generate_registry(
    templates_dir: Path,
    path_prefix: Optional[str] = None,
) -> dict[str, Any]:
    """Generate full registry document from template metadata."""
    if path_prefix is None:
        path_prefix = str(templates_dir)
    apps = discover_apps(templates_dir, path_prefix=path_prefix)

    provides_map = build_provides_map(apps)
    all_app_ids = {app["id"] for app in apps}

    for app in apps:
        resolved = resolve_dependencies(app, provides_map, all_app_ids)
        app["depends_on"] = resolved["depends_on"]
        app["platform_deps"] = resolved["platform_deps"]
        app["requires_shared_storage"] = "media-shared" in resolved["depends_on"]

    apps_dict = {app["id"]: app for app in apps}
    install_order = topological_sort(apps_dict)
    waves = compute_install_waves(apps_dict)

    # Add wave to each app record
    for app_id, wave in waves.items():
        apps_dict[app_id]["install_wave"] = wave

    # Build wave arrays for workflow consumption
    max_wave = max(waves.values()) if waves else 0
    install_waves: list[list[str]] = []
    for w in range(max_wave + 1):
        install_waves.append(sorted(app_id for app_id, wv in waves.items() if wv == w))

    categories: dict[str, list[str]] = {}
    for app in apps:
        category = app["category"]
        if category not in categories:
            categories[category] = []
        categories[category].append(app["id"])

    return {
        "version": "3.2.0",
        "schema_version": "v3.2",
        "generated_by": "vm_builder.core.registry_generator",
        "description": "Auto-generated app registry from atomic playbook metadata",
        "apps": apps_dict,
        "categories": categories,
        "install_order": install_order,
        "install_waves": install_waves,
        "platform_prerequisites": sorted(
            {v for v in PLATFORM_PREREQUISITES.values() if v is not None}
        ),
    }
