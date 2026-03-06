"""VM create operation."""

from __future__ import annotations

from typing import Optional

from vm_builder import bws
from vm_builder import schema as schema_mod
from vm_builder.core.errors import ValidationError as VmValidationError
from vm_builder.core.models import VmCreateRequest, VmCreateResult


def create_vm(
    self,
    request: VmCreateRequest,
    registry_data: Optional[dict] = None,
) -> VmCreateResult:
    """Full VM creation: keygen, build inventory, validate, write to BWS."""
    console_username = bws.get_secret("inventory/shared/secrets/console/username")
    public_key, private_key_b64 = self.generate_ssh_keypair(request.vm_name)

    inventory = self.build_inventory(
        request=request,
        console_username=console_username,
        ssh_public_key=public_key,
        ssh_private_key_b64=private_key_b64,
        registry_data=registry_data,
    )

    if request.hypervisor:
        inventory["provider"]["hypervisor"] = request.hypervisor

    is_valid, errors = schema_mod.validate_inventory(inventory)
    if not is_valid:
        raise VmValidationError(
            f"Inventory validation failed: {'; '.join(errors)}",
            context={"vm_name": request.vm_name, "errors": errors},
        )

    inventory_key = f"inventory/{request.vm_name}"
    created = True
    if bws.secret_exists(inventory_key):
        existing = bws.list_secrets(filter_key=inventory_key)
        if existing:
            bws.edit_secret(existing[0]["id"], inventory)
            created = False
    else:
        bws.create_secret(inventory_key, inventory)

    components = schema_mod.parse_vm_name(request.vm_name)[1]
    return VmCreateResult(
        inventory_key=inventory_key,
        vm_name=request.vm_name,
        client=components["client"],
        platform=request.platform,
        size=request.size,
        k3s_role=inventory["k3s"]["role"],
        apps_count=len(inventory["apps"]["selected_apps"]),
        ingress_mode=inventory["ingress"]["mode"],
        created=created,
    )
