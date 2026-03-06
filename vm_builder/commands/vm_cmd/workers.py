"""K3s worker node command handlers."""

from __future__ import annotations

from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.core.vm_service import VmService

_console = Console()


def list_workers(master_name: str) -> None:
    """List K3s worker nodes belonging to a master."""
    print_banner(f"K3s Workers: {master_name}")
    service = VmService()
    ensure_vm_prerequisites(service)

    try:
        all_vms = service.list_vms()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to list VMs: {exc}", err=True)
        raise click.Abort() from exc

    workers = [vm for vm in all_vms if vm.master_name == master_name]

    if not workers:
        click.echo(f"No workers found for master: {master_name}")
        return

    table = Table(title=f"Workers of {master_name} ({len(workers)})")
    table.add_column("Worker Name", style="cyan", no_wrap=True)
    table.add_column("Platform", style="blue")
    table.add_column("State", style="yellow")
    table.add_column("Apps", justify="right")
    table.add_column("Phase", justify="center")

    for vm in workers:
        table.add_row(vm.name, vm.platform, vm.state, str(vm.apps_count), vm.phase)

    _console.print(table)


def create_worker(master_name: str, config_path: str) -> None:
    """Create a K3s worker node from a YAML config."""
    print_banner(f"Create K3s Worker for: {master_name}")
    service = VmService()
    ensure_vm_prerequisites(service)

    try:
        raw = yaml.safe_load(Path(config_path).read_text())
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to load config: {exc}", err=True)
        raise click.Abort() from exc

    if not isinstance(raw, dict):
        click.echo("ERROR: Config file must define a YAML object", err=True)
        raise click.Abort()

    size = raw.get("size", "small")
    apps = raw.get("apps", [])

    try:
        result = service.create_worker(master_name, size=size, apps=apps)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to create worker: {exc}", err=True)
        raise click.Abort() from exc

    action = "Created" if result.created else "Updated"
    click.echo(f"OK: Worker {action}: {result.vm_name}")
    click.echo(f"  Inventory key: {result.inventory_key}")
    click.echo(f"  Platform: {result.platform}")
    click.echo(f"  Size: {result.size}")
    click.echo(f"  Apps: {result.apps_count}")


def persist_worker_token(master_name: str) -> None:
    """Persist K3s cluster join token from deploy workflow to BWS."""
    print_banner(f"Persist Cluster Token: {master_name}")
    service = VmService()
    ensure_vm_prerequisites(service, check_gh=True)

    try:
        result = service.persist_cluster_token(master_name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to persist token: {exc}", err=True)
        raise click.Abort() from exc

    click.echo("OK: Cluster token persisted to BWS")
    click.echo(f"  Master: {result['master_name']}")
    click.echo(f"  Server URL: {result['server_url']}")
