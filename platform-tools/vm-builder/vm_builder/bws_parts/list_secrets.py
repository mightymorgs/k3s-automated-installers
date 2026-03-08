"""List-secrets operation for BWS CLI wrapper."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from vm_builder.bws_parts.cache import get_cache


def list_secrets(filter_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all secrets, optionally filtered by key prefix.

    Results are cached with a TTL to avoid repeated CLI calls.
    """
    from vm_builder import bws as bws_mod

    cache = get_cache()
    secrets = cache.get_list()

    if secrets is None:
        try:
            result = bws_mod.subprocess.run(
                ["bws", "secret", "list", "--output", "json"],
                capture_output=True,
                check=True,
                text=True,
            )
            secrets = json.loads(result.stdout)
            cache.set_list(secrets)
        except bws_mod.subprocess.CalledProcessError as exc:
            raise bws_mod.BWSError(f"Failed to list secrets: {exc.stderr}")
        except json.JSONDecodeError as exc:
            raise bws_mod.BWSError(f"Failed to parse BWS secret list: {exc}")

    if filter_key:
        secrets = [secret for secret in secrets if secret["key"].startswith(filter_key)]
    return secrets
