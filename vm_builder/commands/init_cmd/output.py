"""Output helpers for init command."""

from __future__ import annotations

import click

from vm_builder.core.models import SecretWriteStatus, SharedSecrets


def print_banner() -> None:
    """Print init command banner."""
    click.echo("=" * 70)
    click.echo("vm-builder: Shared Secrets Initialization")
    click.echo("=" * 70)
    click.echo()


def print_summary(secrets: SharedSecrets) -> None:
    """Print summary of secret keys to be written."""
    bws_map = secrets.to_bws_dict()
    paths = list(bws_map.keys())
    click.echo()
    click.echo("=" * 70)
    click.echo("SUMMARY")
    click.echo("=" * 70)
    for path in paths:
        click.echo(f"  - {path}")
    click.echo(f"\nTotal: {len(paths)} secrets")


def print_results(results: list) -> None:
    """Print secret write status lines."""
    click.echo()
    for result in results:
        if result.status == SecretWriteStatus.CREATED:
            click.echo(f"  OK Created: {result.path}")
        elif result.status == SecretWriteStatus.UPDATED:
            click.echo(f"  OK Updated: {result.path}")
        elif result.status == SecretWriteStatus.SKIPPED:
            click.echo(f"  Skip: {result.path}")
        elif result.status == SecretWriteStatus.ERROR:
            click.echo(f"  ERROR: {result.path} - {result.error}")
    click.echo()
    click.echo("OK: Shared secrets initialized successfully")
