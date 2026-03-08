"""CLI commands for per-app config management."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from vm_builder.core.config_service import ConfigService
from vm_builder.core.vm_service import VmService


def _config_service() -> ConfigService:
    """Build ConfigService for CLI use."""
    tpl_dir = os.environ.get("TEMPLATES_DIR")
    return ConfigService(
        vm_service=VmService(),
        templates_dir=Path(tpl_dir) if tpl_dir else None,
    )


def config_get(vm_name: str, app_id: str, as_json: bool = False) -> None:
    """Show current config for an app."""
    svc = _config_service()
    result = svc.get_app_config(vm_name, app_id, svc._templates_dir)

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    config = result["config"]
    overrides = result["overrides"]
    defaults = result["defaults"]

    click.echo(f"Config for {app_id} on {vm_name}:")
    click.echo(f"  Fields: {len(config)}, Overrides: {len(overrides)}")
    click.echo()

    for key in sorted(config):
        marker = " *" if key in overrides else ""
        default = defaults.get(key)
        value = config[key]
        line = f"  {key}: {value}{marker}"
        if default is not None and str(value) != str(default):
            line += f"  (default: {default})"
        click.echo(line)

    if overrides:
        click.echo()
        click.echo("  * = user override")


def config_set(vm_name: str, app_id: str, field: str, value: str) -> None:
    """Set a config field for an app."""
    svc = _config_service()
    result = svc.update_field(vm_name, app_id, field, value)
    click.echo(f"Updated {app_id}.{field} = {value}")


def config_reset(vm_name: str, app_id: str, field: str) -> None:
    """Reset a config field to its default."""
    svc = _config_service()
    result = svc.reset_field(vm_name, app_id, field, svc._templates_dir)
    default_val = result.get("reset_to")
    click.echo(f"Reset {app_id}.{field} to default: {default_val}")


def config_list(vm_name: str) -> None:
    """Show all apps with override counts."""
    svc = _config_service()
    result = svc.get_all_overrides(vm_name)

    click.echo(f"Config overrides for {vm_name}:")
    click.echo()

    apps = result["apps"]
    if not apps:
        click.echo("  No apps configured.")
        return

    for app_id in sorted(apps):
        info = apps[app_id]
        count = info["override_count"]
        total = info["config_field_count"]
        marker = f" ({count} overrides)" if count else ""
        click.echo(f"  {app_id}: {total} fields{marker}")
