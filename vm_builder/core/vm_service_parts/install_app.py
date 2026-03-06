"""App install workflow operation."""

from __future__ import annotations

import subprocess
import time

from vm_builder.core.errors import DependencyError
from vm_builder.core.models import AppInstallRequest, AppInstallResult
from vm_builder.core.workflow_names import WorkflowNames


def install_app(
    self,
    request: AppInstallRequest,
    installed_apps: list[str],
    registry_service=None,
) -> AppInstallResult:
    """Install a single app on an existing VM."""
    runner_label = f"vm-{request.vm_name}"

    if not request.skip_dependency_check and registry_service:
        check = registry_service.check_installable(request.app_id, installed_apps)
        if not check["installable"]:
            missing = ", ".join(check["missing_deps"])
            raise DependencyError(
                f"Missing dependencies: {missing}",
                context={
                    "vm_name": request.vm_name,
                    "app_id": request.app_id,
                    "missing_deps": check["missing_deps"],
                },
                hint="Install required dependencies first",
            )

    workflow = WorkflowNames.INSTALL_APP
    inventory_key = f"inventory/{request.vm_name}"
    repo_args = self._gh_repo_args()
    start = time.monotonic()
    subprocess.run(
        [
            "gh",
            "workflow",
            "run",
            workflow,
            *repo_args,
            "-f",
            f"inventory_key={inventory_key}",
            "-f",
            f"app_id={request.app_id}",
            "-f",
            f"runner_label={runner_label}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    duration_ms = int((time.monotonic() - start) * 1000)

    if self._audit:
        self._audit.log_gh_trigger(
            workflow=workflow,
            params={
                "inventory_key": inventory_key,
                "app_id": request.app_id,
                "runner_label": runner_label,
            },
            duration_ms=duration_ms,
        )

    time.sleep(3)
    run_url, run_status = self._fetch_latest_run(workflow)

    return AppInstallResult(
        workflow_triggered=True,
        vm_name=request.vm_name,
        app_id=request.app_id,
        run_url=run_url,
        run_status=run_status,
    )
