"""Get-secret-by-key operation for BWS CLI wrapper."""

from __future__ import annotations

from typing import Union


def get_secret(key: str) -> Union[dict, str]:
    """Get secret by key via list-then-fetch-by-id flow."""
    from vm_builder import bws as bws_mod

    try:
        secrets = bws_mod.list_secrets(filter_key=key)
        matching = [secret for secret in secrets if secret["key"] == key]
        if not matching:
            raise bws_mod.BWSError(f"Secret not found: {key}")

        secret_id = matching[0]["id"]
        return bws_mod.get_secret_by_id(secret_id)
    except bws_mod.BWSError:
        raise
    except Exception as exc:
        raise bws_mod.BWSError(f"Failed to get secret '{key}': {exc}")
