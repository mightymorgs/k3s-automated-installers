"""Hypervisor read operation."""

from __future__ import annotations

from vm_builder import bws
from vm_builder.bws import BWSError
from vm_builder.core.errors import HypervisorNotFoundError


def get_hypervisor(self, hypervisor_name: str) -> dict:
    """Get full hypervisor inventory from BWS."""
    inventory_key = f"inventory/hypervisors/{hypervisor_name}"
    try:
        inventory = bws.get_secret(inventory_key)
    except BWSError as exc:
        raise HypervisorNotFoundError(
            f"Hypervisor not found: {hypervisor_name}",
            context={"hypervisor_name": hypervisor_name},
        ) from exc

    if not isinstance(inventory, dict):
        raise HypervisorNotFoundError(
            f"Hypervisor inventory is not JSON: {inventory_key}",
            context={"hypervisor_name": hypervisor_name},
        )

    return inventory
