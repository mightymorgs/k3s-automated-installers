"""Show VM inventory command handler."""

from __future__ import annotations

import json

import click

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.core.vm_service import VmService


def show_vm(vm_name: str, *, as_json: bool = False) -> None:
    """Display VM inventory details or raw JSON."""
    print_banner(f"VM Details: {vm_name}")
    service = VmService()
    ensure_vm_prerequisites(service)

    try:
        inventory = service.get_vm(vm_name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: VM not found: {vm_name}", err=True)
        raise click.Abort() from exc

    if as_json:
        click.echo(json.dumps(inventory, indent=2, default=str))
        return

    identity = inventory.get("identity", {})
    hardware = inventory.get("hardware", {})
    network = inventory.get("network", {})
    apps = inventory.get("apps", {})

    click.echo("Identity:")
    click.echo(f"  Client:   {identity.get('client', '-')}")
    click.echo(f"  Platform: {identity.get('platform', '-')}")
    click.echo(f"  State:    {identity.get('state', '-')}")
    click.echo(f"  Hostname: {identity.get('hostname', '-')}")
    click.echo()

    click.echo("Hardware:")
    click.echo(f"  vCPU:      {hardware.get('vcpu', '-')}")
    click.echo(f"  Memory:    {hardware.get('memory_mb', '-')} MB")
    click.echo(f"  Disk:      {hardware.get('disk_size_gb', '-')} GB")
    click.echo()

    click.echo("Network:")
    click.echo(f"  Mode:      {network.get('network_mode', '-')}")
    click.echo(f"  Static IP: {network.get('static_ip', '-')}")
    click.echo()

    selected = apps.get("selected_apps", [])
    click.echo(f"Apps ({len(selected)}):")
    for app_id in selected:
        click.echo(f"  - {app_id}")
