"""App management command handlers."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from vm_builder.commands.vm_cmd.common import ensure_vm_prerequisites, print_banner
from vm_builder.core.app_install_service import AppInstallService
from vm_builder.core.models import AppConfigureRequest, BatchAppInstallRequest
from vm_builder.core.registry_service import RegistryService
from vm_builder.core.vm_service import VmService

_console = Console()


def _build_services() -> tuple[VmService, AppInstallService]:
    """Instantiate the service stack for app operations."""
    vm_svc = VmService()
    registry = RegistryService(
        registry_path="vm-builder/vm-builder-templates/registry.json",
    )
    app_svc = AppInstallService(registry=registry, vm_service=vm_svc)
    return vm_svc, app_svc


def list_apps(vm_name: str) -> None:
    """List installed apps on a VM."""
    print_banner(f"Installed Apps: {vm_name}")
    vm_svc, app_svc = _build_services()
    ensure_vm_prerequisites(vm_svc)

    try:
        apps = app_svc.list_installed_apps(vm_name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to list apps: {exc}", err=True)
        raise click.Abort() from exc

    if not apps:
        click.echo("No installed apps found.")
        return

    table = Table(title=f"Installed Apps ({len(apps)})")
    table.add_column("App ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="green")
    table.add_column("Category", style="blue")
    table.add_column("Status", justify="center")

    for app in apps:
        table.add_row(app.app_id, app.display_name or "-", app.category or "-", app.status.value)

    _console.print(table)


def install_apps(vm_name: str, app_ids: list[str], *, skip_deps: bool = False) -> None:
    """Install apps on a VM with optional dependency resolution."""
    print_banner(f"Install Apps: {vm_name}")
    vm_svc, app_svc = _build_services()
    ensure_vm_prerequisites(vm_svc, check_gh=True)

    request = BatchAppInstallRequest(apps=app_ids)
    click.echo(f"Apps to install: {', '.join(app_ids)}")

    try:
        result = app_svc.install_apps(vm_name, request)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to install apps: {exc}", err=True)
        raise click.Abort() from exc

    if not result.apps_to_install:
        click.echo("All requested apps are already installed.")
        return

    click.echo(f"Installed: {', '.join(result.apps_to_install)}")
    for status in result.statuses:
        icon = "OK" if not status.error else "FAIL"
        click.echo(f"  [{icon}] {status.app_id}: {status.status.value}")
        if status.error:
            click.echo(f"         {status.error}", err=True)


def configure_app(vm_name: str, app_id: str) -> None:
    """Configure a single app on a VM."""
    print_banner(f"Configure App: {app_id} on {vm_name}")
    vm_svc = VmService()
    ensure_vm_prerequisites(vm_svc, check_gh=True)

    request = AppConfigureRequest(vm_name=vm_name, app_id=app_id, config={})

    try:
        result = vm_svc.configure_app(request)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to configure app: {exc}", err=True)
        raise click.Abort() from exc

    click.echo("OK: Configure workflow triggered")
    if result.run_url:
        click.echo(f"  Status: {result.run_status}")
        click.echo(f"  URL: {result.run_url}")


def uninstall_app(vm_name: str, app_id: str) -> None:
    """Uninstall an app from a VM inventory."""
    print_banner(f"Uninstall App: {app_id} from {vm_name}")
    vm_svc, app_svc = _build_services()
    ensure_vm_prerequisites(vm_svc)

    if not click.confirm(
        f"Remove '{app_id}' from VM '{vm_name}' inventory?",
        default=False,
    ):
        raise click.Abort()

    try:
        result = app_svc.uninstall_app(vm_name, app_id)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to uninstall app: {exc}", err=True)
        raise click.Abort() from exc

    click.echo(f"OK: {result.message}")
    if result.k8s_resources_remain:
        click.echo("  NOTE: K8s resources still remain on the cluster.")
