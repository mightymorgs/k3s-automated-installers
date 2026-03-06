"""Get-secret-by-id operation for BWS CLI wrapper."""

from __future__ import annotations

import json
from typing import Union

from vm_builder.bws_parts.cache import _MISS, get_cache


def get_secret_by_id(secret_id: str) -> Union[dict, str]:
    """Get secret value by UUID from BWS.

    Results are cached with a TTL to avoid repeated CLI calls.
    """
    from vm_builder import bws as bws_mod

    cache = get_cache()
    cached = cache.get_value(secret_id)
    if cached is not _MISS:
        return cached

    try:
        result = bws_mod.subprocess.run(
            ["bws", "secret", "get", secret_id, "--output", "json"],
            capture_output=True,
            check=True,
            text=True,
        )

        data = json.loads(result.stdout)
        value = data["value"]

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value

        cache.set_value(secret_id, parsed)
        return parsed
    except bws_mod.subprocess.CalledProcessError as exc:
        raise bws_mod.BWSError(
            f"Failed to get secret by ID '{secret_id}': {exc.stderr}"
        )
    except (json.JSONDecodeError, KeyError) as exc:
        raise bws_mod.BWSError(
            f"Failed to parse BWS response for ID '{secret_id}': {exc}"
        )
