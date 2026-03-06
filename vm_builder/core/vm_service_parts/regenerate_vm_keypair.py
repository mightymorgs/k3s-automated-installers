"""VM keypair regeneration operation."""

from __future__ import annotations

import copy

from vm_builder import bws
from vm_builder.core.errors import VmNotFoundError


def regenerate_vm_keypair(self, vm_name: str) -> dict:
    """Regenerate SSH keypair for a VM."""
    current = self.get_vm(vm_name)
    updated = copy.deepcopy(current)

    public_key, private_key_b64 = self.generate_ssh_keypair(vm_name)
    updated["ssh"]["keypair"] = {
        "public_key": public_key,
        "private_key_b64": private_key_b64,
    }

    inventory_key = f"inventory/{vm_name}"
    secrets = bws.list_secrets(filter_key=inventory_key)
    matching = [secret for secret in secrets if secret["key"] == inventory_key]
    if not matching:
        raise VmNotFoundError(
            f"Secret not found: {inventory_key}",
            context={"vm_name": vm_name},
        )

    bws.edit_secret(matching[0]["id"], updated)
    return {"public_key": public_key}
