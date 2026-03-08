"""VM update operation."""

from __future__ import annotations

import copy

from vm_builder import bws
from vm_builder import schema as schema_mod
from vm_builder.core.errors import VmNotFoundError, ValidationError as VmValidationError
from vm_builder.core.models import VmUpdateRequest, VmUpdateResult
from vm_builder.core.vm_service_parts.constants import NON_EDITABLE


def update_vm(self, vm_name: str, request: VmUpdateRequest) -> VmUpdateResult:
    """Update existing VM inventory with partial changes."""
    current = self.get_vm(vm_name)
    updated = copy.deepcopy(current)
    changes: dict[str, dict[str, object]] = {}
    warnings: list[str] = []

    editable_sections = {
        "identity": request.identity,
        "hardware": request.hardware,
        "network": request.network,
        "provider": request.provider,
        "apps": request.apps,
        "ssh": request.ssh,
        "tailscale": request.tailscale,
    }

    for section_name, section_data in editable_sections.items():
        if section_data is None:
            continue

        non_editable = NON_EDITABLE.get(section_name, set())

        if section_name not in updated:
            updated[section_name] = {}

        for field, new_value in section_data.items():
            if field in non_editable:
                continue

            old_value = updated[section_name].get(field)
            if old_value != new_value:
                changes[f"{section_name}.{field}"] = {"old": old_value, "new": new_value}
                updated[section_name][field] = new_value

    old_platform = current.get("identity", {}).get("platform")
    new_platform = updated.get("identity", {}).get("platform")
    if old_platform and new_platform and old_platform != new_platform:
        warnings.append(
            f"Platform changed from '{old_platform}' to '{new_platform}'. "
            f"Provider, hardware, and network fields from the old platform "
            f"may no longer apply. Review these sections after saving."
        )

    for disk_field in ["disk_size_gb", "data_disk_size_gb", "boot_disk_size_gb"]:
        old_val = current.get("hardware", {}).get(disk_field)
        new_val = updated.get("hardware", {}).get(disk_field)
        if (
            isinstance(old_val, (int, float))
            and isinstance(new_val, (int, float))
            and new_val < old_val
        ):
            warnings.append(
                f"Disk size '{disk_field}' decreased from {old_val} to {new_val} GB. "
                f"This may fail at deploy time if the existing disk has data."
            )

    if not changes:
        return VmUpdateResult(vm_name=vm_name, updated=False, changes={}, warnings=[])

    is_valid, errors = schema_mod.validate_inventory(updated)
    if not is_valid:
        raise VmValidationError(
            f"Inventory validation failed: {'; '.join(errors)}",
            context={"vm_name": vm_name, "errors": errors},
        )

    inventory_key = f"inventory/{vm_name}"
    secrets = bws.list_secrets(filter_key=inventory_key)
    matching = [secret for secret in secrets if secret["key"] == inventory_key]
    if not matching:
        raise VmNotFoundError(
            f"Secret not found for update: {inventory_key}",
            context={"vm_name": vm_name},
        )
    bws.edit_secret(matching[0]["id"], updated)

    return VmUpdateResult(vm_name=vm_name, updated=True, changes=changes, warnings=warnings)
