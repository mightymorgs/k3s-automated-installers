"""Config workflow trigger for AppInstallService."""

from __future__ import annotations

import subprocess
import time
from typing import Optional

from vm_builder.core.workflow_names import WorkflowNames


def trigger_config_workflow(self, vm_name: str, app_id: str) -> Optional[str]:
    """Trigger the Phase 4 configure workflow via gh CLI."""
    inventory_key = f"inventory/{vm_name}"
    workflow = WorkflowNames.PHASE4_CONFIGURE_APPS

    subprocess.run(
        [
            "gh",
            "workflow",
            "run",
            workflow,
            "-f",
            f"inventory_key={inventory_key}",
            "-f",
            f"app_id={app_id}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    time.sleep(3)
    return self._get_latest_run_url(workflow)
