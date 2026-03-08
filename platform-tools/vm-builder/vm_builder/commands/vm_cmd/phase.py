"""Phase trigger command handler."""

from __future__ import annotations

import click

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.core.vm_service import VmService

_PHASE_MAP = {
    "install-apps": ("3", "trigger_phase3"),
    "configure-apps": ("4", "trigger_phase4"),
    "ingress-sso": ("5", "trigger_phase5"),
}


def trigger_phase(vm_name: str, phase_name: str) -> None:
    """Trigger a deployment phase workflow for a VM."""
    phase_num, method_name = _PHASE_MAP[phase_name]
    print_banner(f"Trigger Phase {phase_num}: {phase_name} ({vm_name})")
    service = VmService()
    ensure_vm_prerequisites(service, check_gh=True)

    method = getattr(service, method_name)

    try:
        result = method(vm_name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to trigger phase {phase_num}: {exc}", err=True)
        raise click.Abort() from exc

    click.echo(f"OK: Phase {phase_num} workflow triggered")
    if result.run_url:
        click.echo(f"  Status: {result.run_status}")
        click.echo(f"  URL: {result.run_url}")
    click.echo()
    click.echo("Monitor progress:")
    click.echo("  gh run watch")
