"""App uninstall operation for AppInstallService."""

from __future__ import annotations

from vm_builder import bws
from vm_builder.core.errors import AppNotFoundError
from vm_builder.core.models import AppUninstallResult


def uninstall_app(self, vm_name: str, app_id: str) -> AppUninstallResult:
    """Remove an app from the VM inventory."""
    inventory = self._vm_service.get_vm(vm_name)
    selected = inventory.get("apps", {}).get("selected_apps", [])

    if app_id not in selected:
        raise AppNotFoundError(
            f"App '{app_id}' is not installed on VM '{vm_name}'",
            context={"app_id": app_id, "vm_name": vm_name},
        )

    selected.remove(app_id)
    inventory["apps"]["selected_apps"] = selected

    app_states = inventory.get("_state", {}).get("apps", {})
    app_states.pop(app_id, None)

    app_configs = inventory.get("_config", {})
    app_configs.pop(app_id, None)

    app_overrides = inventory.get("_overrides", {})
    app_overrides.pop(app_id, None)

    inventory_key = f"inventory/{vm_name}"
    secrets = bws.list_secrets(filter_key=inventory_key)
    if secrets:
        bws.edit_secret(secrets[0]["id"], inventory)

    return AppUninstallResult(
        vm_name=vm_name,
        app_id=app_id,
        removed_from_inventory=True,
        k8s_resources_remain=True,
        message=(
            f"App '{app_id}' removed from inventory. "
            f"K8s resources remain on the cluster. "
            f"Run 'helm uninstall {app_id}' on the target VM to fully clean up."
        ),
    )
