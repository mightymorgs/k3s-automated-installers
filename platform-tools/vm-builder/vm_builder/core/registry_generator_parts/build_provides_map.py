"""Capability-map construction for registry generation."""

from __future__ import annotations

from typing import Any

from vm_builder.core.registry_generator_parts.constants import CAPABILITY_ALIASES


def build_provides_map(apps: list[dict[str, Any]]) -> dict[str, str]:
    """Build capability-to-app mapping from app metadata."""
    provides_map: dict[str, str] = {}
    provides_map.update(CAPABILITY_ALIASES)

    for app in apps:
        app_id = app["id"]
        for capability in app.get("provides", []):
            provides_map[capability] = app_id
            if not capability.endswith("_deployed"):
                provides_map[f"{app_id}_deployed"] = app_id

    return provides_map
