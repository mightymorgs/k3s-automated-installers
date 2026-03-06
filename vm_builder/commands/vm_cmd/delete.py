"""Delete VM inventory command handler."""

from __future__ import annotations

import click

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.commands.vm_cmd.output import print_delete_preview
from vm_builder.core.vm_service import VmService


def delete_vm_inventory(vm_name: str) -> None:
    """Delete a VM inventory key from BWS."""
    print_banner(f"Delete VM Inventory: {vm_name}")
    service = VmService()
    ensure_vm_prerequisites(service)

    try:
        inventory = service.get_vm(vm_name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: VM inventory not found: {vm_name}", err=True)
        raise click.Abort() from exc

    print_delete_preview(vm_name, inventory)
    if not click.confirm(f"Delete inventory '{vm_name}' from BWS?", default=False):
        raise click.Abort()

    try:
        service.delete_vm(vm_name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to delete inventory: {exc}", err=True)
        raise click.Abort() from exc

    click.echo()
    click.echo(f"OK: Deleted VM inventory: {vm_name}")

