"""Remote contents helper for StorageService."""

from __future__ import annotations


def list_remote_contents(self, hypervisor_name: str, source: str) -> list[str]:
    """List top-level directories at a mount source (best-effort)."""
    try:
        mounts = self.detect_mounts(hypervisor_name)
        for mount in mounts:
            if mount.source == source:
                browse = self.browse_path(hypervisor_name, mount.mount_point)
                return [entry["name"] for entry in browse.entries]
    except Exception:
        pass
    return []
