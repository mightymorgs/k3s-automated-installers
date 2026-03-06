"""Path browsing operation for StorageService."""

from __future__ import annotations

from typing import Optional

from vm_builder.core.errors import RemotePathNotFoundError, SshConnectionError
from vm_builder.core.models import StorageBrowseResult


def browse_path(
    self,
    hypervisor_name: str,
    path: str,
    mount_source: Optional[str] = None,
    mount_type: Optional[str] = None,
    mount_point: Optional[str] = None,
) -> StorageBrowseResult:
    """Browse a remote directory on the hypervisor.

    If mount_source and mount_type are provided, ensures the share is
    mounted on the hypervisor before listing (auto-mount for SMB/NFS).
    """
    if mount_source and mount_type and mount_point:
        try:
            self.ensure_mount(hypervisor_name, mount_point, mount_source, mount_type)
        except Exception:
            pass  # Best-effort: browse whatever is there

    result = self._ssh_cmd(hypervisor_name, f"ls -1p {path}")

    if result.returncode != 0:
        if "No such file or directory" in result.stderr:
            raise RemotePathNotFoundError(
                f"Path does not exist on {hypervisor_name}: {path}",
                context={"hypervisor": hypervisor_name, "path": path},
            )
        raise SshConnectionError(
            f"ls failed on {hypervisor_name}: {result.stderr}",
            context={"hypervisor": hypervisor_name},
        )

    entries: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.endswith("/"):
            entries.append({"name": line.rstrip("/"), "entry_type": "dir"})

    return StorageBrowseResult(
        hypervisor_name=hypervisor_name,
        path=path,
        entries=entries,
    )
