"""Phase 5 (Ingress + SSO) workflow trigger."""

from __future__ import annotations

import json
import subprocess
import time

from vm_builder.core.models import PhaseRunResult
from vm_builder.core.workflow_names import WorkflowNames


def _ensure_runner_label(hostname: str, label: str) -> None:
    """Add a label to the self-hosted runner if it doesn't already have it."""
    import os

    repo = os.environ.get("GITHUB_REPO", "").strip()
    if not repo:
        return

    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/actions/runners",
         "--jq", f'.runners[] | select(.name=="{hostname}") | .id'],
        capture_output=True, text=True,
    )
    runner_id = result.stdout.strip()
    if not runner_id:
        return
    subprocess.run(
        ["gh", "api", f"repos/{repo}/actions/runners/{runner_id}/labels",
         "--method", "POST", "--input", "-"],
        input=json.dumps({"labels": [label]}),
        capture_output=True, text=True,
    )


def trigger_phase5(self, vm_name: str) -> PhaseRunResult:
    """Trigger the Phase 5 ingress and SSO deployment workflow via gh CLI.

    Phase 5 deploys Traefik ingress, Authentik SSO, and auto-generates
    IngressRoutes and OAuth apps for all installed applications with UI.
    """
    inventory_key = f"inventory/{vm_name}"
    inventory = self.get_vm(vm_name)
    hostname = inventory.get("identity", {}).get("hostname", vm_name)

    workflow = WorkflowNames.PHASE5_DEPLOY_INGRESS_SSO
    repo_args = self._gh_repo_args()

    # Phase 5 workflow runs-on requires the 'tailscale' label for tailscale
    # ingress mode. Add it to the runner dynamically based on inventory.
    ingress_mode = inventory.get("ingress", {}).get("mode", "")
    if ingress_mode == "tailscale":
        _ensure_runner_label(hostname, "tailscale")

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
        phase="5",
        workflow_triggered=True,
        run_url=run_url,
        run_status=run_status,
    )
