"""Atomic CLI registration modules for vm-builder."""

from vm_builder.cli_atomic.group import main
from vm_builder.cli_atomic.health_command import register_health_command
from vm_builder.cli_atomic.hypervisor_command import register_hypervisor_group
from vm_builder.cli_atomic.ingress_command import register_ingress_group
from vm_builder.cli_atomic.init_command import register_init_group
from vm_builder.cli_atomic.registry_command import register_registry_group
from vm_builder.cli_atomic.schema_command import register_schema_group
from vm_builder.cli_atomic.storage_command import register_storage_group
from vm_builder.cli_atomic.validate_command import register_validate_command
from vm_builder.cli_atomic.vm_command import register_vm_group

__all__ = [
    "main",
    "register_health_command",
    "register_hypervisor_group",
    "register_ingress_group",
    "register_init_group",
    "register_registry_group",
    "register_schema_group",
    "register_storage_group",
    "register_validate_command",
    "register_vm_group",
]
