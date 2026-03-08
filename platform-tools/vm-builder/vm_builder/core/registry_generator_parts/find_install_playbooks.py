"""Install-playbook discovery for an app directory."""

from __future__ import annotations

from pathlib import Path


def find_install_playbooks(app_dir: Path) -> list[Path]:
    """Find all install playbooks (Phase 3)."""
    install_dir = app_dir / "install"
    if install_dir.exists():
        playbooks = list(install_dir.glob("[0-9][0-9]-*.yml"))
        if playbooks:
            return sorted(playbooks, key=lambda path: path.name)

    playbooks = list(app_dir.glob("**/install/[0-9][0-9]-*.yml"))
    if playbooks:
        return sorted(playbooks, key=lambda path: path.name)

    playbooks = list(app_dir.glob("[0-9][0-9]-*.yml"))
    if playbooks:
        return sorted(playbooks, key=lambda path: path.name)

    playbooks = list(app_dir.glob("**/[0-9][0-9]-*.yml"))
    return sorted(playbooks, key=lambda path: path.name)
