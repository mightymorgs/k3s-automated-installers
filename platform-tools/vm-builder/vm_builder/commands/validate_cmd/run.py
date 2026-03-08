"""Main validate command handler."""

from __future__ import annotations

import click

from vm_builder import schema
from vm_builder.commands.validate_cmd.output import (
    print_validation_failure,
    print_validation_success,
)
from vm_builder.core.vm_service import VmService


def validate_vm_inventory(vm_name: str) -> None:
    """Validate a VM inventory against schema v3.1."""
    click.echo("=" * 70)
    click.echo(f"Validating VM Inventory: {vm_name}")
    click.echo("=" * 70)
    click.echo()

    service = VmService()
    prereq = service.check_prerequisites()
    if not prereq.ok:
        click.echo(f"ERROR: {prereq.error}", err=True)
        raise click.Abort()

    try:
        click.echo(f"Fetching inventory: inventory/{vm_name}")
        inventory = service.get_vm(vm_name)
        click.echo("OK: Inventory fetched")
        click.echo()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to fetch inventory: {exc}", err=True)
        raise click.Abort() from exc

    is_valid, errors = schema.validate_inventory(inventory)
    if is_valid:
        print_validation_success(inventory)
        return

    print_validation_failure(errors)
    raise click.Abort()

