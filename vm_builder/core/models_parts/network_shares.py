"""Network share and inventory-storage models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class NetworkShareCredentials(BaseModel):
    """Credentials for SMB/CIFS share access."""

    username: str
    password: str


class NetworkShare(BaseModel):
    """A network share definition stored in BWS per location."""

    id: str
    name: str
    mount_type: str
    source: str
    mount_point: str
    credentials: Optional[NetworkShareCredentials] = None
    discovered_from: Optional[str] = None
    verified_at: Optional[str] = None


class NetworkSharesConfig(BaseModel):
    """All network shares for a physical location, stored in BWS."""

    location: str
    shares: list[NetworkShare] = []


class InventoryMount(BaseModel):
    """A mount reference stored in VM inventory (no credentials)."""

    share_id: str
    mount_type: str
    source: str
    mount_point: str


class InventoryStorageBlock(BaseModel):
    """The storage block in a VM inventory (v3.3+)."""

    location: str
    mounts: list[InventoryMount] = []
    app_paths: dict[str, dict] = {}
