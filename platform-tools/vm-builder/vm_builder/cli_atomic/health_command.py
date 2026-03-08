"""Registration for the ``health`` CLI command."""

from __future__ import annotations

import click

from vm_builder.commands.health import show_system_health


def register_health_command(root: click.Group) -> None:
    """Attach the ``health`` command to the root CLI group."""

    @root.command("health")
    def health() -> None:
        """Check system health (BWS, gh CLI, repo sync)."""
        show_system_health()
