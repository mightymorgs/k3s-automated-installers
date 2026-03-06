"""Config-playbook discovery for an app directory."""

from __future__ import annotations

from pathlib import Path


def find_config_playbooks(app_dir: Path) -> list[Path]:
    """Find all config playbooks (Phase 4)."""
    config_dir = app_dir / "config"
    if config_dir.exists():
        playbooks = list(config_dir.glob("[0-9][0-9]-*.yml"))
        if playbooks:
            return sorted(playbooks, key=lambda path: path.name)

    playbooks = list(app_dir.glob("**/config/[0-9][0-9]-*.yml"))
    if playbooks:
        return sorted(playbooks, key=lambda path: path.name)

    return []
