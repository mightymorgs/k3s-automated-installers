"""App discovery from templates directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from vm_builder.core.registry_generator_parts.build_app_record import build_app_record
from vm_builder.core.registry_generator_parts.extract_playbook_metadata import (
    extract_playbook_metadata,
)
from vm_builder.core.registry_generator_parts.find_config_playbooks import (
    find_config_playbooks,
)
from vm_builder.core.registry_generator_parts.find_entry_playbook import (
    find_entry_playbook,
)
from vm_builder.core.registry_generator_parts.find_install_playbooks import (
    find_install_playbooks,
)


def _extract_config_requires(
    config_playbooks: list[Path],
    app_name: str,
) -> dict[Path, list[str]]:
    """Extract requires_apps from each config playbook's metadata.

    Returns a mapping from playbook path to its requires_apps list.
    Defaults to [app_name] if not specified in the playbook metadata.
    """
    requires_map: dict[Path, list[str]] = {}
    for pb in config_playbooks:
        pb_meta = extract_playbook_metadata(pb)
        if pb_meta and "requires_apps" in pb_meta:
            requires_map[pb] = pb_meta["requires_apps"]
        else:
            requires_map[pb] = [app_name]
    return requires_map


def discover_apps(
    templates_dir: Path,
    path_prefix: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Discover all app records from apps/ metadata and playbooks."""
    apps: list[dict[str, Any]] = []

    scan_dir = templates_dir / "apps"
    if not scan_dir.exists():
        return apps

    for app_dir in sorted(scan_dir.iterdir()):
        if not app_dir.is_dir():
            continue

        deploy_file = find_entry_playbook(app_dir)
        if not deploy_file:
            continue

        metadata = extract_playbook_metadata(deploy_file)
        if not metadata:
            continue

        ui_metadata = metadata.get("ui", {})
        if not ui_metadata:
            continue

        install_playbooks = find_install_playbooks(app_dir)
        config_playbooks = find_config_playbooks(app_dir)
        config_requires = _extract_config_requires(config_playbooks, app_dir.name)

        apps.append(
            build_app_record(
                app_dir=app_dir,
                deploy_file=deploy_file,
                metadata=metadata,
                install_playbooks=install_playbooks,
                config_playbooks=config_playbooks,
                config_requires=config_requires,
                templates_dir=templates_dir,
                path_prefix=path_prefix,
            )
        )

    return apps
