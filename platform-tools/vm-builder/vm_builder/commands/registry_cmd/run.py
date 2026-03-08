"""Registry command handlers -- listing and query operations."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

_console = Console()

# Default registry path relative to the vm-builder-templates directory.
_DEFAULT_REGISTRY = "vm-builder/vm-builder-templates/registry.json"


def _find_registry_path() -> str:
    """Locate registry.json by searching upward from CWD."""
    cwd = Path.cwd()
    for candidate in [
        cwd / _DEFAULT_REGISTRY,
        cwd / "vm-builder-templates" / "registry.json",
        cwd / "registry.json",
    ]:
        if candidate.exists():
            return str(candidate)
    return _DEFAULT_REGISTRY


def _build_service():  # noqa: ANN202
    """Construct a RegistryService with default paths."""
    from vm_builder.core.registry_service import RegistryService  # noqa: PLC0415

    path = _find_registry_path()
    return RegistryService(registry_path=path)


def list_registry_apps(category: str | None, as_json: bool) -> None:
    """List available apps in the registry."""
    click.echo("=" * 70)
    click.echo("App Registry")
    click.echo("=" * 70)
    click.echo()

    service = _build_service()

    try:
        apps = service.list_apps(category=category)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    if as_json:
        click.echo(json.dumps(apps, indent=2))
        return

    if not apps:
        suffix = f" (category: {category})" if category else ""
        click.echo(f"No apps found{suffix}")
        return

    table = Table(title=f"Apps ({len(apps)} total)")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Category", style="green")
    table.add_column("Dependencies", style="yellow")

    for app in apps:
        deps = ", ".join(app.get("dependencies", [])) or "-"
        table.add_row(app.get("id", app.get("app_id", "?")), app.get("category", "?"), deps)

    _console.print(table)


def show_registry_app(app_id: str, as_json: bool) -> None:
    """Show details for a specific app."""
    click.echo("=" * 70)
    click.echo(f"App: {app_id}")
    click.echo("=" * 70)
    click.echo()

    service = _build_service()

    try:
        app = service.get_app(app_id)
    except KeyError:
        click.echo(f"ERROR: App not found: {app_id}", err=True)
        raise click.Abort()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    if as_json:
        click.echo(json.dumps(app, indent=2))
        return

    for key, value in app.items():
        if isinstance(value, list):
            click.echo(f"  {key}: {', '.join(str(v) for v in value) or '-'}")
        elif isinstance(value, dict):
            click.echo(f"  {key}:")
            for sub_key, sub_val in value.items():
                click.echo(f"    {sub_key}: {sub_val}")
        else:
            click.echo(f"  {key}: {value}")
