"""Output helpers for validate command."""

from __future__ import annotations

import click


def print_validation_success(inventory: dict) -> None:
    """Render successful validation details."""
    click.echo("=" * 70)
    click.echo("OK: VALIDATION PASSED")
    click.echo("=" * 70)
    click.echo()
    click.echo("Inventory Details:")
    click.echo(f"  Schema Version: {inventory.get('schema_version')}")
    click.echo(f"  Hostname: {inventory.get('identity', {}).get('hostname')}")
    click.echo(f"  Client: {inventory.get('identity', {}).get('client')}")
    click.echo(f"  Platform: {inventory.get('identity', {}).get('platform')}")
    click.echo(f"  K3s Role: {inventory.get('k3s', {}).get('role')}")
    click.echo(f"  Selected Apps: {len(inventory.get('apps', {}).get('selected_apps', []))}")

    state = inventory.get("_state", {})
    if state:
        click.echo()
        click.echo("Runtime State (_state):")
        phase_completed = state.get("bootstrap", {}).get("phase_completed")
        if phase_completed:
            click.echo(f"  Phase Completed: {phase_completed}")
        ts_ipv4 = state.get("tailscale", {}).get("ipv4")
        if ts_ipv4:
            click.echo(f"  Tailscale IPv4: {ts_ipv4}")
        k3s_version = state.get("k3s", {}).get("version")
        if k3s_version:
            click.echo(f"  K3s Version: {k3s_version}")
    click.echo()


def print_validation_failure(errors: list[str]) -> None:
    """Render validation failure details."""
    click.echo("=" * 70)
    click.echo("ERROR: VALIDATION FAILED")
    click.echo("=" * 70)
    click.echo()
    click.echo(f"Found {len(errors)} error(s):")
    for index, error in enumerate(errors, start=1):
        click.echo(f"  {index}. {error}")
    click.echo()

