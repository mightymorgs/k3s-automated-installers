"""All-playbook discovery for an app directory."""

from __future__ import annotations

from pathlib import Path

from vm_builder.core.registry_generator_parts.find_config_playbooks import (
    find_config_playbooks,
)
from vm_builder.core.registry_generator_parts.find_install_playbooks import (
    find_install_playbooks,
)


def find_all_playbooks(app_dir: Path) -> list[Path]:
    """Find all numbered playbooks in sequence order."""
    install_playbooks = find_install_playbooks(app_dir)
    config_playbooks = find_config_playbooks(app_dir)
    if install_playbooks or config_playbooks:
        return install_playbooks + config_playbooks

    playbooks = list(app_dir.glob("[0-9][0-9]-*.yml"))
    if not playbooks:
        playbooks = list(app_dir.glob("**/[0-9][0-9]-*.yml"))
    return sorted(playbooks, key=lambda path: path.name)
