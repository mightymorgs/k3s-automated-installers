"""Main hypervisor bootstrap command handler."""

from __future__ import annotations

import click

from vm_builder.commands.hypervisor_cmd.prompts import resolve_hypervisor_config
from vm_builder.core.hypervisor_service import HypervisorService


def generate_bootstrap_script(
    name: str,
    output: str,
    local_ip: str | None = None,
    github_repo: str | None = None,
    network_mode: str | None = None,
    platform: str | None = None,
    location: str | None = None,
) -> None:
    """Generate and write a hypervisor bootstrap script."""
    click.echo("=" * 70)
    click.echo("Generating Hypervisor Bootstrap Script")
    click.echo("=" * 70)

    service = HypervisorService()
    prereq = service.check_prerequisites()
    if not prereq.ok:
        click.echo(f"ERROR: {prereq.error}", err=True)
        raise click.Abort()

    config = resolve_hypervisor_config(
        name=name,
        local_ip=local_ip,
        github_repo=github_repo,
        network_mode=network_mode,
        platform=platform,
        location=location,
    )

    try:
        result = service.generate_bootstrap_script(config)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    output_path = service.write_bootstrap_script(result, output)
    click.echo(f"OK: Bootstrap script generated: {output_path}")

