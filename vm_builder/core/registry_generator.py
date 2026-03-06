"""Registry generator -- scans app directories and produces registry JSON."""

from __future__ import annotations

from vm_builder.core.registry_generator_parts import build_provides_map as build_provides_map_part
from vm_builder.core.registry_generator_parts import constants as constants_part
from vm_builder.core.registry_generator_parts import discover_apps as discover_apps_part
from vm_builder.core.registry_generator_parts import extract_playbook_metadata as extract_playbook_metadata_part
from vm_builder.core.registry_generator_parts import find_all_playbooks as find_all_playbooks_part
from vm_builder.core.registry_generator_parts import find_config_playbooks as find_config_playbooks_part
from vm_builder.core.registry_generator_parts import find_entry_playbook as find_entry_playbook_part
from vm_builder.core.registry_generator_parts import find_install_playbooks as find_install_playbooks_part
from vm_builder.core.registry_generator_parts import generate_registry as generate_registry_part
from vm_builder.core.registry_generator_parts import resolve_dependencies as resolve_dependencies_part
from vm_builder.core.registry_generator_parts import topological_sort as topological_sort_part
from vm_builder.core.registry_generator_parts import write_registry as write_registry_part

PLATFORM_PREREQUISITES = constants_part.PLATFORM_PREREQUISITES
CAPABILITY_ALIASES = constants_part.CAPABILITY_ALIASES

extract_playbook_metadata = extract_playbook_metadata_part.extract_playbook_metadata
find_entry_playbook = find_entry_playbook_part.find_entry_playbook
find_install_playbooks = find_install_playbooks_part.find_install_playbooks
find_config_playbooks = find_config_playbooks_part.find_config_playbooks
find_all_playbooks = find_all_playbooks_part.find_all_playbooks
build_provides_map = build_provides_map_part.build_provides_map
resolve_dependencies = resolve_dependencies_part.resolve_dependencies
topological_sort = topological_sort_part.topological_sort
discover_apps = discover_apps_part.discover_apps
generate_registry = generate_registry_part.generate_registry
write_registry = write_registry_part.write_registry

__all__ = [
    "CAPABILITY_ALIASES",
    "PLATFORM_PREREQUISITES",
    "build_provides_map",
    "discover_apps",
    "extract_playbook_metadata",
    "find_all_playbooks",
    "find_config_playbooks",
    "find_entry_playbook",
    "find_install_playbooks",
    "generate_registry",
    "resolve_dependencies",
    "topological_sort",
    "write_registry",
]
