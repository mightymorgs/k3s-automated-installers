"""List all apps with override counts for a VM."""

from __future__ import annotations


def get_all_overrides(self, vm_name: str) -> dict:
    """Return a summary of overrides per app."""
    inventory = self._vm_service.get_vm(vm_name)

    overrides = inventory.get("_overrides", {})
    config = inventory.get("_config", {})
    selected = inventory.get("apps", {}).get("selected_apps", [])

    result = {}
    for app_id in selected:
        app_overrides = overrides.get(app_id, [])
        app_config = config.get(app_id, {})
        result[app_id] = {
            "override_count": len(app_overrides),
            "overrides": app_overrides,
            "config_field_count": len(app_config),
        }

    return {"vm_name": vm_name, "apps": result}
