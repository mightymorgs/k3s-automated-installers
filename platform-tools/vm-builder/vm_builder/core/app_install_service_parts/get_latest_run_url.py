"""GitHub run URL helper for AppInstallService."""

from __future__ import annotations

import json
import subprocess
from typing import Optional


def get_latest_run_url(self, workflow_file: str) -> Optional[str]:
    """Get the URL of the most recent run for a workflow."""
    try:
        result = subprocess.run(
            [
                "gh",
                "run",
                "list",
                f"--workflow={workflow_file}",
                "--limit",
                "1",
                "--json",
                "url,status",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        runs = json.loads(result.stdout)
        if runs:
            return runs[0].get("url")
    except Exception:
        pass

    return None
