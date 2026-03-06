"""Thin vm-builder CLI entrypoint.

Command registration is split into atomic modules under
``vm_builder.cli_atomic`` to keep each unit small and LLM-friendly.
"""

from __future__ import annotations

from vm_builder.cli_atomic.group import main
from vm_builder.cli_atomic.health_command import register_health_command
from vm_builder.cli_atomic.hypervisor_command import register_hypervisor_group
from vm_builder.cli_atomic.ingress_command import register_ingress_group
from vm_builder.cli_atomic.init_command import register_init_group
from vm_builder.cli_atomic.registry_command import register_registry_group
from vm_builder.cli_atomic.schema_command import register_schema_group
from vm_builder.cli_atomic.storage_command import register_storage_group
from vm_builder.cli_atomic.validate_command import register_validate_command
from vm_builder.cli_atomic.scaffold_command import register_scaffold_group
from vm_builder.cli_atomic.vm_command import register_vm_group

register_init_group(main)
register_hypervisor_group(main)
register_vm_group(main)
register_validate_command(main)
register_registry_group(main)
register_storage_group(main)
register_ingress_group(main)
register_schema_group(main)
register_health_command(main)
register_scaffold_group(main)


if __name__ == "__main__":
    main()
