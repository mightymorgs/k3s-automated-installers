"""Storage verification models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class StorageMount(BaseModel):
    """A detected NFS or SMB/CIFS mount on a hypervisor."""

    mount_type: str
    source: str
    mount_point: str
    options: Optional[str] = None


class StorageBrowseResult(BaseModel):
    """Result of browsing a remote directory on a hypervisor via SSH."""

    hypervisor_name: str
    path: str
    entries: list[dict]


class StorageVerifyRequest(BaseModel):
    """Request to verify storage access from a hypervisor."""

    hypervisor_name: str
    mount_type: str
    source: str
    credentials: Optional[dict] = None


class StorageVerifyResult(BaseModel):
    """Result of verifying storage access from a hypervisor."""

    accessible: bool
    mount_type: str
    source: str
    mount_point: Optional[str] = None
    error: Optional[str] = None
    contents: list[str] = []
