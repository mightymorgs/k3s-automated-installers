"""Output formatting helpers for VM CLI command handlers."""

from __future__ import annotations

from typing import Any

import click
from rich.console import Console
from rich.table import Table

from vm_builder.core.workflow_names import WorkflowNames

_console = Console()


def print_create_inputs(config: dict[str, Any]) -> None:
    """Print key VM create inputs."""
    click.echo(f"  VM Name: {config['vm_name']}")
    click.echo(f"  Size: {config['size']}")
    click.echo(f"  Platform: {config['platform']}")
    click.echo()


def print_create_result(result: Any) -> None:
    """Print VM create success details."""
    action = "Created" if result.created else "Updated"
    click.echo()
    click.echo("=" * 70)
    click.echo(f"OK: VM Inventory {action}: {result.inventory_key}")
    click.echo("=" * 70)
    click.echo()
    click.echo("Inventory Details:")
    click.echo(f"  VM: {result.vm_name}")
    click.echo(f"  Client: {result.client}")
    click.echo(f"  Platform: {result.platform}")
    click.echo(f"  Size: {result.size}")
    click.echo(f"  K3s Role: {result.k3s_role}")
    click.echo(f"  Selected Apps: {result.apps_count} apps")
    click.echo()
    click.echo("Next steps:")
    click.echo(f"  1. Trigger deploy: gh workflow run {WorkflowNames.PHASE2_PROVISION_VM}")
    click.echo("  2. Watch deployment: gh run watch")
    click.echo("  3. Phases 2.5 -> 3 -> 4 -> 5 auto-execute")
    click.echo()


def print_vm_list(vms: list[Any], client_filter: str | None = None) -> None:
    """Render VM list as a Rich table."""
    if not vms:
        suffix = f" (client: {client_filter})" if client_filter else ""
        click.echo(f"No VMs found{suffix}")
        return

    table = Table(title=f"VM Inventories ({len(vms)} total)")
    table.add_column("VM Name", style="cyan", no_wrap=True)
    table.add_column("Client", style="green")
    table.add_column("Platform", style="blue")
    table.add_column("State", style="yellow")
    table.add_column("Apps", justify="right")
    table.add_column("Phase", justify="center")

    for vm in vms:
        table.add_row(
            vm.name,
            vm.client,
            vm.platform,
            vm.state,
            str(vm.apps_count),
            vm.phase,
        )

    _console.print(table)


def print_delete_preview(vm_name: str, inventory: dict[str, Any]) -> None:
    """Print inventory summary before delete confirmation."""
    click.echo("VM Inventory to Delete:")
    click.echo(f"  Name: {vm_name}")
    click.echo(f"  Client: {inventory.get('identity', {}).get('client', 'unknown')}")
    click.echo(f"  Platform: {inventory.get('identity', {}).get('platform', 'unknown')}")
    click.echo(f"  State: {inventory.get('identity', {}).get('state', 'unknown')}")
    click.echo(f"  Apps: {len(inventory.get('apps', {}).get('selected_apps', []))}")
    click.echo()
    click.echo("WARNING: This does NOT destroy actual VM resources.")
    click.echo("  Run terraform destroy on the hypervisor separately.")
    click.echo()


def print_deploy_result(result: Any) -> None:
    """Print deploy workflow trigger result."""
    click.echo("OK: Workflow triggered successfully")
    if result.run_url:
        click.echo(f"  Status: {result.run_status}")
        click.echo(f"  URL: {result.run_url}")
    click.echo()
    click.echo("Monitor progress:")
    click.echo("  gh run watch")
    click.echo()

