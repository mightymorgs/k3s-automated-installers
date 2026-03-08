"""BWS network-shares read helper for StorageService."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def bws_get_network_shares(self, location: str) -> Optional[dict]:
    """Read network-shares/{location} from BWS."""
    key = f"network-shares/{location}"

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
        if not match:
            return None

        get_result = subprocess.run(
            ["bws", "secret", "get", match["id"], "--output", "json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return json.loads(json.loads(get_result.stdout)["value"])
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        logger.warning("Failed to read BWS key: %s", key)
        return None
