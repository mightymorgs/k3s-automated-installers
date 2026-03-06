"""Registration for the ``init`` CLI command group."""

from __future__ import annotations

import click

from vm_builder.commands.init import init_shared_secrets, show_init_status


def register_init_group(root: click.Group) -> None:
    """Attach the ``init`` command group to the root CLI."""

    @root.group("init")
    def init() -> None:
        """Shared secrets initialization."""

    @init.command("secrets")
    @click.option(
        "--config",
        type=click.Path(exists=True),
        help="Path to shared secrets YAML config",
    )
    def init_secrets(config: str | None) -> None:
        """Initialize shared secrets in BWS."""
        init_shared_secrets(config)

    @init.command("status")
    def init_status() -> None:
        """Check which shared secrets are configured."""
        show_init_status()
