"""Ingress command handlers."""

from __future__ import annotations

import click

from vm_builder.core.models import IngressValidateResult
from vm_builder.core.vm_service import VmService


def validate_ingress(mode: str, domain: str | None) -> None:
    """Validate ingress configuration for a given mode."""
    click.echo("=" * 70)
    click.echo(f"Validate Ingress: mode={mode}")
    click.echo("=" * 70)
    click.echo()

    service = VmService()

    try:
        result: IngressValidateResult = service.validate_ingress(
            mode=mode, domain=domain,
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    if result.valid:
        click.echo(f"OK: Ingress mode '{mode}' is valid")
        for warning in result.warnings:
            click.echo(f"  WARNING: {warning}")
    else:
        click.echo(f"FAIL: {result.error}", err=True)
        raise click.Abort()


def show_tailnet() -> None:
    """Read and display the Tailscale tailnet name from BWS."""
    click.echo("=" * 70)
    click.echo("Tailscale Tailnet")
    click.echo("=" * 70)
    click.echo()

    from vm_builder import bws  # noqa: PLC0415 — lazy import

    try:
        tailnet = bws.get_secret("inventory/shared/secrets/tailscale/tailnet")
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to read tailnet: {exc}", err=True)
        raise click.Abort() from exc

    click.echo(f"Tailnet: {tailnet}")
