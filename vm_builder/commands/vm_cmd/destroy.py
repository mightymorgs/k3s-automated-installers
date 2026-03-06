"""Destroy VM command handler."""

from __future__ import annotations

import click

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.core.vm_service import VmService


def destroy_vm(vm_name: str) -> None:
    """Destroy VM infrastructure by triggering the destroy workflow."""
    print_banner(f"Destroy VM: {vm_name}")
    service = VmService()
    ensure_vm_prerequisites(service, check_gh=True)

    if not click.confirm(
        f"Destroy VM '{vm_name}'? This tears down hypervisor resources.",
        default=False,
    ):
        raise click.Abort()

    try:
        result = service.destroy_vm(vm_name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to destroy VM: {exc}", err=True)
        raise click.Abort() from exc

    click.echo("OK: Destroy workflow triggered")
    if result.run_url:
        click.echo(f"  Status: {result.run_status}")
        click.echo(f"  URL: {result.run_url}")
    click.echo()
    click.echo("Monitor progress:")
    click.echo("  gh run watch")
