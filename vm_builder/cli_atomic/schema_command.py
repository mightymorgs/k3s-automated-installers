"""Registration for ``schema`` CLI command group."""

from __future__ import annotations

import click

from vm_builder.commands.schema import (
    show_platforms,
    show_resource_defaults,
    show_sizes,
    validate_name,
)


def register_schema_group(root: click.Group) -> None:
    """Attach the ``schema`` command group to the root CLI."""

    @root.group("schema")
    def schema_group() -> None:
        """Schema and validation commands."""

    @schema_group.command("sizes")
    @click.option("--platform", default=None, help="Filter by platform")
    @click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
    def schema_sizes(platform: str | None, as_json: bool) -> None:
        """List VM size presets."""
        show_sizes(platform, as_json)

    @schema_group.command("platforms")
    def schema_platforms() -> None:
        """List supported platforms."""
        show_platforms()

    @schema_group.command("validate-name")
    @click.argument("name")
    def schema_validate_name(name: str) -> None:
        """Validate a VM name format."""
        validate_name(name)

    @schema_group.command("resource-defaults")
    def schema_resource_defaults() -> None:
        """Show resource requirements by category."""
        show_resource_defaults()
