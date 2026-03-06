"""App configure workflow operation."""

from __future__ import annotations

import json
import subprocess
import time

from vm_builder.core.errors import DependencyError
from vm_builder.core.models import AppConfigureRequest, AppConfigureResult
from vm_builder.core.workflow_names import WorkflowNames


def configure_app(self, request: AppConfigureRequest) -> AppConfigureResult:
    """Configure a single app on an existing VM."""
    inventory = self.get_vm(request.vm_name)
    installed = inventory.get("apps", {}).get("selected_apps", [])
    if request.app_id not in installed:
        raise DependencyError(
            f"App '{request.app_id}' is not installed on {request.vm_name}",
            context={
                "vm_name": request.vm_name,
                "app_id": request.app_id,
            },
            hint=f"Install '{request.app_id}' first before configuring",
        )

    workflow = WorkflowNames.CONFIGURE_APP
    runner_label = f"vm-{request.vm_name}"
    inventory_key = f"inventory/{request.vm_name}"
    config_json = json.dumps(request.config)
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
            "-f",
            f"config_json={config_json}",
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

    return AppConfigureResult(
        workflow_triggered=True,
        vm_name=request.vm_name,
        app_id=request.app_id,
        config_keys=list(request.config.keys()),
        run_url=run_url,
        run_status=run_status,
    )
