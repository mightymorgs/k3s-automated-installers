"""Inventory app-state updater for AppInstallService."""

from __future__ import annotations

from typing import Optional

from vm_builder import bws
from vm_builder.core.models import AppStatusEnum


def update_inventory_apps(
    self,
    vm_name: str,
    app_id: str,
    status: AppStatusEnum,
    add_to_selected: bool = False,
    workflow_run_url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Update BWS inventory with app status."""
    inventory = self._vm_service.get_vm(vm_name)

    if "apps" not in inventory.get("_state", {}):
        inventory.setdefault("_state", {})["apps"] = {}

    inventory["_state"]["apps"][app_id] = {
        "status": status.value,
    }
    if workflow_run_url:
        inventory["_state"]["apps"][app_id]["workflow_run_url"] = workflow_run_url
    if error:
        inventory["_state"]["apps"][app_id]["error"] = error

    if add_to_selected:
        selected = inventory.get("apps", {}).get("selected_apps", [])
        if app_id not in selected:
            selected.append(app_id)
            inventory["apps"]["selected_apps"] = selected

    inventory_key = f"inventory/{vm_name}"
    secrets = bws.list_secrets(filter_key=inventory_key)
    if secrets:
        bws.edit_secret(secrets[0]["id"], inventory)
