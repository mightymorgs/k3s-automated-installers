"""VM deploy operation."""

from __future__ import annotations

import subprocess
import time
from typing import Optional

from vm_builder.core.models import VmDeployResult
from vm_builder.core.workflow_names import WorkflowNames


def deploy_vm(self, vm_name: str, hypervisor_key: Optional[str] = None) -> VmDeployResult:
    """Deploy VM by triggering the provision workflow via gh CLI."""
    inventory_key = f"inventory/{vm_name}"
    inventory = self.get_vm(vm_name)
    platform = inventory.get("identity", {}).get("platform", "unknown")
    client = inventory.get("identity", {}).get("client", "unknown")

    workflow = WorkflowNames.provision(platform)

    if not hypervisor_key:
        hypervisor_key = self._auto_detect_hypervisor(platform, client)

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
            f"hypervisor_inventory_key={hypervisor_key}",
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
                "hypervisor_inventory_key": hypervisor_key,
            },
            duration_ms=duration_ms,
        )

    ingress = inventory.get("ingress", {})
    ingress_mode = ingress.get("mode", "nodeport")

    time.sleep(3)
    run_url, run_status = self._fetch_latest_run(workflow)

    return VmDeployResult(
        workflow_triggered=True,
        hypervisor_key=hypervisor_key,
        run_url=run_url,
        run_status=run_status,
        phase5_triggered=False,
        ingress_mode=ingress_mode,
    )
