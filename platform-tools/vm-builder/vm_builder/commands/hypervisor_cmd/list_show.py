"""Hypervisor list and show command handlers."""

from __future__ import annotations

import json

import click
from rich.console import Console
from rich.table import Table

from vm_builder.core.hypervisor_service import HypervisorService

_console = Console()


def list_hypervisors() -> None:
    """List all known hypervisors from BWS."""
    click.echo("=" * 70)
    click.echo("Known Hypervisors")
    click.echo("=" * 70)
    click.echo()

    service = HypervisorService()
    prereq = service.check_prerequisites()
    if not prereq.ok:
        click.echo(f"ERROR: {prereq.error}", err=True)
        raise click.Abort()

    try:
        hypervisors = service.list_hypervisors()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    if not hypervisors:
        click.echo("No hypervisors found.")
        return

    table = Table(title=f"Hypervisors ({len(hypervisors)} total)")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Client", style="green")
    table.add_column("Platform", style="blue")
    table.add_column("State", style="yellow")
    table.add_column("Location", style="magenta")
    table.add_column("Phase0", justify="center")
    table.add_column("Ready", justify="center")

    for hyp in hypervisors:
        phase0 = "[green]yes[/green]" if hyp.phase0_completed else "[red]no[/red]"
        ready = "[green]yes[/green]" if hyp.ready_for_phase2 else "[red]no[/red]"
        table.add_row(
            hyp.name,
            hyp.client,
            hyp.platform,
            hyp.state,
            hyp.location,
            phase0,
            ready,
        )

    _console.print(table)


def show_hypervisor(name: str, as_json: bool) -> None:
    """Show details for a specific hypervisor."""
    click.echo("=" * 70)
    click.echo(f"Hypervisor: {name}")
    click.echo("=" * 70)
    click.echo()

    service = HypervisorService()
    prereq = service.check_prerequisites()
    if not prereq.ok:
        click.echo(f"ERROR: {prereq.error}", err=True)
        raise click.Abort()

    try:
        inventory = service.get_hypervisor(name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    if as_json:
        click.echo(json.dumps(inventory, indent=2))
        return

    _print_inventory(inventory)


def _print_inventory(inventory: dict) -> None:
    """Print hypervisor inventory in human-readable form."""
    for section, data in inventory.items():
        if isinstance(data, dict):
            click.echo(f"  {section}:")
            for key, value in data.items():
                # Never print secret values
                if "secret" in key.lower() or "token" in key.lower():
                    click.echo(f"    {key}: ****")
                else:
                    click.echo(f"    {key}: {value}")
        else:
            click.echo(f"  {section}: {data}")
