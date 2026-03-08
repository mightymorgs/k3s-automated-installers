"""Registration for ``storage`` CLI command group."""

from __future__ import annotations

import click

from vm_builder.commands.storage import browse_path, list_mounts, verify_storage


def register_storage_group(root: click.Group) -> None:
    """Attach the ``storage`` command group to the root CLI."""

    @root.group("storage")
    def storage() -> None:
        """Storage detection and verification."""

    @storage.command("mounts")
    @click.argument("hypervisor_name")
    def storage_mounts(hypervisor_name: str) -> None:
        """Detect NFS/SMB mounts on a hypervisor."""
        list_mounts(hypervisor_name)

    @storage.command("browse")
    @click.argument("hypervisor_name")
    @click.argument("path")
    def storage_browse(hypervisor_name: str, path: str) -> None:
        """Browse remote directory on hypervisor."""
        browse_path(hypervisor_name, path)

    @storage.command("verify")
    @click.option(
        "--type",
        "mount_type",
        required=True,
        type=click.Choice(["nfs", "smb"]),
    )
    @click.option("--source", required=True, help="NFS/SMB source address")
    @click.option("--mount-point", required=True, help="Mount point path")
    def storage_verify(mount_type: str, source: str, mount_point: str) -> None:
        """Verify storage mount accessibility."""
        verify_storage(mount_type, source, mount_point)
