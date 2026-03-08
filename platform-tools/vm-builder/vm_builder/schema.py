"""Inventory schema v3.1/v3.2/v3.3 definitions and validation."""

from __future__ import annotations

from vm_builder.schema_parts import constants as constants_part
from vm_builder.schema_parts import get_resource_defaults as get_resource_defaults_part
from vm_builder.schema_parts import get_size_preset as get_size_preset_part
from vm_builder.schema_parts import migrate_inventory as migrate_inventory_part
from vm_builder.schema_parts import parse_vm_name as parse_vm_name_part
from vm_builder.schema_parts import validate_inventory as validate_inventory_part
from vm_builder.schema_parts.inventory_schema import InventorySchema

SIZE_PRESETS = constants_part.SIZE_PRESETS
GCP_SIZE_PRESETS = constants_part.GCP_SIZE_PRESETS
K3S_OVERHEAD_CPU_MILLICORES = constants_part.K3S_OVERHEAD_CPU_MILLICORES
K3S_OVERHEAD_MEMORY_MB = constants_part.K3S_OVERHEAD_MEMORY_MB
RESOURCE_DEFAULTS = constants_part.RESOURCE_DEFAULTS

get_resource_defaults = get_resource_defaults_part.get_resource_defaults
parse_vm_name = parse_vm_name_part.parse_vm_name
validate_inventory = validate_inventory_part.validate_inventory
get_size_preset = get_size_preset_part.get_size_preset
migrate_inventory = migrate_inventory_part.migrate_inventory

__all__ = [
    "GCP_SIZE_PRESETS",
    "InventorySchema",
    "K3S_OVERHEAD_CPU_MILLICORES",
    "K3S_OVERHEAD_MEMORY_MB",
    "RESOURCE_DEFAULTS",
    "SIZE_PRESETS",
    "get_resource_defaults",
    "get_size_preset",
    "migrate_inventory",
    "parse_vm_name",
    "validate_inventory",
]
