"""SMB verification operation for StorageService."""

from __future__ import annotations

from vm_builder.core.models import StorageVerifyRequest, StorageVerifyResult


def verify_smb(self, request: StorageVerifyRequest) -> StorageVerifyResult:
    """Verify SMB/CIFS share accessibility."""
    source = request.source
    if not source.startswith("//"):
        return StorageVerifyResult(
            accessible=False,
            mount_type="smb",
            source=source,
            error=f"Invalid SMB source format: {source} (expected //server/share)",
        )

    parts = source[2:].split("/", 1)
    server = parts[0]

    if request.credentials:
        user = request.credentials.get("username", "guest")
        password = request.credentials.get("password", "")
        smb_cmd = f"smbclient -L //{server} -U {user}%{password} 2>/dev/null"
    else:
        smb_cmd = f"smbclient -L //{server} -N 2>/dev/null"

    result = self._ssh_cmd(request.hypervisor_name, smb_cmd)

    if result.returncode != 0:
        return StorageVerifyResult(
            accessible=False,
            mount_type="smb",
            source=source,
            error=result.stderr.strip() or "smbclient failed -- SMB server unreachable",
        )

    contents = self._list_remote_contents(request.hypervisor_name, source)

    return StorageVerifyResult(
        accessible=True,
        mount_type="smb",
        source=source,
        contents=contents,
    )
