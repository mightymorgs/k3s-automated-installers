"""VM read operation."""

from __future__ import annotations

from vm_builder import bws
from vm_builder import schema as schema_mod
from vm_builder.bws import BWSError
from vm_builder.core.errors import VmNotFoundError


def get_vm(self, vm_name: str) -> dict:
    """Get single VM inventory dict."""
    inventory_key = f"inventory/{vm_name}"
    try:
        inventory = bws.get_secret(inventory_key)
    except BWSError as exc:
        raise VmNotFoundError(str(exc), context={"vm_name": vm_name}) from exc

    if not isinstance(inventory, dict):
        raise VmNotFoundError(
            f"Inventory is not a JSON object: {inventory_key}",
            context={"vm_name": vm_name},
        )

    return schema_mod.migrate_inventory(inventory)
