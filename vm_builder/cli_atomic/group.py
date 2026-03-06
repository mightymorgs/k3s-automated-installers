"""Root Click group for vm-builder CLI."""

from __future__ import annotations

import click

from vm_builder import __version__


@click.group()
@click.version_option(version=__version__)
@click.pass_context
def main(ctx: click.Context) -> None:
    """vm-builder CLI for inventory + deployment orchestration."""
    ctx.ensure_object(dict)

