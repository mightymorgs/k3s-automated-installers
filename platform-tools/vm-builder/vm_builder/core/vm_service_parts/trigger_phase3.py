"""Phase 3 (Install Apps) workflow trigger."""

from __future__ import annotations

import json
import subprocess
import time

from vm_builder.core.models import PhaseRunResult
from vm_builder.core.workflow_names import WorkflowNames


def trigger_phase3(self, vm_name: str) -> PhaseRunResult:
    """Trigger the Phase 3 dynamic app-install workflow via gh CLI.

    Reads selected_apps from the VM's BWS inventory and passes them
    to the phase3-dynamic.yml workflow.
    """
    inventory_key = f"inventory/{vm_name}"
    inventory = self.get_vm(vm_name)
    hostname = inventory.get("identity", {}).get("hostname", vm_name)
    selected_apps = inventory.get("apps", {}).get("selected_apps", [])

    workflow = WorkflowNames.PHASE3_DEPLOY_APPS
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
            f"vm_hostname={hostname}",
            "-f",
            f"inventory_key={inventory_key}",
            "-f",
            f"selected_apps={json.dumps(selected_apps)}",
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
                "vm_hostname": hostname,
                "inventory_key": inventory_key,
                "selected_apps": selected_apps,
            },
            duration_ms=duration_ms,
        )

    time.sleep(3)
    run_url, run_status = self._fetch_latest_run(workflow)

    return PhaseRunResult(
        phase="3",
        workflow_triggered=True,
        run_url=run_url,
        run_status=run_status,
    )
