"""VM delete operation."""

from __future__ import annotations

from vm_builder import bws
from vm_builder.bws import BWSError
from vm_builder.core.errors import VmNotFoundError


def delete_vm(self, vm_name: str) -> None:
    """Delete VM inventory from BWS."""
    inventory_key = f"inventory/{vm_name}"
    try:
        bws.get_secret(inventory_key)
    except BWSError as exc:
        raise VmNotFoundError(str(exc), context={"vm_name": vm_name}) from exc

    secrets = bws.list_secrets(filter_key=inventory_key)
    if secrets:
        bws.delete_secret(secrets[0]["id"])
