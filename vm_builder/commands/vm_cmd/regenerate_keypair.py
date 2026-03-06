"""Regenerate SSH keypair command handler."""

from __future__ import annotations

import click

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.core.vm_service import VmService


def regenerate_keypair(vm_name: str) -> None:
    """Regenerate SSH keypair for a VM and update BWS."""
    print_banner(f"Regenerate SSH Keypair: {vm_name}")
    service = VmService()
    ensure_vm_prerequisites(service)

    try:
        result = service.regenerate_vm_keypair(vm_name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to regenerate keypair: {exc}", err=True)
        raise click.Abort() from exc

    click.echo("OK: SSH keypair regenerated")
    click.echo(f"  Public key: {result['public_key']}")
    click.echo()
    click.echo("NOTE: Re-deploy the VM to apply the new keypair.")
