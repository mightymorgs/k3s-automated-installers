"""Secret-existence check for BWS CLI wrapper."""

from __future__ import annotations


def secret_exists(key: str) -> bool:
    """Return True when a secret can be fetched by key."""
    from vm_builder import bws as bws_mod

    try:
        bws_mod.get_secret(key)
        return True
    except bws_mod.BWSError:
        return False
