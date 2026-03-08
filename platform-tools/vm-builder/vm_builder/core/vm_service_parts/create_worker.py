"""K3s worker creation operation."""

from __future__ import annotations

from typing import Optional

from vm_builder import bws
from vm_builder import schema as schema_mod
from vm_builder.core.errors import ValidationError as VmValidationError
from vm_builder.core.models import VmCreateRequest, VmCreateResult


def create_worker(
    self,
    master_name: str,
    size: str,
    apps: Optional[list[str]] = None,
    **kwargs,
) -> VmCreateResult:
    """Create a K3s worker VM linked to a master."""
    is_valid, master_components, errors = schema_mod.parse_vm_name(master_name)
    if not is_valid:
        raise VmValidationError(
            f"Invalid master name: {'; '.join(errors)}",
            context={"vm_name": master_name, "field": "master_name"},
        )

    worker_index = self._next_worker_index(master_name)

    worker_name = (
        f"{master_components['client']}-k3s-worker-"
        f"{master_components['state']}-"
        f"{master_components['purpose']}w{worker_index}-"
        f"{master_components['platform']}-"
        f"{master_components['version']}"
    )

    request = VmCreateRequest(
        vm_name=worker_name,
        size=size,
        platform=master_components["platform"],
        apps=apps or [],
        **kwargs,
    )

    console_username = bws.get_secret("inventory/shared/secrets/console/username")
    public_key, private_key_b64 = self.generate_ssh_keypair(worker_name)

    inventory = self.build_inventory(
        request=request,
        console_username=console_username,
        ssh_public_key=public_key,
        ssh_private_key_b64=private_key_b64,
        master_name=master_name,
    )

    is_valid, errors = schema_mod.validate_inventory(inventory)
    if not is_valid:
        raise VmValidationError(
            f"Worker inventory validation failed: {'; '.join(errors)}",
            context={"vm_name": worker_name, "errors": errors},
        )

    inventory_key = f"inventory/{worker_name}"
    if bws.secret_exists(inventory_key):
        existing = bws.list_secrets(filter_key=inventory_key)
        if existing:
            bws.edit_secret(existing[0]["id"], inventory)
            created = False
        else:
            bws.create_secret(inventory_key, inventory)
            created = True
    else:
        bws.create_secret(inventory_key, inventory)
        created = True

    return VmCreateResult(
        inventory_key=inventory_key,
        vm_name=worker_name,
        client=master_components["client"],
        platform=master_components["platform"],
        size=size,
        k3s_role="agent",
        apps_count=len(inventory["apps"]["selected_apps"]),
        created=created,
    )
