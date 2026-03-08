"""Trigger the live-config-update workflow for a single app."""

from __future__ import annotations

import logging
import subprocess

from vm_builder.core.vm_service_parts.check_prerequisites import gh_repo_args
from vm_builder.core.workflow_names import WorkflowNames

logger = logging.getLogger(__name__)


def trigger_live_update(
    self,
    vm_name: str,
    app_id: str,
) -> dict:
    """Trigger the live-config-update workflow via gh CLI.

    Re-renders J2 templates with updated _config values from BWS,
    kubectl applies the result, and waits for StatefulSet rollout.
    """
    inventory = self._vm_service.get_vm(vm_name)
    hostname = inventory.get("identity", {}).get("hostname", vm_name)
    inventory_key = f"inventory/{vm_name}"
    workflow = WorkflowNames.LIVE_CONFIG_UPDATE
    repo_args = gh_repo_args()

    try:
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
                f"app_id={app_id}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("Failed to trigger %s: %s", workflow, exc)
        return {
            "workflow_triggered": False,
            "error": str(exc),
        }

    return {
        "workflow_triggered": True,
        "workflow": workflow,
        "vm_hostname": hostname,
        "app_id": app_id,
    }
