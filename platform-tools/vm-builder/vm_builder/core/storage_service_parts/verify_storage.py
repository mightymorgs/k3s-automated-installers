"""Storage verification dispatcher for StorageService."""

from __future__ import annotations

from vm_builder.core.models import StorageVerifyRequest, StorageVerifyResult


def verify_storage(self, request: StorageVerifyRequest) -> StorageVerifyResult:
    """Verify that a storage source is accessible from the hypervisor."""
    if request.mount_type == "nfs":
        return self._verify_nfs(request)
    if request.mount_type == "smb":
        return self._verify_smb(request)

    return StorageVerifyResult(
        accessible=False,
        mount_type=request.mount_type,
        source=request.source,
        error=f"Unsupported mount type: {request.mount_type}",
    )
