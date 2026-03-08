"""Registration for the ``validate`` CLI command."""

from __future__ import annotations

import click

from vm_builder.commands.validate import validate_vm_inventory


def register_validate_command(root: click.Group) -> None:
    """Attach the ``validate`` command to the root CLI group."""

    @root.command("validate")
    @click.argument("vm_name")
    def validate(vm_name: str) -> None:
        """Validate VM inventory against schema v3.1."""
        validate_vm_inventory(vm_name)

