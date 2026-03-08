"""Storage command handlers."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from vm_builder.core.hypervisor_service import HypervisorService
from vm_builder.core.models import StorageVerifyRequest
from vm_builder.core.storage_service import StorageService

_console = Console()


def _build_service() -> StorageService:
    """Construct a StorageService with hypervisor resolver."""
    hyp = HypervisorService()
    return StorageService(hypervisor_resolver=hyp.get_hypervisor)


def list_mounts(hypervisor_name: str) -> None:
    """Detect and display NFS/SMB mounts on a hypervisor."""
    click.echo("=" * 70)
    click.echo(f"Storage Mounts: {hypervisor_name}")
    click.echo("=" * 70)
    click.echo()

    service = _build_service()

    try:
        mounts = service.detect_mounts(hypervisor_name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    if not mounts:
        click.echo("No NFS/SMB mounts detected.")
        return

    table = Table(title=f"Detected Mounts ({len(mounts)} total)")
    table.add_column("Type", style="cyan", no_wrap=True)
    table.add_column("Source", style="green")
    table.add_column("Mount Point", style="blue")
    table.add_column("Options", style="yellow")

    for mount in mounts:
        table.add_row(
            mount.mount_type,
            mount.source,
            mount.mount_point,
            mount.options or "",
        )

    _console.print(table)


def browse_path(hypervisor_name: str, path: str) -> None:
    """Browse a remote directory on a hypervisor."""
    click.echo("=" * 70)
    click.echo(f"Browse: {hypervisor_name}:{path}")
    click.echo("=" * 70)
    click.echo()

    service = _build_service()

    try:
        result = service.browse_path(hypervisor_name, path)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    if not result.entries:
        click.echo("Directory is empty.")
        return

    for entry in result.entries:
        suffix = "/" if entry.get("entry_type") == "dir" else ""
        click.echo(f"  {entry['name']}{suffix}")

    click.echo()
    click.echo(f"Total: {len(result.entries)} entries")


def verify_storage(mount_type: str, source: str, mount_point: str) -> None:
    """Verify storage mount accessibility."""
    click.echo("=" * 70)
    click.echo(f"Verify Storage: {mount_type}://{source}")
    click.echo("=" * 70)
    click.echo()

    service = _build_service()
    request = StorageVerifyRequest(
        hypervisor_name="local",
        mount_type=mount_type,
        source=source,
    )

    try:
        result = service.verify_storage(request)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    if result.accessible:
        click.echo(f"OK: {mount_type} storage is accessible")
        if result.mount_point:
            click.echo(f"  Mount point: {result.mount_point}")
    else:
        click.echo(f"FAIL: Storage not accessible: {result.error}", err=True)
        raise click.Abort()
