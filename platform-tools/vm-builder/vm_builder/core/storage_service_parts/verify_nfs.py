"""NFS verification operation for StorageService."""

from __future__ import annotations

from vm_builder.core.models import StorageVerifyRequest, StorageVerifyResult


def verify_nfs(self, request: StorageVerifyRequest) -> StorageVerifyResult:
    """Verify NFS export accessibility."""
    parts = request.source.split(":", 1)
    if len(parts) != 2:
        return StorageVerifyResult(
            accessible=False,
            mount_type="nfs",
            source=request.source,
            error=f"Invalid NFS source format: {request.source} (expected server:/path)",
        )

    server, export_path = parts

    result = self._ssh_cmd(
        request.hypervisor_name,
        f"showmount -e {server} 2>/dev/null",
    )

    if result.returncode != 0:
        return StorageVerifyResult(
            accessible=False,
            mount_type="nfs",
            source=request.source,
            error=result.stderr.strip() or "showmount failed -- NFS server unreachable",
        )

    if export_path not in result.stdout:
        return StorageVerifyResult(
            accessible=False,
            mount_type="nfs",
            source=request.source,
            error=f"Export {export_path} not found on {server}",
        )

    contents = self._list_remote_contents(request.hypervisor_name, request.source)

    return StorageVerifyResult(
        accessible=True,
        mount_type="nfs",
        source=request.source,
        contents=contents,
    )
