"""Registration for ``vm`` CLI command group."""

from __future__ import annotations

import click

from vm_builder.commands.vm import (
    configure_app,
    create_vm_inventory,
    create_worker,
    delete_vm_inventory,
    deploy_vm,
    destroy_vm,
    install_apps,
    list_apps,
    list_vms,
    list_workers,
    persist_worker_token,
    regenerate_keypair,
    show_vm,
    show_vm_health,
    trigger_phase,
    uninstall_app,
    update_vm,
)
from vm_builder.commands.vm_cmd.apply_commands import (
    apps_apply,
    apps_preview,
)
from vm_builder.commands.vm_cmd.config_commands import (
    config_get,
    config_list,
    config_reset,
    config_set,
)


def register_vm_group(root: click.Group) -> None:
    """Attach the ``vm`` command group to the root CLI."""

    @root.group("vm")
    def vm() -> None:
        """VM inventory management commands."""

    # --- Core CRUD commands ---

    @vm.command("create")
    @click.option(
        "--config",
        required=True,
        type=click.Path(exists=True),
        help="Path to VM config YAML",
    )
    def vm_create(config: str) -> None:
        """Create VM inventory in BWS from config file."""
        create_vm_inventory(config)

    @vm.command("list")
    @click.option("--client", help="Filter by client name")
    def vm_list(client: str | None) -> None:
        """List existing VMs in BWS."""
        list_vms(client)

    @vm.command("show")
    @click.argument("vm_name")
    @click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
    def vm_show(vm_name: str, as_json: bool) -> None:
        """Show VM inventory details."""
        show_vm(vm_name, as_json=as_json)

    @vm.command("update")
    @click.argument("vm_name")
    @click.option(
        "--config",
        required=True,
        type=click.Path(exists=True),
        help="Updated config YAML",
    )
    def vm_update(vm_name: str, config: str) -> None:
        """Update VM inventory in BWS."""
        update_vm(vm_name, config)

    @vm.command("delete")
    @click.argument("vm_name")
    def vm_delete(vm_name: str) -> None:
        """Delete VM inventory from BWS."""
        delete_vm_inventory(vm_name)

    @vm.command("deploy")
    @click.argument("vm_name")
    @click.option("--hypervisor", help="Hypervisor inventory key")
    def vm_deploy(vm_name: str, hypervisor: str | None) -> None:
        """Deploy VM by triggering the provision workflow."""
        deploy_vm(vm_name, hypervisor)

    @vm.command("destroy")
    @click.argument("vm_name")
    def vm_destroy(vm_name: str) -> None:
        """Destroy VM infrastructure (tear down hypervisor resources)."""
        destroy_vm(vm_name)

    @vm.command("regenerate-keypair")
    @click.argument("vm_name")
    def vm_regenerate_keypair(vm_name: str) -> None:
        """Regenerate SSH keypair for a VM."""
        regenerate_keypair(vm_name)

    @vm.command("health")
    def vm_health() -> None:
        """Show Tailscale health status for all VMs."""
        show_vm_health()

    # --- Phase subgroup ---

    @vm.group("phase")
    def phase() -> None:
        """Trigger deployment phases."""

    @phase.command("install-apps")
    @click.argument("vm_name")
    def phase_install(vm_name: str) -> None:
        """Trigger Phase 3: install selected apps."""
        trigger_phase(vm_name, "install-apps")

    @phase.command("configure-apps")
    @click.argument("vm_name")
    def phase_configure(vm_name: str) -> None:
        """Trigger Phase 4: configure installed apps."""
        trigger_phase(vm_name, "configure-apps")

    @phase.command("ingress-sso")
    @click.argument("vm_name")
    def phase_ingress(vm_name: str) -> None:
        """Trigger Phase 5: deploy ingress and SSO."""
        trigger_phase(vm_name, "ingress-sso")

    # --- Apps subgroup ---

    @vm.group("apps")
    def apps() -> None:
        """App management commands."""

    @apps.command("list")
    @click.argument("vm_name")
    def apps_list(vm_name: str) -> None:
        """List installed apps on a VM."""
        list_apps(vm_name)

    @apps.command("install")
    @click.argument("vm_name")
    @click.argument("app_ids", nargs=-1, required=True)
    @click.option("--skip-deps", is_flag=True, help="Skip dependency resolution")
    def apps_install(
        vm_name: str, app_ids: tuple[str, ...], skip_deps: bool
    ) -> None:
        """Install apps on a VM (with dependency resolution)."""
        install_apps(vm_name, list(app_ids), skip_deps=skip_deps)

    @apps.command("configure")
    @click.argument("vm_name")
    @click.argument("app_id")
    def apps_configure(vm_name: str, app_id: str) -> None:
        """Configure a single app on a VM."""
        configure_app(vm_name, app_id)

    @apps.command("uninstall")
    @click.argument("vm_name")
    @click.argument("app_id")
    def apps_uninstall(vm_name: str, app_id: str) -> None:
        """Uninstall an app from a VM."""
        uninstall_app(vm_name, app_id)

    @apps.command("preview")
    @click.argument("vm_name")
    @click.argument("app_id")
    @click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
    def apps_preview_cmd(vm_name: str, app_id: str, as_json: bool) -> None:
        """Preview rendered config changes for an app."""
        apps_preview(vm_name, app_id, as_json=as_json)

    @apps.command("apply")
    @click.argument("vm_name")
    @click.argument("app_id")
    @click.option("--preview", "dry_run", is_flag=True, help="Dry-run mode")
    @click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
    def apps_apply_cmd(
        vm_name: str, app_id: str, dry_run: bool, as_json: bool
    ) -> None:
        """Apply rendered config to the live VM via kubectl."""
        apps_apply(vm_name, app_id, dry_run=dry_run, as_json=as_json)

    # --- Config subgroup ---

    @apps.group("config")
    def config() -> None:
        """Per-app config field management."""

    @config.command("get")
    @click.argument("vm_name")
    @click.argument("app_id")
    @click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
    def config_get_cmd(vm_name: str, app_id: str, as_json: bool) -> None:
        """Show current config for an app."""
        config_get(vm_name, app_id, as_json=as_json)

    @config.command("set")
    @click.argument("vm_name")
    @click.argument("app_id")
    @click.argument("field")
    @click.argument("value")
    def config_set_cmd(vm_name: str, app_id: str, field: str, value: str) -> None:
        """Set a config field for an app."""
        config_set(vm_name, app_id, field, value)

    @config.command("reset")
    @click.argument("vm_name")
    @click.argument("app_id")
    @click.argument("field")
    def config_reset_cmd(vm_name: str, app_id: str, field: str) -> None:
        """Reset a config field to its default."""
        config_reset(vm_name, app_id, field)

    @config.command("list")
    @click.argument("vm_name")
    def config_list_cmd(vm_name: str) -> None:
        """Show all apps with override counts."""
        config_list(vm_name)

    # --- Workers subgroup ---

    @vm.group("workers")
    def workers() -> None:
        """K3s worker node management."""

    @workers.command("list")
    @click.argument("master_name")
    def workers_list(master_name: str) -> None:
        """List K3s worker nodes."""
        list_workers(master_name)

    @workers.command("create")
    @click.argument("master_name")
    @click.option(
        "--config",
        required=True,
        type=click.Path(exists=True),
        help="Worker config YAML",
    )
    def workers_create(master_name: str, config: str) -> None:
        """Create a new K3s worker node."""
        create_worker(master_name, config)

    @workers.command("persist-token")
    @click.argument("master_name")
    def workers_persist_token(master_name: str) -> None:
        """Persist K3s cluster join token to BWS."""
        persist_worker_token(master_name)
