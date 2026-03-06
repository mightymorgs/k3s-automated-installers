"""Get full config state for an app: config, overrides, defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from vm_builder.core.vm_service_parts.populate_config import extract_app_defaults


def get_app_config(
    self,
    vm_name: str,
    app_id: str,
    templates_dir: Optional[Path] = None,
) -> dict:
    """Return config, overrides, and defaults for an app."""
    inventory = self._vm_service.get_vm(vm_name)

    config = inventory.get("_config", {}).get(app_id, {})
    overrides = inventory.get("_overrides", {}).get(app_id, [])

    defaults = {}
    if templates_dir:
        defaults = extract_app_defaults(app_id, templates_dir)

    return {
        "app_id": app_id,
        "config": config,
        "overrides": overrides,
        "defaults": defaults,
    }
