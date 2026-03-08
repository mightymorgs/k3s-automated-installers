"""App install orchestrator for AppInstallService."""

from __future__ import annotations

from vm_builder.core.errors import AppNotFoundError
from vm_builder.core.models import (
    AppStatus,
    AppStatusEnum,
    BatchAppInstallRequest,
    BatchAppInstallResult,
)


def install_apps(self, vm_name: str, request: BatchAppInstallRequest) -> BatchAppInstallResult:
    """Install app(s) on a running VM."""
    inventory = self._vm_service.get_vm(vm_name)
    existing = inventory.get("apps", {}).get("selected_apps", [])

    for app_id in request.apps:
        try:
            self._registry.get_app(app_id)
        except KeyError:
            raise AppNotFoundError(
                f"App not found in registry: {app_id}",
                context={"app_id": app_id},
            )

    delta = self.compute_install_delta(existing, request.apps)

    if not delta:
        return BatchAppInstallResult(
            vm_name=vm_name,
            apps_requested=request.apps,
            apps_to_install=[],
            statuses=[],
        )

    statuses = [AppStatus(app_id=app_id, status=AppStatusEnum.PENDING) for app_id in delta]

    for index, app_id in enumerate(delta):
        statuses[index].status = AppStatusEnum.INSTALLING
        self._update_inventory_apps(vm_name, app_id, AppStatusEnum.INSTALLING)

        try:
            run_url = self._trigger_install_workflow(
                vm_name, app_id, request.app_configs.get(app_id, {})
            )
            statuses[index].workflow_run_url = run_url
            statuses[index].status = AppStatusEnum.INSTALLED
            self._update_inventory_apps(
                vm_name,
                app_id,
                AppStatusEnum.INSTALLED,
                add_to_selected=True,
                workflow_run_url=run_url,
            )
        except Exception as exc:
            statuses[index].status = AppStatusEnum.INSTALL_FAILED
            statuses[index].error = str(exc)
            self._update_inventory_apps(
                vm_name,
                app_id,
                AppStatusEnum.INSTALL_FAILED,
                error=str(exc),
            )
            continue

    for index, app_id in enumerate(delta):
        if statuses[index].status != AppStatusEnum.INSTALLED:
            continue

        statuses[index].status = AppStatusEnum.CONFIGURING
        self._update_inventory_apps(vm_name, app_id, AppStatusEnum.CONFIGURING)

        try:
            run_url = self._trigger_config_workflow(vm_name, app_id)
            statuses[index].workflow_run_url = run_url
            statuses[index].status = AppStatusEnum.READY
            self._update_inventory_apps(
                vm_name,
                app_id,
                AppStatusEnum.READY,
                workflow_run_url=run_url,
            )
        except Exception as exc:
            statuses[index].status = AppStatusEnum.CONFIG_FAILED
            statuses[index].error = str(exc)
            self._update_inventory_apps(
                vm_name,
                app_id,
                AppStatusEnum.CONFIG_FAILED,
                error=str(exc),
            )

    return BatchAppInstallResult(
        vm_name=vm_name,
        apps_requested=request.apps,
        apps_to_install=delta,
        statuses=statuses,
    )
