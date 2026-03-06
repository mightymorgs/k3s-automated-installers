"""Update a single config field for an app and track as override."""

from __future__ import annotations

from vm_builder import bws
from vm_builder.core.errors import ValidationError as VmValidationError


def update_field(
    self,
    vm_name: str,
    app_id: str,
    field: str,
    value,
) -> dict:
    """Update a config field and record it as an override."""
    inventory = self._vm_service.get_vm(vm_name)

    selected = inventory.get("apps", {}).get("selected_apps", [])
    if app_id not in selected:
        raise VmValidationError(
            f"App '{app_id}' is not in selected_apps for VM '{vm_name}'",
            context={"vm_name": vm_name, "app_id": app_id},
        )

    if "_config" not in inventory:
        inventory["_config"] = {}
    if app_id not in inventory["_config"]:
        inventory["_config"][app_id] = {}
    inventory["_config"][app_id][field] = value

    if "_overrides" not in inventory:
        inventory["_overrides"] = {}
    if app_id not in inventory["_overrides"]:
        inventory["_overrides"][app_id] = []
    if field not in inventory["_overrides"][app_id]:
        inventory["_overrides"][app_id].append(field)
        inventory["_overrides"][app_id].sort()

    self._save_inventory(vm_name, inventory)

    # Auto-trigger live-config-update workflow to apply changes to VM
    workflow_result = self.trigger_live_update(vm_name, app_id)

    return {
        "vm_name": vm_name,
        "app_id": app_id,
        "field": field,
        "value": value,
        "updated": True,
        **workflow_result,
    }
