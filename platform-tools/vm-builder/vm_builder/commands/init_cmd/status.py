"""Init status command handler."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from vm_builder.core.init_service import InitService

_console = Console()


def show_init_status() -> None:
    """Check which shared secrets are configured in BWS."""
    click.echo("=" * 70)
    click.echo("Shared Secrets Status")
    click.echo("=" * 70)
    click.echo()

    service = InitService()
    prereq = service.check_prerequisites()
    if not prereq.ok:
        click.echo(f"ERROR: {prereq.error}", err=True)
        raise click.Abort()

    try:
        statuses = service.get_existing_secrets()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    table = Table(title="Shared Secret Paths")
    table.add_column("Path", style="cyan", no_wrap=True)
    table.add_column("Status", style="bold")

    configured = 0
    for status in statuses:
        if status.exists:
            table.add_row(status.path, "[green]configured[/green]")
            configured += 1
        else:
            table.add_row(status.path, "[red]missing[/red]")

    _console.print(table)
    click.echo()
    click.echo(f"Configured: {configured}/{len(statuses)}")

    if configured < len(statuses):
        click.echo("Run 'vm-builder init secrets' to configure missing secrets.")
