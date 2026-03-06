"""List VM inventories command handler."""

from __future__ import annotations

import click

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.commands.vm_cmd.output import print_vm_list
from vm_builder.core.vm_service import VmService


def list_vms(client_filter: str | None = None) -> None:
    """List VM inventories, optionally filtered by client."""
    print_banner("VM Inventories in BWS")
    service = VmService()
    ensure_vm_prerequisites(service)

    try:
        vms = service.list_vms(client_filter=client_filter)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to list VMs: {exc}", err=True)
        raise click.Abort() from exc

    print_vm_list(vms, client_filter=client_filter)

