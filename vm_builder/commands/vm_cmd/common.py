"""Shared helpers for VM CLI command handlers."""

from __future__ import annotations

import click

from vm_builder.core.vm_service import VmService


def print_banner(title: str) -> None:
    """Print a command banner."""
    click.echo("=" * 70)
    click.echo(title)
    click.echo("=" * 70)
    click.echo()


def ensure_vm_prerequisites(service: VmService, check_gh: bool = False) -> None:
    """Abort command execution if required tooling is unavailable."""
    prereq = service.check_prerequisites(check_gh=check_gh)
    if prereq.ok:
        return
    click.echo(f"ERROR: {prereq.error}", err=True)
    raise click.Abort()

