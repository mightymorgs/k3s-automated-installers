"""Network-shares save operation for StorageService."""

from __future__ import annotations

import json
import logging
import subprocess

logger = logging.getLogger(__name__)


def save_network_shares(self, location: str, config: dict) -> bool:
    """Save network shares config to BWS."""
    key = f"network-shares/{location}"
    value = json.dumps(config)

    try:
        result = subprocess.run(
            ["bws", "secret", "list", "--output", "json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        secrets = json.loads(result.stdout)
        match = next((secret for secret in secrets if secret.get("key") == key), None)

        if match:
            subprocess.run(
                ["bws", "secret", "edit", "--value", value, match["id"]],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        else:
            from vm_builder import bws

            project_id = bws.get_project_id()
            subprocess.run(
                ["bws", "secret", "create", key, value, project_id],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

        return True
    except subprocess.CalledProcessError:
        logger.error("Failed to save BWS key: %s", key)
        return False
