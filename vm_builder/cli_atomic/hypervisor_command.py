"""Registration for ``hypervisor`` CLI command group."""

from __future__ import annotations

import click

from vm_builder.commands.hypervisor import (
    generate_bootstrap_script,
    list_hypervisors,
    show_hypervisor,
)


def register_hypervisor_group(root: click.Group) -> None:
    """Attach the ``hypervisor`` command group to the root CLI."""

    @root.group("hypervisor")
    def hypervisor() -> None:
        """Hypervisor management commands."""

    @hypervisor.command("bootstrap")
    @click.option("--name", required=True, help="Short hypervisor identifier")
    @click.option("--output", default="bootstrap.sh", help="Output script filename")
    @click.option("--platform", help="Hypervisor platform (libvirt/vsphere/etc)")
    @click.option("--location", help="Physical location")
    @click.option("--local-ip", help="Local IP address of hypervisor")
    @click.option("--github-repo", help="GitHub repository (org/repo)")
    @click.option("--network-mode", help="Network mode (nat/bridge/custom)")
    def hypervisor_bootstrap(
        name: str,
        output: str,
        platform: str | None,
        location: str | None,
        local_ip: str | None,
        github_repo: str | None,
        network_mode: str | None,
    ) -> None:
        """Generate hypervisor bootstrap script."""
        generate_bootstrap_script(
            name=name,
            output=output,
            platform=platform,
            location=location,
            local_ip=local_ip,
            github_repo=github_repo,
            network_mode=network_mode,
        )

    @hypervisor.command("list")
    def hypervisor_list() -> None:
        """List known hypervisors."""
        list_hypervisors()

    @hypervisor.command("show")
    @click.argument("name")
    @click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
    def hypervisor_show(name: str, as_json: bool) -> None:
        """Show hypervisor details."""
        show_hypervisor(name, as_json)
