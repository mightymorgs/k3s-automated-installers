"""Installed-app listing for AppInstallService."""

from __future__ import annotations

from vm_builder.core.errors import AppNotFoundError
from vm_builder.core.models import AppStatusEnum, InstalledApp


def list_installed_apps(self, vm_name: str) -> list[InstalledApp]:
    """List apps that have been through the install pipeline on a VM."""
    inventory = self._vm_service.get_vm(vm_name)
    selected = inventory.get("apps", {}).get("selected_apps", [])
    app_states = inventory.get("_state", {}).get("apps", {})

    installed: list[InstalledApp] = []
    for app_id in selected:
        if app_id not in app_states:
            continue

        try:
            app_data = self._registry.get_app(app_id)
            display_name = app_data.get("display_name", app_id)
            category = app_data.get("category", "unknown")
        except (KeyError, AppNotFoundError):
            display_name = app_id
            category = "unknown"

        state_info = app_states[app_id]
        status_str = state_info.get("status", "pending")
        try:
            status = AppStatusEnum(status_str)
        except ValueError:
            status = AppStatusEnum.PENDING

        installed.append(
            InstalledApp(
                app_id=app_id,
                display_name=display_name,
                category=category,
                status=status,
            )
        )

    return installed
