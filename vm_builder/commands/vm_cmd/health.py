"""VM health status command handler."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from vm_builder.commands.vm_cmd.common import print_banner
from vm_builder.core.health_service import HealthService

_console = Console()


def show_vm_health() -> None:
    """Show Tailscale health status for all VMs."""
    print_banner("VM Health Status (Tailscale)")

    try:
        service = HealthService()
        statuses = service.get_vm_health()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to fetch health status: {exc}", err=True)
        raise click.Abort() from exc

    if not statuses:
        click.echo("No VMs found.")
        return

    table = Table(title=f"VM Health ({len(statuses)} VMs)")
    table.add_column("VM Name", style="cyan", no_wrap=True)
    table.add_column("Online", justify="center")
    table.add_column("Tailscale IP", style="blue")
    table.add_column("Last Seen")
    table.add_column("OS")

    for status in statuses:
        online = "[green]yes[/green]" if status.tailscale_online else "[red]no[/red]"
        if status.tailscale_online is None:
            online = "[yellow]-[/yellow]"
        table.add_row(
            status.vm_name,
            online,
            status.tailscale_ip or "-",
            status.last_seen or "-",
            status.os or "-",
        )

    _console.print(table)
