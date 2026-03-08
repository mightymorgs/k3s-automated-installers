"""GitHub workflow run lookup helper."""

from __future__ import annotations

import json
import subprocess
from typing import Optional


def fetch_latest_run(self, workflow_name: str) -> tuple[Optional[str], Optional[str]]:
    """Fetch URL and status of the most recent run for a workflow."""
    try:
        repo_args = self._gh_repo_args()
        result = subprocess.run(
            [
                "gh",
                "run",
                "list",
                *repo_args,
                f"--workflow={workflow_name}",
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
            return runs[0].get("url"), runs[0].get("status")
    except Exception:
        pass
    return None, None
