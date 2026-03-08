"""Update VM inventory command handler."""

from __future__ import annotations

from pathlib import Path

import click
import yaml

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.core.models import VmUpdateRequest
from vm_builder.core.vm_service import VmService


def update_vm(vm_name: str, config_path: str) -> None:
    """Update VM inventory in BWS from a YAML config file."""
    print_banner(f"Update VM Inventory: {vm_name}")
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

    request = VmUpdateRequest(**raw)

    try:
        result = service.update_vm(vm_name, request)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to update VM: {exc}", err=True)
        raise click.Abort() from exc

    if not result.updated:
        click.echo("No changes detected.")
        return

    click.echo("Updated fields:")
    for field, diff in result.changes.items():
        click.echo(f"  {field}: {diff.get('old')} -> {diff.get('new')}")

    for warning in result.warnings:
        click.echo(f"  WARNING: {warning}", err=True)

    click.echo()
    click.echo(f"OK: VM inventory updated: {vm_name}")
