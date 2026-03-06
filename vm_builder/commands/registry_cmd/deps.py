"""Registry command handlers -- dependency and lifecycle operations."""

from __future__ import annotations

from pathlib import Path

import click

from vm_builder.commands.registry_cmd.run import _build_service


def resolve_registry_deps(app_ids: list[str]) -> None:
    """Resolve dependencies for a set of apps."""
    click.echo("=" * 70)
    click.echo("Dependency Resolution")
    click.echo("=" * 70)
    click.echo()

    service = _build_service()

    try:
        ordered = service.resolve_deps(app_ids)
    except KeyError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    click.echo("Install order (dependency-first):")
    for idx, app_id in enumerate(ordered, 1):
        marker = " *" if app_id in app_ids else ""
        click.echo(f"  {idx}. {app_id}{marker}")

    click.echo()
    click.echo(f"Total: {len(ordered)} apps (* = requested)")


def refresh_registry() -> None:
    """Pull git repo and regenerate registry."""
    click.echo("=" * 70)
    click.echo("Registry Refresh")
    click.echo("=" * 70)
    click.echo()

    cwd = Path.cwd()
    for candidate in [
        cwd / "vm-builder" / "vm-builder-templates",
        cwd / "vm-builder-templates",
    ]:
        if candidate.exists():
            templates_dir = str(candidate)
            break
    else:
        click.echo("ERROR: Cannot find vm-builder-templates directory", err=True)
        raise click.Abort()

    service = _build_service()

    try:
        registry = service.refresh(templates_dir=templates_dir)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    app_count = len(registry.get("apps", {}))
    click.echo(f"OK: Registry refreshed ({app_count} apps)")


def check_installable(app_id: str, installed: list[str]) -> None:
    """Check if an app can be installed given current state."""
    click.echo("=" * 70)
    click.echo(f"Installability Check: {app_id}")
    click.echo("=" * 70)
    click.echo()

    service = _build_service()

    try:
        result = service.check_installable(app_id, installed)
    except KeyError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: {exc}", err=True)
        raise click.Abort() from exc

    if result["installable"]:
        click.echo(f"OK: {app_id} is installable")
    else:
        click.echo(f"BLOCKED: {app_id} has unmet dependencies:")
        for dep in result["missing_deps"]:
            click.echo(f"  - {dep}")

    if result["all_deps"]:
        click.echo()
        click.echo("Full dependency chain:")
        for dep in result["all_deps"]:
            click.echo(f"  - {dep}")
