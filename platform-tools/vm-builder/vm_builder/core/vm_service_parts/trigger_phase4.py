"""Phase 4 (Configure Apps) workflow trigger."""

from __future__ import annotations

import subprocess
import time

from vm_builder.core.models import PhaseRunResult
from vm_builder.core.workflow_names import WorkflowNames


def trigger_phase4(self, vm_name: str) -> PhaseRunResult:
    """Trigger the Phase 4 dynamic app-configuration workflow via gh CLI.

    Phase 4 reads installed apps from BWS inventory and runs config
    playbooks filtered by requires_apps metadata.
    """
    inventory_key = f"inventory/{vm_name}"
    inventory = self.get_vm(vm_name)
    hostname = inventory.get("identity", {}).get("hostname", vm_name)

    workflow = WorkflowNames.PHASE4_CONFIGURE_APPS
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
            },
            duration_ms=duration_ms,
        )

    time.sleep(3)
    run_url, run_status = self._fetch_latest_run(workflow)

    return PhaseRunResult(
        phase="4",
        workflow_triggered=True,
        run_url=run_url,
        run_status=run_status,
    )
