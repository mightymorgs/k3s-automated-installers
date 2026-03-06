"""Mount detection operation for StorageService."""

from __future__ import annotations

import re

from vm_builder.core.models import StorageMount


_MOUNT_PATTERN = re.compile(
    r"^(\S+)\s+on\s+(\S+)\s+type\s+(nfs4?|cifs)\s+\(([^)]*)\)$"
)


def detect_mounts(self, hypervisor_name: str) -> list[StorageMount]:
    """Detect NFS and SMB/CIFS mounts on the hypervisor."""
    result = self._ssh_cmd(hypervisor_name, "mount")
    mounts: list[StorageMount] = []

    for line in result.stdout.splitlines():
        match = _MOUNT_PATTERN.match(line.strip())
        if not match:
            continue

        source, mount_point, fs_type, options = match.groups()
        mount_type = "smb" if fs_type == "cifs" else "nfs"
        mounts.append(
            StorageMount(
                mount_type=mount_type,
                source=source,
                mount_point=mount_point,
                options=options,
            )
        )

    return mounts
