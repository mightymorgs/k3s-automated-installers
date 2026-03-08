"""Ensure a network share is mounted on the hypervisor before browsing."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def ensure_mount(
    self,
    hypervisor_name: str,
    mount_point: str,
    source: str,
    mount_type: str,
) -> bool:
    """Check if a path is mounted; if not, mount the share via SSH.

    Supports smb (cifs) and nfs mount types.  For SMB shares, looks up
    credentials from the network-shares BWS config using the hypervisor's
    location.
    Returns True if the mount is active after this call.
    """
    # Check if already mounted
    check = self._ssh_cmd(hypervisor_name, f"mountpoint -q {mount_point}")
    if check.returncode == 0:
        return True

    logger.info(
        "Mount not active at %s on %s, mounting %s (%s)",
        mount_point,
        hypervisor_name,
        source,
        mount_type,
    )

    # Ensure mount point directory exists
    self._ssh_cmd(hypervisor_name, f"sudo mkdir -p {mount_point}")

    if mount_type in ("smb", "cifs"):
        creds = _find_smb_credentials(self, hypervisor_name, source)
        if creds:
            opts = f"username={creds['username']},password={creds['password']},vers=3.0"
        else:
            opts = "guest,vers=3.0"
        cmd = f"sudo mount -t cifs {source} {mount_point} -o {opts}"
    elif mount_type in ("nfs", "nfs4"):
        cmd = f"sudo mount -t nfs {source} {mount_point}"
    else:
        logger.warning("Unsupported mount type for auto-mount: %s", mount_type)
        return False

    result = self._ssh_cmd(hypervisor_name, cmd, timeout=30)
    if result.returncode != 0:
        logger.error(
            "Failed to mount %s at %s: %s",
            source,
            mount_point,
            result.stderr,
        )
        return False

    logger.info("Mounted %s at %s on %s", source, mount_point, hypervisor_name)
    return True


def _find_smb_credentials(
    self, hypervisor_name: str, source: str
) -> Optional[dict]:
    """Look up SMB credentials from network-shares config."""
    inventory = self._hypervisor_resolver(hypervisor_name)
    location = inventory.get("identity", {}).get("location", "")
    if not location:
        return None

    data = self._bws_get_network_shares(location)
    if data is None:
        return None

    for share in data.get("shares", []):
        if share.get("source") == source:
            return share.get("credentials")

    return None
