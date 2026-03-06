"""CLI commands for live config preview and apply."""

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


def apps_preview(vm_name: str, app_id: str, as_json: bool = False) -> None:
    """Preview rendered config changes against k8s-base manifests."""
    svc = _config_service()
    result = svc.preview_changes(vm_name, app_id, svc._templates_dir)

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    click.echo(f"Preview: {app_id} on {vm_name}")
    click.echo(f"  {result['summary']}")
    click.echo()

    for diff_entry in result["diffs"]:
        if diff_entry["has_changes"]:
            click.echo(f"--- {diff_entry['file']} ---")
            click.echo(diff_entry["diff"])
        else:
            click.echo(f"  {diff_entry['file']}: no changes")


def apps_apply(
    vm_name: str,
    app_id: str,
    dry_run: bool = False,
    as_json: bool = False,
) -> None:
    """Apply rendered config to the live VM via kubectl over SSH."""
    svc = _config_service()
    result = svc.apply_live(
        vm_name, app_id, svc._templates_dir, dry_run=dry_run,
    )

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    mode = "DRY RUN" if dry_run else "APPLY"
    click.echo(f"[{mode}] {app_id} on {vm_name} ({result['hostname']})")
    click.echo(f"  Namespace: {result['namespace']}")
    click.echo(f"  {result['summary']}")
    click.echo()

    for r in result["results"]:
        icon = "OK" if r["success"] else "FAIL"
        click.echo(f"  [{icon}] {r['file']}")
        if r["output"]:
            for line in r["output"].splitlines():
                click.echo(f"    {line}")
        if r["error"]:
            for line in r["error"].splitlines():
                click.echo(click.style(f"    {line}", fg="red"))

    if not result["success"]:
        raise SystemExit(1)
