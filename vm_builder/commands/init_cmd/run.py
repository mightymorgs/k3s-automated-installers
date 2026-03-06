"""Main init command handler."""

from __future__ import annotations

from typing import Optional

import click

from vm_builder.commands.init_cmd.config import load_config
from vm_builder.commands.init_cmd.output import print_banner, print_results, print_summary
from vm_builder.commands.init_cmd.prompts import collect_shared_secrets
from vm_builder.core.init_service import InitService


def init_shared_secrets(config_path: Optional[str]) -> None:
    """Initialize shared secrets in BWS."""
    print_banner()
    service = InitService()

    prereq = service.check_prerequisites()
    if not prereq.ok:
        click.echo(f"ERROR: {prereq.error}", err=True)
        raise click.Abort()

    config = load_config(config_path)
    secrets = collect_shared_secrets(config)
    print_summary(secrets)

    if not click.confirm("Proceed with creation?", default=True):
        raise click.Abort()

    overwrite = click.confirm("Overwrite existing secrets?", default=False)
    results = service.write_secrets(secrets, overwrite=overwrite)
    print_results(results)

