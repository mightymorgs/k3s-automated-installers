"""Install workflow trigger for AppInstallService."""

from __future__ import annotations

import json
import subprocess
import time
from typing import Optional

from vm_builder.core.workflow_names import WorkflowNames


def trigger_install_workflow(
    self, vm_name: str, app_id: str, app_config: dict
) -> Optional[str]:
    """Trigger the Phase 3 install workflow via gh CLI."""
    inventory_key = f"inventory/{vm_name}"
    config_json = json.dumps(app_config) if app_config else "{}"
    workflow = WorkflowNames.PHASE3_DEPLOY_APPS

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
            "-f",
            f"app_config={config_json}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    time.sleep(3)
    return self._get_latest_run_url(workflow)
