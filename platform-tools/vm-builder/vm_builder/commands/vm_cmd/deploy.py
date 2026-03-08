"""Deploy VM command handler."""

from __future__ import annotations

import click

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.commands.vm_cmd.output import print_deploy_result
from vm_builder.core.vm_service import VmService


def deploy_vm(vm_name: str, hypervisor_key: str | None = None) -> None:
    """Trigger VM deploy workflow for a VM inventory."""
    print_banner(f"Deploy VM: {vm_name}")
    service = VmService()
    ensure_vm_prerequisites(service, check_gh=True)

    try:
        result = service.deploy_vm(vm_name, hypervisor_key)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to deploy: {exc}", err=True)
        raise click.Abort() from exc

    print_deploy_result(result)

