"""Create VM inventory command handler."""

from __future__ import annotations

import click

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.commands.vm_cmd.create_request import build_request, load_config
from vm_builder.commands.vm_cmd.output import print_create_inputs, print_create_result
from vm_builder.core.vm_service import VmService


def create_vm_inventory(config_path: str) -> None:
    """Create VM inventory in BWS from a YAML config file."""
    print_banner("Creating VM Inventory in BWS")
    service = VmService()
    ensure_vm_prerequisites(service)

    click.echo(f"Loading config: {config_path}")
    config = load_config(config_path)
    print_create_inputs(config)
    request = build_request(config)

    try:
        result = service.create_vm(request)
    except (ValueError, KeyError) as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to create VM: {exc}", err=True)
        raise click.Abort() from exc

    print_create_result(result)

