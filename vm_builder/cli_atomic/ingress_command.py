"""Registration for ``ingress`` CLI command group."""

from __future__ import annotations

import click

from vm_builder.commands.ingress import show_tailnet, validate_ingress


def register_ingress_group(root: click.Group) -> None:
    """Attach the ``ingress`` command group to the root CLI."""

    @root.group("ingress")
    def ingress() -> None:
        """Ingress configuration commands."""

    @ingress.command("validate")
    @click.option(
        "--mode",
        required=True,
        type=click.Choice(["nodeport", "tailscale", "cloudflare"]),
    )
    @click.option("--domain", default=None, help="Domain for cloudflare mode")
    def ingress_validate(mode: str, domain: str | None) -> None:
        """Validate ingress configuration."""
        validate_ingress(mode, domain)

    @ingress.command("tailnet")
    def ingress_tailnet() -> None:
        """Show Tailscale tailnet name from BWS."""
        show_tailnet()
