"""Reset a single config field to its template default."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from vm_builder.core.errors import ValidationError as VmValidationError
from vm_builder.core.vm_service_parts.populate_config import extract_app_defaults


def reset_field(
    self,
    vm_name: str,
    app_id: str,
    field_name: str,
    templates_dir: Optional[Path] = None,
) -> dict:
    """Reset a config field to default and remove from overrides."""
    inventory = self._vm_service.get_vm(vm_name)

    defaults = {}
    if templates_dir:
        defaults = extract_app_defaults(app_id, templates_dir)

    app_config = inventory.get("_config", {}).get(app_id, {})
    if field_name not in app_config:
        raise VmValidationError(
            f"Field '{field_name}' not found in _config for app '{app_id}'",
            context={"vm_name": vm_name, "app_id": app_id, "field_name": field_name},
        )

    if field_name in defaults:
        inventory["_config"][app_id][field_name] = defaults[field_name]
    else:
        del inventory["_config"][app_id][field_name]

    app_overrides = inventory.get("_overrides", {}).get(app_id, [])
    if field_name in app_overrides:
        app_overrides.remove(field_name)
        if not app_overrides:
            inventory.get("_overrides", {}).pop(app_id, None)
        else:
            inventory["_overrides"][app_id] = app_overrides

    self._save_inventory(vm_name, inventory)

    return {
        "vm_name": vm_name,
        "app_id": app_id,
        "field_name": field_name,
        "reset_to": defaults.get(field_name),
        "updated": True,
    }
