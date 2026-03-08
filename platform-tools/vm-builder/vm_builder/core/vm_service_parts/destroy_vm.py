"""VM destroy workflow trigger."""

from __future__ import annotations

import subprocess
import time
from typing import Optional

from vm_builder.core.models import PhaseRunResult
from vm_builder.core.workflow_names import WorkflowNames


def destroy_vm(self, vm_name: str, hypervisor_key: Optional[str] = None) -> PhaseRunResult:
    """Trigger the destroy-vm workflow via gh CLI.

    Drains K3s worker nodes first (if applicable), then triggers the
    destroy-vm.yml workflow which runs on the hypervisor's self-hosted runner.
    """
    inventory_key = f"inventory/{vm_name}"
    inventory = self.get_vm(vm_name)
    hostname = inventory.get("identity", {}).get("hostname", vm_name)
    platform = inventory.get("identity", {}).get("platform", "unknown")
    client = inventory.get("identity", {}).get("client", "unknown")

    # Drain K3s worker before destroy
    k3s_role = inventory.get("k3s", {}).get("role", "none")
    if k3s_role == "agent":
        master_name = inventory.get("k3s", {}).get("master_name")
        if master_name:
            worker_hostname = inventory.get("identity", {}).get("hostname", vm_name)
            self._drain_k3s_node(worker_hostname, master_name)

    if not hypervisor_key:
        hypervisor_key = self._auto_detect_hypervisor(platform, client)

    workflow = WorkflowNames.DESTROY_VM
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
                "vm_hostname": hostname,
                "inventory_key": inventory_key,
                "hypervisor_inventory_key": hypervisor_key,
            },
            duration_ms=duration_ms,
        )

    time.sleep(3)
    run_url, run_status = self._fetch_latest_run(workflow)

    return PhaseRunResult(
        phase="destroy",
        workflow_triggered=True,
        run_url=run_url,
        run_status=run_status,
    )
