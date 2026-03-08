"""Resource defaults accessor by app category."""

from __future__ import annotations

from typing import Dict

from vm_builder.schema_parts.constants import RESOURCE_DEFAULTS


def get_resource_defaults(category: str) -> Dict[str, int]:
    """Get resource defaults for category; fallback to _default."""
    return RESOURCE_DEFAULTS.get(category, RESOURCE_DEFAULTS["_default"]).copy()
