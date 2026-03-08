"""Storage verification API routes -- remote NFS/SMB detection and browsing.

All operations SSH to the hypervisor via Tailscale to detect mounts,
browse directories, and verify storage access. The hypervisor has
LAN access to NFS/SMB shares that the API server may not.

Endpoints:
    GET  /api/v1/storage/{hypervisor_name}/mounts       -- detect NFS/SMB mounts
    GET  /api/v1/storage/{hypervisor_name}/browse        -- browse remote directory
    POST /api/v1/storage/verify                          -- verify storage access
    GET  /api/v1/storage/network-shares/{location}       -- get network shares for a location
    PUT  /api/v1/storage/network-shares/{location}       -- save network shares for a location
"""

from fastapi import APIRouter, HTTPException, Query
from vm_builder.api.deps import get_storage_service
from vm_builder.core.models import StorageVerifyRequest

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


@router.get("/{hypervisor_name}/mounts")
async def list_mounts(hypervisor_name: str):
    """Detect NFS and SMB/CIFS mounts on a hypervisor.

    SSHs to the hypervisor and parses ``mount`` output for NFS/CIFS entries.

    Status codes:
        200: Mounts detected (may be empty list).
        502: SSH connection to hypervisor failed.
    """
    svc = get_storage_service()
    mounts = svc.detect_mounts(hypervisor_name)
    return [m.model_dump() for m in mounts]


@router.get("/{hypervisor_name}/browse")
async def browse_directory(
    hypervisor_name: str,
    path: str = Query(..., description="Absolute path to browse on the hypervisor"),
    mount_source: str = Query(None, description="Share source (e.g. //server/share or server:/path)"),
    mount_type: str = Query(None, description="Mount type: smb, nfs, cifs, nfs4"),
    mount_point: str = Query(None, description="Mount point on the hypervisor"),
):
    """Browse a remote directory on a hypervisor.

    SSHs to the hypervisor and lists subdirectories at the given path.
    If mount_source/mount_type/mount_point are provided, ensures the
    share is mounted on the hypervisor before listing.

    Status codes:
        200: Directory listing returned.
        404: Path does not exist on the hypervisor.
        502: SSH connection failed.
    """
    svc = get_storage_service()
    result = svc.browse_path(
        hypervisor_name,
        path,
        mount_source=mount_source,
        mount_type=mount_type,
        mount_point=mount_point,
    )
    return result.model_dump()


@router.post("/verify")
async def verify_storage(request: StorageVerifyRequest):
    """Verify storage access from a hypervisor.

    Tests NFS export availability or SMB share accessibility from the
    hypervisor via SSH. For SMB, optional credentials can be provided.

    Status codes:
        200: Verification result returned (check ``accessible`` field).
        502: SSH connection to hypervisor failed.
    """
    svc = get_storage_service()
    result = svc.verify_storage(request)
    return result.model_dump()


@router.get("/network-shares/{location}")
async def get_network_shares(location: str):
    """Get network shares for a physical location.

    Returns the shares list with credentials stripped (credentials
    are only used at deploy time, never exposed to the frontend).

    Status codes:
        200: Shares returned (may be empty list).
    """
    svc = get_storage_service()
    data = svc.list_network_shares(location)
    # Strip credentials from response -- frontend never needs them
    for share in data.get("shares", []):
        share.pop("credentials", None)
    return data


@router.put("/network-shares/{location}")
async def save_network_shares(location: str, body: dict):
    """Save network shares for a physical location.

    Creates or updates the ``network-shares/{location}`` BWS secret.
    Credentials included in the body are stored in BWS.

    Status codes:
        200: Save succeeded.
        500: BWS write failed.
    """
    svc = get_storage_service()
    body["location"] = location  # Ensure location matches URL
    saved = svc.save_network_shares(location, body)
    if not saved:
        raise HTTPException(500, "Failed to save network shares to BWS")
    return {"saved": True, "location": location}
