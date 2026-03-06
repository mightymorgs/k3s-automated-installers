"""Registration for ``registry`` CLI command group."""

from __future__ import annotations

import json
from pathlib import Path

import click

from vm_builder.commands.registry import (
    check_installable,
    list_registry_apps,
    refresh_registry,
    resolve_registry_deps,
    show_registry_app,
)
from vm_builder.core.registry_generator import generate_registry, write_registry


def register_registry_group(root: click.Group) -> None:
    """Attach the ``registry`` command group to the root CLI."""

    @root.group("registry")
    def registry() -> None:
        """App registry commands."""

    @registry.command("generate")
    @click.option(
        "--repo-root",
        required=True,
        type=click.Path(exists=True),
        help="Path to templates root",
    )
    @click.option("--output", "-o", default=None, help="Output JSON file path")
    @click.option(
        "--path-prefix",
        default=None,
        help="Prefix for generated paths (defaults to repo-root directory name)",
    )
    def registry_generate(
        repo_root: str,
        output: str | None,
        path_prefix: str | None,
    ) -> None:
        """Generate app registry from playbook metadata."""
        templates_dir = Path(repo_root)
        # Use the full relative path as prefix so registry paths match repo layout.
        # e.g. --repo-root vm-builder/vm-builder-templates → prefix "vm-builder/vm-builder-templates"
        if path_prefix:
            prefix = path_prefix
        elif templates_dir.is_absolute():
            prefix = templates_dir.name
        else:
            prefix = str(templates_dir)

        registry_doc = generate_registry(templates_dir, path_prefix=prefix)
        app_count = len(registry_doc.get("apps", {}))

        if output:
            write_registry(registry_doc, Path(output))
            click.echo(f"Registry written to {output} ({app_count} apps)")
            return

        click.echo(json.dumps(registry_doc, indent=2))

    @registry.command("list")
    @click.option("--category", default=None, help="Filter by category")
    @click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
    def registry_list(category: str | None, as_json: bool) -> None:
        """List available apps in the registry."""
        list_registry_apps(category, as_json)

    @registry.command("show")
    @click.argument("app_id")
    @click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
    def registry_show(app_id: str, as_json: bool) -> None:
        """Show details for a specific app."""
        show_registry_app(app_id, as_json)

    @registry.command("resolve-deps")
    @click.argument("app_ids", nargs=-1, required=True)
    def registry_resolve(app_ids: tuple[str, ...]) -> None:
        """Resolve dependencies for a set of apps."""
        resolve_registry_deps(list(app_ids))

    @registry.command("refresh")
    def registry_refresh_cmd() -> None:
        """Pull git repo and regenerate registry."""
        refresh_registry()

    @registry.command("installable")
    @click.argument("app_id")
    @click.option("--installed", multiple=True, help="Already installed app IDs")
    def registry_installable(app_id: str, installed: tuple[str, ...]) -> None:
        """Check if an app can be installed given current state."""
        check_installable(app_id, list(installed))
